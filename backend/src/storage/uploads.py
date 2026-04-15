"""Elasticsearch storage for Telegram uploads (full-text search index)."""

import json
from datetime import UTC, datetime
from typing import Any

import aiohttp
import structlog

logger = structlog.get_logger()

UPLOADS_INDEX = "telegram-uploads"


class UploadsStorage:
    """Manages the telegram-uploads Elasticsearch index."""

    def __init__(self, es_url: str):
        self.es_url = es_url.rstrip("/")

    async def _ensure_index(self, session: aiohttp.ClientSession):
        """Create index with mappings if it doesn't exist."""
        url = f"{self.es_url}/{UPLOADS_INDEX}"
        async with session.head(url) as resp:
            if resp.status == 200:
                return
        mappings = {
            "mappings": {
                "properties": {
                    "upload_id": {"type": "keyword"},
                    "user_id": {"type": "long"},
                    "media_type": {"type": "keyword"},
                    "mime_type": {"type": "keyword"},
                    "original_filename": {"type": "keyword"},
                    "caption": {"type": "text", "analyzer": "standard"},
                    "content": {"type": "text", "analyzer": "standard"},
                    "transcript": {"type": "text", "analyzer": "standard"},
                    "vision_summary": {"type": "text", "analyzer": "standard"},
                    "file_size": {"type": "long"},
                    "created_at": {"type": "date"},
                    "tags": {"type": "keyword"},
                }
            }
        }
        async with session.put(url, json=mappings) as resp:
            if resp.status not in (200, 201):
                body = await resp.text()
                logger.warning("Failed to create uploads index", status=resp.status, body=body[:200])

    async def index_upload(
        self,
        upload_id: str,
        user_id: int,
        media_type: str,
        mime_type: str | None,
        original_filename: str | None,
        content: str,
        caption: str | None = None,
        transcript: str | None = None,
        vision_summary: str | None = None,
        file_size: int = 0,
        tags: list[str] | None = None,
    ) -> str:
        """Index an upload into ES. Returns the ES document ID."""
        doc = {
            "upload_id": upload_id,
            "user_id": user_id,
            "media_type": media_type,
            "mime_type": mime_type or "",
            "original_filename": original_filename or "",
            "content": content,
            "caption": caption or "",
            "transcript": transcript or "",
            "vision_summary": vision_summary or "",
            "file_size": file_size,
            "tags": tags or [],
            "created_at": datetime.now(UTC).isoformat(),
        }
        async with aiohttp.ClientSession() as session:
            await self._ensure_index(session)
            url = f"{self.es_url}/{UPLOADS_INDEX}/_doc/{upload_id}"
            async with session.put(url, json=doc) as resp:
                body = await resp.json()
                if resp.status not in (200, 201):
                    logger.error("ES index_upload failed", status=resp.status, body=str(body)[:200])
                    raise RuntimeError(f"ES error {resp.status}: {body}")
                return body.get("_id", upload_id)

    async def search_uploads(
        self,
        user_id: int,
        query: str,
        media_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Full-text search over upload content, transcript, caption, vision_summary."""
        must: list[dict] = [
            {"term": {"user_id": user_id}},
            {
                "multi_match": {
                    "query": query,
                    "fields": ["content", "transcript", "caption", "vision_summary", "original_filename"],
                    "type": "best_fields",
                }
            },
        ]
        if media_type:
            must.append({"term": {"media_type": media_type}})

        body = {
            "query": {"bool": {"must": must}},
            "size": limit,
            "sort": [{"created_at": {"order": "desc"}}],
        }
        async with aiohttp.ClientSession() as session:
            url = f"{self.es_url}/{UPLOADS_INDEX}/_search"
            async with session.post(url, json=body) as resp:
                if resp.status == 404:
                    return []
                data = await resp.json()
                hits = data.get("hits", {}).get("hits", [])
                return [
                    {**h["_source"], "_score": h.get("_score", 0)}
                    for h in hits
                ]

    async def get_upload(self, upload_id: str, user_id: int) -> dict | None:
        """Fetch a single upload document by ID."""
        async with aiohttp.ClientSession() as session:
            url = f"{self.es_url}/{UPLOADS_INDEX}/_doc/{upload_id}"
            async with session.get(url) as resp:
                if resp.status == 404:
                    return None
                data = await resp.json()
                if not data.get("found"):
                    return None
                src = data["_source"]
                if src.get("user_id") != user_id:
                    return None
                return src
