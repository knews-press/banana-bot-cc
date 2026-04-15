"""User management commands (owner only)."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...storage.mysql import MySQLStorage


async def cmd_useradd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add or enable a user. Usage: /useradd <telegram_id> [email] [display_name]"""
    settings = context.bot_data["settings"]
    if update.effective_user.id != settings.owner_user_id:
        await update.message.reply_text("⛔ Only the owner can manage users.")
        return

    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "Usage: /useradd &lt;telegram_id&gt; [email] [display_name]\n"
            "Example: /useradd 123456789 user@example.com Jane Doe",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Telegram-ID muss eine Zahl sein.")
        return

    email = context.args[1] if len(context.args) > 1 else None
    display_name = " ".join(context.args[2:]) if len(context.args) > 2 else None

    mysql: MySQLStorage = context.bot_data["mysql"]
    await mysql.add_user(user_id, email=email, display_name=display_name)

    # Invalidate auth cache
    from ..handlers import _invalidate_auth_cache
    _invalidate_auth_cache(user_id)

    parts = [f"✅ User <code>{user_id}</code> aktiviert."]
    if email:
        parts.append(f"📧 {email}")
    if display_name:
        parts.append(f"👤 {display_name}")
    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.HTML)


async def cmd_userdel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable a user. Usage: /userdel <telegram_id>"""
    settings = context.bot_data["settings"]
    if update.effective_user.id != settings.owner_user_id:
        await update.message.reply_text("⛔ Only the owner can manage users.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /userdel &lt;telegram_id&gt;", parse_mode=ParseMode.HTML)
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Telegram-ID muss eine Zahl sein.")
        return

    mysql: MySQLStorage = context.bot_data["mysql"]
    removed = await mysql.remove_user(user_id)

    # Invalidate auth cache
    from ..handlers import _invalidate_auth_cache
    _invalidate_auth_cache(user_id)

    if removed:
        await update.message.reply_text(
            f"✅ User <code>{user_id}</code> deaktiviert.", parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"❌ User <code>{user_id}</code> not found.", parse_mode=ParseMode.HTML
        )


async def cmd_userlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all allowed users."""
    settings = context.bot_data["settings"]
    if update.effective_user.id != settings.owner_user_id:
        await update.message.reply_text("⛔ Only the owner can manage users.")
        return

    mysql: MySQLStorage = context.bot_data["mysql"]
    users = await mysql.list_users()

    if not users:
        await update.message.reply_text("👥 Keine aktiven User.")
        return

    lines = ["👥 <b>Aktive User</b>\n"]
    for u in users:
        uid = u["user_id"]
        name = u["display_name"] or u["telegram_username"] or "—"
        email = u["email"] or "—"
        cost = u["total_cost"]
        lines.append(f"  <code>{uid}</code> {name}\n     📧 {email} · ${cost:.2f}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
