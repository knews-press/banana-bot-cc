"""Approval resolution endpoint for WebUI approve mode."""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...claude.approval import approval_manager
from ..auth import get_api_user

logger = structlog.get_logger()

router = APIRouter()


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(allow|deny|always)$")


@router.post("/approvals/{approval_id}")
async def resolve_approval(
    approval_id: str,
    body: ApprovalDecision,
    user: dict = Depends(get_api_user),
):
    """Resolve a pending tool approval from the WebUI.

    Called by the frontend when the user clicks Allow/Deny/Always in the
    approval modal. The approval_id maps to a pending asyncio.Event in the
    ApprovalManager which is blocking the Claude SDK execution.
    """
    pending = approval_manager.get_pending(approval_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved.")

    # Verify that the requesting user owns this approval
    if pending["user_id"] != user["user_id"]:
        raise HTTPException(status_code=403, detail="Not your approval.")

    approval_manager.resolve(approval_id, body.decision)
    logger.info("WebUI approval resolved",
                approval_id=approval_id, decision=body.decision,
                tool=pending["tool_name"], user_id=user["user_id"])

    return {"ok": True, "decision": body.decision}
