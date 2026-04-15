"""MCP tools for querying cluster databases."""

import json

import aiohttp
import aiomysql
import structlog

from ..config import Settings

logger = structlog.get_logger()


async def query_mysql(settings: Settings, sql: str, database: str | None = None) -> str:
    """Execute a SQL query against the MySQL server."""
    db = database or settings.mysql_database
    try:
        conn = await aiomysql.connect(
            host=settings.mysql_host, port=settings.mysql_port,
            user=settings.mysql_user, password=settings.mysql_password,
            db=db, charset="utf8mb4",
        )
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql)
            if sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("SHOW"):
                rows = await cur.fetchall()
                conn.close()
                return json.dumps(rows, default=str, indent=2, ensure_ascii=False)
            else:
                await conn.commit()
                conn.close()
                return f"OK, {cur.rowcount} rows affected"
    except Exception as e:
        return f"MySQL error: {e}"


async def query_elasticsearch(settings: Settings, method: str, path: str,
                              body: dict | None = None) -> str:
    """Execute a request against Elasticsearch."""
    url = f"{settings.es_url}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            kwargs = {"headers": {"Content-Type": "application/json"}}
            if body:
                kwargs["json"] = body

            if method.upper() == "GET":
                resp = await session.get(url, **kwargs)
            elif method.upper() == "POST":
                resp = await session.post(url, **kwargs)
            elif method.upper() == "PUT":
                resp = await session.put(url, **kwargs)
            elif method.upper() == "DELETE":
                resp = await session.delete(url, **kwargs)
            else:
                return f"Unsupported HTTP method: {method}"

            text = await resp.text()
            try:
                return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                return text
    except Exception as e:
        return f"Elasticsearch error: {e}"


async def query_neo4j(settings: Settings, cypher: str) -> str:
    """Execute a Cypher query against Neo4j."""
    url = f"http://{settings.neo4j_host}:{settings.neo4j_http_port}/db/neo4j/tx/commit"
    auth = aiohttp.BasicAuth(settings.neo4j_user, settings.neo4j_password)
    payload = {"statements": [{"statement": cypher}]}

    try:
        async with aiohttp.ClientSession(auth=auth) as session:
            resp = await session.post(
                url, json=payload,
                headers={"Content-Type": "application/json"},
            )
            result = await resp.json()
            errors = result.get("errors", [])
            if errors:
                return f"Neo4j error: {errors[0].get('message', errors)}"
            data = result.get("results", [{}])[0]
            columns = data.get("columns", [])
            rows = data.get("data", [])
            if not rows:
                return "No results"
            formatted = [dict(zip(columns, r["row"])) for r in rows]
            return json.dumps(formatted, default=str, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Neo4j error: {e}"


async def search_web(settings: Settings, query: str, limit: int = 5) -> str:
    """Search the web via SearXNG."""
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.get(
                f"{settings.searxng_url}/search",
                params={"q": query, "format": "json", "pageno": 1},
                headers={"User-Agent": "banana-bot-cc/1.0"},
            )
            data = await resp.json()
            results = data.get("results", [])[:limit]
            formatted = [
                {"title": r["title"], "url": r["url"],
                 "content": r.get("content", "")[:300]}
                for r in results
            ]
            return json.dumps(formatted, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"SearXNG error: {e}"
