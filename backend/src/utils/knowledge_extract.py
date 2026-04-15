"""Extract structured entities from text via the bot's own API.

Uses the bot's /api/v1/chat endpoint with Haiku for fast, cheap NER.
The extraction prompt is built dynamically from the user's ontology.
"""

import json

import aiohttp
import structlog

logger = structlog.get_logger()

# Haiku for fast/cheap extraction
NER_MODEL = "claude-haiku-4-5"


def build_extraction_prompt(
    ontology: dict,
    memory_type: str,
    name: str,
    description: str,
    content: str,
) -> str:
    """Build a NER prompt dynamically from the user's ontology.

    The ontology defines which node types and edge types exist.
    The extraction_hint provides domain-specific guidance.
    """
    # Build readable node list
    node_types = ", ".join(sorted(ontology.get("nodes", {}).keys()))

    # Build readable edge list
    edge_lines = []
    for edge in ontology.get("edges", []):
        from_types = edge.get("from", ["*"])
        to_types = edge.get("to", ["*"])
        if isinstance(from_types, str):
            from_types = [from_types]
        if isinstance(to_types, str):
            to_types = [to_types]
        from_str = "/".join(from_types)
        to_str = "/".join(to_types)
        edge_lines.append(f"  {edge['type']}: {from_str} -> {to_str}")
    edges_text = "\n".join(edge_lines) if edge_lines else "  (none defined)"

    hint = ontology.get("extraction_hint", "")

    return f"""You analyze text for a knowledge graph. Extract entities and relationships.

User's graph ontology:
Node types: {node_types}
Edge types:
{edges_text}

{"Domain context: " + hint if hint else ""}

The source document is of type "{memory_type}", titled "{name}".
Description: {description}

Text:
{content}

Extract entities MENTIONED in this text and their relationships to the source document.
Return ONLY valid JSON, no other text:
{{
  "entities": [
    {{"label": "NodeType", "name": "Entity Name", "properties": {{"key": "value"}}}}
  ],
  "edges": [
    {{"type": "EDGE_TYPE", "to_label": "NodeType", "to_name": "Entity Name"}}
  ]
}}

Rules:
- Only use node labels and edge types defined in the ontology above
- Edges go FROM the source document TO extracted entities
- Only extract entities actually mentioned in the text
- Use full names for persons, broad categories for topics
- Properties are optional — include role, type, etc. if mentioned
- 3-7 entities max, keep it focused
- Return empty arrays if nothing relevant found"""


async def extract_with_ontology(
    ontology: dict,
    memory_type: str,
    name: str,
    description: str,
    content: str,
    api_url: str,
    api_key: str,
) -> dict:
    """Universal entity extraction driven by user ontology.

    Returns:
        {"entities": [...], "edges": [...]}
    """
    prompt = build_extraction_prompt(
        ontology, memory_type, name, description, content,
    )

    result = await _call_bot_api(api_url, api_key, prompt)
    parsed = _parse_json(result, default={"entities": [], "edges": []})

    if not isinstance(parsed, dict):
        return {"entities": [], "edges": []}

    # Validate: only allow labels/edges defined in ontology
    valid_labels = set(ontology.get("nodes", {}).keys())
    valid_edge_types = {e["type"] for e in ontology.get("edges", [])}

    validated_entities = [
        e for e in parsed.get("entities", [])
        if isinstance(e, dict)
        and e.get("label") in valid_labels
        and e.get("name")
    ]

    validated_edges = [
        e for e in parsed.get("edges", [])
        if isinstance(e, dict)
        and e.get("type") in valid_edge_types
        and e.get("to_label") in valid_labels
        and e.get("to_name")
    ]

    return {"entities": validated_entities, "edges": validated_edges}


async def _call_bot_api(api_url: str, api_key: str, prompt: str) -> str:
    """Make a chat request to the bot's own API."""
    url = f"{api_url.rstrip('/')}/api/v1/chat"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": prompt,
        "model": NER_MODEL,
        "force_new": True,
        "mode": "plan",  # Read-only, no tool use
        "hidden": True,  # Don't show NER sessions in sidebar
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("NER API call failed", status=resp.status, body=body[:200])
                return ""
            data = await resp.json()
            return data.get("content", "")


def _parse_json(text: str, default):
    """Extract JSON from a response that might contain markdown fences."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse NER response as JSON", text=text[:200])
        return default
