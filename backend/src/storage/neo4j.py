"""Neo4j storage for the knowledge graph."""

import json
from base64 import b64encode

import aiohttp
import structlog

logger = structlog.get_logger()

# Convention: vector index name = "{label_lower}_embeddings"
# Indexes are discovered dynamically from Neo4j rather than hardcoded.
# Legacy map kept as fallback for indexes with non-standard names.
_LEGACY_VECTOR_INDEXES = {
    "TopicIdea": "topicidea_embeddings",
}


def _vector_index_name(label: str) -> str:
    """Derive vector index name from node label.

    Convention: label.lower() + '_embeddings'
    E.g. Article -> article_embeddings, Decision -> decision_embeddings
    """
    return _LEGACY_VECTOR_INDEXES.get(label, f"{label.lower()}_embeddings")


class Neo4jStorage:
    def __init__(self, host: str, port: int, user: str, password: str):
        self.base_url = f"http://{host}:{port}"
        self.tx_url = f"{self.base_url}/db/neo4j/tx/commit"
        credentials = b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
        }
        self.session: aiohttp.ClientSession | None = None

    async def initialize(self):
        self.session = aiohttp.ClientSession()
        # Verify connectivity
        try:
            result = await self.execute("RETURN 1 AS ok")
            if result and result[0].get("ok") == 1:
                logger.info("Neo4j storage initialized", url=self.base_url)
            else:
                logger.error("Neo4j connectivity check failed")
        except Exception as e:
            logger.error("Neo4j initialization error", error=str(e))

    async def close(self):
        if self.session:
            await self.session.close()

    # --- Core ---

    async def execute(self, cypher: str, params: dict | None = None) -> list[dict]:
        """Execute a Cypher query and return results as list of dicts."""
        statement = {"statement": cypher}
        if params:
            statement["parameters"] = params
        payload = {"statements": [statement]}

        resp = await self.session.post(
            self.tx_url, json=payload, headers=self.headers,
        )
        data = await resp.json()

        errors = data.get("errors", [])
        if errors:
            msg = errors[0].get("message", "Unknown Neo4j error")
            logger.error("Neo4j query error", error=msg, cypher=cypher[:200])
            raise RuntimeError(f"Neo4j error: {msg}")

        results = data.get("results", [])
        if not results or not results[0].get("data"):
            return []

        columns = results[0]["columns"]
        rows = []
        for row in results[0]["data"]:
            record = {}
            for i, col in enumerate(columns):
                val = row["row"][i]
                record[col] = val
            rows.append(record)
        return rows

    # --- Node operations ---

    async def merge_node(
        self,
        label: str,
        user_id: int,
        key_props: dict,
        extra_props: dict | None = None,
    ) -> dict:
        """Create or update a node. Key props are used for matching (MERGE),
        extra props are set/updated on the node.

        Returns the node properties.
        """
        params = {"user_id": user_id, **key_props}
        key_parts = ", ".join(
            f"{k}: ${k}" for k in ["user_id", *key_props.keys()]
        )

        if extra_props:
            params["_extra"] = extra_props
            cypher = (
                f"MERGE (n:{label} {{{key_parts}}}) "
                f"SET n += $_extra "
                f"RETURN properties(n) AS props"
            )
        else:
            cypher = (
                f"MERGE (n:{label} {{{key_parts}}}) "
                f"RETURN properties(n) AS props"
            )

        rows = await self.execute(cypher, params)
        return rows[0]["props"] if rows else {}

    async def create_edge(
        self,
        from_label: str,
        from_key: dict,
        to_label: str,
        to_key: dict,
        rel_type: str,
        user_id: int,
        props: dict | None = None,
        memory_version: int | None = None,
    ) -> bool:
        """Create or update an edge between two nodes (identified by label +
        key props + user_id). Returns True if the edge was created/matched.

        memory_version: when provided, stored on the edge so stale connections
        can be identified (edge.memory_version < current memory version).
        created_at is set once on creation and never overwritten.
        """
        params: dict = {}

        # Build MATCH clause for source node
        from_match_parts = ["user_id: $a_user_id"]
        params["a_user_id"] = user_id
        for k, v in from_key.items():
            pkey = f"a_{k}"
            from_match_parts.append(f"{k}: ${pkey}")
            params[pkey] = v

        # Build MATCH clause for target node
        to_match_parts = ["user_id: $b_user_id"]
        params["b_user_id"] = user_id
        for k, v in to_key.items():
            pkey = f"b_{k}"
            to_match_parts.append(f"{k}: ${pkey}")
            params[pkey] = v

        from_clause = ", ".join(from_match_parts)
        to_clause = ", ".join(to_match_parts)

        # ON CREATE: stamp creation time and initial version
        on_create_parts = ["r.created_at = datetime()"]
        if memory_version is not None:
            params["_memory_version"] = memory_version
            on_create_parts.append("r.memory_version = $_memory_version")
        on_create_clause = f"ON CREATE SET {', '.join(on_create_parts)} "

        # ON MATCH: update version so we know this edge was last confirmed here
        on_match_clause = ""
        if memory_version is not None:
            on_match_clause = "ON MATCH SET r.memory_version = $_memory_version "

        set_clause = ""
        if props:
            params["_edge_props"] = props
            set_clause = "SET r += $_edge_props "

        cypher = (
            f"MATCH (a:{from_label} {{{from_clause}}}), "
            f"(b:{to_label} {{{to_clause}}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"{on_create_clause}"
            f"{on_match_clause}"
            f"{set_clause}"
            f"RETURN type(r) AS rel"
        )

        rows = await self.execute(cypher, params)
        return len(rows) > 0

    async def find_nodes(
        self,
        label: str,
        user_id: int,
        filters: dict | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Find nodes by label and optional property filters."""
        params: dict = {"user_id": user_id, "limit": limit}
        where_parts = ["n.user_id = $user_id"]

        if filters:
            for k, v in filters.items():
                param_key = f"f_{k}"
                where_parts.append(f"n.{k} = ${param_key}")
                params[param_key] = v

        where_clause = " AND ".join(where_parts)
        cypher = (
            f"MATCH (n:{label}) "
            f"WHERE {where_clause} "
            f"RETURN properties(n) AS props "
            f"LIMIT $limit"
        )
        rows = await self.execute(cypher, params)
        return [r["props"] for r in rows]

    async def get_neighbors(
        self,
        label: str,
        key: dict,
        user_id: int,
        rel_types: list[str] | None = None,
        depth: int = 1,
    ) -> list[dict]:
        """Find neighbors of a node via graph traversal.

        Returns list of dicts with: neighbor (properties), rel_type, direction.
        """
        params: dict = {"user_id": user_id, **key}
        key_parts = ", ".join(
            f"{k}: ${k}" for k in ["user_id", *key.keys()]
        )

        if rel_types:
            rel_pattern = ":" + "|".join(rel_types)
        else:
            rel_pattern = ""

        cypher = (
            f"MATCH (n:{label} {{{key_parts}}})-[r{rel_pattern}*1..{depth}]-(m) "
            f"WHERE m.user_id = $user_id "
            f"UNWIND r AS rel "
            f"WITH DISTINCT m, last(r) AS rel "
            f"RETURN properties(m) AS neighbor, type(rel) AS rel_type, "
            f"labels(m) AS labels"
        )
        rows = await self.execute(cypher, params)
        return rows

    async def vector_search(
        self,
        label: str,
        embedding: list[float],
        user_id: int,
        limit: int = 10,
    ) -> list[dict]:
        """Semantic similarity search using Neo4j vector index.

        Returns nodes sorted by cosine similarity, filtered to user_id.
        """
        index_name = _vector_index_name(label)

        # Query more than needed, then filter by user_id
        fetch_limit = limit * 3
        cypher = (
            f"CALL db.index.vector.queryNodes($index, $fetch_limit, $embedding) "
            f"YIELD node, score "
            f"WHERE node.user_id = $user_id "
            f"RETURN properties(node) AS props, score "
            f"LIMIT $limit"
        )
        params = {
            "index": index_name,
            "fetch_limit": fetch_limit,
            "embedding": embedding,
            "user_id": user_id,
            "limit": limit,
        }
        rows = await self.execute(cypher, params)
        # Remove embedding from results (large, not useful for display)
        for row in rows:
            row["props"].pop("embedding", None)
        return rows

    async def delete_node(
        self,
        label: str,
        key: dict,
        user_id: int,
    ) -> bool:
        """Delete a node and all its edges."""
        params = {"user_id": user_id, **key}
        key_parts = ", ".join(
            f"{k}: ${k}" for k in ["user_id", *key.keys()]
        )
        cypher = (
            f"MATCH (n:{label} {{{key_parts}}}) "
            f"DETACH DELETE n "
            f"RETURN count(n) AS deleted"
        )
        rows = await self.execute(cypher, params)
        return rows[0]["deleted"] > 0 if rows else False

    async def count_by_topic(
        self,
        user_id: int,
        min_articles: int = 3,
    ) -> list[dict]:
        """Find topics with N+ articles — used for dossier suggestions."""
        cypher = (
            "MATCH (t:Topic {user_id: $user_id})<-[:COVERS]-(a:Article) "
            "WITH t, count(a) AS article_count "
            "WHERE article_count >= $min_articles "
            "RETURN t.name AS topic, article_count "
            "ORDER BY article_count DESC"
        )
        return await self.execute(cypher, {
            "user_id": user_id,
            "min_articles": min_articles,
        })

    async def cleanup_orphans(self, user_id: int) -> int:
        """Remove orphan nodes that have no edges left.

        Keeps standalone Topic, Concept, Organization nodes (they have
        independent meaning). Only removes leaf types that only exist
        because they were connected to something: Person, Tag.
        """
        cypher = (
            "MATCH (n) "
            "WHERE n.user_id = $user_id "
            "  AND NOT (n)--() "
            "  AND NOT n:Topic AND NOT n:Concept AND NOT n:Organization "
            "WITH n, labels(n) AS lbls "
            "DELETE n "
            "RETURN count(n) AS deleted"
        )
        rows = await self.execute(cypher, {"user_id": user_id})
        deleted = rows[0]["deleted"] if rows else 0
        if deleted > 0:
            logger.info("Neo4j orphan cleanup", deleted=deleted, user_id=user_id)
        return deleted
