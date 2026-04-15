"""Session management endpoints."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_api_user
from ..models import SessionInfo, SessionDetail

logger = structlog.get_logger()

router = APIRouter()


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(request: Request, user: dict = Depends(get_api_user)):
    """List active sessions for the authenticated user."""
    mysql = request.app.state.mysql
    sessions = await mysql.get_user_sessions(user["user_id"], limit=100)
    return [
        SessionInfo(
            session_id=s["session_id"],
            project_path=s["project_path"],
            last_used=s.get("last_used"),
            total_turns=s.get("total_turns", 0),
            total_cost=s.get("total_cost", 0),
            compact_count=s.get("compact_count") or 0,
            context_tokens=s.get("context_tokens") or 0,
            last_channel=s.get("last_channel"),
            running_channel=s.get("running_channel") if s.get("is_running") else None,
            display_name=s.get("display_name"),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, request: Request, user: dict = Depends(get_api_user)):
    """Get details for a specific session."""
    mysql = request.app.state.mysql
    # Verify session belongs to user
    sessions = await mysql.get_user_sessions(user["user_id"], limit=100)
    session = next((s for s in sessions if s["session_id"] == session_id), None)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionDetail(
        session_id=session["session_id"],
        project_path=session["project_path"],
        last_used=session.get("last_used"),
        total_turns=session.get("total_turns", 0),
        total_cost=session.get("total_cost", 0),
        compact_count=session.get("compact_count") or 0,
        context_tokens=session.get("context_tokens") or 0,
        last_channel=session.get("last_channel"),
        running_channel=session.get("running_channel") if session.get("is_running") else None,
        display_name=session.get("display_name"),
    )



@router.get("/sessions/active-lock")
async def get_active_lock(request: Request, user: dict = Depends(get_api_user)):
    """Return whether ANY session for this user is currently locked, and by which channel.

    Used by the web UI to detect Telegram activity across all sessions,
    not just the one currently open in the browser.
    """
    mysql = request.app.state.mysql
    row = await mysql.get_any_running_session(user["user_id"])
    if row:
        return {"is_running": True, "channel": row["running_channel"], "session_id": row["session_id"]}
    return {"is_running": False, "channel": None, "session_id": None}


@router.get("/sessions/{session_id}/lock")
async def get_session_lock(session_id: str, request: Request, user: dict = Depends(get_api_user)):
    """Return the current execution lock status for a session."""
    mysql = request.app.state.mysql
    sessions = await mysql.get_user_sessions(user["user_id"], limit=100)
    session = next((s for s in sessions if s["session_id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    channel = await mysql.get_running_channel(session_id)
    return {"is_running": channel is not None, "channel": channel}


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, request: Request, user: dict = Depends(get_api_user)):
    """Cancel a running task for a session (cross-channel stop)."""
    mysql = request.app.state.mysql
    claude = request.app.state.claude
    sessions = await mysql.get_user_sessions(user["user_id"], limit=100)
    session = next((s for s in sessions if s["session_id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    cancelled = claude.cancel_task(session_id)
    if not cancelled:
        # No in-memory task — just clear a potentially stale lock
        await mysql.release_running_lock(session_id)

    logger.info("stop_session called", session_id=session_id, cancelled=cancelled)
    return {
        "stopped": cancelled,
        "message": "Stop signal gesendet." if cancelled else "Keine laufende Aufgabe, Lock freigegeben.",
    }


@router.delete("/sessions/{session_id}")
async def end_session(session_id: str, request: Request, user: dict = Depends(get_api_user)):
    """Deactivate a session."""
    mysql = request.app.state.mysql
    # Verify ownership
    sessions = await mysql.get_user_sessions(user["user_id"], limit=100)
    session = next((s for s in sessions if s["session_id"] == session_id), None)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await mysql.deactivate_session(session_id, user["user_id"])
    return {"message": f"Session {session_id} deactivated"}
