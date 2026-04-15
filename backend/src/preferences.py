"""Central preferences resolver — single source of truth for both channels.

Both Telegram and WebUI call resolve_execute_args() before every execute().
This ensures consistent behavior regardless of which channel the user is on.
"""

import structlog

from .config import Settings

logger = structlog.get_logger()

# Profile keys injected into the system prompt
PROFILE_KEYS = {
    "display_name", "language", "github_username",
    "email", "custom_instructions",
}

# Models that support extended thinking
_THINKING_MODELS = {
    "claude-sonnet-4-6",
    "claude-opus-4-6",
}

# Safety bounds
_MIN_MAX_TURNS = 3
_MAX_MAX_TURNS = 200
_MIN_BUDGET_USD = 0.01
_MAX_BUDGET_USD = 50.0
_DEFAULT_THINKING_BUDGET = 10_000
_MIN_THINKING_BUDGET = 1_024
_MAX_THINKING_BUDGET = 128_000


async def resolve_execute_args(mysql, settings: Settings, user_id: int) -> dict:
    """Load user preferences from MySQL and return a dict ready for execute().

    Returns:
        dict with keys: mode, model, profile, max_turns, thinking,
        thinking_budget, budget, verbose, working_directory
    """
    prefs = await mysql.get_preferences(user_id)

    # --- Model resolution: user pref > env default > None (CLI decides) ---
    user_model = prefs.get("model", "default")
    if user_model and user_model != "default":
        model = user_model
    elif settings.claude_default_model:
        model = settings.claude_default_model
    else:
        model = None

    # --- Profile for system prompt ---
    profile = {k: prefs[k] for k in PROFILE_KEYS if prefs.get(k)}

    # --- Permission mode ---
    mode = prefs.get("permission_mode", "yolo")
    if mode not in ("yolo", "approve", "plan"):
        logger.warning("Invalid permission_mode, falling back to yolo", mode=mode, user_id=user_id)
        mode = "yolo"

    # --- Max turns with safety bounds ---
    raw_turns = prefs.get("max_turns")
    if isinstance(raw_turns, int) and raw_turns > 0:
        max_turns = max(_MIN_MAX_TURNS, min(raw_turns, _MAX_MAX_TURNS))
    else:
        max_turns = settings.claude_max_turns

    # --- Thinking ---
    thinking = bool(prefs.get("thinking", False))
    thinking_budget = prefs.get("thinking_budget", _DEFAULT_THINKING_BUDGET)
    if isinstance(thinking_budget, int):
        thinking_budget = max(_MIN_THINKING_BUDGET, min(thinking_budget, _MAX_THINKING_BUDGET))
    else:
        thinking_budget = _DEFAULT_THINKING_BUDGET

    # Disable thinking for models that don't support it
    if thinking and model and model not in _THINKING_MODELS:
        logger.info("Thinking disabled — model does not support it", model=model)
        thinking = False

    # --- Budget ---
    raw_budget = prefs.get("budget")
    if isinstance(raw_budget, (int, float)) and raw_budget > 0:
        budget = max(_MIN_BUDGET_USD, min(float(raw_budget), _MAX_BUDGET_USD))
    else:
        budget = None  # unlimited

    # --- Verbose (Telegram-only, but resolved centrally) ---
    verbose = prefs.get("verbose", 1)
    if not isinstance(verbose, int):
        verbose = 1

    # --- Working directory ---
    working_directory = prefs.get("working_directory") or settings.approved_directory

    return {
        "mode": mode,
        "model": model,
        "profile": profile,
        "max_turns": max_turns,
        "thinking": thinking,
        "thinking_budget": thinking_budget,
        "budget": budget,
        "verbose": verbose,
        "working_directory": working_directory,
    }
