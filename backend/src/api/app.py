"""FastAPI application factory."""

import time

import structlog
from fastapi import FastAPI

from ..claude.client import ClaudeClient
from ..config import Settings
from ..storage.elasticsearch import ElasticsearchStorage
from ..storage.mysql import MySQLStorage
from ..storage.uploads import UploadsStorage
from .routes.chat import router as chat_router
from .routes.sessions import router as sessions_router
from .routes.admin import router as admin_router
from .routes.files import router as files_router
from .routes.graph import router as graph_router
from .routes.memories import router as memories_router
from .routes.preferences import router as preferences_router
from .routes.auth import router as auth_router
from .routes.claude_auth import router as claude_auth_router
from .routes.commands import router as commands_router

logger = structlog.get_logger()


def create_api(
    settings: Settings,
    claude: ClaudeClient,
    mysql: MySQLStorage,
    es: ElasticsearchStorage,
    uploads_storage: UploadsStorage | None = None,
    neo4j=None,
) -> FastAPI:
    """Create the FastAPI app with all dependencies injected."""

    app = FastAPI(
        title=f"banana-bot API ({settings.instance_name})",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Store dependencies on app.state for access in routes
    app.state.settings = settings
    app.state.claude = claude
    app.state.mysql = mysql
    app.state.es = es
    app.state.uploads_storage = uploads_storage
    app.state.neo4j = neo4j
    app.state.start_time = time.time()

    # Register routers
    app.include_router(chat_router, prefix="/api/v1", tags=["chat"])
    app.include_router(sessions_router, prefix="/api/v1", tags=["sessions"])
    app.include_router(admin_router, prefix="/api/v1", tags=["admin"])
    app.include_router(files_router, prefix="/api/v1", tags=["files"])
    app.include_router(preferences_router, prefix="/api/v1", tags=["preferences"])
    app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
    app.include_router(commands_router, prefix="/api/v1", tags=["commands"])
    app.include_router(graph_router, prefix="/api/v1", tags=["graph"])
    app.include_router(memories_router, prefix="/api/v1", tags=["memories"])
    app.include_router(claude_auth_router, prefix="/api/v1", tags=["claude-auth"])

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    logger.info("FastAPI app created", instance=settings.instance_name)
    return app
