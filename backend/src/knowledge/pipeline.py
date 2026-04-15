"""Knowledge graph write pipeline.

Automatically enriches saved memories with graph nodes and embeddings.
The pipeline is ONTOLOGY-DRIVEN — it reads the user's graph schema and
builds extraction prompts dynamically. No hardcoded memory types.

This is NOT an MCP tool — it runs as a background side-effect when
save_memory writes to Elasticsearch.
"""

import json
from typing import Any

import structlog

from ..config import Settings
from ..storage.neo4j import Neo4jStorage
from ..utils.embeddings import get_embedding
from ..utils.knowledge_extract import extract_with_ontology

logger = structlog.get_logger()


async def enrich_memory(
    neo4j: Neo4jStorage,
    settings: Settings,
    user_id: int,
    name: str,
    memory_type: str,
    description: str,
    content: str,
    tags: list[str] | None = None,
    ontology: dict | None = None,
    memory_version: int = 1,
    memory_id: str | None = None,
) -> dict[str, Any]:
    """Enrich a saved memory with graph nodes, edges, and embeddings.

    Ontology-driven: the user's schema defines what gets extracted.
    If no ontology is provided, nothing happens (graph not activated).

    memory_version: the ES version of the memory being saved. Stamped on
    all edges so stale connections can be identified later
    (edge.memory_version < current memory version = potentially stale).

    memory_id: the stable ES memory UUID. Stored on the primary node so
    graph search results can be linked back to the full memory document.
    """
    result = {"nodes": 0, "edges": 0, "entities": [], "suggestions": []}

    if not ontology:
        return result

    try:
        # Determine the node label for this memory
        label = _resolve_label(memory_type, ontology)

        # Generate embedding if the ontology says so
        node_config = ontology.get("nodes", {}).get(label, {})
        embedding = None
        if node_config.get("embedding", True):
            embed_text = f"{name}. {description}. {content[:2000]}"
            embedding = await get_embedding(embed_text, settings.openai_api_key)

        # Create the primary node for this memory
        # Always use "name" as key for memory-sourced nodes, regardless of
        # what the ontology defines as key (url, message_id, etc.).
        # The ontology key is for extracted entities from other sources.
        # save_memory always provides a stable "name" identifier.
        extra_props: dict[str, Any] = {"description": description}
        if embedding:
            extra_props["embedding"] = embedding
        if tags:
            extra_props["tags"] = tags
        if memory_id:
            extra_props["memory_id"] = memory_id

        await neo4j.merge_node(
            label, user_id,
            key_props={"name": name},
            extra_props=extra_props,
        )
        result["nodes"] += 1

        # Tag nodes (always, if tags provided and Tag is in ontology)
        if tags and "Tag" in ontology.get("nodes", {}):
            allowed_edges = _allowed_edge_types(ontology)
            for tag in tags:
                await neo4j.merge_node("Tag", user_id, key_props={"name": tag})
                if "TAGGED" in allowed_edges:
                    await neo4j.create_edge(
                        label, {"name": name},
                        "Tag", {"name": tag},
                        "TAGGED", user_id,
                        memory_version=memory_version,
                    )
                    result["edges"] += 1

        # Extract entities via Haiku using the user's ontology
        if settings.internal_api_key and len(content) > 30:
            extracted = await extract_with_ontology(
                ontology=ontology,
                memory_type=memory_type,
                name=name,
                description=description,
                content=content,
                api_url=settings.internal_api_url,
                api_key=settings.internal_api_key,
            )

            # Create extracted entity nodes
            for entity in extracted.get("entities", []):
                entity_label = entity["label"]
                entity_name = entity["name"]
                entity_config = ontology.get("nodes", {}).get(entity_label, {})
                entity_key = entity_config.get("key", "name")

                extra = {}
                if entity.get("properties"):
                    extra = {k: v for k, v in entity["properties"].items()
                             if v is not None}

                # Embedding for extracted entities if their ontology says so
                if entity_config.get("embedding", False):
                    entity_embed = await get_embedding(
                        entity_name, settings.openai_api_key,
                    )
                    extra["embedding"] = entity_embed

                await neo4j.merge_node(
                    entity_label, user_id,
                    key_props={entity_key: entity_name},
                    extra_props=extra or None,
                )
                result["nodes"] += 1

            # Create edges from primary node to extracted entities
            for edge in extracted.get("edges", []):
                to_label = edge["to_label"]
                to_name = edge["to_name"]
                to_config = ontology.get("nodes", {}).get(to_label, {})
                to_key = to_config.get("key", "name")

                created = await neo4j.create_edge(
                    label, {"name": name},
                    to_label, {to_key: to_name},
                    edge["type"], user_id,
                    props=edge.get("properties"),
                    memory_version=memory_version,
                )
                if created:
                    result["edges"] += 1

            result["entities"] = extracted.get("entities", [])

        # Check for dossier-like suggestions (topics with 3+ connections)
        if "Dossier" in ontology.get("nodes", {}):
            topic_counts = await neo4j.count_by_topic(user_id, min_articles=3)
            for tc in topic_counts:
                dossier_name = f"Dossier: {tc['topic']}"
                dossier_embedding = await get_embedding(
                    f"Dossier about {tc['topic']}", settings.openai_api_key,
                )
                await neo4j.merge_node(
                    "Dossier", user_id,
                    key_props={"name": dossier_name},
                    extra_props={
                        "topic": tc["topic"],
                        "article_count": tc["article_count"],
                        "status": "active",
                        "embedding": dossier_embedding,
                    },
                )
                allowed_edges = _allowed_edge_types(ontology)
                if "COVERS" in allowed_edges:
                    await neo4j.create_edge(
                        "Dossier", {"name": dossier_name},
                        "Topic", {"name": tc["topic"]},
                        "COVERS", user_id,
                        memory_version=memory_version,
                    )
                result["nodes"] += 1
                result["edges"] += 1
                result["suggestions"].append(
                    f"Dossier '{dossier_name}' erstellt ({tc['article_count']} Artikel)"
                )

    except Exception as e:
        logger.error("Knowledge enrichment failed", error=str(e),
                     memory_type=memory_type, name=name)

    if result["nodes"] > 0:
        logger.info("Knowledge enrichment complete",
                    memory_type=memory_type, name=name,
                    nodes=result["nodes"], edges=result["edges"])

    return result


