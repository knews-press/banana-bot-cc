"""Telegram command dispatchers — thin wrappers around core.py.

Each command builds a CommandContext, calls execute_command(), and
sends the result formatted as Telegram HTML.
"""

import html
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .core import CommandContext, CommandResult, execute_command
from .registry import COMMAND_REGISTRY, find_command
from .profile import (
    cmd_me_show, cmd_me_name, cmd_me_lang, cmd_me_github,
    cmd_me_email, cmd_me_instructions,
)


# ---------------------------------------------------------------------------
# Markdown → Telegram HTML converter
# ---------------------------------------------------------------------------

def md_to_tg_html(text: str) -> str:
    """Convert Markdown to Telegram-compatible HTML.

    Handles: **bold**, *italic*, _italic_, `inline code`, ```code blocks```,
    [links](url), and basic list markers.
    """
    # Code blocks first (before other transforms) — ```lang\n...\n```
    def _code_block(m: re.Match) -> str:
        code = html.escape(m.group(2).strip())
        return f"<pre>{code}</pre>"
    text = re.sub(r"```(\w*)\n?(.*?)```", _code_block, text, flags=re.DOTALL)

    # Inline code — `...`
    def _inline_code(m: re.Match) -> str:
        return f"<code>{html.escape(m.group(1))}</code>"
    text = re.sub(r"`([^`]+)`", _inline_code, text)

    # Bold — **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic — *text* or _text_ (but not inside HTML tags or URLs)
    text = re.sub(r"(?<![<\w])_(.+?)_(?![>\w])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # Links — [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Headings — strip # markers, make bold
    text = re.sub(r"^#{1,3}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # List markers — "- item" → "• item"
    text = re.sub(r"^- ", "• ", text, flags=re.MULTILINE)

    return text


# ---------------------------------------------------------------------------
# Telegram adapter helpers
# ---------------------------------------------------------------------------

def _build_ctx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> CommandContext:
    """Build a transport-agnostic CommandContext from Telegram objects."""
    return CommandContext(
        user_id=update.effective_user.id,
        args=[],  # set by caller
        mysql=context.bot_data["mysql"],
        es=context.bot_data["es"],
        settings=context.bot_data["settings"],
        user_prefs=dict(context.user_data),
    )


async def _send_result(update: Update, context: ContextTypes.DEFAULT_TYPE, result: CommandResult):
    """Format a CommandResult and send as Telegram message."""
    if result.error and not result.success:
        await update.message.reply_text(
            f"❌ {html.escape(result.error)}",
            parse_mode=ParseMode.HTML,
        )
        return

    text = md_to_tg_html(result.content)

    # Truncate for Telegram
    if len(text) > 4000:
        text = text[:3980] + "\n\n... (truncated)"

    try:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        # Fallback: send as plain text if HTML parsing fails
        await update.message.reply_text(result.content[:4000])

    # Apply side effects (preference changes) to Telegram's user_data
    if result.data:
        _apply_side_effects(context, result.data)


def _apply_side_effects(context: ContextTypes.DEFAULT_TYPE, data: dict):
    """Sync preference changes from CommandResult.data to Telegram user_data."""
    pref_keys = {"model", "mode", "permission_mode", "thinking", "thinking_budget",
                 "max_turns", "budget", "verbose", "working_directory",
                 "language", "display_name", "github_username",
                 "email", "custom_instructions"}
    for key, value in data.items():
        if key in pref_keys:
            context.user_data[key] = value
    # Special: force_new flag
    if data.get("force_new"):
        context.user_data["force_new_session"] = True
    if data.get("resume_session_id"):
        context.user_data["resume_session_id"] = data["resume_session_id"]


# ---------------------------------------------------------------------------
# Generic command handler factory
# ---------------------------------------------------------------------------

def _make_command(command_name: str):
    """Create a Telegram handler that delegates to execute_command()."""
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ctx = _build_ctx(update, context)
        args = context.args or []
        result = await execute_command(command_name, args, ctx)
        await _send_result(update, context, result)
    return handler


# Create handlers for all core commands
cmd_new = _make_command("new")
cmd_session = _make_command("session")
cmd_status = _make_command("status")
cmd_model_cmd = _make_command("model")
cmd_mode = _make_command("mode")
cmd_memory_dispatch = _make_command("memory")


# /me — kept as custom dispatcher because profile commands use Telegram-specific flows
async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show or edit user profile — delegates to core for display, keeps Telegram handlers for edits."""
    subcommands = {
        "name": cmd_me_name,
        "lang": cmd_me_lang,
        "github": cmd_me_github,
        "email": cmd_me_email,
        "instructions": cmd_me_instructions,
    }
    if not context.args:
        # Use core for display
        ctx = _build_ctx(update, context)
        result = await execute_command("me", [], ctx)
        await _send_result(update, context, result)
        return
    sub = context.args[0].lower()
    handler = subcommands.get(sub)
    if not handler:
        await update.message.reply_text(
            f"❌ Unknown: <code>{html.escape(sub)}</code>\n\n"
            "Available: <code>name</code> · <code>lang</code> · <code>github</code> · "
            "<code>org</code> · <code>email</code> · <code>instructions</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    context.args = context.args[1:]
    await handler(update, context)
