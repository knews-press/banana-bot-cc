"""User profile commands (/me)."""

import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .prefs import save_pref

_LANGUAGE_OPTIONS = {
    "de": "🇩🇪 Deutsch",
    "en": "🇬🇧 English",
    "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español",
    "it": "🇮🇹 Italiano",
    "nl": "🇳🇱 Nederlands",
    "pt": "🇵🇹 Português",
    "pl": "🇵🇱 Polski",
    "tr": "🇹🇷 Türkçe",
}


async def cmd_me_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current user profile."""
    ud = context.user_data
    name    = ud.get("display_name") or "—"
    lang    = ud.get("language", "de")
    gh      = ud.get("github_username") or "—"
    email   = ud.get("email") or "—"
    instr   = ud.get("custom_instructions") or "—"

    lang_label = _LANGUAGE_OPTIONS.get(lang, lang)

    await update.message.reply_text(
        "👤 <b>Your Profile</b>\n\n"
        f"├─ Name:         <b>{html.escape(name)}</b>\n"
        f"├─ Language:     <b>{lang_label}</b>\n"
        f"├─ GitHub:       <b>{html.escape(gh)}</b>\n"
        f"├─ Email:        <b>{html.escape(email)}</b>\n"
        f"└─ Instructions: <i>{html.escape(instr)}</i>\n\n"
        "Edit with:\n"
        "  <code>/me name</code> <i>Your Name</i>\n"
        "  <code>/me lang</code> <i>de|en|fr|es|…</i>\n"
        "  <code>/me github</code> <i>username</i>\n"
        "  <code>/me email</code> <i>address@example.com</i>\n"
        "  <code>/me instructions</code> <i>Free text</i>\n"
        "  <code>/me clear instructions</code>  Clear field",
        parse_mode=ParseMode.HTML,
    )


async def cmd_me_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: <code>/me name Dein Name</code>", parse_mode=ParseMode.HTML)
        return
    value = " ".join(context.args)
    await save_pref(context, update.effective_user.id, "display_name", value)
    await update.message.reply_text(f"✅ Name set: <b>{html.escape(value)}</b>", parse_mode=ParseMode.HTML)


async def cmd_me_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        opts = "  ".join(f"<code>{k}</code>" for k in _LANGUAGE_OPTIONS)
        await update.message.reply_text(
            f"Usage: <code>/me lang</code> <i>code</i>\n\nAvailable: {opts}",
            parse_mode=ParseMode.HTML,
        )
        return
    code = context.args[0].lower()
    if code not in _LANGUAGE_OPTIONS:
        opts = ", ".join(_LANGUAGE_OPTIONS.keys())
        await update.message.reply_text(
            f"❌ Unknown: <code>{html.escape(code)}</code>\nAvailable: {opts}",
            parse_mode=ParseMode.HTML,
        )
        return
    await save_pref(context, update.effective_user.id, "language", code)
    await update.message.reply_text(
        f"✅ Language set: <b>{_LANGUAGE_OPTIONS[code]}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_me_github(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: <code>/me github username</code>", parse_mode=ParseMode.HTML)
        return
    value = context.args[0].strip()
    await save_pref(context, update.effective_user.id, "github_username", value)
    await update.message.reply_text(f"✅ GitHub: <b>{html.escape(value)}</b>", parse_mode=ParseMode.HTML)


async def cmd_me_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: <code>/me email address@example.com</code>", parse_mode=ParseMode.HTML)
        return
    value = context.args[0].strip()
    await save_pref(context, update.effective_user.id, "email", value)
    await update.message.reply_text(f"✅ E-Mail: <b>{html.escape(value)}</b>", parse_mode=ParseMode.HTML)


async def cmd_me_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/me instructions Free text</code>\n"
            "Löschen: <code>/me instructions clear</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    # Allow "clear" as special value to delete
    if context.args[0].lower() == "clear":
        await save_pref(context, update.effective_user.id, "custom_instructions", "")
        await update.message.reply_text("✅ Instructions cleared.", parse_mode=ParseMode.HTML)
        return
    value = " ".join(context.args)
    await save_pref(context, update.effective_user.id, "custom_instructions", value)
    await update.message.reply_text(
        f"✅ Instructions set:\n<i>{html.escape(value)}</i>",
        parse_mode=ParseMode.HTML,
    )
