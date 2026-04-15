"""MCP server definitions for all custom tools.

These are real MCP servers that Claude can call via the SDK.
Each server groups related tools.
"""

import asyncio
import json
from typing import Any

import structlog
from claude_agent_sdk import tool, create_sdk_mcp_server

from ..bus import live_bus
from ..config import Settings
from ..storage.elasticsearch import ElasticsearchStorage
from ..storage.neo4j import Neo4jStorage

logger = structlog.get_logger()

# Reserved memory name for the user's graph ontology
ONTOLOGY_MEMORY_NAME = "_graph_schema"


async def _load_user_ontology(es: ElasticsearchStorage, user_id: int) -> dict | None:
    """Load the user's graph ontology from their _graph_schema memory.

    Returns the parsed JSON ontology, or None if the user hasn't set one up.
    """
    try:
        mem = await es.find_memory_by_name(user_id, ONTOLOGY_MEMORY_NAME)
        if not mem:
            return None
        content = mem.get("content", "")
        ontology = json.loads(content)
        if isinstance(ontology, dict) and "nodes" in ontology:
            return ontology
        logger.warning("Invalid ontology format", user_id=user_id)
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Failed to load user ontology", user_id=user_id, error=str(e))
        return None


def create_memory_server(es: ElasticsearchStorage, user_id: int,
                         neo4j: Neo4jStorage | None = None,
                         settings: Settings | None = None,
                         ontology: dict | None = None):
    """Create MCP server for memory tools bound to a specific user."""

    # Build dynamic tool descriptions based on user's graph schema
    if ontology:
        node_types = ", ".join(sorted(ontology.get("nodes", {}).keys()))
        _save_tool_desc = (
            "Save important information to persistent memory. "
            "If a memory with the same name already exists, it is versioned "
            "(old version kept in history, new version becomes current). "
            f"Your graph is active — use one of your node types as memory_type: {node_types}."
        )
        _type_field_desc = f"Graph node type. Valid types: {node_types}"
    else:
        _save_tool_desc = (
            "Save important information to persistent memory. "
            "If a memory with the same name already exists, it is versioned "
            "(old version kept in history, new version becomes current). "
            "The memory_type is a free string — use whatever category fits best. "
            "Common types: user, feedback, project, reference, decision, convention, "
            "credential, todo, article, dossier, thought, excerpt, skill, draft."
        )
        _type_field_desc = "Category for the memory (e.g. user, project, decision, convention, article, thought, draft — any string)"

    @tool(
        "search_memory",
        "Search memories by keyword/topic. Use BEFORE answering questions about past work.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        },
    )
    async def search_memory(args: dict[str, Any]) -> dict[str, Any]:
        results = await es.search_memories(user_id, args["query"], args.get("limit", 10))
        if not results:
            return {"content": [{"type": "text", "text": "No memories found."}]}
        lines = []
        for m in results:
            lines.append(f"[{m['type']}] {m['name']}: {m.get('description', '')}")
            if m.get("content"):
                lines.append(f"  {m['content'][:300]}")
            lines.append(f"  (id: {m['id']})")
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "save_memory",
        _save_tool_desc,
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short identifier"},
                "memory_type": {"type": "string", "description": _type_field_desc},
                "description": {"type": "string", "description": "One-line description"},
                "content": {"type": "string", "description": "Full content"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
            },
            "required": ["name", "memory_type", "description", "content"],
        },
    )
    async def save_memory(args: dict[str, Any]) -> dict[str, Any]:
        # Check if a memory with this name already exists → version it
        existing = await es.find_memory_by_name(user_id, args["name"])
        memory_id = existing["id"] if existing else None
        version_info = ""
        new_version = 1
        if existing:
            old_version = existing.get("version", 1)
            new_version = old_version + 1
            version_info = f" (v{old_version} → v{new_version})"

        doc_id = await es.save_memory(
            user_id=user_id, name=args["name"], memory_type=args["memory_type"],
            description=args["description"], content=args["content"],
            tags=args.get("tags"), memory_id=memory_id,
        )

        # Knowledge graph enrichment (background, non-blocking)
        # Only runs if user has a graph ontology defined
        if neo4j and settings and settings.internal_api_key:
            _new_version = new_version  # capture for closure
            _memory_id = doc_id         # doc_id is the stable memory UUID returned by save_memory
            async def _enrich():
                try:
                    ontology = await _load_user_ontology(es, user_id)
                    if not ontology:
                        return  # Graph not activated for this user
                    from ..knowledge.pipeline import enrich_memory
                    await enrich_memory(
                        neo4j=neo4j, settings=settings, user_id=user_id,
                        name=args["name"], memory_type=args["memory_type"],
                        description=args["description"], content=args["content"],
                        tags=args.get("tags"), ontology=ontology,
                        memory_version=_new_version,
                        memory_id=_memory_id,
                    )
                except Exception as e:
                    logger.error("Knowledge enrichment failed", error=str(e), name=args["name"])
            asyncio.create_task(_enrich())

        return {"content": [{"type": "text", "text": f"Memory saved: {args['name']}{version_info} (id: {doc_id})"}]}

    @tool(
        "delete_memory",
        "Soft-delete a memory by its ID. The memory is marked as deleted but all versions are preserved in history. Use purge_memory for permanent deletion.",
        {"type": "object", "properties": {"memory_id": {"type": "string", "description": "The memory ID (stable across versions)"}}, "required": ["memory_id"]},
    )
    async def delete_memory(args: dict[str, Any]) -> dict[str, Any]:
        ok = await es.delete_memory(args["memory_id"], user_id)
        text = f"Soft-deleted {args['memory_id']} (history preserved)" if ok else f"Not found: {args['memory_id']}"
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "purge_memory",
        "Permanently delete a memory and ALL its versions. Also removes the corresponding node from the knowledge graph. This is irreversible.",
        {"type": "object", "properties": {"memory_id": {"type": "string", "description": "The memory ID to permanently delete"}}, "required": ["memory_id"]},
    )
    async def purge_memory(args: dict[str, Any]) -> dict[str, Any]:
        mid = args["memory_id"]
        # Get memory info before purging (for graph cleanup)
        history = await es.get_memory_history(mid, user_id)
        name = history[0].get("name") if history else None
        mtype = history[0].get("type") if history else None

        deleted = await es.purge_memory(mid, user_id)
        if deleted == 0:
            return {"content": [{"type": "text", "text": f"Not found: {mid}"}]}

        # Remove from knowledge graph + orphan cleanup
        graph_msg = ""
        if neo4j and name and mtype:
            async def _remove():
                try:
                    ontology = await _load_user_ontology(es, user_id)
                    from ..knowledge.pipeline import remove_memory_from_graph
                    removed = await remove_memory_from_graph(neo4j, user_id, name, mtype, ontology)
                    if removed > 0:
                        logger.info("Graph cleanup after purge", name=name, removed=removed)
                except Exception as e:
                    logger.error("Graph cleanup failed", error=str(e), name=name)
            asyncio.create_task(_remove())
            graph_msg = " + graph node queued for removal"

        return {"content": [{"type": "text", "text": f"Purged {mid}: {deleted} version(s) deleted{graph_msg}"}]}

    @tool(
        "memory_history",
        "Show all versions of a memory, including soft-deleted ones.",
        {"type": "object", "properties": {"memory_id": {"type": "string", "description": "The memory ID"}}, "required": ["memory_id"]},
    )
    async def memory_history(args: dict[str, Any]) -> dict[str, Any]:
        history = await es.get_memory_history(args["memory_id"], user_id)
        if not history:
            return {"content": [{"type": "text", "text": f"No history found for {args['memory_id']}"}]}
        lines = [f"History for: {history[0].get('name', '?')} ({args['memory_id']})"]
        lines.append("")
        for h in history:
            v = h.get("version", "?")
            current = "✓" if h.get("is_current") else ""
            deleted = " [DELETED]" if h.get("deleted_at") else ""
            updated = h.get("updated_at", "?")[:16]
            desc = h.get("description", "")[:80]
            lines.append(f"  v{v} {current}{deleted} ({updated}): {desc}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "list_memories",
        "List all stored memories for the current user.",
        {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}, "required": []},
    )
    async def list_memories(args: dict[str, Any]) -> dict[str, Any]:
        results = await es.get_all_memories(user_id, args.get("limit", 50))
        if not results:
            return {"content": [{"type": "text", "text": "No memories stored."}]}
        by_type: dict[str, list] = {}
        for m in results:
            by_type.setdefault(m["type"], []).append(m)
        lines = []
        for t, items in sorted(by_type.items()):
            lines.append(f"## {t.capitalize()}")
            for m in items:
                lines.append(f"- {m['name']}: {m.get('description', '')[:100]} (id: {m['id']})")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "search_conversations",
        "Full-text search over ALL past conversations across all sessions.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    )
    async def search_conversations(args: dict[str, Any]) -> dict[str, Any]:
        results = await es.search_conversations(user_id, args["query"], args.get("limit", 10))
        if not results:
            return {"content": [{"type": "text", "text": "No conversations found."}]}
        lines = []
        for r in results:
            ts = r.get("timestamp", "")[:16]
            role = r.get("role", "?")
            content = r.get("content", "")[:300]
            lines.append(f"[{ts}] {role}: {content}")
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    return create_sdk_mcp_server(
        name="memory",
        version="2.0.0",
        tools=[search_memory, save_memory, delete_memory, purge_memory,
               memory_history, list_memories, search_conversations],
    )


