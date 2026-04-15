"""Memory commands."""

import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...storage.elasticsearch import ElasticsearchStorage
from ...utils.session_names import short_name

TYPE_ICONS = {"user": "👤", "feedback": "💬", "project": "📋", "reference": "🔗"}


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    es: ElasticsearchStorage = context.bot_data["es"]
    memories = await es.get_all_memories(update.effective_user.id, limit=30)
    if not memories:
        await update.message.reply_text("🧠 Keine gespeicherten Memories.")
        return

    by_type: dict[str, list] = {}
    for m in memories:
        by_type.setdefault(m["type"], []).append(m)

    lines = ["🧠 <b>Memories</b>\n"]
    for mem_type, items in sorted(by_type.items()):
        icon = TYPE_ICONS.get(mem_type, "📌")
        lines.append(f"\n{icon} <b>{mem_type.capitalize()}</b>")
        for m in items:
            name = html.escape(m["name"])
            desc = html.escape(m.get("description", "")[:80])
            mid = m["id"][:8]
            lines.append(f"  · <b>{name}</b>\n    {desc}\n    <code>{mid}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /remember <text>")
        return
    text = " ".join(context.args)
    es: ElasticsearchStorage = context.bot_data["es"]
    doc_id = await es.save_memory(
        user_id=update.effective_user.id,
        name=text[:50],
        memory_type="user",
        description=text,
        content=text,
    )
    await update.message.reply_text(
        f"✅ <b>Memory gespeichert</b>\n"
        f"   📌 \"{html.escape(text[:80])}\"\n"
        f"   <code>{doc_id[:8]}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /forget <memory_id>")
        return
    mid = context.args[0]
    es: ElasticsearchStorage = context.bot_data["es"]
    ok = await es.delete_memory(mid, update.effective_user.id)
    if ok:
        await update.message.reply_text(f"✅ Memory <code>{mid[:8]}</code> soft-deleted (History bleibt erhalten).", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"❌ Memory <code>{mid[:8]}</code> not found.", parse_mode=ParseMode.HTML)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search <query>")
        return
    query = " ".join(context.args)
    es: ElasticsearchStorage = context.bot_data["es"]
    results = await es.search_conversations(update.effective_user.id, query, limit=5)
    if not results:
        await update.message.reply_text(f"🔍 No results for \"{html.escape(query)}\".", parse_mode=ParseMode.HTML)
        return
    lines = [f"🔍 <b>Konversationen: \"{html.escape(query)}\"</b>\n"]
    for r in results:
        role = "👤" if r.get("role") == "user" else "🤖"
        content = html.escape(r.get("content", "")[:150])
        ts = r.get("timestamp", "")[:16]
        sid = short_name(r.get("session_id", ""))
        lines.append(f"{role} <i>{ts}</i>  <code>{sid}</code>\n   {content}")
    await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_recall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /recall <query>")
        return
    query = " ".join(context.args)
    es: ElasticsearchStorage = context.bot_data["es"]
    results = await es.search_memories(update.effective_user.id, query, limit=10)
    if not results:
        await update.message.reply_text(f"🧠 Keine Memories zu \"{html.escape(query)}\".", parse_mode=ParseMode.HTML)
        return
    lines = [f"🧠 <b>Memories: \"{html.escape(query)}\"</b>\n"]
    for m in results:
        icon = TYPE_ICONS.get(m.get("type", ""), "📌")
        name = html.escape(m["name"])
        content = html.escape(m.get("content", "")[:150])
        lines.append(f"{icon} <b>{name}</b>\n   {content}")
    await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)
