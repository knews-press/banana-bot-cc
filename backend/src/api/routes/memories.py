"""Memory REST endpoint — save a memory and trigger the NER pipeline.

Used by the web frontend's /ingest route (browser extension flow).
Unlike the MCP save_memory tool, this is a plain HTTP endpoint that can
be called without a Claude session.
"""

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth import get_api_user
from ...knowledge.pipeline import enrich_memory

logger = structlog.get_logger()
router = APIRouter()


class MemoryIngestRequest(BaseModel):
    name: str
    memory_type: str = "Article"
    description: str = ""
    content: str
    tags: list[str] | None = None


@router.post("/memories")
async def ingest_memory(
    body: MemoryIngestRequest,
    request: Request,
    user: dict = Depends(get_api_user),
):
    """Save a memory and run the NER enrichment pipeline.

    Mirrors the MCP save_memory tool but as a plain REST endpoint,
    so it can be called from the web frontend / browser extension
    without a running Claude session.
    """
    if not body.name or not body.content:
        raise HTTPException(status_code=400, detail="name und content sind erforderlich.")

    es = request.app.state.es
    neo4j = getattr(request.app.state, "neo4j", None)
    settings = request.app.state.settings
    user_id: int = user["user_id"]

    # Check for existing memory (versioning)
    existing = await es.find_memory_by_name(user_id, body.name)
    memory_id = existing["id"] if existing else None
    version = (existing.get("version", 1) + 1) if existing else 1

    # Save to Elasticsearch
    doc_id = await es.save_memory(
        user_id=user_id,
        name=body.name,
        memory_type=body.memory_type,
        description=body.description,
        content=body.content,
        tags=body.tags,
        memory_id=memory_id,
    )

    # Trigger NER pipeline (non-blocking on error)
    enrichment: dict = {"nodes": 0, "edges": 0, "entities": []}
    if neo4j:
        try:
            ontology_mem = await es.find_memory_by_name(user_id, "_graph_schema")
            ontology = None
            if ontology_mem:
                try:
                    ontology = json.loads(ontology_mem.get("content", ""))
                except Exception:
                    pass

            if ontology:
                enrichment = await enrich_memory(
                    neo4j=neo4j,
                    settings=settings,
                    user_id=user_id,
                    name=body.name,
                    memory_type=body.memory_type,
                    description=body.description,
                    content=body.content,
                    tags=body.tags,
                    ontology=ontology,
                    memory_version=version,
                    memory_id=doc_id,
                )
        except Exception as e:
            logger.error("ingest enrichment failed", error=str(e), name=body.name[:80])

    logger.info(
        "memory ingested via REST",
        user_id=user_id,
        name=body.name[:80],
        doc_id=doc_id,
        version=version,
        nodes=enrichment["nodes"],
        edges=enrichment["edges"],
    )

    return {
        "id": doc_id,
        "version": version,
        "enrichment": {
            "nodes": enrichment["nodes"],
            "edges": enrichment["edges"],
            "entities": [e["name"] for e in enrichment.get("entities", [])],
        },
    }
