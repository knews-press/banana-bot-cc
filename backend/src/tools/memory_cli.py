"""CLI wrapper for memory tools — used by Claude Code in SSH sessions.

Called via: python3 -m src.tools.memory_cli <command> [args]
Uses the owner_user_id from config for user identification.
"""

import asyncio
import json
import sys

from ..config import Settings
from ..storage.elasticsearch import ElasticsearchStorage


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m src.tools.memory_cli <command> [args]")
        print("Commands: search <query> | save <name> <type> <description> <content> | list | delete <id> | purge <id> | history <id> | search_conversations <query>")
        sys.exit(1)

    settings = Settings()
    es = ElasticsearchStorage(settings.es_url)
    await es.initialize()
    user_id = settings.owner_user_id

    cmd = sys.argv[1]

    if cmd == "search" and len(sys.argv) >= 3:
        query = " ".join(sys.argv[2:])
        results = await es.search_memories(user_id, query)
        for m in results:
            print(f"[{m['type']}] {m['name']} (id: {m['id']})")
            print(f"  {m.get('description', '')}")
            print(f"  {m.get('content', '')[:300]}")
            print()

    elif cmd == "save" and len(sys.argv) >= 6:
        name, mem_type, description = sys.argv[2], sys.argv[3], sys.argv[4]
        content = " ".join(sys.argv[5:])
        doc_id = await es.save_memory(user_id, name, mem_type, description, content)
        print(f"Saved: {name} (id: {doc_id})")

    elif cmd == "list":
        results = await es.get_all_memories(user_id)
        for m in results:
            print(f"[{m['type']}] {m['name']}: {m.get('description', '')[:80]} (id: {m['id']})")

    elif cmd == "delete" and len(sys.argv) >= 3:
        ok = await es.delete_memory(sys.argv[2], user_id)
        print("Soft-deleted (history preserved)" if ok else "Not found")

    elif cmd == "purge" and len(sys.argv) >= 3:
        deleted = await es.purge_memory(sys.argv[2], user_id)
        print(f"Purged: {deleted} version(s) deleted" if deleted else "Not found")

    elif cmd == "history" and len(sys.argv) >= 3:
        history = await es.get_memory_history(sys.argv[2], user_id)
        for h in history:
            v = h.get("version", "?")
            current = " [CURRENT]" if h.get("is_current") else ""
            deleted = " [DELETED]" if h.get("deleted_at") else ""
            print(f"v{v}{current}{deleted} ({h.get('updated_at', '?')[:16]}): {h.get('description', '')[:80]}")

    elif cmd == "search_conversations" and len(sys.argv) >= 3:
        query = " ".join(sys.argv[2:])
        results = await es.search_conversations(user_id, query)
        for r in results:
            print(f"[{r.get('timestamp', '')[:16]}] {r['role']}: {r.get('content', '')[:200]}")
            print()

    else:
        print(f"Unknown command or missing args: {cmd}")
        sys.exit(1)

    await es.close()


if __name__ == "__main__":
    asyncio.run(main())
