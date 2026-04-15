"""Utility commands — /help and internal helpers."""

import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("permission_mode", "yolo")
    model = context.user_data.get("model", "default")
    name = context.user_data.get("display_name", "")
    greeting = f"Hi {html.escape(name)}  · " if name else ""

    await update.message.reply_text(
        f"<b>Claude Code Bot</b>\n"
        f"{greeting}⚙️ {mode} · {model}\n\n"

        "🆕 <code>/new</code>         New session\n"
        "📋 <code>/session</code>     Manage sessions\n"
        "📊 <code>/status</code>      Session status &amp; context\n\n"

        "⏹ <code>/stop</code>        Abort execution\n\n"

        "🤖 <code>/model</code>       Switch model\n"
        "⚙️ <code>/mode</code>        Mode &amp; settings\n"
        "👤 <code>/me</code>          Profile &amp; language\n\n"

        "🧠 <code>/memory</code>      Memories &amp; search\n\n"

        "<i>Type a command without arguments\n"
        "to see all subcommands.</i>",
        parse_mode=ParseMode.HTML,
    )
