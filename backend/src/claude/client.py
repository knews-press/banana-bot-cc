"""Claude Code SDK wrapper with MySQL session sync, ES memory, and Telegram approval."""

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from typing import Any

import aiofiles
import structlog
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

from ..config import Settings
from ..storage.elasticsearch import ElasticsearchStorage
from ..storage.mysql import MySQLStorage
from ..storage.neo4j import Neo4jStorage
from ..tools.mcp_servers import (
    create_memory_server, create_cluster_server, create_comms_server,
    create_utils_server, create_uploads_server,
    create_tts_server, create_image_server, create_knowledge_server,
    _load_user_ontology,
)
from .approval import SAFE_TOOLS, ALL_TOOLS, approval_manager
from .session_sync import SessionSync

logger = structlog.get_logger()

# Known context window sizes per model family
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4": 1_000_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
}


def _get_context_window(model: str | None) -> int:
    """Return the context window size for a model, defaulting to 200k."""
    if model:
        for prefix, size in _MODEL_CONTEXT_WINDOWS.items():
            if model.startswith(prefix):
                return size
    return 200_000


# Berlin timezone (CET/CEST)
_BERLIN_TZ = timezone(timedelta(hours=1))  # CET; CEST would be +2

_LANGUAGE_LABELS = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
    "pl": "Polish",
    "tr": "Turkish",
}

DEFAULT_SYSTEM_PROMPT = """You are a personal AI assistant running as a self-hosted Telegram bot.
You have access to persistent memory, databases, and various tools.

Current date/time: {current_datetime}
{user_section}
## Memory (Elasticsearch)
- search_memory: Search memories by keyword. Use BEFORE answering questions about past work.
- save_memory: Save info. Type is a free string (e.g. user, project, decision, convention, article, thought, draft — or any domain-specific type).
- delete_memory: Remove by ID.
- list_memories: Show all.
- search_conversations: Full-text search over ALL past conversations.
When asked to remember → save_memory. When asked to recall → search_memory/search_conversations.
Proactively save decisions, preferences, and project state.
When saving knowledge, check existing memories for connections and mention non-obvious links.

## Databases
- query_mysql: SQL against the bot's MySQL database
- query_elasticsearch: Raw ES requests
- query_neo4j: Cypher queries against Neo4j (if knowledge graph is enabled)
- search_web: Web search via SearXNG (if enabled)

## Email
- send_email: Send emails via SMTP (if configured). Parameters: to, subject, body, html (optional).

## Telegram
- send_telegram: Send a Telegram message directly to the user and inject it into their active
  session (or a new one after 72h inactivity). The user can reply in context — you will have
  full conversation history. Use for proactive reports, reminders, and alerts.
  Parameters: text (plain text, no Markdown).

## Time
- current_time: Get current date/time. Use instead of Bash 'date' to save tokens.

## GitHub
Use the `gh` CLI via Bash (if GH_TOKEN is set).

## Telegram Uploads
Files sent via Telegram are automatically processed and indexed. Use these tools to access them:
- search_uploads: Full-text search across all uploaded files (PDFs, docs, videos, audio, images, etc.).
- get_upload: Retrieve full content of a specific upload by its upload_id.
- query_table: Query rows from a tabular upload (XLSX/CSV) stored in MySQL.
Media types: image, video, audio, pdf, docx, xlsx, csv, text, voice.
Voice messages are transcribed and passed directly as text prompts (not stored).

{language_instruction}"""


def _load_system_prompt_template() -> str:
    """Load system prompt from config file, falling back to built-in default."""
    import os
    prompt_file = os.environ.get("SYSTEM_PROMPT_FILE", "/app/config/system-prompt.md")
    try:
        with open(prompt_file, "r") as f:
            content = f.read().strip()
            if content:
                # Ensure the required placeholders are present
                if "{current_datetime}" not in content:
                    content = "Current date/time: {current_datetime}\n\n" + content
                if "{user_section}" not in content:
                    content += "\n{user_section}"
                if "{language_instruction}" not in content:
                    content += "\n{language_instruction}"
                return content
    except FileNotFoundError:
        pass
    return DEFAULT_SYSTEM_PROMPT


def _build_user_section(profile: dict) -> str:
    """Build the ## User section from a profile dict. Returns empty string if no profile."""
    lines = []
    if profile.get("display_name"):
        lines.append(f"- Name: {profile['display_name']}")
    if profile.get("email"):
        lines.append(f"- Email: {profile['email']}")

    gh = profile.get("github_username", "")
    if gh:
        lines.append(f"- GitHub: {gh}")

    if profile.get("custom_instructions"):
        lines.append(f"- Instructions: {profile['custom_instructions']}")

    if not lines:
        return ""
    return "\n## User\n" + "\n".join(lines) + "\n"


