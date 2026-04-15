"""Elasticsearch storage for memories and conversation logs."""

import json
import uuid as _uuid
from datetime import UTC, datetime

import aiohttp
import structlog

logger = structlog.get_logger()

MEMORY_INDEX = "claude-memories"
CONVERSATION_INDEX = "claude-conversations"

MEMORY_MAPPING = {
    "mappings": {
        "properties": {
            "user_id": {"type": "long"},
            "memory_id": {"type": "keyword"},
            "version": {"type": "integer"},
            "is_current": {"type": "boolean"},
            "deleted_at": {"type": "date"},
            "type": {"type": "keyword"},
            "name": {"type": "keyword"},
            "description": {"type": "text"},
            "content": {"type": "text", "analyzer": "standard"},
            "tags": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }
}

CONVERSATION_MAPPING = {
    "mappings": {
        "properties": {
            "session_id": {"type": "keyword"},
            "user_id": {"type": "long"},
            "timestamp": {"type": "date"},
            "role": {"type": "keyword"},
            "content": {"type": "text", "analyzer": "standard"},
            "tools_used": {"type": "keyword"},
            "cost": {"type": "float"},
            "model": {"type": "keyword"},
            "input_tokens": {"type": "integer"},
            "output_tokens": {"type": "integer"},
            "cache_creation_tokens": {"type": "integer"},
            "cache_read_tokens": {"type": "integer"},
        }
    }
}


class ElasticsearchStorage:
    def __init__(self, es_url: str):
        self.es_url = es_url.rstrip("/")
        self.session: aiohttp.ClientSession | None = None

    async def initialize(self):
        self.session = aiohttp.ClientSession()

        for index, mapping in [
            (MEMORY_INDEX, MEMORY_MAPPING),
            (CONVERSATION_INDEX, CONVERSATION_MAPPING),
        ]:
            resp = await self.session.head(f"{self.es_url}/{index}")
            if resp.status == 404:
                resp = await self.session.put(
                    f"{self.es_url}/{index}",
                    json=mapping,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status in (200, 201):
                    logger.info("Created ES index", index=index)
                else:
                    body = await resp.text()
                    logger.error("Failed to create ES index", index=index, body=body)
            else:
                # Index exists — apply any new mapping fields (additive only)
                resp = await self.session.put(
                    f"{self.es_url}/{index}/_mapping",
                    json=mapping["mappings"],
                    headers={"Content-Type": "application/json"},
                )
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.warning("ES mapping update failed", index=index, body=body[:200])

        logger.info("Elasticsearch storage initialized")

    async def close(self):
        if self.session:
            await self.session.close()

    # --- Memory ---

    async def save_memory(self, user_id: int, name: str, memory_type: str,
                          description: str, content: str,
                          tags: list[str] | None = None,
                          memory_id: str | None = None) -> str:
        """Save a memory with versioning.

        If memory_id is provided, creates a new version of that memory
        (marks the old current version as non-current).
        If memory_id is None, creates a brand-new memory with version 1.
        Returns the memory_id (stable across versions).
        """
        now = datetime.now(UTC).isoformat()

        if memory_id:
            # Existing memory — find current version to bump
            prev = await self._get_current_version(user_id, memory_id)
            if prev:
                version = prev.get("version", 1) + 1
                # Mark old version as non-current
                await self.session.post(
                    f"{self.es_url}/{MEMORY_INDEX}/_update/{prev['_es_id']}",
                    json={"doc": {"is_current": False}},
                    headers={"Content-Type": "application/json"},
                )
            else:
                version = 1
        else:
            memory_id = str(_uuid.uuid4())
            version = 1

        doc = {
            "user_id": user_id,
            "memory_id": memory_id,
            "version": version,
            "is_current": True,
            "type": memory_type,
            "name": name,
            "description": description,
            "content": content,
            "tags": tags or [],
            "created_at": now if version == 1 else (
                (await self._get_first_created(user_id, memory_id)) or now
            ),
            "updated_at": now,
        }
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_doc",
            json=doc,
            headers={"Content-Type": "application/json"},
        )
        await resp.json()
        # Refresh so subsequent searches see the new version immediately
        await self.session.post(f"{self.es_url}/{MEMORY_INDEX}/_refresh")
        return memory_id

    async def _get_current_version(self, user_id: int, memory_id: str) -> dict | None:
        """Get the current version doc for a memory_id. Returns source + _es_id."""
        search = {
            "query": {"bool": {"must": [
                {"term": {"user_id": user_id}},
                {"term": {"memory_id": memory_id}},
                {"term": {"is_current": True}},
            ]}},
            "size": 1,
        }
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_search",
            json=search, headers={"Content-Type": "application/json"},
        )
        data = await resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return {"_es_id": hits[0]["_id"], **hits[0]["_source"]}

    async def _get_first_created(self, user_id: int, memory_id: str) -> str | None:
        """Get the original created_at timestamp for a memory."""
        search = {
            "query": {"bool": {"must": [
                {"term": {"user_id": user_id}},
                {"term": {"memory_id": memory_id}},
            ]}},
            "size": 1,
            "sort": [{"version": "asc"}],
            "_source": ["created_at"],
        }
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_search",
            json=search, headers={"Content-Type": "application/json"},
        )
        data = await resp.json()
        hits = data.get("hits", {}).get("hits", [])
        return hits[0]["_source"]["created_at"] if hits else None

    def _normalize_hit(self, hit: dict) -> dict:
        """Normalize a hit for backward compat: add memory_id/version if missing."""
        src = hit["_source"]
        # Lazy migration: old docs without memory_id get their ES _id as memory_id
        if "memory_id" not in src:
            src["memory_id"] = hit["_id"]
            src.setdefault("version", 1)
            src.setdefault("is_current", True)
        # Expose memory_id as the stable "id" for tools
        return {"id": src["memory_id"], **src}

    async def search_memories(self, user_id: int, query: str,
                              limit: int = 10) -> list[dict]:
        search = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"user_id": user_id}},
                        {"multi_match": {
                            "query": query,
                            "fields": ["name^3", "description^2", "content", "tags^2"],
                        }},
                    ],
                    "must_not": [
                        {"exists": {"field": "deleted_at"}},
                    ],
                    "should": [
                        {"term": {"is_current": True}},
                    ],
                    "minimum_should_match": 0,
                }
            },
            "size": limit,
            "sort": [{"_score": "desc"}, {"updated_at": "desc"}],
            # Prefer is_current:true via should boost; filter out deleted
            "post_filter": {
                "bool": {
                    "should": [
                        {"term": {"is_current": True}},
                        # Old docs without is_current field — treat as current
                        {"bool": {"must_not": {"exists": {"field": "is_current"}}}},
                    ],
                }
            },
        }
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_search",
            json=search,
            headers={"Content-Type": "application/json"},
        )
        result = await resp.json()
        return [
            self._normalize_hit(hit)
            for hit in result.get("hits", {}).get("hits", [])
        ]

    async def get_all_memories(self, user_id: int, limit: int = 100) -> list[dict]:
        search = {
            "query": {
                "bool": {
                    "must": [{"term": {"user_id": user_id}}],
                    "must_not": [{"exists": {"field": "deleted_at"}}],
                    "should": [
                        {"term": {"is_current": True}},
                        {"bool": {"must_not": {"exists": {"field": "is_current"}}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": limit,
            "sort": [{"updated_at": "desc"}],
        }
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_search",
            json=search,
            headers={"Content-Type": "application/json"},
        )
        result = await resp.json()
        return [
            self._normalize_hit(hit)
            for hit in result.get("hits", {}).get("hits", [])
        ]

    async def delete_memory(self, memory_id: str, user_id: int) -> bool:
        """Soft delete: marks the current version as non-current + sets deleted_at.

        The memory_id can be either the stable memory_id (UUID) or a legacy ES _id.
        All versions are preserved for history.
        """
        now = datetime.now(UTC).isoformat()

        # Try by memory_id field first (new format)
        current = await self._get_current_version(user_id, memory_id)
        if current:
            await self.session.post(
                f"{self.es_url}/{MEMORY_INDEX}/_update/{current['_es_id']}",
                json={"doc": {"is_current": False, "deleted_at": now}},
                headers={"Content-Type": "application/json"},
            )
            await self.session.post(f"{self.es_url}/{MEMORY_INDEX}/_refresh")
            return True

        # Fallback: legacy doc where memory_id == ES _id
        search_resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_search",
            json={"query": {"bool": {"must": [
                {"term": {"user_id": user_id}},
                {"ids": {"values": [memory_id]}},
            ]}}},
            headers={"Content-Type": "application/json"},
        )
        data = await search_resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return False
        await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_update/{memory_id}",
            json={"doc": {"is_current": False, "deleted_at": now}},
            headers={"Content-Type": "application/json"},
        )
        await self.session.post(f"{self.es_url}/{MEMORY_INDEX}/_refresh")
        return True

    async def purge_memory(self, memory_id: str, user_id: int) -> int:
        """Hard delete: removes ALL versions of a memory permanently.

        Returns the number of documents deleted.
        """
        # Delete by memory_id field (new format)
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_delete_by_query",
            json={"query": {"bool": {"must": [
                {"term": {"user_id": user_id}},
                {"term": {"memory_id": memory_id}},
            ]}}},
            headers={"Content-Type": "application/json"},
        )
        result = await resp.json()
        deleted = result.get("deleted", 0)

        if deleted == 0:
            # Fallback: legacy doc where ES _id == memory_id
            search_resp = await self.session.post(
                f"{self.es_url}/{MEMORY_INDEX}/_search",
                json={"query": {"bool": {"must": [
                    {"term": {"user_id": user_id}},
                    {"ids": {"values": [memory_id]}},
                ]}}},
                headers={"Content-Type": "application/json"},
            )
            data = await search_resp.json()
            if data.get("hits", {}).get("hits"):
                del_resp = await self.session.delete(
                    f"{self.es_url}/{MEMORY_INDEX}/_doc/{memory_id}",
                )
                if del_resp.status == 200:
                    deleted = 1

        if deleted > 0:
            await self.session.post(f"{self.es_url}/{MEMORY_INDEX}/_refresh")
        return deleted

    async def get_memory_history(self, memory_id: str, user_id: int) -> list[dict]:
        """Get all versions of a memory, ordered by version ascending."""
        search = {
            "query": {"bool": {"must": [
                {"term": {"user_id": user_id}},
                # Try memory_id field OR ES _id for legacy
                {"bool": {"should": [
                    {"term": {"memory_id": memory_id}},
                    {"ids": {"values": [memory_id]}},
                ]}},
            ]}},
            "size": 100,
            "sort": [{"version": {"order": "asc", "missing": "_first"}}],
        }
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_search",
            json=search, headers={"Content-Type": "application/json"},
        )
        result = await resp.json()
        return [
            self._normalize_hit(hit)
            for hit in result.get("hits", {}).get("hits", [])
        ]

    async def find_memory_by_name(self, user_id: int, name: str) -> dict | None:
        """Find the current version of a memory by exact name match."""
        search = {
            "query": {"bool": {
                "must": [
                    {"term": {"user_id": user_id}},
                    {"term": {"name": name}},
                ],
                "must_not": [{"exists": {"field": "deleted_at"}}],
                "should": [
                    {"term": {"is_current": True}},
                    {"bool": {"must_not": {"exists": {"field": "is_current"}}}},
                ],
                "minimum_should_match": 1,
            }},
            "size": 1,
            "sort": [{"version": {"order": "desc", "missing": "_first"}}],
        }
        resp = await self.session.post(
            f"{self.es_url}/{MEMORY_INDEX}/_search",
            json=search, headers={"Content-Type": "application/json"},
        )
        data = await resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return self._normalize_hit(hits[0])

    # --- Conversation Log ---

    async def log_conversation(self, session_id: str, user_id: int,
                               role: str, content: str,
                               tools_used: list[str] | None = None,
                               cost: float = 0.0, model: str = "",
                               input_tokens: int = 0, output_tokens: int = 0,
                               cache_creation_tokens: int = 0, cache_read_tokens: int = 0):
        doc = {
            "session_id": session_id,
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "role": role,
            "content": content,
            "tools_used": tools_used or [],
            "cost": cost,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens": cache_read_tokens,
        }
        await self.session.post(
            f"{self.es_url}/{CONVERSATION_INDEX}/_doc",
            json=doc,
            headers={"Content-Type": "application/json"},
        )

    async def search_conversations(self, user_id: int, query: str,
                                   limit: int = 20) -> list[dict]:
        search = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"user_id": user_id}},
                        {"match": {"content": query}},
                    ]
                }
            },
            "size": limit,
            "sort": [{"timestamp": "desc"}],
        }
        resp = await self.session.post(
            f"{self.es_url}/{CONVERSATION_INDEX}/_search",
            json=search,
            headers={"Content-Type": "application/json"},
        )
        result = await resp.json()
        return [
            {"id": hit["_id"], **hit["_source"]}
            for hit in result.get("hits", {}).get("hits", [])
        ]
