"""Preference persistence helper for commands."""

from telegram.ext import ContextTypes

# UI/UX settings — persisted per user
PREF_KEYS = {
    "permission_mode", "model", "thinking", "thinking_budget", "max_turns",
    "budget", "verbose", "working_directory",
}

# Identity/profile fields — also persisted, injected into system prompt
PROFILE_KEYS = {
    "display_name", "language", "github_username",
    "email", "custom_instructions",
}

ALL_PREF_KEYS = PREF_KEYS | PROFILE_KEYS


async def save_pref(context: ContextTypes.DEFAULT_TYPE, user_id: int, key: str, value):
    """Save a preference or profile field to user_data AND persist to MySQL."""
    from ...storage.mysql import MySQLStorage

    context.user_data[key] = value
    if key in ALL_PREF_KEYS:
        mysql: MySQLStorage = context.bot_data["mysql"]
        prefs = await mysql.get_preferences(user_id)
        prefs[key] = value
        await mysql.save_preferences(user_id, prefs)
