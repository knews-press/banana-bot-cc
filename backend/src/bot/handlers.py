"""Telegram handler registration and main message handler."""

import asyncio
import html
import re

import telegramify_markdown
import structlog
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from ..bus import live_bus
from ..claude.approval import approval_manager
from ..claude.client import ClaudeClient, MODE_YOLO
from ..config import Settings
from ..preferences import resolve_execute_args
from ..storage.elasticsearch import ElasticsearchStorage
from ..storage.mysql import MySQLStorage
from ..storage.uploads import UploadsStorage
from ..tools.email import send_email
from .media import MediaProcessor

from .auth_flow import is_authenticated, ensure_authenticated, build_auth_url, exchange_code, save_credentials
from .commands.dispatch import (
    cmd_new, cmd_session, cmd_status, cmd_model_cmd, cmd_mode,
    cmd_me, cmd_memory_dispatch,
)
from .commands.claude_code import cmd_stop
from .commands.utils import cmd_help

# Auth cache invalidation (called from commands/users.py)
_auth_cache_ref = None

def _invalidate_auth_cache(user_id: int | None = None):
    """Clear auth cache entry or entire cache."""
    if _auth_cache_ref is None:
        return
    if user_id is not None:
        _auth_cache_ref.pop(user_id, None)
    else:
        _auth_cache_ref.clear()

logger = structlog.get_logger()

MAX_TELEGRAM_LENGTH = 4000


def _is_markdown(text: str) -> bool:
    """Check if text contains markdown formatting."""
    return bool(re.search(r'[*_`\[\]#]', text))


def _escape_md2(text: str) -> str:
    """Escape special chars for MarkdownV2, preserving formatting."""
    # MarkdownV2 requires escaping these outside of formatting
    # But we want to KEEP markdown formatting, so we try sending as-is
    # and fall back to plain text if it fails
    return text


def truncate(text: str, max_len: int = MAX_TELEGRAM_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 20] + "\n\n... (truncated)"


