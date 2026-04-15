"""Claude Code provider — wraps the existing ClaudeClient behind ProviderClient."""

from __future__ import annotations

import asyncio
from typing import Any

from ..claude.client import ClaudeClient
from ..config import Settings
from ..storage.elasticsearch import ElasticsearchStorage
from ..storage.mysql import MySQLStorage
from .base import OnMessageCallback, ProviderClient


# Models offered by Claude Code
_CLAUDE_MODELS = [
    {"name": "claude-opus-4-6", "display_name": "Claude Opus 4.6", "context_window": 1_000_000},
    {"name": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6", "context_window": 200_000},
    {"name": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5", "context_window": 200_000},
]


class ClaudeProvider(ProviderClient):
    """ProviderClient implementation backed by the Claude Code SDK."""

    def __init__(
        self,
        settings: Settings,
        mysql: MySQLStorage,
        es: ElasticsearchStorage,
        uploads_storage=None,
    ):
        self._client = ClaudeClient(settings, mysql, es, uploads_storage=uploads_storage)
        self._settings = settings

    # Expose the underlying client for Telegram-specific features
    # (approval callbacks, MCP server binding, etc.) during transition.
    @property
    def client(self) -> ClaudeClient:
        return self._client

    # --- Provider metadata ---------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def provider_display_name(self) -> str:
        return "Claude Code"

    def get_available_models(self) -> list[dict[str, Any]]:
        return list(_CLAUDE_MODELS)

    def get_default_model(self) -> str:
        return self._settings.claude_default_model or "claude-sonnet-4-6"

    # --- Execution -----------------------------------------------------------

    async def execute(
        self,
        prompt: str,
        user_id: int,
        session_id: str | None = None,
        cwd: str | None = None,
        on_message: OnMessageCallback | None = None,
        mode: str = "yolo",
        model: str | None = None,
        profile: dict | None = None,
        max_turns: int | None = None,
        thinking: bool = False,
        thinking_budget: int = 10_000,
        budget: float | None = None,
        **kwargs,
    ) -> dict:
        """Delegate to the underlying ClaudeClient.execute()."""
        return await self._client.execute(
            prompt=prompt,
            user_id=user_id,
            session_id=session_id,
            cwd=cwd,
            on_message=on_message,
            mode=mode,
            model=model,
            profile=profile,
            max_turns=max_turns,
            thinking=thinking,
            thinking_budget=thinking_budget,
            budget=budget,
            # Pass through transport-specific kwargs (bot, chat_id, runner)
            bot=kwargs.get("bot"),
            chat_id=kwargs.get("chat_id"),
            runner=kwargs.get("runner"),
        )

    # --- Task management -----------------------------------------------------

    def register_task(self, session_id: str, task: asyncio.Task) -> None:
        self._client.register_task(session_id, task)

    def unregister_task(self, session_id: str) -> None:
        self._client.unregister_task(session_id)

    def cancel_task(self, session_id: str) -> bool:
        return self._client.cancel_task(session_id)

    # --- Session management --------------------------------------------------

    async def restore_sessions(self, user_id: int) -> None:
        await self._client.restore_sessions(user_id)
