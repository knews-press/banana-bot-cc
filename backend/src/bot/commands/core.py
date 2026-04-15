"""Transport-agnostic command core — shared by Telegram and Web API.

Each handler receives a CommandContext and returns a CommandResult.
No Telegram or HTTP dependencies allowed in this module.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import timezone
from zoneinfo import ZoneInfo

from ...utils.session_names import short_name


@dataclass
class CommandContext:
    """All data a command handler needs."""
    user_id: int
    args: list[str]
    mysql: object          # MySQLStorage
    es: object             # ElasticsearchStorage
    settings: object       # Settings
    user_prefs: dict       # from mysql.get_preferences()


@dataclass
class CommandResult:
    """Structured command response."""
    success: bool = True
    title: str = ""
    content: str = ""      # Plain text or markdown (NOT HTML)
    data: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        d = {"success": self.success, "title": self.title, "content": self.content}
        if self.data:
            d["data"] = self.data
        if self.error:
            d["error"] = self.error
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _progress_bar(pct: float, width: int = 20) -> str:
    filled = round(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


_CONTEXT_WINDOWS = {
    "claude-opus-4": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet-4": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
}

_MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    "default": None,
}

_MODEL_INFO = {
    "claude-opus-4-6": ("Opus 4.6", "1M"),
    "claude-sonnet-4-6": ("Sonnet 4.6", "200k"),
    "claude-haiku-4-5-20251001": ("Haiku 4.5", "200k"),
}

_LANGUAGE_OPTIONS = {
    "de": "🇩🇪 Deutsch", "en": "🇬🇧 English", "fr": "🇫🇷 Français",
    "es": "🇪🇸 Español", "it": "🇮🇹 Italiano", "nl": "🇳🇱 Nederlands",
    "pt": "🇵🇹 Português", "pl": "🇵🇱 Polski", "tr": "🇹🇷 Türkçe",
}


# ---------------------------------------------------------------------------
# /new
# ---------------------------------------------------------------------------

async def exec_new(ctx: CommandContext) -> CommandResult:
    mysql = ctx.mysql
    old = await mysql.get_active_session(ctx.user_id, ctx.settings.approved_directory)
    data = {"force_new": True}
    if old:
        return CommandResult(
            title="New Session",
            content=f"🆕 New session started\nPrevious: `{short_name(old['session_id'], old.get('display_name'))}` ({old['total_turns']} turns, ${old['total_cost']:.4f})",
            data=data,
        )
    return CommandResult(title="New Session", content="🆕 New session started", data=data)


# ---------------------------------------------------------------------------
# /session [list|load|delete|export]
# ---------------------------------------------------------------------------

async def exec_session(ctx: CommandContext) -> CommandResult:
    mysql = ctx.mysql
    session = await mysql.get_active_session(ctx.user_id, ctx.settings.approved_directory)
    if not session:
        return CommandResult(title="Session", content="📋 No active session.\n\n`/new` — Start a new session")

    sid = short_name(session["session_id"], session.get("display_name"))
    turns = session["total_turns"]
    cost = session["total_cost"]
    model = ctx.user_prefs.get("model", "default")
    mode = ctx.user_prefs.get("permission_mode", "yolo")
    path = session["project_path"].replace("/root/workspace", "~")

    started = ""
    if session.get("last_used"):
        last = session["last_used"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Berlin"))
        started = last.strftime("%H:%M")

    return CommandResult(
        title="Active Session",
        content=(
            f"📋 **Active Session**\n"
            f"- ID: `{sid}`\n"
            f"- Model: **{model}**\n"
            f"- Mode: **{mode}**\n"
            f"- Turns: {turns}\n"
            f"- Cost: ${cost:.4f}\n"
            f"- Last used: {started}\n"
            f"- Directory: {path}"
        ),
        data={"session_id": session["session_id"]},
    )


async def exec_session_list(ctx: CommandContext) -> CommandResult:
    sessions = await ctx.mysql.get_user_sessions(ctx.user_id)
    if not sessions:
        return CommandResult(title="Sessions", content="📋 No sessions found.")

    lines = ["📋 **Sessions**\n"]  # header stays
    for i, s in enumerate(sessions, 1):
        sid = short_name(s["session_id"], s.get("display_name"))
        path = s["project_path"].replace("/root/workspace", "~")
        turns = s["total_turns"]
        cost = s["total_cost"]
        last = ""
        if s.get("last_used"):
            last = s["last_used"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Berlin")).strftime("%H:%M")
        lines.append(f"{i}. `{sid}`  {path}\n   {turns} turns · ${cost:.4f} · {last}")

    return CommandResult(title="Sessions", content="\n".join(lines))


async def exec_session_load(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(success=False, title="Session Load", error="Usage: /session load <id or name>")
    prefix = ctx.args[0]
    resolved = await ctx.mysql.resolve_session_id(ctx.user_id, prefix)
    if not resolved:
        return CommandResult(success=False, title="Session Load", error=f"No session found for `{prefix}`.")
    sid = resolved["session_id"]
    display = resolved.get("display_name")
    return CommandResult(
        title="Session Load",
        content=f"🔄 Resuming session `{short_name(sid, display)}`.",
        data={"resume_session_id": sid},
    )


async def exec_session_delete(ctx: CommandContext) -> CommandResult:
    mysql = ctx.mysql
    session = await mysql.get_active_session(ctx.user_id, ctx.settings.approved_directory)
    if not session:
        return CommandResult(title="Session", content="📋 No active session.")

    sid = short_name(session["session_id"], session.get("display_name"))
    turns = session["total_turns"]
    cost = session["total_cost"]
    await mysql.deactivate_session(session["session_id"], ctx.user_id)

    return CommandResult(
        title="Session ended",
        content=f"✅ Session `{sid}` ended ({turns} turns, ${cost:.4f})",
    )


async def exec_session_export(ctx: CommandContext) -> CommandResult:
    mysql = ctx.mysql
    session = await mysql.get_active_session(ctx.user_id, ctx.settings.approved_directory)
    if not session:
        return CommandResult(title="Export", content="📋 No active session.")

    content = await mysql.get_session_content(session["session_id"], ctx.user_id)
    if not content or not content.get("jsonl_content"):
        return CommandResult(title="Export", content="📋 Session content not available.")

    sn = short_name(session["session_id"], session.get("display_name"))
    lines = [f"# Session {sn}\n"]
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

    return CommandResult(
        title="Export",
        content="\n".join(lines),
        data={"filename": f"session-{sn}.md"},
    )


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

async def exec_status(ctx: CommandContext) -> CommandResult:
    mysql = ctx.mysql
    session = await mysql.get_active_session(ctx.user_id, ctx.settings.approved_directory)
    if not session:
        return CommandResult(title="Status", content="ℹ️ No active session.\n\n`/new` — Start a new session")

    session_id = session["session_id"]
    turns = session.get("total_turns", 0)
    cost = session.get("total_cost", 0)
    tokens = await mysql.get_session_token_count(session_id, ctx.user_id)

    model = ctx.user_prefs.get("model", "default")
    env_default = ctx.settings.claude_default_model
    effective_model = model if model != "default" else (env_default or "claude-sonnet-4-6")
    context_window = _CONTEXT_WINDOWS.get(effective_model, 200_000)
    pct = min(round(tokens / context_window * 100), 100) if context_window else 0

    mode = ctx.user_prefs.get("permission_mode", "yolo")
    thinking = ctx.user_prefs.get("thinking", False)
    thinking_str = "off"
    if thinking:
        tb = ctx.user_prefs.get("thinking_budget", 10000)
        thinking_str = f"on ({tb // 1000}k budget)"

    max_turns = ctx.user_prefs.get("max_turns", ctx.settings.claude_max_turns)
    budget = ctx.user_prefs.get("budget", "∞")
    cwd = (ctx.user_prefs.get("working_directory") or ctx.settings.approved_directory).replace("/root/workspace", "~")
    model_display = effective_model.replace("claude-", "").replace("-20251001", "")

    started = ""
    if session.get("last_used"):
        last = session["last_used"].replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Berlin"))
        started = last.strftime("%H:%M")

    bar = _progress_bar(pct)

    return CommandResult(
        title="Status",
        content=(
            f"📊 **Status**\n\n"
            f"- Session: `{short_name(session_id, session.get('display_name'))}` ({started})\n"
            f"- Model: **{model_display}**\n"
            f"- Mode: **{mode}**\n"
            f"- Thinking: **{thinking_str}**\n"
            f"- Turns: **{turns}/{max_turns}**\n"
            f"- Context: {_fmt_tokens(tokens)} / {_fmt_tokens(context_window)} ({pct}%)\n"
            f"  `{bar}`\n"
            f"- Cost: **${cost:.4f}** (Budget: ${budget})\n"
            f"- Directory: {cwd}"
        ),
        data={
            "session_id": session_id,
            "model": effective_model,
            "mode": mode,
            "turns": turns,
            "max_turns": max_turns,
            "context_tokens": tokens,
            "context_max": context_window,
            "context_pct": pct,
            "cost": cost,
        },
    )


# ---------------------------------------------------------------------------
# /model [name]
# ---------------------------------------------------------------------------

async def exec_model(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        current = ctx.user_prefs.get("model", "default")
        env_default = ctx.settings.claude_default_model
        effective_id = current if current != "default" else (env_default or "claude-sonnet-4-6")
        info = _MODEL_INFO.get(effective_id, (effective_id, "?"))
        return CommandResult(
            title="Model",
            content=f"🤖 **Current model:** {info[0]} ({info[1]} context)",
            data={"model": effective_id, "context_window": info[1]},
        )

    name = ctx.args[0].lower()
    if name not in _MODEL_MAP:
        return CommandResult(success=False, title="Model", error=f"Unknown model: {name}")

    model_id = _MODEL_MAP[name] or "default"
    await _save_pref(ctx, "model", model_id)
    info = _MODEL_INFO.get(model_id, (name, ""))
    ctx_str = f" ({info[1]} context)" if info[1] else ""
    return CommandResult(
        title="Model",
        content=f"🤖 Model → **{info[0]}**{ctx_str}",
        data={"model": model_id},
    )


# ---------------------------------------------------------------------------
# /mode [sub]
# ---------------------------------------------------------------------------

async def exec_mode(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        mode = ctx.user_prefs.get("permission_mode", "yolo")
        thinking = ctx.user_prefs.get("thinking", False)
        thinking_str = "off"
        if thinking:
            tb = ctx.user_prefs.get("thinking_budget", 10000)
            thinking_str = f"on ({tb:,} tokens)"
        verbose_level = ctx.user_prefs.get("verbose", 1)
        max_turns = ctx.user_prefs.get("max_turns", ctx.settings.claude_max_turns)
        budget = ctx.user_prefs.get("budget", "∞")

        return CommandResult(
            title="Mode & Settings",
            content=(
                f"⚙️ **Mode & Settings**\n\n"
                f"- Mode: **{mode}**\n"
                f"- Thinking: **{thinking_str}**\n"
                f"- Max turns: **{max_turns}**\n"
                f"- Cost limit: **${budget}**\n"
                f"- Verbose: **{verbose_level}**"
            ),
            data={"mode": mode, "thinking": thinking, "verbose": verbose_level, "max_turns": max_turns, "budget": budget},
        )

    sub = ctx.args[0].lower()
    ctx.args = ctx.args[1:]

    if sub in ("yolo", "approve", "plan"):
        await _save_pref(ctx, "permission_mode", sub)
        icons = {"yolo": "🚀", "approve": "🔐", "plan": "📖"}
        return CommandResult(title="Mode", content=f"⚙️ Mode → **{sub}** {icons.get(sub, '')}", data={"mode": sub})

    if sub == "thinking":
        if ctx.args:
            try:
                budget = int(ctx.args[0])
                budget = max(1024, min(budget, 128000))
                await _save_pref(ctx, "thinking", True)
                await _save_pref(ctx, "thinking_budget", budget)
                return CommandResult(title="Thinking", content=f"⚙️ Extended Thinking: **ON** (Budget: {budget:,} tokens)")
            except ValueError:
                pass
        current = ctx.user_prefs.get("thinking", False)
        await _save_pref(ctx, "thinking", not current)
        new_state = "ON" if not current else "OFF"
        return CommandResult(title="Thinking", content=f"⚙️ Extended Thinking: **{new_state}**")

    if sub == "turns":
        if not ctx.args:
            current = ctx.user_prefs.get("max_turns", ctx.settings.claude_max_turns)
            return CommandResult(title="Turns", content=f"⚙️ Max Turns: **{current}**")
        try:
            n = int(ctx.args[0])
            await _save_pref(ctx, "max_turns", n)
            return CommandResult(title="Turns", content=f"⚙️ Max Turns → **{n}**")
        except ValueError:
            return CommandResult(success=False, title="Turns", error="Usage: /mode turns <number>")

    if sub == "budget":
        if not ctx.args:
            current = ctx.user_prefs.get("budget", "unlimited")
            return CommandResult(title="Budget", content=f"⚙️ Budget: **${current}**")
        try:
            usd = float(ctx.args[0])
            await _save_pref(ctx, "budget", usd)
            return CommandResult(title="Budget", content=f"⚙️ Budget → **${usd:.2f}** per message")
        except ValueError:
            return CommandResult(success=False, title="Budget", error="Usage: /mode budget <usd>")

    if sub == "verbose":
        if not ctx.args:
            current = ctx.user_prefs.get("verbose", 1)
            levels = {0: "Quiet", 1: "Compact", 2: "Verbose"}
            return CommandResult(title="Verbose", content=f"⚙️ Verbose: **{current}** ({levels.get(current, '?')})")
        try:
            level = min(max(int(ctx.args[0]), 0), 2)
            await _save_pref(ctx, "verbose", level)
            levels = {0: "Quiet", 1: "Compact", 2: "Verbose"}
            return CommandResult(title="Verbose", content=f"⚙️ Verbose → **{level}** ({levels.get(level, '')})")
        except ValueError:
            return CommandResult(success=False, title="Verbose", error="Usage: /mode verbose <0|1|2>")

    return CommandResult(success=False, title="Mode", error=f"Unknown subcommand: {sub}")


# ---------------------------------------------------------------------------
# /me [sub]
# ---------------------------------------------------------------------------

async def exec_me(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        p = ctx.user_prefs
        name = p.get("display_name") or "—"
        lang = p.get("language", "de")
        gh = p.get("github_username") or "—"
        email = p.get("email") or "—"
        instr = p.get("custom_instructions") or "—"
        lang_label = _LANGUAGE_OPTIONS.get(lang, lang)

        return CommandResult(
            title="Profile",
            content=(
                f"👤 **Your Profile**\n\n"
                f"- Name: **{name}**\n"
                f"- Language: **{lang_label}**\n"
                f"- GitHub: **{gh}**\n"
                f"- Email: **{email}**\n"
                f"- Instructions: _{instr}_"
            ),
        )

    sub = ctx.args[0].lower()
    ctx.args = ctx.args[1:]

    field_map = {
        "name": "display_name", "lang": "language", "github": "github_username",
        "email": "email", "instructions": "custom_instructions",
    }

    if sub not in field_map:
        return CommandResult(success=False, title="Profile", error=f"Unknown field: {sub}")

    if sub == "lang":
        if not ctx.args:
            return CommandResult(success=False, title="Language", error="Usage: /me lang <de|en|fr|...>")
        code = ctx.args[0].lower()
        if code not in _LANGUAGE_OPTIONS:
            return CommandResult(success=False, title="Language", error=f"Unknown language code: {code}")
        await _save_pref(ctx, "language", code)
        return CommandResult(title="Language", content=f"✅ Language → **{_LANGUAGE_OPTIONS[code]}**")

    if sub == "instructions" and ctx.args and ctx.args[0].lower() == "clear":
        await _save_pref(ctx, "custom_instructions", "")
        return CommandResult(title="Profile", content="✅ Instructions cleared.")

    if not ctx.args:
        return CommandResult(success=False, title="Profile", error=f"Usage: /me {sub} <value>")

    value = " ".join(ctx.args)
    await _save_pref(ctx, field_map[sub], value)
    return CommandResult(title="Profile", content=f"✅ {sub.capitalize()} → **{value}**")


# ---------------------------------------------------------------------------
# /memory [list|delete|search|recall]
# ---------------------------------------------------------------------------

_TYPE_ICONS = {"user": "👤", "feedback": "💬", "project": "📋", "reference": "🔗"}


async def exec_memory(ctx: CommandContext) -> CommandResult:
    es = ctx.es
    memories = await es.get_all_memories(ctx.user_id, limit=100)

    if not memories:
        return CommandResult(title="Memory", content="🧠 **Memory:** 0 entries")

    by_type: dict[str, int] = {}
    for m in memories:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1

    type_parts = ", ".join(f"{count} {t}" for t, count in sorted(by_type.items(), key=lambda x: -x[1]))
    return CommandResult(
        title="Memory",
        content=f"🧠 **Memory:** {len(memories)} entries\nTypes: {type_parts}",
        data={"count": len(memories), "types": by_type},
    )


async def exec_memory_list(ctx: CommandContext) -> CommandResult:
    es = ctx.es
    memories = await es.get_all_memories(ctx.user_id, limit=30)
    if not memories:
        return CommandResult(title="Memories", content="🧠 No saved memories.")

    by_type: dict[str, list] = {}
    for m in memories:
        by_type.setdefault(m["type"], []).append(m)

    lines = ["🧠 **Memories**\n"]
    for mem_type, items in sorted(by_type.items()):
        icon = _TYPE_ICONS.get(mem_type, "📌")
        lines.append(f"\n{icon} **{mem_type.capitalize()}**")
        for m in items:
            lines.append(f"- **{m['name']}**\n  {m.get('description', '')[:80]}\n  `{m['id'][:8]}`")

    return CommandResult(title="Memories", content="\n".join(lines))


async def exec_memory_delete(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(success=False, title="Memory", error="Usage: /memory delete <id>")
    mid = ctx.args[0]
    ok = await ctx.es.delete_memory(mid)
    if ok:
        return CommandResult(title="Memory", content=f"✅ Memory `{mid[:8]}` deleted.")
    return CommandResult(success=False, title="Memory", error=f"Memory `{mid[:8]}` not found.")


async def exec_memory_search(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(success=False, title="Search", error="Usage: /memory search <query>")
    query = " ".join(ctx.args)
    results = await ctx.es.search_conversations(ctx.user_id, query, limit=5)
    if not results:
        return CommandResult(title="Search", content=f'🔍 No results for "{query}".')

    lines = [f'🔍 **Conversations: "{query}"**\n']
    for r in results:
        role = "👤" if r.get("role") == "user" else "🤖"
        content = r.get("content", "")[:150]
        ts = r.get("timestamp", "")[:16]
        sid = short_name(r.get("session_id", ""))
        lines.append(f"{role} _{ts}_ `{sid}`\n  {content}")

    return CommandResult(title="Search", content="\n\n".join(lines))


async def exec_memory_recall(ctx: CommandContext) -> CommandResult:
    if not ctx.args:
        return CommandResult(success=False, title="Recall", error="Usage: /memory recall <query>")
    query = " ".join(ctx.args)
    results = await ctx.es.search_memories(ctx.user_id, query, limit=10)
    if not results:
        return CommandResult(title="Recall", content=f'🧠 No memories found for "{query}".')

    lines = [f'🧠 **Memories: "{query}"**\n']
    for m in results:
        icon = _TYPE_ICONS.get(m.get("type", ""), "📌")
        lines.append(f"{icon} **{m['name']}**\n  {m.get('content', '')[:150]}")

    return CommandResult(title="Recall", content="\n\n".join(lines))




# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

# Maps command names + subcommands to core handlers

async def exec_stop(ctx: CommandContext) -> CommandResult:
    """Stop execution — in Web UI this is informational, actual stop is via the stop button."""
    return CommandResult(
        title="Stop",
        content="⏹ Use the **Stop button** next to the input field to abort the current execution.",
    )


_COMMAND_HANDLERS: dict[str, dict[str | None, callable]] = {
    "new": {None: exec_new},
    "stop": {None: exec_stop},
    "session": {
        None: exec_session, "list": exec_session_list, "load": exec_session_load,
        "delete": exec_session_delete, "export": exec_session_export,
    },
    "status": {None: exec_status},
    "model": {None: exec_model},
    "mode": {None: exec_mode},
    "me": {None: exec_me},
    "memory": {
        None: exec_memory, "list": exec_memory_list, "delete": exec_memory_delete,
        "del": exec_memory_delete, "search": exec_memory_search,
        "recall": exec_memory_recall, "find": exec_memory_recall,
    },
}


async def execute_command(command: str, args: list[str], ctx: CommandContext) -> CommandResult:
    """Main entry point — execute a slash command and return structured result."""
    handlers = _COMMAND_HANDLERS.get(command)
    if not handlers:
        return CommandResult(success=False, title="Error", error=f"Unknown command: /{command}")

    # Check for subcommand
    sub = None
    if args and args[0].lower() in handlers:
        sub = args[0].lower()
        ctx.args = args[1:]
    else:
        ctx.args = args

    handler = handlers.get(sub)
    if not handler:
        handler = handlers.get(None)
    if not handler:
        return CommandResult(success=False, title="Error", error=f"Unknown subcommand: /{command} {sub}")

    try:
        return await handler(ctx)
    except Exception as e:
        return CommandResult(success=False, title="Error", error=str(e)[:500])


# ---------------------------------------------------------------------------
# Pref helper (writes to MySQL only, no Telegram context)
# ---------------------------------------------------------------------------

async def _save_pref(ctx: CommandContext, key: str, value):
    """Persist a preference to MySQL."""
    prefs = await ctx.mysql.get_preferences(ctx.user_id)
    prefs[key] = value
    await ctx.mysql.save_preferences(ctx.user_id, prefs)
    # Also update local copy
    ctx.user_prefs[key] = value