def setup_handlers(app, settings: Settings, claude: ClaudeClient,
                   mysql: MySQLStorage, es: ElasticsearchStorage,
                   uploads_storage: UploadsStorage | None = None,
                   neo4j=None):
    """Register all handlers on the Telegram application."""

    # Inject dependencies via bot_data
    app.bot_data["settings"] = settings
    app.bot_data["claude"] = claude
    app.bot_data["mysql"] = mysql
    app.bot_data["es"] = es
    app.bot_data["uploads_storage"] = uploads_storage
    app.bot_data["neo4j"] = neo4j

    media_processor = MediaProcessor(
        uploads_dir=settings.uploads_directory,
        openai_api_key=settings.openai_api_key,
    )

    async def auth_check(user_id: int) -> bool:
        """Check if user is allowed via MySQL (cached for 60s)."""
        now = asyncio.get_event_loop().time()
        cache = auth_check._cache
        if user_id in cache:
            allowed, ts = cache[user_id]
            if now - ts < 60:
                return allowed
        allowed = await mysql.is_user_allowed(user_id)
        cache[user_id] = (allowed, now)
        return allowed
    auth_check._cache = {}
    global _auth_cache_ref
    _auth_cache_ref = auth_check._cache

    # --- Start ---

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await auth_check(update.effective_user.id):
            return
        await update.message.reply_text(
            f"Claude Code ({settings.instance_name}) bereit.\n"
            "Schreib mir was du brauchst, oder /help für alle Commands."
        )

    # --- Load preferences + profile from MySQL on first contact ---
    from .commands.prefs import ALL_PREF_KEYS

    async def _load_prefs(context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Load preferences and profile from MySQL into user_data (once per bot session)."""
        if context.user_data.get("_prefs_loaded"):
            return
        prefs = await mysql.get_preferences(user_id)
        for key, value in prefs.items():
            if key in ALL_PREF_KEYS and key not in context.user_data:
                context.user_data[key] = value
        context.user_data["_prefs_loaded"] = True

    # --- Auth wrapper for all commands ---

    def auth(handler):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not await auth_check(update.effective_user.id):
                return
            await _load_prefs(context, update.effective_user.id)
            return await handler(update, context)
        return wrapper

    # --- Main message handler ---

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await auth_check(update.effective_user.id):
            return
        await _load_prefs(context, update.effective_user.id)
        if not update.message:
            return

        user_id = update.effective_user.id
        username = update.effective_user.username

        # ── Media routing ──────────────────────────────────────────────────
        msg = update.message
        prompt: str = ""
        _upload_result = None
        _upload_storage: UploadsStorage | None = context.bot_data.get("uploads_storage")

        if msg.voice:
            # Voice message: transcribe → normal text prompt (no storage)
            status_msg = await msg.reply_text("🎤 Transkribiere Sprachnachricht...")
            try:
                from .media.downloader import download_telegram_file
                upload_id, local_path, fsize = await download_telegram_file(
                    context.bot, msg.voice.file_id,
                    settings.uploads_directory, extension=".ogg"
                )
                result = await media_processor.process_voice(local_path, upload_id)
                # Delete the temp file — voice is not stored
                import os as _os
                try:
                    _os.unlink(local_path)
                except Exception:
                    pass
                if result.voice_text:
                    prompt = result.voice_text
                    await status_msg.edit_text(f"🎤 Transkribiert: {result.voice_text[:100]}...")
                else:
                    await status_msg.edit_text("❌ Transkription fehlgeschlagen.")
                    return
            except Exception as e:
                logger.error("Voice processing failed", error=str(e))
                await status_msg.edit_text(f"❌ Fehler bei Sprachnachricht: {e}")
                return

        elif msg.photo or msg.document or msg.video or msg.audio or msg.animation:
            # File/media: download, process, index
            status_msg = await msg.reply_text("⏳ Datei wird verarbeitet...")
            try:
                from .media.downloader import download_telegram_file

                if msg.photo:
                    # Take highest-resolution photo
                    photo = msg.photo[-1]
                    upload_id, local_path, fsize = await download_telegram_file(
                        context.bot, photo.file_id,
                        settings.uploads_directory, extension=".jpg"
                    )
                    fname = f"photo_{upload_id}.jpg"
                    mime = "image/jpeg"
                elif msg.document:
                    doc = msg.document
                    upload_id, local_path, fsize = await download_telegram_file(
                        context.bot, doc.file_id,
                        settings.uploads_directory,
                        filename=doc.file_name,
                    )
                    fname = doc.file_name
                    mime = doc.mime_type
                elif msg.video:
                    vid = msg.video
                    ext = ".mp4"
                    upload_id, local_path, fsize = await download_telegram_file(
                        context.bot, vid.file_id,
                        settings.uploads_directory,
                        filename=vid.file_name or f"video{ext}",
                    )
                    fname = vid.file_name or f"video_{upload_id}.mp4"
                    mime = vid.mime_type or "video/mp4"
                elif msg.audio:
                    aud = msg.audio
                    upload_id, local_path, fsize = await download_telegram_file(
                        context.bot, aud.file_id,
                        settings.uploads_directory,
                        filename=aud.file_name or f"audio_{upload_id}.mp3",
                    )
                    fname = aud.file_name or f"audio_{upload_id}.mp3"
                    mime = aud.mime_type or "audio/mpeg"
                elif msg.animation:
                    anim = msg.animation
                    upload_id, local_path, fsize = await download_telegram_file(
                        context.bot, anim.file_id,
                        settings.uploads_directory, extension=".gif"
                    )
                    fname = f"animation_{upload_id}.gif"
                    mime = "image/gif"

                caption = msg.caption

                _upload_result = await media_processor.process_file(
                    local_path=local_path,
                    upload_id=upload_id,
                    original_filename=fname,
                    mime_type=mime,
                    caption=caption,
                )

                # Index in ES + MySQL
                if _upload_storage:
                    es_id = await _upload_storage.index_upload(
                        upload_id=upload_id,
                        user_id=user_id,
                        media_type=_upload_result.media_type,
                        mime_type=mime,
                        original_filename=fname,
                        content=_upload_result.content_text,
                        caption=caption,
                        transcript=_upload_result.transcript,
                        vision_summary=_upload_result.vision_summary,
                        file_size=fsize,
                    )
                else:
                    es_id = None

                await mysql.save_upload(
                    upload_id=upload_id,
                    user_id=user_id,
                    telegram_file_id=getattr(msg.photo[-1] if msg.photo else msg.document or msg.video or msg.audio, "file_id", None),
                    original_filename=fname,
                    media_type=_upload_result.media_type,
                    mime_type=mime,
                    file_size=fsize,
                    storage_path=local_path,
                    es_id=es_id,
                    caption=caption,
                    transcript=_upload_result.transcript,
                    vision_summary=_upload_result.vision_summary,
                )

                # Store tabular data in MySQL
                if _upload_result.table_rows:
                    await mysql.save_upload_rows(upload_id, user_id, _upload_result.table_rows)

                await status_msg.edit_text(_upload_result.summary)

                # Knowledge enrichment: classify upload → save as memory → graph
                # Runs in background so the user gets immediate feedback
                async def _enrich_upload():
                    try:
                        from ..knowledge.upload_enrichment import enrich_upload
                        result = await enrich_upload(
                            es=es, neo4j=neo4j, settings=settings,
                            user_id=user_id, upload_id=upload_id,
                            original_filename=fname, media_type=_upload_result.media_type,
                            content_text=_upload_result.content_text,
                            caption=caption,
                            transcript=_upload_result.transcript,
                            vision_summary=_upload_result.vision_summary,
                            mysql=mysql,
                        )
                        if result and result.get("nodes", 0) > 0:
                            logger.info("Upload enriched",
                                        upload_id=upload_id, nodes=result["nodes"],
                                        edges=result.get("edges", 0))
                    except Exception as e:
                        logger.error("Upload enrichment failed",
                                     error=str(e), upload_id=upload_id)
                asyncio.create_task(_enrich_upload())

                # Build prompt for Claude
                prompt = media_processor.build_prompt_from_result(_upload_result, caption)

            except Exception as e:
                logger.error("Media processing failed", error=str(e))
                await status_msg.edit_text(f"❌ Fehler bei Dateiverarbeitung: {e}")
                return

        elif msg.text:
            prompt = msg.text
        else:
            return  # Unsupported message type (stickers, etc.)
        # ── End of media routing ───────────────────────────────────────────

        # ── Claude auth flow ───────────────────────────────────────────────
        pending_auth = context.user_data.get("pending_auth_code")
        if pending_auth:
            # User is responding with the OAuth code
            if not msg.text:
                await update.message.reply_text("Bitte schick mir den Code als Text.")
                return
            code = msg.text.strip()
            verifier = pending_auth["verifier"]
            status_msg = await update.message.reply_text("🔐 Code wird verarbeitet…")
            try:
                token_data = await exchange_code(code, verifier)
                save_credentials(token_data)
                context.user_data.pop("pending_auth_code", None)
                await status_msg.edit_text(
                    "✅ Claude erfolgreich authentifiziert! Du kannst jetzt loslegen."
                )
            except Exception as e:
                logger.error("Auth code exchange failed", error=str(e))
                await status_msg.edit_text(
                    f"❌ Authentifizierung fehlgeschlagen: {e}\n\n"
                    "Bitte versuche es erneut oder schick eine neue Nachricht um einen neuen Link zu erhalten."
                )
                context.user_data.pop("pending_auth_code", None)
            return

        if not await ensure_authenticated():
            auth_url, verifier = build_auth_url()
            context.user_data["pending_auth_code"] = {"verifier": verifier}
            await update.message.reply_text(
                "🔐 Claude ist noch nicht eingeloggt.\n\n"
                "Öffne diesen Link in deinem Browser "
                "(wichtig: nicht im Telegram-Browser, sondern extern öffnen):\n\n"
                f"{auth_url}\n\n"
                "Melde dich an, bestätige die Autorisierung, "
                "und schick mir den Code, der danach angezeigt wird."
            )
            return
        # ── End of Claude auth flow ────────────────────────────────────────

        # Guard: reject if an execution is already running for this user
        existing = context.user_data.get("running_task")
        if existing and not existing.done():
            await update.message.reply_text(
                "⏳ Es läuft bereits eine Ausführung.\n"
                "Nutze /stop zum Abbrechen oder warte bis sie fertig ist."
            )
            return

        await mysql.ensure_user(user_id, username)

        # Check for pending mail (text-only)
        pending_mail = context.user_data.pop("pending_mail", None)
        if pending_mail and isinstance(prompt, str):
            result = await send_email(
                settings, pending_mail["to"], pending_mail["subject"], prompt
            )
            await update.message.reply_text(result)
            return

        # Determine session
        session_id = None
        force_new = context.user_data.pop("force_new_session", False)
        explicit_resume = context.user_data.pop("resume_session_id", None)
        cwd = context.user_data.get("working_directory", settings.approved_directory)

        if explicit_resume:
            # Resolve short IDs or display names (e.g. "82490df7", "bold-fox")
            if len(explicit_resume) < 36:
                resolved = await mysql.resolve_session_id(user_id, explicit_resume)
                session_id = resolved["session_id"] if resolved else explicit_resume
            else:
                session_id = explicit_resume
        elif not force_new:
            existing = await mysql.get_active_session(user_id, cwd, channel="telegram")
            if existing:
                session_id = existing["session_id"]

        # Cross-channel lock: reject if Web-UI is already running this session
        _session_lock_id: str | None = None
        if session_id:
            acquired = await mysql.acquire_running_lock(session_id, "telegram")
            if not acquired:
                active_ch = await mysql.get_running_channel(session_id)
                source = "der Web-UI" if active_ch == "web" else "einem anderen Kanal"
                await update.message.reply_text(
                    f"⏳ Diese Session wird gerade von {source} ausgeführt.\n"
                    "Warte bis sie fertig ist oder nutze /stop zum Abbrechen."
                )
                return
            _session_lock_id = session_id

        # Persist prompt immediately so web polling sees it right away
        # (response stays NULL until Claude finishes; updated in finally block)
        _prompt_str = prompt if isinstance(prompt, str) else f"[media: {_upload_result.media_type if _upload_result else 'file'}]"
        _pending_message_id: int | None = None
        if session_id:
            try:
                _pending_message_id = await mysql.save_message_prompt(
                    session_id, user_id, _prompt_str
                )
            except Exception:
                pass  # Non-fatal: falls back to old write-at-end behaviour

        # Typing indicator + keep-alive task
        await update.message.chat.send_action(ChatAction.TYPING)
        typing_active = True

        async def keep_typing():
            while typing_active:
                try:
                    await update.message.chat.send_action(ChatAction.TYPING)
                except Exception:
                    pass
                await asyncio.sleep(4)  # Telegram typing expires after 5s

        typing_task = asyncio.create_task(keep_typing())

        # Verbose levels:
        # 0 = Silent (nur Typing + Ergebnis)
        # 1 = Tool-Icons + Reasoning + Live-Preview (Zwei-Phasen)
        # 2 = + längere Output-Previews (300 statt 150 Zeichen)
        # Resolve all preferences fresh from MySQL (cross-channel consistent)
        exec_args = await resolve_execute_args(mysql, settings, user_id)
        verbose = exec_args["verbose"]
        progress_msg = None
        # Full history for summary at the end
        _tool_history = []  # list of {icon, short, summary, success, duration, preview}
        # Live state
        _tool_timer_task = None
        _current_tool = None  # current tool line (live)
        _last_result = None   # last completed tool (with result)
        _last_reasoning = None  # last reasoning snippet

        def _tool_icon(name: str) -> str:
            """Return a tool-specific icon."""
            icons = {
                "Bash": "⚡", "Read": "📖", "Write": "📝",
                "Edit": "✏️", "MultiEdit": "✏️",
                "Glob": "🔍", "Grep": "🔍",
                "WebFetch": "🌐", "WebSearch": "🔎",
                "Agent": "🤖", "TodoWrite": "📋",
            }
            if name in icons:
                return icons[name]
            if name.startswith("mcp__"):
                lower = name.lower()
                if any(k in lower for k in ("mysql", "elastic", "neo4j", "postgres", "redis")):
                    return "🗄️"
                if any(k in lower for k in ("email", "mail", "send_email")):
                    return "📧"
                if any(k in lower for k in ("memory", "search_memory", "save_memory")):
                    return "🧠"
                if "search_web" in lower:
                    return "🔎"
                if "current_time" in lower:
                    return "🕐"
            return "🔧"

        def _tool_input_summary(name: str, inp: dict) -> str:
            if name == "Bash":
                return f"$ {inp.get('command', '?')[:150]}"
            elif name in ("Read", "Write"):
                path = inp.get("file_path", inp.get("path", "?"))
                # Shorten common prefixes
                return path.replace("/root/workspace/", "~/")
            elif name in ("Edit", "MultiEdit"):
                path = inp.get("file_path", inp.get("path", "?")).replace("/root/workspace/", "~/")
                old = inp.get("old_string", "")
                if old:
                    return f"{path} ({len(old)} chars)"
                return path
            elif name in ("Glob", "Grep"):
                pattern = inp.get("pattern", "?")
                path = inp.get("path", "")
                if path:
                    path = path.replace("/root/workspace/", "~/")
                return f"{pattern}" + (f" in {path}" if path else "")
            elif name == "WebFetch":
                return inp.get("url", "?")[:100]
            elif name == "WebSearch":
                return inp.get("query", "?")[:100]
            elif name == "TodoWrite":
                todos = inp.get("todos", [])
                return f"{len(todos)} items"
            elif name == "Agent":
                return inp.get("description", inp.get("prompt", "?")[:80])
            elif name.startswith("mcp__"):
                parts = []
                for k in ("query", "sql", "cypher", "command", "to", "name", "method", "path"):
                    if k in inp:
                        parts.append(f"{k}={str(inp[k])[:80]}")
                return ", ".join(parts) if parts else ""
            return ""

        def _short_name(name: str) -> str:
            if name.startswith("mcp__"):
                parts = name.split("__")
                return parts[-1] if len(parts) >= 3 else parts[-1]
            return name

        def _format_preview(preview: str, max_len: int) -> str:
            if not preview:
                return ""
            clean = preview.strip()
            if len(clean) > max_len:
                clean = clean[:max_len] + "..."
            return clean

        _last_sent_text = None
        _last_text_update = 0.0  # throttle text events

        def _build_live_text() -> str:
            """Build the live progress message: reasoning + last result + current tool."""
            parts = []
            if _last_reasoning:
                parts.append(f"💭 <i>{_last_reasoning}</i>")
                parts.append("")
            if _last_result:
                parts.append(_last_result)
            if _current_tool:
                if _last_result:
                    parts.append("")  # spacer between result and current
                parts.append(_current_tool)
            return "\n".join(parts)

        async def _update_progress(force: bool = False):
            nonlocal progress_msg, _last_sent_text
            text = _build_live_text()
            if not text.strip():
                return
            # Skip if nothing changed (prevents "message not modified" errors)
            if text == _last_sent_text and not force:
                return
            # Telegram message limit safety
            if len(text) > 3900:
                text = text[:3900]
            try:
                if progress_msg:
                    await progress_msg.edit_text(text, parse_mode=ParseMode.HTML)
                else:
                    progress_msg = await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                _last_sent_text = text
            except Exception as e:
                err_msg = str(e).lower()
                if "not modified" in err_msg:
                    _last_sent_text = text  # sync state
                    return  # ignore, don't fall back to plain text
                # Only fall back for actual HTML parse errors
                try:
                    if progress_msg:
                        await progress_msg.edit_text(text)
                    else:
                        progress_msg = await update.message.reply_text(text)
                    _last_sent_text = text
                except Exception:
                    pass

        async def _live_timer(start_time: float):
            """Update the timer on the current tool line every 3s."""
            nonlocal _current_tool
            while True:
                await asyncio.sleep(3)
                elapsed = asyncio.get_event_loop().time() - start_time
                try:
                    if _current_tool and "⏳" in _current_tool:
                        _current_tool = re.sub(
                            r'⏳[^\n]*', f'⏳ {elapsed:.0f}s...', _current_tool
                        )
                        await _update_progress()
                except Exception:
                    pass

        async def on_message(msg_type: str, content: str, extra: dict = None):
            nonlocal progress_msg, _tool_timer_task, _current_tool, _last_result, _last_reasoning, _last_text_update
            extra = extra or {}

            # Publish to LiveEventBus so web subscribers get live events
            if session_id and live_bus.has_subscribers(session_id):
                if msg_type == "tool_start":
                    await live_bus.publish(session_id, {
                        "event": "tool_start", "tool": content, "input": extra,
                    })
                elif msg_type == "tool_result":
                    await live_bus.publish(session_id, {
                        "event": "tool_result", "tool": content, **extra,
                    })
                elif msg_type == "text":
                    await live_bus.publish(session_id, {
                        "event": "text", "content": content,
                    })
                elif msg_type == "thinking_text":
                    await live_bus.publish(session_id, {
                        "event": "thinking_text", "content": content,
                    })
                elif msg_type == "context_usage":
                    await live_bus.publish(session_id, {
                        "event": "context_usage", **extra,
                    })

            if verbose == 0:
                return

            if msg_type == "tool_start":
                # Cancel previous timer
                if _tool_timer_task:
                    _tool_timer_task.cancel()
                    _tool_timer_task = None

                icon = _tool_icon(content)
                short = _short_name(content)
                summary = _tool_input_summary(content, extra)

                if summary:
                    _current_tool = f"{icon} <b>{short}</b>  ⏳\n  <code>{html.escape(summary)}</code>"
                else:
                    _current_tool = f"{icon} <b>{short}</b>  ⏳"

                # Record for history
                _tool_history.append({
                    "icon": icon, "short": short, "summary": summary,
                    "success": None, "duration": 0, "preview": "",
                })

                await _update_progress()

                # Start live timer
                _tool_timer_task = asyncio.create_task(
                    _live_timer(asyncio.get_event_loop().time())
                )

            elif msg_type == "tool_result":
                # Cancel timer
                if _tool_timer_task:
                    _tool_timer_task.cancel()
                    _tool_timer_task = None

                success = extra.get("success", True)
                duration = extra.get("duration", 0)
                preview = extra.get("preview", "")
                status_icon = "✅" if success else "❌"
                dur_str = f"{duration:.1f}s" if duration else ""

                # Update history
                if _tool_history:
                    _tool_history[-1].update({
                        "success": success, "duration": duration, "preview": preview,
                    })

                # Build last result line (replaces previous last_result)
                max_len = 300 if verbose >= 2 else 150
                formatted_preview = _format_preview(preview, max_len)

                last_entry = _tool_history[-1] if _tool_history else None
                if last_entry:
                    result_line = f"{last_entry['icon']} <b>{last_entry['short']}</b>  {status_icon} {dur_str}"
                    if last_entry['summary']:
                        result_line += f"\n  <code>{html.escape(last_entry['summary'][:100])}</code>"
                    if formatted_preview:
                        result_line += f"\n  ↳ <code>{html.escape(formatted_preview)}</code>"
                    _last_result = result_line

                _current_tool = None
                await _update_progress()

            elif msg_type == "thinking_text":
                # Proper reasoning/thinking block — throttle to max every 2s
                now = asyncio.get_event_loop().time()
                snippet = content.strip()
                if snippet:
                    # Show first 300 chars of the thinking block
                    _last_reasoning = html.escape(snippet[:300])
                    if now - _last_text_update >= 2.0:
                        _last_text_update = now
                        await _update_progress()

            elif msg_type == "text":
                # Regular response text — clear reasoning display
                _last_reasoning = ""

        # Set up approval manager for this chat
        logger.info("handle_message: resolved mode", mode=exec_args["mode"], user_id=user_id,
                     prefs_snapshot={k: exec_args.get(k) for k in ("mode", "model", "thinking", "verbose")})
        approval_manager.set_bot(context.bot, update.effective_chat.id)

        # Execute as task (so /stop can cancel it)
        execute_task = asyncio.create_task(claude.execute(
            prompt=prompt,
            user_id=user_id,
            session_id=session_id,
            cwd=cwd,
            on_message=on_message if verbose > 0 else None,
            mode=exec_args["mode"],
            model=exec_args["model"],
            profile=exec_args["profile"],
            max_turns=exec_args["max_turns"],
            thinking=exec_args["thinking"],
            thinking_budget=exec_args["thinking_budget"],
            budget=exec_args["budget"],
            bot=context.bot,
            chat_id=update.effective_chat.id,
        ))
        context.user_data["running_task"] = execute_task
        context.user_data["running_start"] = asyncio.get_event_loop().time()
        if session_id:
            claude.register_task(session_id, execute_task)

        tools_used: list[str] = []  # initialised early so CancelledError handler can reference it

        try:
            result = await execute_task

            response = result["content"] or ""
            new_session_id = result["session_id"]
            cost = result["cost"]
            duration_ms = result["duration_ms"]
            tools_used = result["tools_used"]

            # Extract token/model info from result
            result_model = result.get("model", "")
            usage = result.get("usage", {}) or {}
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            cache_creation_tokens = usage.get("cache_creation_input_tokens", 0) or 0
            cache_read_tokens = usage.get("cache_read_input_tokens", 0) or 0

            # Persist to MySQL
            context_tokens = result.get("context_tokens", 0) or 0
            context_max_tokens = result.get("context_max_tokens", 0) or 0
            if new_session_id:
                await mysql.save_session(
                    new_session_id, user_id, cwd,
                    cost=cost, turns=1, messages=1,
                    context_tokens=context_tokens,
                    context_max_tokens=context_max_tokens,
                )

            effective_session = new_session_id or "unknown"

            # Build tools_json for DB persistence (WebUI display)
            persisted_tools = [
                {
                    "tool": t["short"],
                    "status": "done" if t.get("success") else ("error" if t.get("success") is False else "running"),
                    "success": t.get("success"),
                    "duration": t.get("duration", 0),
                    "preview": t.get("preview", ""),
                    "isBackgroundTask": False,
                }
                for t in _tool_history
            ] if _tool_history else None

            if _pending_message_id:
                # Update the row we already wrote (prompt-only) with the response
                await mysql.update_message_response(
                    message_id=_pending_message_id,
                    response=response,
                    cost=cost,
                    duration_ms=duration_ms,
                    model=result_model or None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    cache_read_tokens=cache_read_tokens,
                    session_id=effective_session if new_session_id else None,
                    tools_json=persisted_tools,
                )
            else:
                await mysql.save_message(
                    session_id=effective_session,
                    user_id=user_id, prompt=_prompt_str, response=response,
                    cost=cost, duration_ms=duration_ms,
                    model=result_model or None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    cache_read_tokens=cache_read_tokens,
                )

            # Notify web subscribers that this session is done
            if session_id and live_bus.has_subscribers(session_id):
                await live_bus.publish(session_id, {
                    "event": "done",
                    "session_id": effective_session,
                    "cost": cost,
                    "duration_ms": duration_ms,
                    "tools_used": tools_used,
                })
            # Always update user aggregates
            await mysql.update_user_stats(user_id, cost)
            if cost > 0:
                await mysql.track_cost(user_id, cost)
            for tool in tools_used:
                await mysql.save_tool_usage(new_session_id or "unknown", tool)

            # Log to ES (with model + tokens for assistant messages)
            await es.log_conversation(
                new_session_id or "unknown", user_id, "user", _prompt_str
            )
            await es.log_conversation(
                new_session_id or "unknown", user_id, "assistant", response,
                tools_used=tools_used, cost=cost,
                model=result_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
            )

            await mysql.log_event(user_id, "message", {
                "session_id": new_session_id, "cost": cost, "tools": tools_used,
            })

            # Stop typing + timer
            typing_active = False
            typing_task.cancel()
            if _tool_timer_task:
                _tool_timer_task.cancel()

            # Finalize progress message
            if progress_msg and not _tool_history:
                # No tools used — delete the reasoning bubble (response follows as new msg)
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
                progress_msg = None

            if progress_msg and _tool_history:
                try:
                    cost_str = f"${cost:.4f}" if cost > 0 else ""
                    dur_str = f"{duration_ms / 1000:.1f}s" if duration_ms else ""
                    # Token summary for footer
                    def _fmt_tok(n: int) -> str:
                        return f"{n/1000:.1f}k" if n >= 1000 else str(n)
                    tok_str = ""
                    if output_tokens or input_tokens:
                        tok_str = f"in {_fmt_tok(input_tokens)} · out {_fmt_tok(output_tokens)}"
                        if cache_read_tokens:
                            tok_str += f" · cache {_fmt_tok(cache_read_tokens)}"
                    model_short = result_model.replace("claude-", "").replace("-latest", "") if result_model else ""

                    if verbose >= 2:
                        # Detailed: full tool list with previews
                        header_parts = ["✅ <b>Fertig</b>", f"{len(tools_used)} tools", dur_str, cost_str]
                        if model_short:
                            header_parts.append(f"<i>{html.escape(model_short)}</i>")
                        header = " · ".join(p for p in header_parts if p) + "\n"
                        if tok_str:
                            header += f"   <i>{html.escape(tok_str)}</i>\n"
                        lines = [header]
                        for t in _tool_history:
                            s_icon = "✅" if t["success"] else "❌" if t["success"] is not None else "⏳"
                            d_str = f"{t['duration']:.1f}s" if t["duration"] else ""
                            summary_short = html.escape((t["summary"] or "")[:80])
                            line = f" {t['icon']} <b>{t['short']}</b>  {s_icon} {d_str}"
                            if summary_short:
                                line += f"\n    <code>{summary_short}</code>"
                            preview = _format_preview(t.get("preview", ""), 300)
                            if preview:
                                line += f"\n    ↳ <code>{html.escape(preview)}</code>"
                            lines.append(line)
                        summary_text = "\n".join(lines)
                    else:
                        # Compact: summary line + token/model hint
                        parts = ["✅ <b>Fertig</b>", f"{len(tools_used)} tools", dur_str, cost_str]
                        summary_text = " · ".join(p for p in parts if p)
                        extras = []
                        if model_short:
                            extras.append(f"<i>{html.escape(model_short)}</i>")
                        if tok_str:
                            extras.append(f"<i>{html.escape(tok_str)}</i>")
                        if extras:
                            summary_text += "\n   " + " · ".join(extras)

                    if len(summary_text) > 3900:
                        summary_text = summary_text[:3900] + "..."
                    await progress_msg.edit_text(summary_text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass

            # Send response as separate messages with proper Telegram formatting
            if response.strip():
                try:
                    tg_chunks = await telegramify_markdown.telegramify(
                        response,
                        render_mermaid=False,
                        min_file_lines=0,  # keep code blocks inline as pre entities
                    )
                except Exception:
                    tg_chunks = None

                if tg_chunks:
                    for chunk in tg_chunks:
                        if isinstance(chunk, telegramify_markdown.Text):
                            if not chunk.text.strip():
                                continue
                            try:
                                await update.message.reply_text(
                                    chunk.text,
                                    entities=chunk.entities,
                                )
                            except Exception:
                                await update.message.reply_text(chunk.text)
                else:
                    # Fallback: plain text, split at Telegram limit
                    for i in range(0, len(response), MAX_TELEGRAM_LENGTH):
                        await update.message.reply_text(response[i:i + MAX_TELEGRAM_LENGTH])

        except asyncio.CancelledError:
            # /stop was called
            typing_active = False
            typing_task.cancel()
            if _tool_timer_task:
                _tool_timer_task.cancel()

            elapsed = asyncio.get_event_loop().time() - context.user_data.get("running_start", 0)
            if progress_msg and _tool_history:
                try:
                    lines = [f"⏹ <b>Abgebrochen</b> nach {elapsed:.1f}s, {len(_tool_history)} tools\n"]
                    for t in _tool_history:
                        s_icon = "✅" if t["success"] else "❌" if t["success"] is not None else "⏳"
                        d_str = f"{t['duration']:.1f}s" if t["duration"] else ""
                        line = f" {t['icon']} <b>{t['short']}</b>  {s_icon} {d_str}"
                        lines.append(line)
                    await progress_msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)
                except Exception:
                    pass
            else:
                await update.message.reply_text(f"⏹ Abgebrochen nach {elapsed:.1f}s")

            await mysql.log_event(user_id, "stop", {"elapsed": elapsed, "tools": tools_used})

        except Exception as e:
            typing_active = False
            typing_task.cancel()
            if _tool_timer_task:
                _tool_timer_task.cancel()
            logger.error("Message handling failed", error=str(e))
            error_text = f"Fehler: {str(e)[:500]}"
            if progress_msg:
                try:
                    await progress_msg.edit_text(error_text)
                except Exception:
                    await update.message.reply_text(error_text)
            else:
                await update.message.reply_text(error_text)
            await mysql.log_event(user_id, "error", {"error": str(e)}, success=False)
        finally:
            context.user_data.pop("running_task", None)
            context.user_data.pop("running_start", None)
            if _session_lock_id:
                claude.unregister_task(_session_lock_id)
                await mysql.release_running_lock(_session_lock_id)

    # --- Register all handlers ---

    commands = {
        # Core
        "start": cmd_start,
        "help": cmd_help,
        # Standalone
        "new": cmd_new,
        "stop": cmd_stop,
        "status": cmd_status,
        "model": cmd_model_cmd,
        # Dispatchers
        "session": cmd_session,
        "mode": cmd_mode,
        "me": cmd_me,
        "memory": cmd_memory_dispatch,
    }

    # --- Approval callback handler ---

    async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query or not query.data:
            return
        if not await auth_check(query.from_user.id):
            await query.answer("Nicht autorisiert.")
            return

        parts = query.data.split(":", 1)
        if len(parts) != 2 or parts[0] not in ("approve", "deny", "always"):
            return

        decision, approval_id = parts
        decision_map = {"approve": "allow", "deny": "deny", "always": "always"}
        approval_manager.resolve(approval_id, decision_map[decision])

        labels = {"approve": "✅ Erlaubt", "deny": "❌ Abgelehnt", "always": "✅ Immer erlaubt"}
        await query.answer(labels[decision])
        await query.edit_message_text(f"{query.message.text}\n\n→ {labels[decision]}")

    for name, handler in commands.items():
        app.add_handler(CommandHandler(name, auth(handler)))

    app.add_handler(CallbackQueryHandler(handle_approval_callback))

    # Media filter: text messages, photos, documents, video, audio, voice, animation
    _media_filter = (
        filters.TEXT
        | filters.PHOTO
        | filters.Document.ALL
        | filters.VIDEO
        | filters.AUDIO
        | filters.VOICE
        | filters.ANIMATION
    )
    app.add_handler(MessageHandler(_media_filter & ~filters.COMMAND, handle_message))
