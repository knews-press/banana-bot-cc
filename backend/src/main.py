"""Claude Code Custom — entry point."""

import asyncio
import os
import sys

import structlog

# Disable Claude Code's built-in auto-memory (we use ES via MCP tools)
os.environ["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
from telegram.ext import Application

from .bot.handlers import setup_handlers
from .config import Settings
from .claude.client import ClaudeClient
from .storage.elasticsearch import ElasticsearchStorage
from .storage.mysql import MySQLStorage
from .storage.neo4j import Neo4jStorage
from .storage.uploads import UploadsStorage

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


async def main():
    settings = Settings()

    logger.info("Starting custom-bot", instance=settings.instance_name)

    # Initialize storage
    mysql = MySQLStorage(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
    )
    await mysql.initialize()

    es = ElasticsearchStorage(settings.es_url)
    await es.initialize()

    uploads_storage = UploadsStorage(settings.es_url)

    # Neo4j knowledge graph (optional — degrades gracefully if unavailable)
    neo4j = None
    if settings.neo4j_password:
        neo4j = Neo4jStorage(
            host=settings.neo4j_host,
            port=settings.neo4j_http_port,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
        await neo4j.initialize()

    # Ensure uploads directory exists
    import pathlib
    pathlib.Path(settings.uploads_directory).mkdir(parents=True, exist_ok=True)

    # Claude client (with session + memory sync)
    claude = ClaudeClient(settings, mysql, es, uploads_storage=uploads_storage, neo4j=neo4j)
    if claude.cli_path:
        logger.info("Claude CLI found", path=claude.cli_path)
    else:
        logger.warning("Claude CLI not found — SDK calls will fail")

    # Seed allowed users from ALLOWED_USERS env var (bootstrap)
    if settings.allowed_user_ids:
        owner_id = settings.owner_user_id
        for uid in settings.allowed_user_ids:
            # Set email only for the primary owner (first/lowest ID)
            email = settings.owner_email if (uid == owner_id and settings.owner_email) else None
            await mysql.add_user(uid, email=email)
            await claude.restore_sessions(uid)
        logger.info("Seeded users from env", count=len(settings.allowed_user_ids))
        owner_user_ids = list(settings.allowed_user_ids)
    else:
        # Restore sessions for all allowed users in DB
        users = await mysql.list_users()
        for u in users:
            await claude.restore_sessions(u["user_id"])
        owner_user_ids = [u["user_id"] for u in users]

    # Clear any stale execution locks left over from a previous pod instance.
    # Scoped to this pod's own users so other pods' sessions are not touched.
    cleared = await mysql.reset_running_locks_for_users(owner_user_ids)
    if cleared:
        logger.warning("Cleared stale execution locks at startup", count=cleared)

    # Telegram bot
    # concurrent_updates=True is required so /stop can interrupt a running execution.
    # Without it, PTB queues updates sequentially and /stop never reaches the handler
    # while handle_message is blocked on await execute_task.
    app = Application.builder().token(settings.telegram_bot_token).concurrent_updates(True).build()
    setup_handlers(app, settings, claude, mysql, es, uploads_storage=uploads_storage, neo4j=neo4j)

    logger.info("Bot starting", username=settings.telegram_bot_username)

    # Run with polling
    await app.initialize()
    await app.start()

    # Register commands with BotFather automatically
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("new", "Start a new session"),
        BotCommand("session", "Manage sessions (list/load/delete/export)"),
        BotCommand("status", "Status der aktiven Session"),
        BotCommand("model", "Switch model"),
        BotCommand("mode", "Mode & settings"),
        BotCommand("memory", "Search & manage memories"),
        BotCommand("me", "Profile & language"),
        BotCommand("stop", "Stop execution"),
        BotCommand("help", "All commands"),
    ])
    logger.info("Bot commands registered with Telegram")

    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("Telegram bot is running", username=settings.telegram_bot_username)

    # --- FastAPI (cluster-internal API) ---
    from .api.app import create_api
    import uvicorn

    api = create_api(settings, claude, mysql, es, uploads_storage=uploads_storage, neo4j=neo4j)
    api.state.telegram_bot = app.bot  # Make Telegram bot available to API routes
    api_port = int(os.environ.get("API_PORT", "8080"))
    api_config = uvicorn.Config(api, host="0.0.0.0", port=api_port, log_level="warning")
    api_server = uvicorn.Server(api_config)

    logger.info("API server starting", port=api_port)

    # Keep running until interrupted
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_event_loop()
    try:
        import signal
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)
    except (NotImplementedError, AttributeError):
        pass  # Windows

    # Run API server alongside Telegram polling
    api_task = asyncio.create_task(api_server.serve())

    await stop_event.wait()

    # Cleanup
    logger.info("Shutting down...")
    api_server.should_exit = True
    await api_task
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    await mysql.close()
    await es.close()
    if neo4j:
        await neo4j.close()


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