def create_cluster_server(settings: Settings):
    """Create MCP server for cluster database tools."""

    import aiomysql
    import aiohttp

    @tool(
        "query_mysql",
        "Execute SQL query against the MySQL database.",
        {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL query"},
                "database": {"type": "string", "description": "Database name (default: claude_code)"},
            },
            "required": ["sql"],
        },
    )
    async def query_mysql(args: dict[str, Any]) -> dict[str, Any]:
        db = args.get("database", settings.mysql_database)
        try:
            conn = await aiomysql.connect(
                host=settings.mysql_host, port=settings.mysql_port,
                user=settings.mysql_user, password=settings.mysql_password,
                db=db, charset="utf8mb4",
            )
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(args["sql"])
                sql_upper = args["sql"].strip().upper()
                if sql_upper.startswith("SELECT") or sql_upper.startswith("SHOW") or sql_upper.startswith("DESCRIBE"):
                    rows = await cur.fetchall()
                    conn.close()
                    return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2, ensure_ascii=False)}]}
                else:
                    await conn.commit()
                    result = f"OK, {cur.rowcount} rows affected"
                    conn.close()
                    return {"content": [{"type": "text", "text": result}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"MySQL error: {e}"}], "is_error": True}

    @tool(
        "query_elasticsearch",
        "Execute raw Elasticsearch HTTP request.",
        {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                "path": {"type": "string", "description": "ES path, e.g. /_cat/indices?v"},
                "body": {"type": "object", "description": "Optional JSON body"},
            },
            "required": ["method", "path"],
        },
    )
    async def query_elasticsearch(args: dict[str, Any]) -> dict[str, Any]:
        url = f"{settings.es_url}{args['path']}"
        try:
            async with aiohttp.ClientSession() as session:
                kwargs = {"headers": {"Content-Type": "application/json"}}
                if args.get("body"):
                    kwargs["json"] = args["body"]
                method = args["method"].upper()
                resp = await getattr(session, method.lower())(url, **kwargs)
                text = await resp.text()
                try:
                    text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass
                return {"content": [{"type": "text", "text": text}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"ES error: {e}"}], "is_error": True}

    @tool(
        "query_neo4j",
        "Execute Cypher query against Neo4j graph database.",
        {"type": "object", "properties": {"cypher": {"type": "string"}}, "required": ["cypher"]},
    )
    async def query_neo4j(args: dict[str, Any]) -> dict[str, Any]:
        url = f"http://{settings.neo4j_host}:{settings.neo4j_http_port}/db/neo4j/tx/commit"
        auth = aiohttp.BasicAuth(settings.neo4j_user, settings.neo4j_password)
        try:
            async with aiohttp.ClientSession(auth=auth) as session:
                resp = await session.post(url, json={"statements": [{"statement": args["cypher"]}]},
                                         headers={"Content-Type": "application/json"})
                result = await resp.json()
                errors = result.get("errors", [])
                if errors:
                    return {"content": [{"type": "text", "text": f"Neo4j error: {errors[0].get('message', str(errors))}"}], "is_error": True}
                data = result.get("results", [{}])[0]
                columns = data.get("columns", [])
                rows = data.get("data", [])
                if not rows:
                    return {"content": [{"type": "text", "text": "No results"}]}
                formatted = [dict(zip(columns, r["row"])) for r in rows]
                return {"content": [{"type": "text", "text": json.dumps(formatted, default=str, indent=2, ensure_ascii=False)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Neo4j error: {e}"}], "is_error": True}

    @tool(
        "search_web",
        "Search the web via SearXNG meta search engine.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    )
    async def search_web(args: dict[str, Any]) -> dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.get(
                    f"{settings.searxng_url}/search",
                    params={"q": args["query"], "format": "json"},
                    headers={"User-Agent": "banana-bot-cc/1.0"},
                )
                data = await resp.json()
                results = data.get("results", [])[:args.get("limit", 5)]
                formatted = [{"title": r["title"], "url": r["url"], "content": r.get("content", "")[:200]} for r in results]
                return {"content": [{"type": "text", "text": json.dumps(formatted, indent=2, ensure_ascii=False)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"SearXNG error: {e}"}], "is_error": True}

    return create_sdk_mcp_server(
        name="cluster",
        version="1.0.0",
        tools=[query_mysql, query_elasticsearch, query_neo4j, search_web],
    )


def create_comms_server(
    settings: Settings,
    bot=None,
    mysql=None,
    user_id: int | None = None,
    chat_id: int | None = None,
    cwd: str | None = None,
):
    """Create MCP server for communication tools (email + Telegram)."""

    import smtplib
    import uuid as _uuid
    from datetime import datetime, timezone
    from pathlib import Path
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from ..claude.session_sync import _find_jsonl, _project_dir_for_cwd

    @tool(
        "send_email",
        "Send email via SMTP. Sender address is configured via SMTP_USER.",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient address"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain text body"},
                "html": {"type": "string", "description": "Optional HTML body"},
            },
            "required": ["to", "subject", "body"],
        },
    )
    async def send_email(args: dict[str, Any]) -> dict[str, Any]:
        if not settings.smtp_host or not settings.smtp_user:
            return {"content": [{"type": "text", "text": "SMTP not configured"}], "is_error": True}
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = settings.smtp_user
            msg["To"] = args["to"]
            msg["Subject"] = args["subject"]
            msg.attach(MIMEText(args["body"], "plain", "utf-8"))
            if args.get("html"):
                msg.attach(MIMEText(args["html"], "html", "utf-8"))
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
            return {"content": [{"type": "text", "text": f"Email sent to {args['to']}: {args['subject']}"}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Email error: {e}"}], "is_error": True}

    tools_list = [send_email]

    # send_telegram is only available when bot + mysql + user_id + chat_id are wired up
    if bot is not None and mysql is not None and user_id is not None and chat_id is not None:

        @tool(
            "send_telegram",
            (
                "Send a Telegram message directly to the user and inject it into their active "
                "session so they can reply in context. Use for proactive notifications, reports, "
                "or reminders. The message is written into the conversation history — when the "
                "user replies, you will have full context of what you sent."
            ),
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Message text to send. Plain text, no Markdown.",
                    },
                },
                "required": ["text"],
            },
        )
        async def send_telegram(args: dict[str, Any]) -> dict[str, Any]:
            text = args["text"]
            cwd_path = cwd or settings.approved_directory
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            try:
                # ── 1. Find or create session ──────────────────────────────
                active = await mysql.get_active_session(user_id, cwd_path)
                if active:
                    session_id = active["session_id"]
                    is_new_session = False
                else:
                    session_id = str(_uuid.uuid4())
                    await mysql.save_session(session_id, user_id, cwd_path)
                    is_new_session = True

                # ── 2. Build JSONL entries ─────────────────────────────────
                # Synthetic user turn (needed so Claude SDK sees a valid u→a pair)
                user_entry_uuid = str(_uuid.uuid4())
                asst_entry_uuid = str(_uuid.uuid4())

                # Find parentUuid from last real JSONL entry
                parent_uuid = None
                if not is_new_session:
                    jsonl_path = _find_jsonl(session_id, cwd_path)
                    if jsonl_path and jsonl_path.exists():
                        for raw in reversed(jsonl_path.read_text().splitlines()):
                            try:
                                entry = json.loads(raw)
                                if entry.get("uuid"):
                                    parent_uuid = entry["uuid"]
                                    break
                            except Exception:
                                pass

                user_entry = json.dumps({
                    "parentUuid": parent_uuid,
                    "isSidechain": False,
                    "promptId": str(_uuid.uuid4()),
                    "type": "user",
                    "message": {"role": "user", "content": "(Proaktive Nachricht)"},
                    "uuid": user_entry_uuid,
                    "timestamp": now_iso,
                    "permissionMode": "dontAsk",
                    "userType": "external",
                    "entrypoint": "sdk-py",
                    "cwd": cwd_path,
                    "sessionId": session_id,
                    "version": "2.1.96",
                    "gitBranch": "HEAD",
                }, ensure_ascii=False)

                asst_entry = json.dumps({
                    "parentUuid": user_entry_uuid,
                    "isSidechain": False,
                    "message": {
                        "model": "claude-opus-4-6",
                        "id": f"msg_proactive_{asst_entry_uuid[:12]}",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": text}],
                        "stop_reason": "end_turn",
                        "stop_sequence": None,
                        "usage": {
                            "input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "output_tokens": 0,
                        },
                    },
                    "uuid": asst_entry_uuid,
                    "timestamp": now_iso,
                    "cwd": cwd_path,
                    "sessionId": session_id,
                    "version": "2.1.96",
                    "costUSD": 0.0,
                    "durationMs": 0,
                    "usage": {
                        "input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "output_tokens": 0,
                    },
                }, ensure_ascii=False)

                last_prompt_entry = json.dumps({
                    "type": "last-prompt",
                    "lastPrompt": "(Proaktive Nachricht)",
                    "sessionId": session_id,
                }, ensure_ascii=False)

                new_lines = f"{user_entry}\n{asst_entry}\n{last_prompt_entry}\n"

                # ── 3. Write / append JSONL on disk ────────────────────────
                project_dir = _project_dir_for_cwd(cwd_path)
                jsonl_path = project_dir / f"{session_id}.jsonl"

                if is_new_session or not jsonl_path.exists():
                    jsonl_path.write_text(new_lines, encoding="utf-8")
                else:
                    # Strip any trailing last-prompt line, then append
                    existing_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
                    while existing_lines and '"last-prompt"' in existing_lines[-1]:
                        existing_lines.pop()
                    prefix = "\n".join(existing_lines) + "\n" if existing_lines else ""
                    jsonl_path.write_text(prefix + new_lines, encoding="utf-8")

                # ── 4. Sync JSONL to MySQL session_content ─────────────────
                await mysql.save_session_content(
                    session_id, user_id, cwd_path,
                    jsonl_path.read_text(encoding="utf-8"),
                )

                # ── 5. Write to messages table (visible in web UI) ─────────
                await mysql.save_message(
                    session_id=session_id,
                    user_id=user_id,
                    prompt="(Proaktive Nachricht)",
                    response=text,
                    cost=0.0,
                    duration_ms=0,
                    model="proactive",
                )

                # ── 6. Push live event to WebUI via LiveEventBus ──────────
                if live_bus.has_subscribers(session_id):
                    await live_bus.publish(session_id, {"event": "text", "content": text})
                    await live_bus.publish(session_id, {
                        "event": "done",
                        "session_id": session_id,
                        "cost": 0.0,
                        "duration_ms": 0,
                        "tools_used": [],
                    })

                # ── 7. Send via Telegram ───────────────────────────────────
                await bot.send_message(chat_id=chat_id, text=text)

                from ..utils.session_names import short_name as _sn
                mode = "fortgesetzt" if not is_new_session else "neu"
                return {"content": [{"type": "text", "text": (
                    f"Nachricht gesendet. Session {_sn(session_id)} ({mode}). "
                    f"Antworten des Nutzers landen in dieser Session."
                )}]}

            except Exception as e:
                return {"content": [{"type": "text", "text": f"Fehler: {e}"}], "is_error": True}

        tools_list.append(send_telegram)

    # create_document + send_file are always available (no bot required for creation)
    @tool(
        "create_document",
        (
            "Create a file (Word .docx, Excel .xlsx, CSV, or plain text/Markdown) and return "
            "its path on disk. Use send_file afterwards to deliver it to the user via Telegram, "
            "or the user can download it from the Web-UI. "
            "For docx: pass content as plain text with # / ## / ### headings. "
            "For xlsx/csv: pass sheets as a list of objects with 'name', 'headers', 'rows'. "
            "For txt/md: pass content as plain text."
        ),
        {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename including extension, e.g. 'report.docx', 'data.xlsx', 'notes.md'",
                },
                "format": {
                    "type": "string",
                    "enum": ["docx", "xlsx", "csv", "txt", "md"],
                    "description": "File format",
                },
                "content": {
                    "type": "string",
                    "description": "Text content for docx / txt / md formats",
                },
                "sheets": {
                    "type": "array",
                    "description": "Sheet definitions for xlsx/csv: [{name, headers, rows}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "headers": {"type": "array", "items": {"type": "string"}},
                            "rows": {"type": "array", "items": {"type": "array"}},
                        },
                    },
                },
            },
            "required": ["filename", "format"],
        },
    )
    async def create_document(args: dict[str, Any]) -> dict[str, Any]:
        from .files import create_docx, create_xlsx, create_csv, create_text

        fmt = args["format"]
        filename = args["filename"]
        try:
            if fmt == "docx":
                path = create_docx(filename, args.get("content", ""))
            elif fmt == "xlsx":
                path = create_xlsx(filename, args.get("sheets", []))
            elif fmt == "csv":
                sheets = args.get("sheets", [{}])
                first = sheets[0] if sheets else {}
                path = create_csv(filename, first.get("headers", []), first.get("rows", []))
            else:  # txt / md
                path = create_text(filename, args.get("content", ""))
            return {"content": [{"type": "text", "text": str(path)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Fehler beim Erstellen: {e}"}], "is_error": True}

    tools_list.append(create_document)

    if bot is not None and chat_id is not None:

        @tool(
            "send_file",
            (
                "Send a file to the user via Telegram. Pass the file path returned by "
                "create_document (or any other path on disk). Optionally add a caption."
            ),
            {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file on disk",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional caption shown below the file in Telegram",
                    },
                },
                "required": ["path"],
            },
        )
        async def send_file(args: dict[str, Any]) -> dict[str, Any]:
            from pathlib import Path as _Path

            file_path = _Path(args["path"])
            if not file_path.exists():
                return {"content": [{"type": "text", "text": f"Datei nicht gefunden: {file_path}"}], "is_error": True}
            try:
                with open(file_path, "rb") as fh:
                    await bot.send_document(
                        chat_id=chat_id,
                        document=fh,
                        filename=file_path.name,
                        caption=args.get("caption") or "",
                    )
                return {"content": [{"type": "text", "text": f"Datei '{file_path.name}' gesendet."}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Fehler beim Senden: {e}"}], "is_error": True}

        tools_list.append(send_file)

    return create_sdk_mcp_server(
        name="comms",
        version="1.0.0",
        tools=tools_list,
    )


def create_utils_server():
    """Create MCP server for lightweight utility tools (time, etc.)."""

    from datetime import datetime, timezone

    @tool(
        "current_time",
        "Get current date and time. Token-efficient alternative to Bash 'date'.",
        {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Optional strftime format (default: ISO 8601)",
                },
            },
            "required": [],
        },
    )
    async def current_time(args: dict[str, Any]) -> dict[str, Any]:
        try:
            now = datetime.now().astimezone()
        except Exception:
            now = datetime.now(timezone.utc)
        fmt = args.get("format")
        if fmt:
            text = now.strftime(fmt)
        else:
            text = now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")
        return {"content": [{"type": "text", "text": text}]}

    return create_sdk_mcp_server(
        name="utils",
        version="1.0.0",
        tools=[current_time],
    )


def create_uploads_server(es_upload_storage, mysql: "MySQLStorage", user_id: int):
    """Create MCP server for searching and querying Telegram uploads."""

    @tool(
        "search_uploads",
        "Full-text search over all files/documents sent via Telegram (PDFs, videos, DOCX, images, etc.).",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "media_type": {
                    "type": "string",
                    "description": "Optional filter: image, video, audio, pdf, docx, xlsx, csv, text",
                },
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    )
    async def search_uploads(args: dict[str, Any]) -> dict[str, Any]:
        results = await es_upload_storage.search_uploads(
            user_id=user_id,
            query=args["query"],
            media_type=args.get("media_type"),
            limit=args.get("limit", 10),
        )
        if not results:
            return {"content": [{"type": "text", "text": "Keine Uploads gefunden."}]}
        lines = []
        for r in results:
            ts = r.get("created_at", "")[:10]
            fname = r.get("original_filename") or r.get("media_type", "?")
            mtype = r.get("media_type", "?")
            uid = r.get("upload_id", "?")
            preview = (r.get("content") or r.get("transcript") or "")[:200]
            lines.append(f"[{ts}] {mtype}: {fname} (id: {uid})")
            if preview:
                lines.append(f"  {preview}")
            lines.append("")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "get_upload",
        "Retrieve the full content of a specific upload by its upload_id.",
        {
            "type": "object",
            "properties": {
                "upload_id": {"type": "string", "description": "Upload ID"},
            },
            "required": ["upload_id"],
        },
    )
    async def get_upload(args: dict[str, Any]) -> dict[str, Any]:
        doc = await es_upload_storage.get_upload(args["upload_id"], user_id)
        if not doc:
            return {"content": [{"type": "text", "text": f"Upload nicht gefunden: {args['upload_id']}"}], "is_error": True}
        output = json.dumps(doc, ensure_ascii=False, indent=2, default=str)
        return {"content": [{"type": "text", "text": output}]}

    @tool(
        "query_table",
        "Query rows from a tabular upload (XLSX/CSV) stored in MySQL. Use upload_id from search_uploads.",
        {
            "type": "object",
            "properties": {
                "upload_id": {"type": "string", "description": "Upload ID of the table"},
                "limit": {"type": "integer", "default": 100, "description": "Max rows to return"},
            },
            "required": ["upload_id"],
        },
    )
    async def query_table(args: dict[str, Any]) -> dict[str, Any]:
        rows = await mysql.query_upload_rows(args["upload_id"], user_id, args.get("limit", 100))
        if not rows:
            return {"content": [{"type": "text", "text": "Keine Zeilen gefunden."}]}
        output = json.dumps(rows, ensure_ascii=False, indent=2, default=str)
        return {"content": [{"type": "text", "text": output}]}

    return create_sdk_mcp_server(
        name="uploads",
        version="1.0.0",
        tools=[search_uploads, get_upload, query_table],
    )


