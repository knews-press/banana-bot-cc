"""User-level TTS settings — stored in MySQL, cached in-process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import aiomysql
import structlog

from ..config import Settings

logger = structlog.get_logger()


@dataclass
class TTSUserSettings:
    """Resolved TTS configuration for a single user call.

    Values are already merged (user prefs → instance defaults → built-in fallback).
    """

    provider: str = "gemini"        # "gemini" | "openai"
    voice: str = "Puck"
    style_prompt: str | None = None
    model: str | None = None        # None = provider default
    output_format: str = "oga"


# In-process cache: user_id → TTSUserSettings
# Invalidated when set_tts_settings() is called.
_cache: dict[int, TTSUserSettings] = {}
_cache_lock = asyncio.Lock()


async def get_user_tts_settings(
    user_id: int,
    settings: Settings,
) -> TTSUserSettings:
    """Return merged TTS settings for *user_id*.

    Priority: user DB row  →  instance env defaults  →  built-in fallback.
    Results are cached in-process until the user calls set_tts_settings().
    """
    async with _cache_lock:
        if user_id in _cache:
            return _cache[user_id]

    row = await _fetch_row(user_id, settings)

    merged = TTSUserSettings(
        provider=row.get("provider") or settings.tts_default_provider or "gemini",
        voice=row.get("voice") or settings.tts_default_voice or "Puck",
        style_prompt=row.get("style_prompt") or settings.tts_default_style_prompt or None,
        model=row.get("model") or settings.tts_default_model or None,
        output_format=row.get("output_format") or "oga",
    )

    async with _cache_lock:
        _cache[user_id] = merged

    return merged


async def save_user_tts_settings(
    user_id: int,
    settings: Settings,
    *,
    provider: str | None = None,
    voice: str | None = None,
    style_prompt: str | None = None,
    clear_style: bool = False,
    model: str | None = None,
    clear_model: bool = False,
    output_format: str | None = None,
) -> TTSUserSettings:
    """Persist TTS preferences for *user_id* and invalidate cache.

    Only fields that are not None are updated (UPSERT).
    Pass clear_style=True to explicitly set style_prompt to NULL.
    Pass clear_model=True to explicitly set model to NULL.
    """
    # Build SET clause dynamically
    updates: dict[str, Any] = {}
    if provider is not None:
        updates["provider"] = provider
    if voice is not None:
        updates["voice"] = voice
    if clear_style:
        updates["style_prompt"] = None
    elif style_prompt is not None:
        updates["style_prompt"] = style_prompt
    if clear_model:
        updates["model"] = None
    elif model is not None:
        updates["model"] = model
    if output_format is not None:
        updates["output_format"] = output_format

    if updates:
        await _upsert_row(user_id, updates, settings)

    # Invalidate cache
    async with _cache_lock:
        _cache.pop(user_id, None)

    # Return fresh merged settings
    return await get_user_tts_settings(user_id, settings)


# ── MySQL helpers ─────────────────────────────────────────────────────────────


async def _get_conn(settings: Settings) -> aiomysql.Connection:
    return await aiomysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        db=settings.mysql_database,
        charset="utf8mb4",
    )


async def _fetch_row(user_id: int, settings: Settings) -> dict:
    """Return the DB row for *user_id*, or an empty dict if none exists."""
    try:
        conn = await _get_conn(settings)
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT provider, voice, style_prompt, model, output_format "
                "FROM user_tts_settings WHERE user_id = %s",
                (user_id,),
            )
            row = await cur.fetchone()
        conn.close()
        return row or {}
    except Exception as exc:
        logger.warning("tts_settings_fetch_failed", user_id=user_id, error=str(exc))
        return {}


async def _upsert_row(user_id: int, updates: dict[str, Any], settings: Settings) -> None:
    """INSERT ... ON DUPLICATE KEY UPDATE for *user_id*."""
    # Build INSERT columns (always include user_id)
    columns = ["user_id"] + list(updates.keys())
    values = [user_id] + list(updates.values())
    placeholders = ", ".join(["%s"] * len(values))
    col_list = ", ".join(columns)

    # ON DUPLICATE KEY UPDATE clause
    update_clause = ", ".join(
        f"{col} = VALUES({col})" for col in updates.keys()
    )

    sql = (
        f"INSERT INTO user_tts_settings ({col_list}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    try:
        conn = await _get_conn(settings)
        async with conn.cursor() as cur:
            await cur.execute(sql, values)
        await conn.commit()
        conn.close()
        logger.info("tts_settings_saved", user_id=user_id, updates=list(updates.keys()))
    except Exception as exc:
        logger.error("tts_settings_save_failed", user_id=user_id, error=str(exc))
        raise
