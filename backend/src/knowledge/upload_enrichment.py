"""Upload → Memory enrichment pipeline.

When a user uploads a file via Telegram, this module:
1. Loads the user's ontology (graph schema)
2. Asks Haiku to classify the upload into an appropriate memory type
3. Saves it as a memory in ES (so it becomes a first-class knowledge item)
4. Triggers the standard enrichment pipeline (embedding, NER, graph)

This makes uploads "look like memories" — they appear in the memory index,
get graph nodes, and are searchable alongside manually created memories.

Only runs if the user has a graph ontology defined (`_graph_schema` memory).
Without it, uploads are still stored in the telegram-uploads index but don't
enter the knowledge pipeline.
"""

import json

import aiohttp
import structlog

from ..config import Settings
from ..storage.elasticsearch import ElasticsearchStorage
from ..storage.neo4j import Neo4jStorage
from ..utils.knowledge_extract import NER_MODEL

logger = structlog.get_logger()


async def enrich_upload(
    es: ElasticsearchStorage,
    neo4j: Neo4jStorage | None,
    settings: Settings,
    user_id: int,
    upload_id: str,
    original_filename: str,
    media_type: str,
    content_text: str,
    caption: str | None = None,
    transcript: str | None = None,
    vision_summary: str | None = None,
    mysql=None,
) -> dict | None:
    """Classify an upload and save it as a memory with full enrichment.

    Returns the enrichment result dict, or None if skipped.
    """
    from ..tools.mcp_servers import _load_user_ontology

    ontology = await _load_user_ontology(es, user_id)
    if not ontology:
        logger.debug("Upload enrichment skipped — no ontology", upload_id=upload_id)
        return None

    if not settings.internal_api_key:
        logger.warning("Upload enrichment skipped — no INTERNAL_API_KEY")
        return None

    # Build the best available text representation
    text = _build_text(content_text, transcript, vision_summary, caption)
    if len(text.strip()) < 30:
        logger.debug("Upload enrichment skipped — text too short", upload_id=upload_id)
        return None

    # Step 1: Ask Haiku to classify
    classification = await _classify_upload(
        ontology=ontology,
        filename=original_filename,
        media_type=media_type,
        text=text,
        api_url=settings.internal_api_url,
        api_key=settings.internal_api_key,
    )

    if not classification:
        logger.warning("Upload classification failed", upload_id=upload_id)
        return None

    memory_type = classification["type"]
    name = classification["name"]
    description = classification["description"]
    tags = classification.get("tags", [])

    # Step 2: Save as memory
    memory_id = await es.save_memory(
        user_id=user_id,
        name=name,
        memory_type=memory_type,
        description=description,
        content=text[:50_000],  # Cap content for very large files
        tags=tags,
    )

    # Link upload → memory in MySQL for Graph badge
    if mysql and hasattr(mysql, "link_upload_memory"):
        try:
            await mysql.link_upload_memory(upload_id, memory_id)
        except Exception as e:
            logger.warning("Failed to link upload to memory", error=str(e))

    logger.info(
        "Upload saved as memory",
        upload_id=upload_id, memory_id=memory_id,
        memory_type=memory_type, name=name,
    )

    # Step 3: Run standard enrichment (embedding, NER, graph)
    if neo4j:
        from .pipeline import enrich_memory

        result = await enrich_memory(
            neo4j=neo4j, settings=settings, user_id=user_id,
            name=name, memory_type=memory_type,
            description=description, content=text[:50_000],
            tags=tags, ontology=ontology,
        )
        logger.info(
            "Upload enrichment complete",
            upload_id=upload_id, name=name,
            nodes=result.get("nodes", 0), edges=result.get("edges", 0),
        )
        return result

    return {"nodes": 0, "edges": 0, "memory_id": memory_id}


def _build_text(
    content_text: str,
    transcript: str | None,
    vision_summary: str | None,
    caption: str | None,
) -> str:
    """Combine all available text sources into a single string for classification."""
    parts = []
    if content_text:
        parts.append(content_text)
    if transcript:
        parts.append(f"Transcript: {transcript}")
    if vision_summary:
        parts.append(f"Visual description: {vision_summary}")
    if caption:
        parts.append(f"Caption: {caption}")
    return "\n\n".join(parts)


async def _classify_upload(
    ontology: dict,
    filename: str,
    media_type: str,
    text: str,
    api_url: str,
    api_key: str,
) -> dict | None:
    """Ask Haiku to classify an upload into an ontology memory type.

    Returns: {"type": "article", "name": "...", "description": "...", "tags": [...]}
    """
    # Build the list of available memory types from ontology
    node_types = []
    for label, config in ontology.get("nodes", {}).items():
        desc = config.get("description", "")
        node_types.append(f"  - {label}: {desc}" if desc else f"  - {label}")

    types_text = "\n".join(node_types)

    prompt = f"""You classify uploaded files into knowledge categories.

The user's knowledge graph defines these node types:
{types_text}

The uploaded file:
- Filename: {filename}
- Media type: {media_type}
- Content (first 3000 chars):
{text[:3000]}

Classify this upload. Return ONLY valid JSON:
{{
  "type": "the_node_type",
  "name": "A concise, descriptive title for this content",
  "description": "1-2 sentence summary of what this document contains",
  "tags": ["tag1", "tag2"]
}}

Rules:
- type MUST be one of the node types listed above (use the exact label, case-sensitive)
- Prefer specific types over generic ones (e.g. "Article" over "Memory")
- name should be human-readable, like a title — not the filename
- description should capture the essence, not just repeat the title
- 2-5 tags, lowercase, broad categories
- If unsure about the type, use the most general content type available"""

    url = f"{api_url.rstrip('/')}/api/v1/chat"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": prompt,
        "model": NER_MODEL,
        "force_new": True,
        "mode": "plan",
        "hidden": True,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Classification API failed", status=resp.status, body=body[:200])
                    return None
                data = await resp.json()
                content = data.get("content", "")
    except Exception as e:
        logger.error("Classification API error", error=str(e))
        return None

    # Parse the response
    parsed = _parse_json(content)
    if not parsed:
        return None

    # Validate type against ontology
    valid_labels = set(ontology.get("nodes", {}).keys())
    if parsed.get("type") not in valid_labels:
        # Try case-insensitive match
        for label in valid_labels:
            if label.lower() == str(parsed.get("type", "")).lower():
                parsed["type"] = label
                break
        else:
            logger.warning(
                "Classification returned invalid type",
                type=parsed.get("type"), valid=list(valid_labels),
            )
            return None

    if not parsed.get("name"):
        return None

    return {
        "type": parsed["type"],
        "name": parsed["name"],
        "description": parsed.get("description", ""),
        "tags": parsed.get("tags", [])[:5],
    }


def _parse_json(text: str) -> dict | None:
    """Parse JSON from a response that might contain markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        logger.warning("Failed to parse classification response", text=text[:200])
        return None
