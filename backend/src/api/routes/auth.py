"""Internal auth helper endpoints (called by the web frontend, not users)."""

import os

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter()

INTERNAL_SECRET = os.environ.get("INTERNAL_API_SECRET", "internal")


class SendLoginLinkRequest(BaseModel):
    chat_id: int
    text: str


@router.post("/auth/send-login-link")
async def send_login_link(body: SendLoginLinkRequest, request: Request):
    """Send a login link via Telegram. Called internally by the web frontend."""
    # Verify internal secret
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    bot = getattr(request.app.state, "telegram_bot", None)
    if not bot:
        logger.warning("send-login-link: no Telegram bot available")
        raise HTTPException(status_code=503, detail="Telegram bot not available")

    try:
        await bot.send_message(chat_id=body.chat_id, text=body.text)
        logger.info("Login link sent via Telegram", chat_id=body.chat_id)
        return {"ok": True}
    except Exception as e:
        logger.error("Failed to send Telegram login link", error=str(e), chat_id=body.chat_id)
        raise HTTPException(status_code=500, detail="Failed to send message")
