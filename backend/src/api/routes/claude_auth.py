"""Claude OAuth auth endpoints (called by the web frontend)."""

import time
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_api_user
from ...bot.auth_flow import (
    ensure_authenticated,
    is_authenticated,
    start_pkce_auth,
    complete_pkce_auth,
)

logger = structlog.get_logger()

router = APIRouter()

# In-memory PKCE flow store: {flow_id: {code_verifier, state, created_at}}
# Entries expire after FLOW_TTL_SECONDS.
_flows: dict[str, dict] = {}
FLOW_TTL_SECONDS = 10 * 60  # 10 minutes


def _purge_expired() -> None:
    """Remove stale flow entries (called lazily on each request)."""
    now = time.time()
    stale = [k for k, v in _flows.items() if now - v["created_at"] > FLOW_TTL_SECONDS]
    for k in stale:
        _flows.pop(k, None)


# ── Models ─────────────────────────────────────────────────────────────────

class StartResponse(BaseModel):
    flow_id: str
    auth_url: str


class CompleteRequest(BaseModel):
    flow_id: str
    code: str


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/claude-auth/status")
async def claude_auth_status(_user: dict = Depends(get_api_user)) -> dict:
    """Return current Claude authentication status."""
    return {"authenticated": is_authenticated()}


@router.post("/claude-auth/start", response_model=StartResponse)
async def claude_auth_start(_user: dict = Depends(get_api_user)) -> StartResponse:
    """Generate a PKCE authorization URL and return a flow_id to track it."""
    _purge_expired()
    try:
        auth_url, code_verifier, state = start_pkce_auth()
    except Exception as e:
        logger.error("Failed to start PKCE flow", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to start auth flow: {e}")

    flow_id = str(uuid.uuid4())
    _flows[flow_id] = {
        "code_verifier": code_verifier,
        "state": state,
        "created_at": time.time(),
    }
    logger.info("Claude auth flow started", flow_id=flow_id[:8])
    return StartResponse(flow_id=flow_id, auth_url=auth_url)


@router.post("/claude-auth/complete")
async def claude_auth_complete(
    body: CompleteRequest,
    _user: dict = Depends(get_api_user),
) -> dict:
    """Complete the OAuth flow: exchange code for tokens."""
    _purge_expired()

    flow = _flows.pop(body.flow_id, None)
    if not flow:
        raise HTTPException(
            status_code=400,
            detail="Ungültige oder abgelaufene flow_id. Bitte neu starten.",
        )

    age = time.time() - flow["created_at"]
    if age > FLOW_TTL_SECONDS:
        raise HTTPException(
            status_code=400,
            detail="Auth-Flow abgelaufen. Bitte neu starten.",
        )

    try:
        await complete_pkce_auth(
            body.code,
            flow["code_verifier"],
            flow["state"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("PKCE completion failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Auth-Fehler: {e}")

    logger.info("Claude auth completed via WebUI")
    return {"ok": True}
