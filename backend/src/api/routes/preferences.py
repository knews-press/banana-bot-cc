"""Preferences API — read and update user preferences from WebUI."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_api_user

logger = structlog.get_logger()

router = APIRouter()

# Valid preference keys (must match prefs.py definitions)
_PREF_KEYS = {
    "permission_mode", "model", "thinking", "thinking_budget", "max_turns",
    "budget", "verbose", "working_directory",
}
_PROFILE_KEYS = {
    "display_name", "language", "github_username",
    "email", "custom_instructions",
}
_ALL_KEYS = _PREF_KEYS | _PROFILE_KEYS


@router.get("/preferences")
async def get_preferences(request: Request, user: dict = Depends(get_api_user)):
    """Return current user preferences."""
    mysql = request.app.state.mysql
    prefs = await mysql.get_preferences(user["user_id"])
    return prefs


@router.patch("/preferences")
async def update_preferences(body: dict, request: Request, user: dict = Depends(get_api_user)):
    """Update one or more preferences. Only known keys are accepted."""
    mysql = request.app.state.mysql
    user_id = user["user_id"]

    # Validate keys
    unknown = set(body.keys()) - _ALL_KEYS
    if unknown:
        raise HTTPException(400, f"Unknown preference keys: {', '.join(sorted(unknown))}")

    # Validate specific values
    if "permission_mode" in body and body["permission_mode"] not in ("yolo", "plan", "approve"):
        raise HTTPException(400, "permission_mode must be yolo, plan, or approve")
    if "verbose" in body and body["verbose"] not in (0, 1, 2):
        raise HTTPException(400, "verbose must be 0, 1, or 2")
    if "max_turns" in body:
        try:
            body["max_turns"] = int(body["max_turns"])
        except (ValueError, TypeError):
            raise HTTPException(400, "max_turns must be an integer")
    if "thinking_budget" in body:
        try:
            body["thinking_budget"] = int(body["thinking_budget"])
        except (ValueError, TypeError):
            raise HTTPException(400, "thinking_budget must be an integer")

    prefs = await mysql.get_preferences(user_id)
    prefs.update(body)
    await mysql.save_preferences(user_id, prefs)

    logger.info("Preferences updated via API", user_id=user_id, keys=list(body.keys()))
    return prefs
