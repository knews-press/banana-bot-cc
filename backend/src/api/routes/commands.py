"""Slash command API — GET registry + POST execute."""

import structlog
from fastapi import APIRouter, Depends, Request

from ..auth import get_api_user
from ..models import CommandRequest, CommandResponse
from ...bot.commands.registry import get_registry_dict
from ...bot.commands.core import CommandContext, execute_command

logger = structlog.get_logger()

router = APIRouter()


@router.get("/commands")
async def list_commands(request: Request, user: dict = Depends(get_api_user)):
    """Return the command registry for autocomplete."""
    return get_registry_dict()


@router.post("/commands")
async def run_command(
    body: CommandRequest,
    request: Request,
    user: dict = Depends(get_api_user),
):
    """Execute a slash command and return structured result."""
    mysql = request.app.state.mysql
    es = request.app.state.es
    settings = request.app.state.settings
    user_id = user["user_id"]

    # Load user preferences
    prefs = await mysql.get_preferences(user_id)

    ctx = CommandContext(
        user_id=user_id,
        args=body.args,
        mysql=mysql,
        es=es,
        settings=settings,
        user_prefs=prefs,
    )

    result = await execute_command(body.command, body.args, ctx)

    logger.info(
        "command_executed",
        user_id=user_id,
        command=body.command,
        args=body.args,
        success=result.success,
    )

    return result.to_dict()
