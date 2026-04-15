"""MCP tools for memory management via Elasticsearch.

Claude calls these tools directly instead of writing local files.
Provides semantic search over memories and conversations.
"""

import json

from ..storage.elasticsearch import ElasticsearchStorage


async def search_memory(es: ElasticsearchStorage, user_id: int,
                        query: str, limit: int = 10) -> str:
    """Search memories by content, name, description, or tags.

    Returns relevant memories ranked by relevance.
    """
    results = await es.search_memories(user_id, query, limit=limit)
    if not results:
        return "No memories found matching that query."

    lines = []
    for m in results:
        lines.append(f"[{m['type']}] {m['name']}")
        lines.append(f"  {m.get('description', '')}")
        content = m.get('content', '')
        if content:
            lines.append(f"  {content[:500]}")
        v = m.get("version", "?")
        lines.append(f"  (id: {m['id']}, v{v})")
        lines.append("")
    return "\n".join(lines)


async def save_memory(es: ElasticsearchStorage, user_id: int,
                      name: str, memory_type: str, description: str,
                      content: str, tags: list[str] | None = None) -> str:
    """Save a new memory or create a new version of an existing one."""
    existing = await es.find_memory_by_name(user_id, name)
    memory_id = existing["id"] if existing else None

    doc_id = await es.save_memory(
        user_id=user_id, name=name, memory_type=memory_type,
        description=description, content=content, tags=tags,
        memory_id=memory_id,
    )
    version_info = ""
    if existing:
        old_v = existing.get("version", 1)
        version_info = f" (v{old_v} → v{old_v + 1})"
    return f"Memory saved: {name}{version_info} (id: {doc_id})"


async def delete_memory(es: ElasticsearchStorage, user_id: int,
                        memory_id: str) -> str:
    """Soft-delete a memory by its ID."""
    ok = await es.delete_memory(memory_id, user_id)
    if ok:
        return f"Memory {memory_id} soft-deleted (history preserved)."
    return f"Memory {memory_id} not found."


async def list_memories(es: ElasticsearchStorage, user_id: int,
                        limit: int = 50) -> str:
    """List all memories for the current user."""
    results = await es.get_all_memories(user_id, limit=limit)
    if not results:
        return "No memories stored."

    by_type: dict[str, list] = {}
    for m in results:
        by_type.setdefault(m["type"], []).append(m)

    lines = []
    for mem_type, items in sorted(by_type.items()):
        lines.append(f"## {mem_type.capitalize()}")
        for m in items:
            v = m.get("version", "?")
            lines.append(f"- {m['name']}: {m.get('description', '')[:100]} (id: {m['id']}, v{v})")
        lines.append("")
    return "\n".join(lines)


async def search_conversations(es: ElasticsearchStorage, user_id: int,
                               query: str, limit: int = 10) -> str:
    """Full-text search over past conversations.

    Searches through all messages (user and assistant) across all sessions.
    """
    results = await es.search_conversations(user_id, query, limit=limit)
    if not results:
        return "No conversations found matching that query."

    lines = []
    for r in results:
        ts = r.get("timestamp", "")[:16]
        role = r.get("role", "?")
        content = r.get("content", "")[:400]
        from ..utils.session_names import short_name
        sid = short_name(r.get("session_id", ""))
        tools = ", ".join(r.get("tools_used", []))
        lines.append(f"[{ts}] ({role}, session {sid})")
        lines.append(f"  {content}")
        if tools:
            lines.append(f"  Tools: {tools}")
        lines.append("")
    return "\n".join(lines)
