"""Status command — /status.

Shows session info, context window usage, model, mode, and costs at a glance.
Replaces the old /compact command.
"""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...utils.session_names import short_name

from ...storage.mysql import MySQLStorage


def _progress_bar(pct: float, width: int = 20) -> str:
    """Create a text progress bar: ██░░░░░░░░░░░░░░░░░░"""
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def _fmt_tokens(n: int) -> str:
    """Format token count: 1234567 → 1.23M, 12345 → 12.3k"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# Model context window sizes
_CONTEXT_WINDOWS = {
    "claude-opus-4": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet-4": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
}


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current session status, context usage, and settings."""
    mysql: MySQLStorage = context.bot_data["mysql"]
    settings = context.bot_data["settings"]
    user_id = update.effective_user.id

    session = await mysql.get_active_session(user_id, settings.approved_directory)
    if not session:
        await update.message.reply_text("ℹ️ No active session.\n\n<code>/new</code> — Start a new session", parse_mode=ParseMode.HTML)
        return

    session_id = session["session_id"]
    turns = session.get("total_turns", 0)
    cost = session.get("total_cost", 0)
    tokens = await mysql.get_session_token_count(session_id, user_id)

    # Model info
    model = context.user_data.get("model", "default")
    env_default = settings.claude_default_model
    effective_model = model if model != "default" else (env_default or "claude-sonnet-4-6")
    context_window = _CONTEXT_WINDOWS.get(effective_model, 200_000)
    pct = min(round(tokens / context_window * 100), 100) if context_window else 0

    # Mode & settings
    mode = context.user_data.get("permission_mode", "yolo")
    thinking = context.user_data.get("thinking", False)
    thinking_str = "off"
    if thinking:
        tb = context.user_data.get("thinking_budget", 10000)
        thinking_str = f"on ({tb // 1000}k Budget)"
    max_turns = context.user_data.get("max_turns", settings.claude_max_turns)
    budget = context.user_data.get("budget", "∞")
    cwd = (context.user_data.get("working_directory") or settings.approved_directory).replace("/root/workspace", "~")

    # Compaction info
    compacted = ""
    if session.get("compacted_from"):
        compacted = "\n├─ Compacted: yes"

    # Session age
    from datetime import timezone
    from zoneinfo import ZoneInfo
    started = ""
    if session.get("last_used"):
        last = session["last_used"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Berlin"))
        started = last.strftime("%H:%M")

    # Short model name for display
    model_display = effective_model.replace("claude-", "").replace("-20251001", "")

    await update.message.reply_text(
        f"📊 <b>Status</b>\n\n"
        f"├─ Session: <code>{short_name(session_id, session.get('display_name'))}</code> ({started})\n"
        f"├─ Model: <b>{model_display}</b>\n"
        f"├─ Mode: <b>{mode}</b>\n"
        f"├─ Thinking: <b>{thinking_str}</b>\n"
        f"├─ Turns: <b>{turns}/{max_turns}</b>\n"
        f"├─ Context: {_fmt_tokens(tokens)} / {_fmt_tokens(context_window)} ({pct}%)\n"
        f"│  <code>{_progress_bar(pct)}</code>\n"
        f"├─ Cost: <b>${cost:.4f}</b> (Budget: ${budget})"
        f"{compacted}\n"
        f"└─ Directory: {cwd}",
        parse_mode=ParseMode.HTML,
    )
