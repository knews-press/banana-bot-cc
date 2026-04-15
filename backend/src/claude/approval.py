"""Telegram-based tool approval system.

When permission_mode is 'default', Claude asks for permission via can_use_tool.
This module sends approval requests to Telegram as inline buttons and waits
for the user's response.
"""

import asyncio
import uuid

import structlog

logger = structlog.get_logger()

# Tools that are always safe (no approval needed even in /approve mode)
SAFE_TOOLS = {
    "Read", "Glob", "Grep", "LS",
    "Task", "TaskOutput", "TodoRead", "TodoWrite",
    "NotebookRead",
    # MCP tools are always safe (they go through our own code)
    "mcp__memory__search_memory",
    "mcp__memory__save_memory",
    "mcp__memory__delete_memory",
    "mcp__memory__purge_memory",
    "mcp__memory__memory_history",
    "mcp__memory__list_memories",
    "mcp__memory__search_conversations",
    # Knowledge graph (read-only)
    "mcp__knowledge__graph_search",
    "mcp__knowledge__graph_explore",
    "mcp__knowledge__graph_topics",
    "mcp__knowledge__graph_stats",
    "mcp__cluster__query_mysql",
    "mcp__cluster__query_elasticsearch",
    "mcp__cluster__query_neo4j",
    "mcp__cluster__search_web",
    "mcp__comms__send_email",
    "mcp__comms__send_telegram",
    "mcp__comms__create_document",
    "mcp__comms__send_file",
    "mcp__utils__current_time",
    # Uploads
    "mcp__uploads__search_uploads",
    "mcp__uploads__get_upload",
    "mcp__uploads__query_table",
    # TTS
    "mcp__tts__generate_tts",
    "mcp__tts__set_tts_settings",
    # Image generation
    "mcp__image__generate_image",
    "mcp__image__set_image_settings",
    # Job management
    "mcp__jobs__create_cronjob",
    "mcp__jobs__create_job",
    "mcp__jobs__list_jobs",
    "mcp__jobs__delete_job",
    "mcp__jobs__run_job_now",
    "mcp__jobs__get_job_logs",
}

# All tools including ones that need approval
ALL_TOOLS = SAFE_TOOLS | {
    "Write", "Edit", "MultiEdit", "Bash",
    "WebFetch", "WebSearch", "NotebookEdit",
}


def _summarize_tool(tool_name: str, input_data: dict) -> str:
    """Create a human-readable summary of a tool call."""
    if tool_name == "Bash":
        return f"🖥 Bash: {input_data.get('command', '?')[:200]}"
    elif tool_name in ("Write", "Edit", "MultiEdit"):
        path = input_data.get("file_path", input_data.get("path", "?"))
        return f"📝 {tool_name}: {path}"
    elif tool_name == "WebFetch":
        return f"🌐 WebFetch: {input_data.get('url', '?')[:100]}"
    elif tool_name == "WebSearch":
        return f"🔍 WebSearch: {input_data.get('query', '?')[:100]}"
    elif tool_name == "NotebookEdit":
        return f"📓 NotebookEdit: {input_data.get('notebook_path', '?')}"
    return f"🔧 {tool_name}"


