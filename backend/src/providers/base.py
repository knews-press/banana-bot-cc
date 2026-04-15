"""Abstract base class for AI provider clients.

Every provider (Claude, Codex, Gemini, ...) must implement this interface.
The on_message callback follows a standardised event protocol so that both
Telegram and Web frontends can render progress identically.

Event types emitted via on_message(event_type, content, extra):
    tool_start     — Tool invocation started.    content=tool_name, extra=input_dict
    tool_result    — Tool finished.              content=tool_name, extra={success, duration, preview}
    text           — Final response text.        content=text,      extra={}
    thinking_text  — Intermediate reasoning.     content=text,      extra={}
    compaction     — Session compacted.           content=message,   extra={trigger, session_id}
    context_usage  — Context window usage.       content="",        extra={input_tokens, max_tokens, percentage?}
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable


# Type alias for the on_message callback
OnMessageCallback = Callable[[str, str, dict], Awaitable[None]]


class ProviderClient(ABC):
    """Abstract interface for AI code-execution providers."""

    # --- Provider metadata ---------------------------------------------------

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short machine-readable name, e.g. 'claude', 'codex'."""

    @property
    @abstractmethod
    def provider_display_name(self) -> str:
        """Human-readable label, e.g. 'Claude Code', 'OpenAI Codex'."""

    @abstractmethod
    def get_available_models(self) -> list[dict[str, Any]]:
        """Return list of models this provider offers.

        Each dict should have at least: {name, display_name, context_window}.
        """

    @abstractmethod
    def get_default_model(self) -> str:
        """Return the default model name for this provider."""

    # --- Execution -----------------------------------------------------------

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        user_id: int,
        session_id: str | None = None,
        cwd: str | None = None,
        on_message: OnMessageCallback | None = None,
        mode: str = "yolo",
        model: str | None = None,
        profile: dict | None = None,
        max_turns: int | None = None,
        thinking: bool = False,
        thinking_budget: int = 10_000,
        budget: float | None = None,
        # Transport-specific extras (Telegram bot, chat_id, runner)
        # are passed via **kwargs so the interface stays transport-agnostic.
        **kwargs,
    ) -> dict:
        """Execute a prompt and return a standardised result dict.

        Required keys in the returned dict:
            content          str   — Final response text
            session_id       str   — Session UUID (new or resumed)
            cost             float — USD cost
            duration_ms      int   — Execution wall-clock time
            tools_used       list  — Unique tool names invoked
            model            str   — Model name actually used
            usage            dict  — Token breakdown
            model_usage      dict  — Extended usage metadata
            context_tokens   int   — Current context token count
            context_max_tokens int — Context window limit
        """

    # --- Task management (cross-channel cancellation) ------------------------

    @abstractmethod
    def register_task(self, session_id: str, task: asyncio.Task) -> None:
        """Register a running task so it can be cancelled cross-channel."""

    @abstractmethod
    def unregister_task(self, session_id: str) -> None:
        """Remove a task from the registry."""

    @abstractmethod
    def cancel_task(self, session_id: str) -> bool:
        """Cancel a running task by session_id. Returns True if cancelled."""

    # --- Session management --------------------------------------------------

    @abstractmethod
    async def restore_sessions(self, user_id: int) -> None:
        """Restore session state from persistent storage (e.g. JSONL ↔ MySQL)."""