# ══════════════════════════════════════════════════════════════════════════════
# TTS SERVER
# ══════════════════════════════════════════════════════════════════════════════

def create_tts_server(settings: Settings, user_id: int):
    """MCP server for text-to-speech (Gemini and/or OpenAI).

    Exposes two tools:
      • generate_tts  — synthesise audio, using user/instance defaults for unset params
      • set_tts_settings — persist TTS preferences for the current user
    """
    import base64 as _base64

    from .gemini_tts import generate_tts as _gemini_tts
    from .openai_tts import (
        generate_tts as _openai_tts,
        OPENAI_TTS_MODELS,
    )
    from .tts_settings import get_user_tts_settings, save_user_tts_settings

    # ── generate_tts ──────────────────────────────────────────────────────────
    @tool(
        "generate_tts",
        (
            "Convert text to speech. Supports two providers:\n"
            "  • gemini  — voices: Aoede, Kore, Puck, Charon, Fenrir, Zephyr, Achernar, Gacrux;\n"
            "              style_prompt prepended to text (all models).\n"
            "  • openai  — models: tts-1, tts-1-hd (voices: alloy, echo, fable, onyx, nova, shimmer);\n"
            "              gpt-4o-mini-tts (voices: alloy, ash, ballad, coral, echo, fable, nova,\n"
            "              onyx, sage, shimmer, verse; supports style via instructions param).\n"
            "All parameters are optional — user preferences and instance defaults are used as fallback.\n"
            "Returns base64-encoded audio."
        ),
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to synthesise"},
                "provider": {
                    "type": "string",
                    "enum": ["gemini", "openai"],
                    "description": "TTS provider. Default: from user settings or instance config.",
                },
                "voice": {
                    "type": "string",
                    "description": "Voice name. Must be valid for the chosen provider/model.",
                },
                "style_prompt": {
                    "type": "string",
                    "description": "Style instruction, e.g. 'speak slowly and warmly'. "
                                   "Gemini: always effective. OpenAI: only with gpt-4o-mini-tts.",
                },
                "model": {
                    "type": "string",
                    "description": "Model override (OpenAI only): tts-1, tts-1-hd, gpt-4o-mini-tts.",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["oga", "mp3", "wav", "flac", "aac"],
                    "description": "Audio format. Default: oga",
                },
            },
            "required": ["text"],
        },
    )
    async def generate_tts(args: dict[str, Any]) -> dict[str, Any]:
        try:
            # Load user/instance defaults, then apply explicit args on top
            defaults = await get_user_tts_settings(user_id, settings)

            provider     = args.get("provider")     or defaults.provider
            voice        = args.get("voice")        or defaults.voice
            style_prompt = args.get("style_prompt") or defaults.style_prompt
            model        = args.get("model")        or defaults.model
            fmt          = args.get("output_format") or defaults.output_format

            if provider == "openai":
                if not settings.openai_api_key:
                    return {"content": [{"type": "text", "text": "Error: OPENAI_API_KEY not configured."}]}
                audio_bytes = _openai_tts(
                    api_key=settings.openai_api_key,
                    text=args["text"],
                    voice=voice,
                    style_prompt=style_prompt,
                    model=model or "tts-1-hd",
                    output_format=fmt,
                )
            else:
                # Default: gemini
                if not settings.gemini_api_key:
                    return {"content": [{"type": "text", "text": "Error: GEMINI_API_KEY not configured."}]}
                audio_bytes = _gemini_tts(
                    api_key=settings.gemini_api_key,
                    text=args["text"],
                    voice=voice,
                    style_prompt=style_prompt,
                    output_format=fmt,
                )

            b64 = _base64.b64encode(audio_bytes).decode()
            return {"content": [{"type": "text", "text": json.dumps({
                "audio_base64": b64,
                "format": fmt,
                "provider": provider,
                "voice": voice,
                "size_bytes": len(audio_bytes),
            })}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"TTS error: {e}"}]}

    # ── set_tts_settings ──────────────────────────────────────────────────────
    @tool(
        "set_tts_settings",
        (
            "Persist TTS preferences for the current user. "
            "Settings are saved to the database and used as defaults for all future generate_tts calls. "
            "Only pass fields you want to change — omitted fields keep their current value. "
            "Pass clear_style=true to remove a style_prompt, clear_model=true to reset to provider default."
        ),
        {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["gemini", "openai"],
                    "description": "Default TTS provider.",
                },
                "voice": {
                    "type": "string",
                    "description": "Default voice name.",
                },
                "style_prompt": {
                    "type": "string",
                    "description": "Default style instruction.",
                },
                "clear_style": {
                    "type": "boolean",
                    "description": "Set to true to remove the style_prompt.",
                },
                "model": {
                    "type": "string",
                    "description": "Default model (OpenAI only: tts-1, tts-1-hd, gpt-4o-mini-tts).",
                },
                "clear_model": {
                    "type": "boolean",
                    "description": "Set to true to reset model to provider default.",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["oga", "mp3", "wav", "flac", "aac"],
                    "description": "Default audio format.",
                },
            },
            "required": [],
        },
    )
    async def set_tts_settings(args: dict[str, Any]) -> dict[str, Any]:
        try:
            merged = await save_user_tts_settings(
                user_id=user_id,
                settings=settings,
                provider=args.get("provider"),
                voice=args.get("voice"),
                style_prompt=args.get("style_prompt"),
                clear_style=bool(args.get("clear_style", False)),
                model=args.get("model"),
                clear_model=bool(args.get("clear_model", False)),
                output_format=args.get("output_format"),
            )
            return {"content": [{"type": "text", "text": json.dumps({
                "status": "saved",
                "current_settings": {
                    "provider": merged.provider,
                    "voice": merged.voice,
                    "style_prompt": merged.style_prompt,
                    "model": merged.model,
                    "output_format": merged.output_format,
                },
            })}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error saving TTS settings: {e}"}]}

    return create_sdk_mcp_server(name="tts", version="1.0.0", tools=[generate_tts, set_tts_settings])


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE GENERATION SERVER
# ══════════════════════════════════════════════════════════════════════════════

def create_image_server(settings: Settings, user_id: int, bot=None, chat_id: int | None = None):
    """MCP server for AI image generation (Google Gemini / Imagen 4 + OpenAI).

    Exposes two tools:
      • generate_image     — generate an image, auto-send via Telegram if available
      • set_image_settings — persist image preferences for the current user
    """
    import base64 as _base64
    import tempfile
    from pathlib import Path as _Path

    from .gemini_image import (
        generate_image as _gemini_image,
        GEMINI_MODELS, IMAGEN_MODELS,
        IMAGEN_ASPECT_RATIOS,
        DEFAULT_MODEL as GEMINI_DEFAULT,
    )
    from .openai_image import (
        generate_image as _openai_image,
        GPT_IMAGE_MODELS, DALLE_MODELS,
        GPT_IMAGE_SIZES, DALLE3_SIZES,
        GPT_IMAGE_QUALITIES, DALLE3_QUALITIES,
        DEFAULT_MODEL as OPENAI_DEFAULT,
    )
    from .image_settings import get_user_image_settings, save_user_image_settings

    _GEMINI_MODEL_LIST = list(GEMINI_MODELS.keys()) + list(IMAGEN_MODELS.keys())
    _OPENAI_MODEL_LIST = list(GPT_IMAGE_MODELS.keys()) + list(DALLE_MODELS.keys())
    _ALL_MODELS = _GEMINI_MODEL_LIST + _OPENAI_MODEL_LIST

    # ── generate_image ────────────────────────────────────────────────────────
    @tool(
        "generate_image",
        (
            "Generate an image using AI. Supports:\n"
            "  • gemini provider:\n"
            "      - gemini-2.5-flash-image       (Nano Banana — fast, free tier)\n"
            "      - gemini-3.1-flash-image-preview (Nano Banana 2 — improved, 4K)\n"
            "      - gemini-3-pro-image-preview    (Nano Banana Pro — highest quality)\n"
            "      - imagen-4.0-fast-generate-001  (Imagen 4 Fast — $0.02)\n"
            "      - imagen-4.0-generate-001       (Imagen 4 Standard — $0.04)\n"
            "      - imagen-4.0-ultra-generate-001 (Imagen 4 Ultra — $0.06)\n"
            "  • openai provider:\n"
            "      - gpt-image-1.5    (flagship, best instruction following)\n"
            "      - gpt-image-1      (previous generation)\n"
            "      - gpt-image-1-mini (budget, high-volume)\n"
            "      - dall-e-3         (legacy, deprecated May 2026)\n"
            "All parameters optional — user preferences are used as fallback.\n"
            "Generated image is automatically sent to the user via Telegram."
        ),
        {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed text description of the image to generate",
                },
                "provider": {
                    "type": "string",
                    "enum": ["gemini", "openai"],
                    "description": "Image provider. Default: from user settings.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Gemini: gemini-2.5-flash-image / gemini-3.1-flash-image-preview / "
                        "gemini-3-pro-image-preview / imagen-4.0-fast-generate-001 / "
                        "imagen-4.0-generate-001 / imagen-4.0-ultra-generate-001. "
                        "OpenAI: gpt-image-1.5 / gpt-image-1 / gpt-image-1-mini / dall-e-3."
                    ),
                },
                "size": {
                    "type": "string",
                    "description": (
                        "OpenAI only. GPT-image: 1024x1024 / 1536x1024 / 1024x1536 / auto. "
                        "DALL-E 3: 1024x1024 / 1792x1024 / 1024x1792."
                    ),
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": IMAGEN_ASPECT_RATIOS,
                    "description": "Gemini/Imagen 4 only. Aspect ratio. Default: 1:1.",
                },
                "quality": {
                    "type": "string",
                    "description": (
                        "OpenAI only. GPT-image: low / medium / high / auto. "
                        "DALL-E 3: standard / hd."
                    ),
                },
                "style_prompt": {
                    "type": "string",
                    "description": "Optional style instruction prepended to the prompt.",
                },
            },
            "required": ["prompt"],
        },
    )
    async def generate_image(args: dict[str, Any]) -> dict[str, Any]:
        try:
            defaults = await get_user_image_settings(user_id, settings)

            provider     = args.get("provider")      or defaults.provider
            model        = args.get("model")         or defaults.model
            size         = args.get("size")          or defaults.size
            aspect_ratio = args.get("aspect_ratio")  or defaults.aspect_ratio
            quality      = args.get("quality")       or defaults.quality
            style_prompt = args.get("style_prompt")  or defaults.style_prompt
            prompt       = args["prompt"]

            if provider == "openai":
                if not settings.openai_api_key:
                    return {"content": [{"type": "text", "text": "Error: OPENAI_API_KEY not configured."}]}
                resolved_model = model or OPENAI_DEFAULT
                img_bytes = _openai_image(
                    api_key=settings.openai_api_key,
                    prompt=prompt,
                    model=resolved_model,
                    size=size,
                    quality=quality,
                    style_prompt=style_prompt,
                )
            else:
                # Default: gemini
                if not settings.gemini_api_key:
                    return {"content": [{"type": "text", "text": "Error: GEMINI_API_KEY not configured."}]}
                resolved_model = model or GEMINI_DEFAULT
                img_bytes = _gemini_image(
                    api_key=settings.gemini_api_key,
                    prompt=prompt,
                    model=resolved_model,
                    aspect_ratio=aspect_ratio,
                    style_prompt=style_prompt,
                )

            # ── Persist to disk ───────────────────────────────────────────────
            import uuid as _uuid
            creations_dir = _Path("/root/creations")
            creations_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{_uuid.uuid4().hex}.png"
            file_path = creations_dir / filename
            file_path.write_bytes(img_bytes)

            # Web UI URL (authenticated download, served inline)
            instance = settings.instance_name
            image_url = (
                f"/api/{instance}/files/download"
                f"?path=/root/creations/{filename}&inline=true"
            )
            image_markdown = f"![Generiertes Bild]({image_url})"

            # ── Send via Telegram ─────────────────────────────────────────────
            if bot is not None and chat_id is not None:
                from io import BytesIO
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=BytesIO(img_bytes),
                    caption=f"🎨 {prompt[:200]}{'…' if len(prompt) > 200 else ''}",
                )

            return {"content": [{"type": "text", "text": json.dumps({
                "status": "generated",
                "provider": provider,
                "model": resolved_model,
                "size_bytes": len(img_bytes),
                "file_path": str(file_path),
                "image_url": image_url,
                "image_markdown": image_markdown,
                "sent_to_telegram": bot is not None and chat_id is not None,
                "instruction": (
                    "Include the image in your response using this exact markdown: "
                    + image_markdown
                ),
            })}]}

        except Exception as e:
            return {"content": [{"type": "text", "text": f"Image generation error: {e}"}], "is_error": True}

    # ── set_image_settings ────────────────────────────────────────────────────
    @tool(
        "set_image_settings",
        (
            "Persist image generation preferences for the current user. "
            "Settings are saved to the database and used as defaults for all future generate_image calls. "
            "Only pass fields you want to change — omitted fields keep their current value."
        ),
        {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["gemini", "openai"],
                    "description": "Default image provider.",
                },
                "model": {
                    "type": "string",
                    "description": "Default model ID.",
                },
                "clear_model": {
                    "type": "boolean",
                    "description": "Set to true to reset model to provider default.",
                },
                "size": {
                    "type": "string",
                    "description": "Default size (OpenAI): 1024x1024 / 1536x1024 / 1024x1536.",
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": IMAGEN_ASPECT_RATIOS,
                    "description": "Default aspect ratio (Gemini/Imagen): 1:1 / 16:9 / 9:16 etc.",
                },
                "quality": {
                    "type": "string",
                    "description": "Default quality (OpenAI): low / medium / high / standard / hd.",
                },
                "style_prompt": {
                    "type": "string",
                    "description": "Default style instruction prepended to every prompt.",
                },
                "clear_style": {
                    "type": "boolean",
                    "description": "Set to true to remove the style_prompt.",
                },
            },
            "required": [],
        },
    )
    async def set_image_settings(args: dict[str, Any]) -> dict[str, Any]:
        try:
            merged = await save_user_image_settings(
                user_id=user_id,
                settings=settings,
                provider=args.get("provider"),
                model=args.get("model"),
                clear_model=bool(args.get("clear_model", False)),
                size=args.get("size"),
                aspect_ratio=args.get("aspect_ratio"),
                quality=args.get("quality"),
                style_prompt=args.get("style_prompt"),
                clear_style=bool(args.get("clear_style", False)),
            )
            return {"content": [{"type": "text", "text": json.dumps({
                "status": "saved",
                "current_settings": {
                    "provider": merged.provider,
                    "model": merged.model,
                    "size": merged.size,
                    "aspect_ratio": merged.aspect_ratio,
                    "quality": merged.quality,
                    "style_prompt": merged.style_prompt,
                },
            })}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error saving image settings: {e}"}]}

    return create_sdk_mcp_server(
        name="image",
        version="1.0.0",
        tools=[generate_image, set_image_settings],
    )


# ══════════════════════════════════════════════════════════════════════════════
def create_knowledge_server(
    neo4j: Neo4jStorage, settings: Settings, user_id: int,
    ontology: dict | None = None,
):
    """Create MCP server for knowledge graph READ tools.

    The graph is populated by the write pipeline (knowledge/pipeline.py),
    not by these tools. The bot can only query, not write.

    The ontology parameter drives dynamic label enums — if provided,
    graph_search offers only node types that have embeddings enabled.
    """

    # Build dynamic label enum from ontology
    if ontology:
        searchable_labels = [
            label for label, config in ontology.get("nodes", {}).items()
            if config.get("embedding", False)
        ]
    else:
        # Fallback for legacy/no-ontology case
        searchable_labels = ["Article", "Thought", "Decision", "Concept", "Dossier"]

    # All node labels (for graph_explore)
    all_labels = list(ontology.get("nodes", {}).keys()) if ontology else searchable_labels

    @tool(
        "graph_search",
        "Semantic similarity search across the knowledge graph. Finds related content by meaning — even without shared keywords. Use when looking for thematically related content.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text (will be embedded and compared)"},
                "label": {
                    "type": "string",
                    "description": f"Node type to search. Default: Article. Available: {', '.join(searchable_labels)}",
                    "enum": searchable_labels,
                },
                "limit": {"type": "integer", "description": "Max results (default: 10)"},
            },
            "required": ["query"],
        },
    )
    async def graph_search(args: dict[str, Any]) -> dict[str, Any]:
        from ..utils.embeddings import get_embedding
        query_embedding = await get_embedding(args["query"], settings.openai_api_key)
        label = args.get("label", "Article")
        limit = args.get("limit", 10)

        results = await neo4j.vector_search(label, query_embedding, user_id, limit)
        if not results:
            return {"content": [{"type": "text", "text": f"No {label} nodes found."}]}

        lines = []
        for r in results:
            score = f"{r['score']:.3f}"
            props = r["props"]
            name = props.get("name", props.get("title", "?"))
            desc = props.get("description", props.get("text", ""))[:200]
            lines.append(f"- [{score}] {name}: {desc}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "graph_explore",
        "Explore the knowledge graph around a specific node. Shows all connected nodes via graph traversal. Use to answer 'What do I know about X?'",
        {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": f"Node type. Available: {', '.join(all_labels)}",
                },
                "name": {"type": "string", "description": "Node name to explore"},
                "depth": {"type": "integer", "description": "Traversal depth (1-3, default: 1)"},
            },
            "required": ["label", "name"],
        },
    )
    async def graph_explore(args: dict[str, Any]) -> dict[str, Any]:
        label = args["label"]
        name = args["name"]
        depth = min(args.get("depth", 1), 3)

        neighbors = await neo4j.get_neighbors(
            label, {"name": name}, user_id, depth=depth,
        )
        if not neighbors:
            # Check if the node itself exists
            nodes = await neo4j.find_nodes(label, user_id, filters={"name": name}, limit=1)
            if not nodes:
                return {"content": [{"type": "text", "text": f"Node {label}:{name} not found."}]}
            return {"content": [{"type": "text", "text": f"Node {label}:{name} exists but has no connections."}]}

        lines = [f"Connections for {label}:{name}:"]
        for n in neighbors:
            n_labels = n.get("labels", ["?"])
            n_label = n_labels[0] if n_labels else "?"
            n_props = n.get("neighbor", {})
            n_name = n_props.get("name", n_props.get("title", "?"))
            rel = n.get("rel_type", "?")
            lines.append(f"  -[{rel}]-> {n_label}:{n_name}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "graph_topics",
        "Show topics with the most articles in the knowledge graph. Use for finding dossier candidates, identifying research patterns, or getting an overview of covered themes.",
        {
            "type": "object",
            "properties": {
                "min_articles": {"type": "integer", "description": "Minimum articles per topic (default: 2)"},
            },
            "required": [],
        },
    )
    async def graph_topics(args: dict[str, Any]) -> dict[str, Any]:
        min_articles = args.get("min_articles", 2)
        topics = await neo4j.count_by_topic(user_id, min_articles)
        if not topics:
            return {"content": [{"type": "text", "text": f"No topics with {min_articles}+ articles found."}]}

        lines = ["Topics by article count:"]
        for t in topics:
            lines.append(f"  {t['topic']}: {t['article_count']} articles")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "graph_stats",
        "Show knowledge graph statistics — how many nodes of each type, total edges. Use for a quick overview of the graph size.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    async def graph_stats(args: dict[str, Any]) -> dict[str, Any]:
        cypher = (
            "MATCH (n {user_id: $user_id}) "
            "RETURN labels(n)[0] AS label, count(n) AS count "
            "ORDER BY count DESC"
        )
        nodes = await neo4j.execute(cypher, {"user_id": user_id})

        edge_cypher = (
            "MATCH (a {user_id: $user_id})-[r]->(b {user_id: $user_id}) "
            "RETURN type(r) AS rel_type, count(r) AS count "
            "ORDER BY count DESC"
        )
        edges = await neo4j.execute(edge_cypher, {"user_id": user_id})

        lines = ["Nodes:"]
        total_nodes = 0
        for n in nodes:
            lines.append(f"  {n['label']}: {n['count']}")
            total_nodes += n["count"]
        lines.append(f"  Total: {total_nodes}")

        lines.append("\nEdges:")
        total_edges = 0
        for e in edges:
            lines.append(f"  {e['rel_type']}: {e['count']}")
            total_edges += e["count"]
        lines.append(f"  Total: {total_edges}")

        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    return create_sdk_mcp_server(
        name="knowledge",
        version="1.0.0",
        tools=[graph_search, graph_explore, graph_topics, graph_stats],
    )