def _build_system_prompt(profile: dict | None = None) -> str:
    """Build system prompt with current date/time and optional user profile injected."""
    try:
        now = datetime.now().astimezone()
    except Exception:
        now = datetime.now(timezone.utc)
    current_dt = now.strftime("%A, %d %B %Y, %H:%M %Z")

    profile = profile or {}
    lang_code = profile.get("language", "de")
    lang_label = _LANGUAGE_LABELS.get(lang_code, "German")

    if lang_code == "de":
        lang_instruction = "The user's language is German. Respond in German unless asked otherwise."
    else:
        lang_instruction = f"The user's language is {lang_label}. Respond in {lang_label} unless asked otherwise."

    template = _load_system_prompt_template()
    return template.format(
        current_datetime=current_dt,
        user_section=_build_user_section(profile),
        language_instruction=lang_instruction,
    )


def find_claude_cli() -> str | None:
    path = shutil.which("claude")
    if path:
        return path
    for candidate in ["/usr/local/bin/claude", "/root/.local/bin/claude"]:
        if os.path.isfile(candidate):
            return candidate
    return None


# Permission modes
MODE_YOLO = "yolo"          # All tools auto-approved
MODE_PLAN = "plan"          # Read-only
MODE_APPROVE = "approve"    # Safe tools auto, rest via Telegram buttons


