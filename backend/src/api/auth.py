"""API key authentication dependency."""

import structlog
from fastapi import Depends, HTTPException, Request

logger = structlog.get_logger()


async def get_api_user(request: Request) -> dict:
    """FastAPI dependency: validate Bearer token and return user info.

    Returns dict with: api_key, user_id, name, permissions
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    api_key = auth[7:].strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="Empty API key")

    mysql = request.app.state.mysql
    user = await mysql.validate_api_key(api_key)

    if not user:
        logger.warning("Invalid API key attempt", key_prefix=api_key[:8])
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    return user
