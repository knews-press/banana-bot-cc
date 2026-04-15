"""Claude Code configuration commands."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .prefs import save_pref


_MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    "default": None,
}

_MODEL_INFO = {
    "claude-opus-4-6": ("Opus 4.6", "1M"),
    "claude-sonnet-4-6": ("Sonnet 4.6", "200k"),
    "claude-haiku-4-5-20251001": ("Haiku 4.5", "200k"),
}


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        current = context.user_data.get("model", "default")
        env_default = context.bot_data["settings"].claude_default_model
        effective_id = current if current != "default" else (env_default or "claude-sonnet-4-6")
        info = _MODEL_INFO.get(effective_id, (effective_id, "?"))

        await update.message.reply_text(
            f"🤖 <b>Current model:</b> {info[0]} ({info[1]} context)\n\n"
            "  <code>/model sonnet</code>  — Sonnet 4.6 (200k, fast)\n"
            "  <code>/model opus</code>    — Opus 4.6 (1M, powerful)\n"
            "  <code>/model haiku</code>   — Haiku 4.5 (200k, cheap)\n"
            "  <code>/model default</code> — Default"
            + (f" ({env_default})" if env_default else ""),
            parse_mode=ParseMode.HTML,
        )
        return

    name = context.args[0].lower()
    if name not in _MODEL_MAP:
        await update.message.reply_text(f"❌ Unknown model: {name}")
        return
    model_id = _MODEL_MAP[name] or "default"
    await save_pref(context, update.effective_user.id, "model", model_id)
    info = _MODEL_INFO.get(model_id, (name, ""))
    ctx_str = f" ({info[1]} context)" if info[1] else ""
    await update.message.reply_text(f"🤖 Model → <b>{info[0]}</b>{ctx_str}", parse_mode=ParseMode.HTML)


async def cmd_thinking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        # /thinking <budget> — enable with specific token budget
        try:
            budget = int(context.args[0])
            budget = max(1024, min(budget, 128000))
            await save_pref(context, update.effective_user.id, "thinking", True)
            await save_pref(context, update.effective_user.id, "thinking_budget", budget)
            await update.message.reply_text(
                f"⚙️ Extended Thinking: ✅ <b>ON</b> (Budget: {budget:,} tokens)",
                parse_mode=ParseMode.HTML,
            )
            return
        except ValueError:
            pass
    # Toggle on/off
    current = context.user_data.get("thinking", False)
    await save_pref(context, update.effective_user.id, "thinking", not current)
    icon = "✅" if not current else "❌"
    budget_info = ""
    if not current:
        tb = context.user_data.get("thinking_budget", 10000)
        budget_info = f" (Budget: {tb:,} tokens)"
    await update.message.reply_text(
        f"⚙️ Extended Thinking: {icon} <b>{'ON' if not current else 'OFF'}</b>{budget_info}\n\n"
        "Tip: <code>/thinking 20000</code> sets a custom budget.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_turns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        current = context.user_data.get("max_turns", context.bot_data["settings"].claude_max_turns)
        await update.message.reply_text(f"⚙️ Max Turns: <b>{current}</b>", parse_mode=ParseMode.HTML)
        return
    try:
        n = int(context.args[0])
        await save_pref(context, update.effective_user.id, "max_turns", n)
        await update.message.reply_text(f"⚙️ Max Turns → <b>{n}</b>", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("Usage: <code>/turns &lt;number&gt;</code>", parse_mode=ParseMode.HTML)


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        current = context.user_data.get("budget", "unlimited")
        await update.message.reply_text(f"⚙️ Budget: <b>${current}</b>", parse_mode=ParseMode.HTML)
        return
    try:
        usd = float(context.args[0])
        await save_pref(context, update.effective_user.id, "budget", usd)
        await update.message.reply_text(f"⚙️ Budget → <b>${usd:.2f}</b> per message", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("Usage: <code>/budget &lt;usd&gt;</code>", parse_mode=ParseMode.HTML)


async def cmd_verbose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        current = context.user_data.get("verbose", 1)
        levels = {0: "Quiet", 1: "Compact", 2: "Verbose"}
        await update.message.reply_text(
            f"⚙️ Verbose: <b>{current}</b> ({levels.get(current, '?')})\n\n"
            "  <code>0</code> = Typing indicator + result only\n"
            "  <code>1</code> = Live progress + compact summary\n"
            "  <code>2</code> = Live progress + full tool list",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        level = int(context.args[0])
        level = min(max(level, 0), 2)
        await save_pref(context, update.effective_user.id, "verbose", level)
        levels = {0: "Quiet", 1: "Compact", 2: "Verbose"}
        await update.message.reply_text(f"⚙️ Verbose → <b>{level}</b> ({levels.get(level, '')})", parse_mode=ParseMode.HTML)
    except ValueError:
        await update.message.reply_text("Usage: <code>/verbose &lt;0|1|2&gt;</code>", parse_mode=ParseMode.HTML)


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_pref(context, update.effective_user.id, "permission_mode", "plan")
    await update.message.reply_text(
        "⚙️ Mode → <b>Plan</b> 📖\n"
        "   Read and research only, no changes.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_pref(context, update.effective_user.id, "permission_mode", "approve")
    await update.message.reply_text(
        "⚙️ Mode → <b>Approve</b> 🔐\n"
        "   Read tools: auto\n"
        "   Bash/Write/Edit: inline buttons",
        parse_mode=ParseMode.HTML,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = context.user_data.get("running_task")
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("⏹ Stopping...")
    else:
        await update.message.reply_text("⏹ Nothing is running.")


async def cmd_yolo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_pref(context, update.effective_user.id, "permission_mode", "yolo")
    await update.message.reply_text(
        "⚙️ Mode → <b>YOLO</b> 🚀\n"
        "   Unrestricted, no confirmations.",
        parse_mode=ParseMode.HTML,
    )