class ClaudeClient:
    """Claude Code with MySQL sessions, ES memory, and Telegram approval."""

    def __init__(self, settings: Settings, mysql: MySQLStorage, es: ElasticsearchStorage, uploads_storage=None, neo4j: Neo4jStorage | None = None):
        self.settings = settings
        self.mysql = mysql
        self.es = es
        self.uploads_storage = uploads_storage
        self.neo4j = neo4j
        self.cli_path = find_claude_cli()
        self.session_sync = SessionSync(mysql)
        # Cross-channel task registry: session_id → running asyncio.Task
        self._running_tasks: dict[str, asyncio.Task] = {}
        # Compaction events pending post-execute JSONL scan: session_id → metadata
        self._compaction_pending: dict[str, dict] = {}

    def register_task(self, session_id: str, task: asyncio.Task) -> None:
        """Register a running task so it can be cancelled cross-channel."""
        self._running_tasks[session_id] = task

    def unregister_task(self, session_id: str) -> None:
        """Remove a task from the registry (call in finally block)."""
        self._running_tasks.pop(session_id, None)

    def cancel_task(self, session_id: str) -> bool:
        """Cancel a running task by session_id. Returns True if a task was cancelled."""
        task = self._running_tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def restore_sessions(self, user_id: int):
        await self.session_sync.restore_from_mysql(user_id)

    async def execute(
        self,
        prompt: str,
        user_id: int,
        session_id: str | None = None,
        cwd: str | None = None,
        on_message=None,
        mode: str = MODE_YOLO,
        model: str | None = None,
        profile: dict | None = None,
        max_turns: int | None = None,
        thinking: bool = False,
        thinking_budget: int = 10_000,
        budget: float | None = None,
        bot=None,
        chat_id: int | None = None,
    ) -> dict:
        """Execute a prompt through Claude Code.

        prompt: str for text, or list[dict] of SDK content blocks for multimodal (Vision)
        mode: 'yolo' (all auto), 'plan' (read-only), 'approve' (Telegram buttons)
        profile: user profile dict (display_name, language, github_username, …)
        max_turns: max agentic turns (None = global default from settings)
        thinking: enable extended thinking
        thinking_budget: token budget for thinking (default 10000)
        budget: max USD spend per execution (None = unlimited)
        Returns dict with: content, session_id, cost, duration_ms, tools_used
        """
        cwd = cwd or self.settings.approved_directory

        system_prompt = _build_system_prompt(profile)

        # Load user ontology once — used for dynamic tool descriptions + knowledge server
        user_ontology = await _load_user_ontology(self.es, user_id)

        # Create MCP servers for this request (bound to user_id)
        mcp_servers = {
            "memory": create_memory_server(
                self.es, user_id,
                neo4j=self.neo4j, settings=self.settings,
                ontology=user_ontology,
            ),
            "cluster": create_cluster_server(self.settings),
            "comms": create_comms_server(
                self.settings,
                bot=bot,
                mysql=self.mysql,
                user_id=user_id,
                chat_id=chat_id,
                cwd=cwd,
            ),
            "utils": create_utils_server(),
        }
        if self.uploads_storage is not None:
            mcp_servers["uploads"] = create_uploads_server(self.uploads_storage, self.mysql, user_id)
        if self.settings.gemini_api_key or self.settings.openai_api_key:
            mcp_servers["tts"] = create_tts_server(self.settings, user_id)
            mcp_servers["image"] = create_image_server(
                self.settings, user_id, bot=bot, chat_id=chat_id
            )
        if self.neo4j and user_ontology:
            # Knowledge graph tools are opt-in: only available if user has a _graph_schema memory
            mcp_servers["knowledge"] = create_knowledge_server(
                self.neo4j, self.settings, user_id, ontology=user_ontology,
            )

        # Build options based on mode
        effective_max_turns = max_turns or self.settings.claude_max_turns
        logger.info("execute: building options", mode=mode, user_id=user_id)
        _approve_callback = None
        if mode == MODE_PLAN:
            options = ClaudeAgentOptions(
                allowed_tools=list(SAFE_TOOLS),
                permission_mode="plan",
                max_turns=effective_max_turns,
                cwd=cwd,
                system_prompt=system_prompt,
                mcp_servers=mcp_servers,
            )
        elif mode == MODE_APPROVE:
            _approve_callback = self._make_approve_callback(user_id)
            # Only pre-approve SAFE_TOOLS — dangerous tools (Bash, Write, Edit)
            # are NOT in allowed_tools, so the CLI will ask permission for them
            # via the can_use_tool callback.
            options = ClaudeAgentOptions(
                allowed_tools=list(SAFE_TOOLS),
                permission_mode="default",
                can_use_tool=_approve_callback,
                max_turns=effective_max_turns,
                cwd=cwd,
                system_prompt=system_prompt,
                mcp_servers=mcp_servers,
            )
        else:  # MODE_YOLO
            options = ClaudeAgentOptions(
                allowed_tools=list(ALL_TOOLS),
                permission_mode="dontAsk",
                max_turns=effective_max_turns,
                cwd=cwd,
                system_prompt=system_prompt,
                mcp_servers=mcp_servers,
            )

        if model:
            options.model = model

        # Extended thinking
        if thinking:
            options.thinking = {"type": "enabled", "budget_tokens": thinking_budget}

        # Per-execution budget cap
        if budget and isinstance(budget, (int, float)) and budget > 0:
            options.max_budget_usd = float(budget)

        if self.cli_path:
            options.cli_path = self.cli_path

        if session_id:
            options.resume = session_id

        # Register PreCompact hook so we learn when SDK auto-compaction fires
        options.hooks = {"PreCompact": [HookMatcher(hooks=[self._make_precompact_hook(user_id)])]}

        result_content = ""
        result_session_id = session_id
        result_cost = 0.0
        result_usage = {}
        result_model_usage = {}
        result_model = model or ""
        result_context_usage = None
        tools_used = []
        start = asyncio.get_event_loop().time()

        _last_tool_time = None
        _last_tool_name = None

        async def _run_claude():
            nonlocal result_content, result_session_id, result_cost
            nonlocal result_usage, result_model_usage, result_model, result_context_usage
            nonlocal _last_tool_time, _last_tool_name

            # Buffer for the most recent assistant text block.
            # Each time a new text arrives while one is pending, the old one is
            # emitted as `thinking_text` (intermediate) — visible in the collapsible
            # reasoning area.  Only the last text is emitted as `text` (final answer).
            _pending_text: str | None = None
            async with ClaudeSDKClient(options=options) as client:
                # The Claude Code SDK query() only accepts a plain string.
                # For multimodal input (images), the list has already been
                # converted to a text prompt containing the file path — Claude
                # Code's Read tool handles images natively.
                query_text = prompt if isinstance(prompt, str) else str(prompt)
                await client.query(query_text)

                async for message in client.receive_response():
                    cls = type(message).__name__

                    if cls == "AssistantMessage":
                        # Track model used
                        msg_model = getattr(message, "model", "")
                        if msg_model:
                            result_model = msg_model

                        for block in getattr(message, "content", []):
                            # Thinking/reasoning block (claude-agent-sdk wraps
                            # Anthropic ThinkingBlock — check .thinking attr first)
                            if hasattr(block, "thinking") and block.thinking:
                                if on_message:
                                    await on_message("thinking_text", block.thinking, {})
                            elif hasattr(block, "text"):
                                if on_message:
                                    # If a previous text is pending, demote it to
                                    # intermediate (thinking) before buffering the new one.
                                    if _pending_text is not None:
                                        await on_message("thinking_text", _pending_text, {})
                                    _pending_text = block.text
                            elif hasattr(block, "name"):
                                tool_name = block.name
                                tool_input = getattr(block, "input", {}) or {}
                                tools_used.append(tool_name)
                                _last_tool_time = asyncio.get_event_loop().time()
                                _last_tool_name = tool_name
                                if on_message:
                                    await on_message("tool_start", tool_name, tool_input)

                    elif cls in ("ToolResultMessage", "ToolResult") or (
                        cls == "UserMessage" and (
                            # tool_use_result is always set for tool-result UserMessages;
                            # parent_tool_use_id is always None (not reliable as discriminator).
                            # Also accept if content contains a ToolResultBlock (MCP tools).
                            getattr(message, "tool_use_result", None) is not None or
                            any(
                                type(b).__name__ == "ToolResultBlock"
                                for b in (getattr(message, "content", None) or [])
                                if not isinstance(b, str)
                            )
                        )
                    ):
                        # Tool finished — calc duration.
                        # The SDK emits tool results as UserMessage with tool_use_result dict
                        # set (built-in tools like Bash) or ToolResultBlock in .content (MCP).
                        # parent_tool_use_id is always None — do not use it as discriminator.
                        duration = 0.0
                        if _last_tool_time:
                            duration = asyncio.get_event_loop().time() - _last_tool_time
                        is_error = getattr(message, "is_error", False) or False
                        content = getattr(message, "content", "")
                        # For UserMessage: extract from ToolResultBlock in content list
                        if isinstance(content, list):
                            for block in content:
                                block_cls = type(block).__name__
                                if block_cls == "ToolResultBlock":
                                    is_error = getattr(block, "is_error", False) or False
                                    content = getattr(block, "content", "") or ""
                                    break
                        if isinstance(content, list):
                            content = " ".join(
                                b.get("text", "") for b in content if isinstance(b, dict)
                            )
                        if on_message:
                            await on_message("tool_result", _last_tool_name or "?", {
                                "success": not is_error,
                                "duration": duration,
                                "preview": str(content)[:150] if content else "",
                            })
                        _last_tool_time = None

                    elif cls == "ResultMessage":
                        result_content = getattr(message, "result", "")
                        result_session_id = getattr(message, "session_id", session_id)
                        result_cost = getattr(message, "total_cost_usd", 0.0) or 0.0
                        _usage_obj = getattr(message, "usage", None)
                        if _usage_obj is not None and hasattr(_usage_obj, "model_dump"):
                            result_usage = _usage_obj.model_dump()
                        elif isinstance(_usage_obj, dict):
                            result_usage = _usage_obj
                        else:
                            result_usage = {}
                        _model_usage_obj = getattr(message, "model_usage", None)
                        if _model_usage_obj is not None and hasattr(_model_usage_obj, "model_dump"):
                            result_model_usage = _model_usage_obj.model_dump()
                        elif isinstance(_model_usage_obj, dict):
                            result_model_usage = _model_usage_obj
                        else:
                            result_model_usage = {}

                # Query SDK for accurate context window usage while still connected
                try:
                    result_context_usage = await client.get_context_usage()
                except Exception as e:
                    logger.debug("get_context_usage failed", error=str(e))

            # Flush the final pending text as the actual response.
            # All earlier texts were already emitted as thinking_text above.
            if _pending_text is not None and on_message:
                await on_message("text", _pending_text, {})

        try:
            await asyncio.wait_for(_run_claude(), timeout=self.settings.claude_timeout_seconds)
        except asyncio.TimeoutError:
            logger.error("Claude execution timed out", timeout=self.settings.claude_timeout_seconds)
            raise TimeoutError(f"Claude hat nach {self.settings.claude_timeout_seconds}s nicht geantwortet")
        except Exception as e:
            logger.error("Claude execution failed", error=str(e))
            raise

        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        # POST: sync session JSONL to MySQL
        if result_session_id:
            await self.session_sync.save_to_mysql(result_session_id, user_id, cwd)
            # Check whether SDK compaction occurred during this execution
            await self._maybe_persist_compaction(result_session_id, user_id, on_message)

        # Emit live context-usage indicator — prefer SDK's own measurement
        if on_message:
            if result_context_usage:
                await on_message("context_usage", "", {
                    "input_tokens": result_context_usage["totalTokens"],
                    "max_tokens": result_context_usage["maxTokens"],
                    "percentage": result_context_usage["percentage"],
                })
            elif result_usage:
                # Fallback: sum all token types from API response
                total_context = (
                    result_usage.get("input_tokens", 0)
                    + result_usage.get("cache_creation_input_tokens", 0)
                    + result_usage.get("cache_read_input_tokens", 0)
                )
                context_max = _get_context_window(result_model)
                await on_message("context_usage", "", {
                    "input_tokens": total_context,
                    "max_tokens": context_max,
                })

        return {
            "content": result_content,
            "session_id": result_session_id,
            "cost": result_cost,
            "duration_ms": elapsed,
            "tools_used": list(set(tools_used)),
            "model": result_model,
            "usage": result_usage,
            "model_usage": result_model_usage,
            "context_tokens": result_context_usage["totalTokens"] if result_context_usage else 0,
            "context_max_tokens": result_context_usage["maxTokens"] if result_context_usage else _get_context_window(result_model),
        }

    def _make_precompact_hook(self, user_id: int):
        """Return a PreCompact hook callback.

        The SDK/CLI fires this BEFORE it compacts the session JSONL.
        We record the transcript path so we can extract the summary after
        execute() completes and persist it to MySQL.
        """
        async def on_precompact(input_data, tool_use_id, context):
            sid = input_data.get("session_id", "")
            path = input_data.get("transcript_path", "")
            trigger = input_data.get("trigger", "auto")
            logger.info("SDK compaction triggered", session_id=sid, trigger=trigger)
            if sid:
                self._compaction_pending[sid] = {
                    "transcript_path": path,
                    "trigger": trigger,
                    "user_id": user_id,
                }
            return {"continue_": True}

        return on_precompact

    async def _extract_compact_summary_from_jsonl(self, transcript_path: str) -> str | None:
        """Scan the session JSONL for the most recent isCompactSummary entry."""
        try:
            summary_entries = []
            async with aiofiles.open(transcript_path, encoding="utf-8") as fh:
                async for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("isCompactSummary"):
                            summary_entries.append(entry)
                    except json.JSONDecodeError:
                        continue
            if not summary_entries:
                return None
            content = summary_entries[-1].get("message", {}).get("content", "")
            if isinstance(content, list):
                return "\n".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ).strip() or None
            return str(content).strip() or None
        except Exception as e:
            logger.warning("could not read compact summary from jsonl",
                           path=transcript_path, error=str(e))
            return None

    async def _maybe_persist_compaction(
        self,
        session_id: str,
        user_id: int,
        on_message,
    ) -> None:
        """After execute(), check if SDK compaction occurred and persist to MySQL."""
        pending = self._compaction_pending.pop(session_id, None)
        if not pending:
            return

        transcript_path = pending.get("transcript_path", "")
        trigger = pending.get("trigger", "auto")

        summary = None
        if transcript_path:
            summary = await self._extract_compact_summary_from_jsonl(transcript_path)

        await self.mysql.save_compaction_event(
            session_id=session_id,
            user_id=user_id,
            summary=summary or "",
            trigger=trigger,
        )

        trigger_label = "manuell" if trigger == "manual" else "automatisch"
        if on_message:
            await on_message(
                "compaction",
                f"⚡ Kontext {trigger_label} kompaktiert — Session läuft nahtlos weiter.",
                {"trigger": trigger, "session_id": session_id},
            )

        logger.info("compaction event persisted",
                    session_id=session_id, trigger=trigger, has_summary=bool(summary))

    def _make_approve_callback(self, user_id: int):
        """Create a can_use_tool callback for approve mode.

        Safe tools (Read, Grep, MCP tools, etc.) are auto-approved.
        Dangerous tools (Bash, Write, Edit) trigger a Telegram approval request
        with inline buttons (Allow / Deny / Always Allow).
        """
        async def callback(
            tool_name: str,
            tool_input: dict[str, Any],
            ctx: ToolPermissionContext,
        ) -> PermissionResultAllow | PermissionResultDeny:
            logger.info("approve callback invoked",
                        tool=tool_name, user_id=user_id,
                        is_safe=tool_name in SAFE_TOOLS,
                        has_bot=approval_manager.bot is not None,
                        has_chat_id=approval_manager.chat_id is not None)
            # Safe tools are always allowed
            if tool_name in SAFE_TOOLS:
                return PermissionResultAllow()

            # Check runtime "always allow" list
            if approval_manager.is_always_allowed(user_id, tool_name, tool_input):
                logger.info("approve: always-allowed", tool=tool_name, user_id=user_id)
                return PermissionResultAllow()

            # Ask user via Telegram buttons
            logger.info("approve: requesting Telegram approval", tool=tool_name, user_id=user_id)
            allowed, updated_input = await approval_manager.request_approval(
                user_id, tool_name, tool_input
            )
            if allowed:
                if updated_input != tool_input:
                    return PermissionResultAllow(updated_input=updated_input)
                return PermissionResultAllow()
            return PermissionResultDeny(message="Vom Benutzer abgelehnt")

        return callback