class TelegramApprovalManager:
    """Manages pending approval requests sent via Telegram inline buttons."""

    def __init__(self):
        # approval_id -> asyncio.Event
        self._events: dict[str, asyncio.Event] = {}
        # approval_id -> "allow" | "deny" | "always"
        self._decisions: dict[str, str] = {}
        # Persistently allowed tool patterns (runtime, per user)
        self._always_allowed: dict[int, set[str]] = {}
        # Reference to Telegram bot (set by handlers.py)
        self.bot = None
        self.chat_id: int | None = None

    def set_bot(self, bot, chat_id: int):
        """Set the Telegram bot and chat for sending approval messages."""
        self.bot = bot
        self.chat_id = chat_id

    def is_always_allowed(self, user_id: int, tool_name: str, input_data: dict) -> bool:
        """Check if this tool is in the user's runtime always-allow list."""
        user_allowed = self._always_allowed.get(user_id, set())
        # Check exact tool name
        if tool_name in user_allowed:
            return True
        # Check tool with pattern (e.g. "Bash(git *)")
        if tool_name == "Bash":
            cmd = input_data.get("command", "")
            for pattern in user_allowed:
                if pattern.startswith("Bash(") and pattern.endswith(")"):
                    # Simple prefix match
                    prefix = pattern[5:-1].rstrip("*").rstrip(" ")
                    if cmd.startswith(prefix):
                        return True
        return False

    def add_always_allowed(self, user_id: int, tool_name: str, input_data: dict):
        """Add a tool to the user's runtime always-allow list."""
        if user_id not in self._always_allowed:
            self._always_allowed[user_id] = set()
        if tool_name == "Bash":
            # Allow the specific command prefix
            cmd = input_data.get("command", "")
            first_word = cmd.split()[0] if cmd.split() else cmd
            self._always_allowed[user_id].add(f"Bash({first_word} *)")
            logger.info("Added always-allow", user_id=user_id, pattern=f"Bash({first_word} *)")
        else:
            self._always_allowed[user_id].add(tool_name)
            logger.info("Added always-allow", user_id=user_id, tool=tool_name)

    async def request_approval(self, user_id: int, tool_name: str,
                               input_data: dict) -> tuple[bool, dict]:
        """Send approval request via Telegram and wait for response.

        Returns (allowed: bool, updated_input: dict)
        """
        if not self.bot or not self.chat_id:
            logger.warning("No Telegram bot configured for approvals, auto-denying",
                           tool=tool_name, user_id=user_id,
                           bot_type=type(self.bot).__name__ if self.bot else "None",
                           chat_id=self.chat_id)
            return False, input_data

        # Check runtime always-allow
        if self.is_always_allowed(user_id, tool_name, input_data):
            return True, input_data

        approval_id = str(uuid.uuid4())[:8]
        summary = _summarize_tool(tool_name, input_data)

        # Create event for waiting
        event = asyncio.Event()
        self._events[approval_id] = event

        # Send Telegram message with inline buttons
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Allow", callback_data=f"approve:{approval_id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"deny:{approval_id}"),
            ],
            [
                InlineKeyboardButton("✅ Always allow", callback_data=f"always:{approval_id}"),
            ],
        ])

        await self.bot.send_message(
            self.chat_id,
            f"⚠️ Approval required:\n\n{summary}",
            reply_markup=keyboard,
        )

        # Store tool info for "always" decision
        self._decisions[f"{approval_id}_tool"] = tool_name
        self._decisions[f"{approval_id}_input"] = input_data

        # Wait for response (timeout 5 minutes)
        try:
            await asyncio.wait_for(event.wait(), timeout=300)
        except asyncio.TimeoutError:
            self._cleanup(approval_id)
            await self.bot.send_message(self.chat_id, "⏰ Timeout — request denied.")
            return False, input_data

        decision = self._decisions.get(approval_id, "deny")

        if decision == "always":
            self.add_always_allowed(user_id, tool_name, input_data)
            self._cleanup(approval_id)
            return True, input_data
        elif decision == "allow":
            self._cleanup(approval_id)
            return True, input_data
        else:
            self._cleanup(approval_id)
            return False, input_data

    def resolve(self, approval_id: str, decision: str):
        """Called by Telegram callback handler when user clicks a button."""
        self._decisions[approval_id] = decision
        event = self._events.get(approval_id)
        if event:
            event.set()

    def _cleanup(self, approval_id: str):
        self._events.pop(approval_id, None)
        self._decisions.pop(f"{approval_id}_tool", None)
        self._decisions.pop(f"{approval_id}_input", None)


# Global instance
approval_manager = TelegramApprovalManager()
