"""Session & conversation commands."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from io import BytesIO

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...storage.mysql import MySQLStorage
from ...utils.session_names import short_name


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mysql: MySQLStorage = context.bot_data["mysql"]
    settings = context.bot_data["settings"]
    old = await mysql.get_active_session(update.effective_user.id, settings.approved_directory, channel="telegram")
    context.user_data["force_new_session"] = True
    if old:
        sid = short_name(old["session_id"], old.get("display_name"))
        turns = old["total_turns"]
        cost = old["total_cost"]
        await update.message.reply_text(
            f"🔄 <b>New session started</b>\n"
            f"   Previous: <code>{sid}</code> ({turns} turns, ${cost:.4f})",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("🔄 <b>New session started</b>", parse_mode=ParseMode.HTML)


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mysql: MySQLStorage = context.bot_data["mysql"]
    sessions = await mysql.get_user_sessions(update.effective_user.id)
    if not sessions:
        await update.message.reply_text("🔄 No active sessions.")
        return
    lines = ["🔄 <b>Sessions</b>\n"]
    for i, s in enumerate(sessions, 1):
        sid = short_name(s["session_id"], s.get("display_name"))
        path = s["project_path"].replace("/root/workspace", "~")
        turns = s["total_turns"]
        cost = s["total_cost"]
        if s["last_used"]:
            utc_dt = s["last_used"].replace(tzinfo=timezone.utc)
            last = utc_dt.astimezone(ZoneInfo("Europe/Berlin")).strftime("%H:%M")
        else:
            last = "?"
        lines.append(f"  {i}. <code>{sid}</code>  {path}\n     {turns} turns · ${cost:.4f} · {last}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /resume <session_id or display_name>")
        return
    prefix = context.args[0]
    mysql: MySQLStorage = context.bot_data["mysql"]
    resolved = await mysql.resolve_session_id(update.effective_user.id, prefix)
    if not resolved:
        await update.message.reply_text(
            f"❌ No session found for <code>{prefix}</code>.",
            parse_mode=ParseMode.HTML,
        )
        return
    sid = resolved["session_id"]
    display = resolved.get("display_name")
    context.user_data["resume_session_id"] = sid
    await update.message.reply_text(
        f"🔄 Resuming session <code>{short_name(sid, display)}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mysql: MySQLStorage = context.bot_data["mysql"]
    settings = context.bot_data["settings"]
    session = await mysql.get_active_session(update.effective_user.id, settings.approved_directory, channel="telegram")
    if session:
        sid = short_name(session["session_id"], session.get("display_name"))
        turns = session["total_turns"]
        cost = session["total_cost"]
        path = session["project_path"].replace("/root/workspace", "~")
        await mysql.deactivate_session(session["session_id"], update.effective_user.id)
        await update.message.reply_text(
            f"✅ <b>Session ended</b>\n"
            f"   <code>{sid}</code>  {path}\n"
            f"   {turns} turns · ${cost:.4f}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("🔄 No active session.")


async def cmd_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        settings = context.bot_data["settings"]
        cwd = context.user_data.get("working_directory", settings.approved_directory)
        await update.message.reply_text(f"📁 <b>Working Directory</b>\n   {cwd}", parse_mode=ParseMode.HTML)
        return
    from .prefs import save_pref
    path = " ".join(context.args)
    await save_pref(context, update.effective_user.id, "working_directory", path)
    await update.message.reply_text(f"📁 <b>Working Directory</b>\n   → {path}", parse_mode=ParseMode.HTML)


async def cmd_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mysql: MySQLStorage = context.bot_data["mysql"]
    settings = context.bot_data["settings"]
    session = await mysql.get_active_session(update.effective_user.id, settings.approved_directory, channel="telegram")
    if not session:
        await update.message.reply_text("🔄 No active session.")
        return
    model = context.user_data.get("model", "default")
    mode = context.user_data.get("permission_mode", "yolo")
    verbose = context.user_data.get("verbose", 1)
    thinking = "an" if context.user_data.get("thinking", False) else "aus"
    path = session["project_path"].replace("/root/workspace", "~")
    await update.message.reply_text(
        f"🔄 <b>Aktive Session</b>\n"
        f"├─ ID: <code>{short_name(session['session_id'], session.get('display_name'))}</code>\n"
        f"├─ Projekt: {path}\n"
        f"├─ Turns: {session['total_turns']}\n"
        f"├─ Cost: ${session['total_cost']:.4f}\n"
        f"├─ Last active: {session['last_used'].replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Berlin')).strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"├─ Model: {model}\n"
        f"├─ Mode: {mode}\n"
        f"├─ Thinking: {thinking}\n"
        f"└─ Verbose: {verbose}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mysql: MySQLStorage = context.bot_data["mysql"]
    settings = context.bot_data["settings"]
    session = await mysql.get_active_session(update.effective_user.id, settings.approved_directory, channel="telegram")
    if not session:
        await update.message.reply_text("🔄 No active session.")
        return
    content = await mysql.get_session_content(session["session_id"], update.effective_user.id)
    if not content or not content.get("jsonl_content"):
        await update.message.reply_text("🔄 Session content not available.")
        return
    lines = [f"# Session {short_name(session['session_id'], session.get('display_name'))}\n"]
    for line in content["jsonl_content"].strip().split("\n"):
        try:
            msg = json.loads(line)
            role = msg.get("role", msg.get("type", "?"))
            text = msg.get("content", "")
            if isinstance(text, list):
                text = " ".join(b.get("text", "") for b in text if isinstance(b, dict))
            if text:
                lines.append(f"**{role}**: {text[:500]}\n")
        except json.JSONDecodeError:
            continue
    export = "\n".join(lines)
    f = BytesIO(export.encode("utf-8"))
    sn = short_name(session['session_id'], session.get('display_name'))
    f.name = f"session-{sn}.md"
    await update.message.reply_document(f, caption=f"📄 Export: {sn}")
