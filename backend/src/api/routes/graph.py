"""Graph endpoints — search nodes and get node detail for 3-D visualisation."""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import get_api_user

logger = structlog.get_logger()
router = APIRouter()


def _clean_props(props: dict) -> dict:
    """Strip heavy / internal fields that should not leave the API."""
    p = dict(props)
    p.pop("embedding", None)
    return p


@router.get("/graph/search")
async def graph_search(
    request: Request,
    user: dict = Depends(get_api_user),
    domain: str | None = Query(None, description="Filter by domain (e.g. journalism)"),
    types: str | None = Query(None, description="Comma-separated node labels to include"),
    q: str | None = Query(None, description="Text search across name / title / content"),
    limit: int = Query(default=200, le=500, description="Max nodes to return"),
) -> dict[str, Any]:
    """Return nodes + inter-node edges for 3-D force-graph visualisation.

    Three-query approach when a type filter is active:
      1. Fetch primary nodes matching the type/text filter (up to *limit*).
      2. Expand: fetch direct neighbours of those nodes so that cross-domain
         and universal-domain nodes are included — this is what makes edges
         visible between e.g. Film↔Person or Repo↔Tag.
      3. Fetch all edges whose both endpoints are in the combined node set.

    Without a type filter (full graph view) step 2 is skipped.
    """
    neo4j = getattr(request.app.state, "neo4j", None)
    if neo4j is None:
        raise HTTPException(status_code=503, detail="Graph nicht verfügbar.")

    user_id: int = user["user_id"]
    type_list: list[str] = [t.strip() for t in types.split(",")] if types else []

    # ── Build WHERE clause ────────────────────────────────────────────────────
    conditions = ["n.user_id = $userId"]
    params: dict[str, Any] = {"userId": user_id, "limit": limit}

    if q:
        conditions.append(
            "(toLower(coalesce(n.name, '')) CONTAINS toLower($q) "
            "OR toLower(coalesce(n.title, '')) CONTAINS toLower($q) "
            "OR toLower(coalesce(n.content, '')) CONTAINS toLower($q))"
        )
        params["q"] = q

    if type_list:
        conditions.append("any(lbl IN labels(n) WHERE lbl IN $types)")
        params["types"] = type_list

    where_clause = " AND ".join(conditions)

    # ── Step 1: fetch primary nodes ───────────────────────────────────────────
    nodes_cypher = (
        f"MATCH (n) WHERE {where_clause} "
        "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props "
        "ORDER BY n.created_at DESC LIMIT $limit"
    )
    raw_nodes = await neo4j.execute(nodes_cypher, params)

    if not raw_nodes:
        return {"nodes": [], "edges": []}

    # ── Step 2: neighbour expansion (only when a type filter is active) ───────
    # Without this, cross-domain edges (e.g. Film↔Topic, Repo↔Tag) and edges
    # to universal-domain nodes (Person, Organization …) are invisible because
    # the edge query requires both endpoints to be present in the node set.
    if type_list:
        primary_ids = [row["id"] for row in raw_nodes]
        neighbour_cypher = (
            "MATCH (p)-[]-(n) "
            "WHERE elementId(p) IN $primaryIds AND n.user_id = $userId "
            "RETURN DISTINCT elementId(n) AS id, labels(n) AS labels, properties(n) AS props "
            "LIMIT $neighborLimit"
        )
        neighbour_rows = await neo4j.execute(neighbour_cypher, {
            "primaryIds": primary_ids,
            "userId": user_id,
            "neighborLimit": limit,
        })
        existing_ids: set[str] = {row["id"] for row in raw_nodes}
        for row in neighbour_rows:
            if row["id"] not in existing_ids:
                raw_nodes.append(row)
                existing_ids.add(row["id"])

    nodes: list[dict] = []
    node_ids: list[str] = []
    for row in raw_nodes:
        props = _clean_props(row["props"])
        nodes.append({"id": row["id"], "labels": row["labels"], "props": props})
        node_ids.append(row["id"])

    # ── Step 3: fetch edges between those nodes ───────────────────────────────
    edges_cypher = (
        "MATCH (a)-[r]-(b) "
        "WHERE elementId(a) IN $nodeIds AND elementId(b) IN $nodeIds "
        "RETURN DISTINCT "
        "  elementId(startNode(r)) AS source, "
        "  elementId(endNode(r))   AS target, "
        "  type(r) AS type"
    )
    raw_edges = await neo4j.execute(edges_cypher, {"nodeIds": node_ids})

    # Deduplicate: undirected MATCH returns a→b and b→a as separate rows
    seen: set[tuple] = set()
    edges: list[dict] = []
    for row in raw_edges:
        key = (
            min(row["source"], row["target"]),
            max(row["source"], row["target"]),
            row["type"],
        )
        if key not in seen:
            seen.add(key)
            edges.append({
                "source": row["source"],
                "target": row["target"],
                "type": row["type"],
            })

    logger.info(
        "graph_search",
        user_id=user_id,
        nodes=len(nodes),
        edges=len(edges),
        domain=domain,
        types=type_list,
        q=q,
    )
    return {"nodes": nodes, "edges": edges}


@router.get("/graph/node/{element_id:path}")
async def graph_node(
    element_id: str,
    request: Request,
    user: dict = Depends(get_api_user),
) -> dict[str, Any]:
    """Return full properties of a node plus all its direct neighbours."""
    neo4j = getattr(request.app.state, "neo4j", None)
    if neo4j is None:
        raise HTTPException(status_code=503, detail="Graph nicht verfügbar.")

    user_id: int = user["user_id"]

    node_cypher = (
        "MATCH (n) WHERE elementId(n) = $eid AND n.user_id = $userId "
        "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props"
    )
    rows = await neo4j.execute(node_cypher, {"eid": element_id, "userId": user_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Knoten nicht gefunden.")

    node = rows[0]
    props = _clean_props(node["props"])

    neighbors_cypher = (
        "MATCH (n)-[r]-(m) "
        "WHERE elementId(n) = $eid AND m.user_id = $userId "
        "RETURN "
        "  elementId(m) AS id, "
        "  labels(m)    AS labels, "
        "  properties(m) AS props, "
        "  type(r)       AS rel_type, "
        "  CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END AS direction "
        "LIMIT 100"
    )
    raw_nbrs = await neo4j.execute(
        neighbors_cypher, {"eid": element_id, "userId": user_id}
    )

    neighbors: list[dict] = []
    for row in raw_nbrs:
        nprops = _clean_props(row["props"])
        neighbors.append({
            "id": row["id"],
            "labels": row["labels"],
            "props": nprops,
            "rel_type": row["rel_type"],
            "direction": row["direction"],
        })

    return {
        "node": {"id": node["id"], "labels": node["labels"], "props": props},
        "neighbors": neighbors,
    }