async def remove_memory_from_graph(
    neo4j: Neo4jStorage,
    user_id: int,
    name: str,
    memory_type: str,
    ontology: dict | None = None,
) -> int:
    """Remove a memory's node from the graph and clean up orphans.

    Called on hard delete (purge). Performs DETACH DELETE + orphan cleanup.
    """
    total_deleted = 0
    try:
        label = _resolve_label(memory_type, ontology)
        # Memory-sourced nodes always use "name" as key (see enrich_memory)
        deleted = await neo4j.delete_node(label, {"name": name}, user_id)
        if deleted:
            total_deleted += 1
            orphans = await neo4j.cleanup_orphans(user_id)
            total_deleted += orphans

        logger.info("Memory removed from graph",
                    name=name, memory_type=memory_type,
                    deleted=total_deleted)
    except Exception as e:
        logger.error("Graph removal failed", error=str(e),
                     name=name, memory_type=memory_type)

    return total_deleted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_label(memory_type: str, ontology: dict | None) -> str:
    """Map memory_type to Neo4j node label.

    Uses ontology if available, otherwise capitalizes the type.
    """
    label = memory_type.capitalize()

    # Check if a matching label exists in ontology (case-insensitive)
    if ontology:
        nodes = ontology.get("nodes", {})
        # Direct match
        if label in nodes:
            return label
        # Case-insensitive search
        for node_label in nodes:
            if node_label.lower() == memory_type.lower():
                return node_label
        # Not in ontology — use generic label
        return "Memory"

    # No ontology — just capitalize
    if not label.isalpha():
        label = "Memory"
    return label


def _allowed_edge_types(ontology: dict) -> set[str]:
    """Extract set of allowed edge types from ontology."""
    return {e["type"] for e in ontology.get("edges", []) if "type" in e}
