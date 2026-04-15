"""Admin endpoints: status, stats, API key management."""

import secrets
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_api_user
from ..models import BotStatus, ApiKeyCreate, ApiKeyInfo, ApiKeyResponse

logger = structlog.get_logger()

router = APIRouter()


@router.get("/status", response_model=BotStatus)
async def status(request: Request, user: dict = Depends(get_api_user)):
    """Bot status and health info."""
    settings = request.app.state.settings
    claude = request.app.state.claude
    mysql = request.app.state.mysql

    stats = await mysql.get_stats()
    uptime = time.time() - request.app.state.start_time

    return BotStatus(
        instance_name=settings.instance_name,
        uptime_seconds=uptime,
        claude_cli=claude.cli_path is not None,
        active_sessions=stats.get("sessions", 0),
        total_messages=stats.get("messages", 0),
        total_cost=stats.get("total_cost", 0),
    )


@router.get("/stats")
async def stats(request: Request, user: dict = Depends(get_api_user)):
    """Usage statistics."""
    mysql = request.app.state.mysql
    stats = await mysql.get_stats()
    user_stats = await mysql.get_user_stats(user["user_id"])
    return {
        "global": stats,
        "user": user_stats,
    }


# --- API Key Management ---

@router.post("/keys", response_model=ApiKeyResponse)
async def create_key(body: ApiKeyCreate, request: Request, user: dict = Depends(get_api_user)):
    """Create a new API key. Only the owner can create keys."""
    settings = request.app.state.settings
    mysql = request.app.state.mysql

    # Only allow owner to create keys
    if user["user_id"] != settings.owner_user_id:
        raise HTTPException(status_code=403, detail="Only the owner can create API keys")

    target_user_id = body.user_id or settings.owner_user_id

    # Generate key
    api_key = f"sk-{secrets.token_urlsafe(32)}"

    # Ensure target user exists
    await mysql.ensure_user(target_user_id)
    await mysql.create_api_key(api_key, target_user_id, body.name)

    logger.info("API key created", name=body.name, user_id=target_user_id)
    return ApiKeyResponse(api_key=api_key, name=body.name)


@router.get("/keys", response_model=list[ApiKeyInfo])
async def list_keys(request: Request, user: dict = Depends(get_api_user)):
    """List API keys for the authenticated user."""
    mysql = request.app.state.mysql
    keys = await mysql.list_api_keys(user["user_id"])
    return [
        ApiKeyInfo(
            api_key=f"{k['api_key'][:12]}...{k['api_key'][-4:]}",  # Masked
            name=k["name"],
            user_id=k["user_id"],
            created_at=k.get("created_at"),
            last_used=k.get("last_used"),
            is_active=k.get("is_active", True),
        )
        for k in keys
    ]


@router.delete("/keys/{api_key}")
async def revoke_key(api_key: str, request: Request, user: dict = Depends(get_api_user)):
    """Revoke an API key."""
    settings = request.app.state.settings
    mysql = request.app.state.mysql

    if user["user_id"] != settings.owner_user_id:
        raise HTTPException(status_code=403, detail="Only the owner can revoke API keys")

    revoked = await mysql.revoke_api_key(api_key)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")

    logger.info("API key revoked", key_prefix=api_key[:12])
    return {"message": "API key revoked"}
