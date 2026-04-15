"""MySQL storage for sessions, users, messages, costs, audit."""

import json
from datetime import UTC, datetime, timedelta

import aiomysql
import structlog

logger = structlog.get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    telegram_username VARCHAR(255),
    email VARCHAR(255) UNIQUE,
    display_name VARCHAR(255),
    preferences JSON,
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_allowed BOOLEAN DEFAULT FALSE,
    total_cost DOUBLE DEFAULT 0.0,
    message_count INT DEFAULT 0,
    session_count INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    project_path VARCHAR(1024) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_used DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_cost DOUBLE DEFAULT 0.0,
    total_turns INT DEFAULT 0,
    message_count INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    compact_count INT DEFAULT 0,
    display_name VARCHAR(64),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    message_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    user_id BIGINT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    prompt TEXT NOT NULL,
    response LONGTEXT,
    cost DOUBLE DEFAULT 0.0,
    duration_ms INT,
    model VARCHAR(255),
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    cache_creation_tokens INT DEFAULT 0,
    cache_read_tokens INT DEFAULT 0,
    error TEXT,
    INDEX idx_session (session_id),
    INDEX idx_user (user_id),
    INDEX idx_timestamp (timestamp)
);

CREATE TABLE IF NOT EXISTS tool_usage (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    message_id BIGINT,
    tool_name VARCHAR(255) NOT NULL,
    tool_input JSON,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    INDEX idx_session (session_id)
);

CREATE TABLE IF NOT EXISTS cost_tracking (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    date DATE NOT NULL,
    daily_cost DOUBLE DEFAULT 0.0,
    request_count INT DEFAULT 0,
    UNIQUE KEY uq_user_date (user_id, date)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    event_type VARCHAR(255) NOT NULL,
    event_data JSON,
    success BOOLEAN DEFAULT TRUE,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_timestamp (timestamp)
);

CREATE TABLE IF NOT EXISTS session_content (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    project_path VARCHAR(1024),
    jsonl_content LONGTEXT NOT NULL,
    metadata JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id)
);

CREATE TABLE IF NOT EXISTS api_keys (
    api_key VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_used DATETIME,
    is_active BOOLEAN DEFAULT TRUE,
    permissions JSON,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    INDEX idx_user (user_id)
);

CREATE TABLE IF NOT EXISTS telegram_uploads (
    upload_id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    telegram_file_id VARCHAR(512),
    original_filename VARCHAR(512),
    media_type VARCHAR(64) NOT NULL,
    mime_type VARCHAR(255),
    file_size BIGINT DEFAULT 0,
    storage_path VARCHAR(1024),
    es_id VARCHAR(255),
    caption TEXT,
    transcript TEXT,
    vision_summary TEXT,
    memory_id VARCHAR(64) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_created (created_at),
    INDEX idx_media_type (media_type)
);

CREATE TABLE IF NOT EXISTS telegram_upload_rows (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    upload_id VARCHAR(64) NOT NULL,
    user_id BIGINT NOT NULL,
    row_index INT NOT NULL,
    row_data JSON NOT NULL,
    INDEX idx_upload (upload_id),
    INDEX idx_user (user_id)
);
"""


class MySQLStorage:
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.pool: aiomysql.Pool | None = None

    async def initialize(self):
        # Try to create database (may fail if user lacks CREATE privileges — that's OK)
        try:
            conn = await aiomysql.connect(
                host=self.host, port=self.port, user=self.user, password=self.password
            )
            async with conn.cursor() as cur:
                await cur.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}`")
            conn.close()
        except Exception as e:
            logger.info("Database creation skipped (may already exist)", error=str(e))

        # Create connection pool
        self.pool = await aiomysql.create_pool(
            host=self.host, port=self.port, user=self.user, password=self.password,
            db=self.database, minsize=2, maxsize=10, autocommit=True,
            charset="utf8mb4",
        )

        # Run schema
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                for statement in SCHEMA.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        await cur.execute(stmt)

        # Migrations for existing tables
        await self._run_migrations()

        logger.info("MySQL storage initialized", database=self.database)

    async def _run_migrations(self):
        """Add columns that may not exist in older schemas. Each migration is idempotent."""
        migrations = [
            "ALTER TABLE users ADD COLUMN email VARCHAR(255) UNIQUE",
            "ALTER TABLE users ADD COLUMN display_name VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN preferences JSON",
            "ALTER TABLE messages ADD COLUMN model VARCHAR(255)",
            "ALTER TABLE messages ADD COLUMN input_tokens INT DEFAULT 0",
            "ALTER TABLE messages ADD COLUMN output_tokens INT DEFAULT 0",
            "ALTER TABLE messages ADD COLUMN cache_creation_tokens INT DEFAULT 0",
            "ALTER TABLE messages ADD COLUMN cache_read_tokens INT DEFAULT 0",
            # Session compaction
            "ALTER TABLE sessions ADD COLUMN context_summary TEXT",
            "ALTER TABLE sessions ADD COLUMN compacted_from VARCHAR(255)",
            # Cross-channel execution lock
            "ALTER TABLE sessions ADD COLUMN is_running TINYINT(1) DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN running_channel VARCHAR(64)",
            "ALTER TABLE sessions ADD COLUMN running_since DATETIME",
            # Image generation user settings
            """CREATE TABLE IF NOT EXISTS user_image_settings (
                user_id BIGINT PRIMARY KEY,
                provider VARCHAR(64) DEFAULT 'gemini',
                model VARCHAR(128),
                size VARCHAR(32) DEFAULT '1024x1024',
                aspect_ratio VARCHAR(16) DEFAULT '1:1',
                quality VARCHAR(32) DEFAULT 'medium',
                style_prompt TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""",
            # Last channel tracking (Telegram marker in Web UI)
            "ALTER TABLE sessions ADD COLUMN last_channel VARCHAR(64)",
            # Context usage tracking
            "ALTER TABLE sessions ADD COLUMN compact_count INT DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN context_tokens INT DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN context_max_tokens INT DEFAULT 200000",
            # Human-readable session display names
            "ALTER TABLE sessions ADD COLUMN display_name VARCHAR(64)",
            # Tool events per message (for WebUI display after reload)
            "ALTER TABLE messages ADD COLUMN tools_json JSON",
            # Link uploads to enriched memories (knowledge pipeline)
            "ALTER TABLE telegram_uploads ADD COLUMN memory_id VARCHAR(64) DEFAULT NULL",
            # Per-user instance access control (null = allow all)
            "ALTER TABLE users ADD COLUMN allowed_instances JSON DEFAULT NULL",
        ]
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                for sql in migrations:
                    try:
                        await cur.execute(sql)
                        logger.debug("Migration applied", sql=sql[:60])
                    except Exception:
                        pass  # Column already exists — expected on re-runs

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    # --- Users ---

    async def ensure_user(self, user_id: int, username: str | None = None):
        """Create user if not exists (is_allowed defaults to FALSE).
        Does NOT overwrite is_allowed for existing users."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO users (user_id, telegram_username)
                       VALUES (%s, %s)
                       ON DUPLICATE KEY UPDATE
                           telegram_username = COALESCE(%s, telegram_username),
                           last_active = NOW()""",
                    (user_id, username, username),
                )

    async def is_user_allowed(self, user_id: int) -> bool:
        """Check if user exists and is allowed."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT is_allowed FROM users WHERE user_id = %s",
                    (user_id,),
                )
                row = await cur.fetchone()
                return bool(row and row[0])

    async def add_user(self, user_id: int, email: str | None = None,
                       display_name: str | None = None,
                       username: str | None = None) -> bool:
        """Add or enable a user. Returns True if newly created."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO users (user_id, telegram_username, email, display_name, is_allowed)
                       VALUES (%s, %s, %s, %s, TRUE)
                       ON DUPLICATE KEY UPDATE
                           is_allowed = TRUE,
                           email = COALESCE(%s, email),
                           display_name = COALESCE(%s, display_name),
                           telegram_username = COALESCE(%s, telegram_username)""",
                    (user_id, username, email, display_name,
                     email, display_name, username),
                )
                return cur.lastrowid != 0

    async def remove_user(self, user_id: int) -> bool:
        """Disable a user (soft delete). Returns True if user existed."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE users SET is_allowed = FALSE WHERE user_id = %s",
                    (user_id,),
                )
                return cur.rowcount > 0

    async def list_users(self) -> list[dict]:
        """List all allowed users."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT user_id, telegram_username, email, display_name,
                              first_seen, last_active, is_allowed, total_cost
                       FROM users WHERE is_allowed = TRUE
                       ORDER BY last_active DESC""",
                )
                return await cur.fetchall()

    async def get_user_by_email(self, email: str) -> dict | None:
        """Find user by email address."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM users WHERE email = %s AND is_allowed = TRUE",
                    (email,),
                )
                return await cur.fetchone()

    async def get_preferences(self, user_id: int) -> dict:
        """Load user preferences from MySQL. Returns empty dict if none set."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT preferences FROM users WHERE user_id = %s",
                    (user_id,),
                )
                row = await cur.fetchone()
                if row and row["preferences"]:
                    prefs = row["preferences"]
                    return json.loads(prefs) if isinstance(prefs, str) else prefs
                return {}

    async def save_preferences(self, user_id: int, prefs: dict):
        """Save user preferences to MySQL."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE users SET preferences = %s WHERE user_id = %s",
                    (json.dumps(prefs), user_id),
                )

    async def get_user_stats(self, user_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT
                        u.user_id,
                        u.telegram_username,
                        u.first_seen,
                        u.last_active,
                        (SELECT COUNT(*)              FROM messages WHERE user_id = u.user_id) as message_count,
                        (SELECT COUNT(*)              FROM sessions WHERE user_id = u.user_id) as session_count,
                        (SELECT COALESCE(SUM(cost),0) FROM messages WHERE user_id = u.user_id) as total_cost,
                        (SELECT COALESCE(SUM(input_tokens),0)          FROM messages WHERE user_id = u.user_id) as total_input_tokens,
                        (SELECT COALESCE(SUM(output_tokens),0)         FROM messages WHERE user_id = u.user_id) as total_output_tokens,
                        (SELECT COALESCE(SUM(cache_creation_tokens),0) FROM messages WHERE user_id = u.user_id) as total_cache_creation_tokens,
                        (SELECT COALESCE(SUM(cache_read_tokens),0)     FROM messages WHERE user_id = u.user_id) as total_cache_read_tokens
                    FROM users u
                    WHERE u.user_id = %s""",
                    (user_id,),
                )
                return await cur.fetchone()

    async def get_daily_stats(self, user_id: int) -> list[dict]:
        """Return per-day token/cost breakdown since the first message."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT
                        DATE(timestamp) AS date,
                        model,
                        COALESCE(SUM(input_tokens), 0)          AS input_tokens,
                        COALESCE(SUM(output_tokens), 0)         AS output_tokens,
                        COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                        COALESCE(SUM(cache_read_tokens), 0)     AS cache_read_tokens,
                        COALESCE(SUM(cost), 0)                  AS cost,
                        COUNT(*)                                AS messages
                    FROM messages
                    WHERE user_id = %s AND response IS NOT NULL
                    GROUP BY DATE(timestamp), model
                    ORDER BY date ASC""",
                    (user_id,),
                )
                rows = await cur.fetchall()
                # Convert date objects to ISO strings for JSON serialisation
                return [
                    {**row, "date": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"])}
                    for row in rows
                ]

    async def get_tool_stats(self, user_id: int, limit: int = 15) -> list[dict]:
        """Return top-N tools by usage count for a user."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT tu.tool_name, COUNT(*) AS count
                    FROM tool_usage tu
                    JOIN sessions s ON tu.session_id = s.session_id
                    WHERE s.user_id = %s
                    GROUP BY tu.tool_name
                    ORDER BY count DESC
                    LIMIT %s""",
                    (user_id, limit),
                )
                return await cur.fetchall()

    # --- Sessions ---

    async def save_session(self, session_id: str, user_id: int, project_path: str,
                           cost: float = 0.0, turns: int = 0, messages: int = 0,
                           context_tokens: int = 0, context_max_tokens: int = 0) -> bool:
        """Upsert session stats. Returns True if this was a brand-new session."""
        from ..utils.session_names import generate_display_name
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO sessions
                       (session_id, user_id, project_path, total_cost, total_turns, message_count, context_tokens, context_max_tokens, display_name)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           last_used = NOW(),
                           total_cost = total_cost + %s,
                           total_turns = total_turns + %s,
                           message_count = message_count + %s,
                           context_tokens = IF(%s > 0, %s, context_tokens),
                           context_max_tokens = IF(%s > 0, %s, context_max_tokens),
                           display_name = IF(display_name IS NULL, %s, display_name)""",
                    (session_id, user_id, project_path, cost, turns, messages, context_tokens, context_max_tokens,
                     generate_display_name(),
                     cost, turns, messages, context_tokens, context_tokens, context_max_tokens, context_max_tokens,
                     generate_display_name()),
                )
                # ROW_COUNT() == 1 → INSERT (new session), 2 → UPDATE (existing)
                is_new = cur.rowcount == 1
                if is_new:
                    await cur.execute(
                        "UPDATE users SET session_count = session_count + 1 WHERE user_id = %s",
                        (user_id,),
                    )
                return is_new

    async def get_active_session(
        self, user_id: int, project_path: str, channel: str | None = None
    ) -> dict | None:
        """Return the most recent active session for user+project.

        When *channel* is given (e.g. "telegram" or "web"), sessions that were
        last used on that channel are preferred over sessions from other channels.
        This prevents Telegram and the WebUI from silently hijacking each other's
        active sessions when a new session is started on one channel.
        """
        timeout = datetime.now(UTC) - timedelta(hours=72)
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if channel:
                    # Prefer a session that was last used on the same channel
                    await cur.execute(
                        """SELECT * FROM sessions
                           WHERE user_id = %s AND project_path = %s
                             AND is_active = TRUE AND last_used > %s
                             AND last_channel = %s
                           ORDER BY last_used DESC LIMIT 1""",
                        (user_id, project_path, timeout, channel),
                    )
                    row = await cur.fetchone()
                    if row:
                        return row
                # Fallback: any active session (preserves previous behaviour when
                # no channel-specific session exists yet)
                await cur.execute(
                    """SELECT * FROM sessions
                       WHERE user_id = %s AND project_path = %s
                         AND is_active = TRUE AND last_used > %s
                       ORDER BY last_used DESC LIMIT 1""",
                    (user_id, project_path, timeout),
                )
                return await cur.fetchone()

    async def get_user_sessions(self, user_id: int, limit: int = 10) -> list[dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT s.session_id, s.project_path, s.last_used,
                              s.total_turns, s.total_cost,
                              s.compact_count,
                              s.context_tokens,
                              s.context_max_tokens,
                              s.last_channel,
                              s.is_running,
                              s.running_channel,
                              s.display_name
                       FROM sessions s
                       WHERE s.user_id = %s AND s.is_active = TRUE
                       ORDER BY s.last_used DESC LIMIT %s""",
                    (user_id, limit),
                )
                return await cur.fetchall()

    async def resolve_session_id(self, user_id: int, prefix: str) -> dict | None:
        """Resolve a short session ID prefix or display_name prefix to full session info.

        Returns dict with session_id and display_name, or None.
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # First try display_name match (exact or prefix)
                await cur.execute(
                    "SELECT session_id, display_name FROM sessions "
                    "WHERE user_id = %s AND display_name LIKE %s "
                    "ORDER BY last_used DESC LIMIT 1",
                    (user_id, f"{prefix}%"),
                )
                row = await cur.fetchone()
                if row:
                    return row
                # Fall back to session_id prefix match
                await cur.execute(
                    "SELECT session_id, display_name FROM sessions "
                    "WHERE user_id = %s AND session_id LIKE %s "
                    "ORDER BY last_used DESC LIMIT 1",
                    (user_id, f"{prefix}%"),
                )
                row = await cur.fetchone()
                return row if row else None

    async def deactivate_session(self, session_id: str, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE sessions SET is_active = FALSE WHERE session_id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                return cur.rowcount > 0

    # --- Execution lock (cross-channel: Telegram ↔ Web) ---

    async def acquire_running_lock(
        self, session_id: str, channel: str, stale_after_minutes: int = 10
    ) -> bool:
        """Atomically set is_running=1 for *session_id* if it is not already locked.

        First resets any stale lock older than *stale_after_minutes*.
        Returns True if the lock was acquired, False if another channel is active.
        *channel* should be 'telegram' or 'web'.
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 1. Reset stale lock (safety net for crashed pods)
                await cur.execute(
                    """UPDATE sessions
                       SET is_running = 0, running_since = NULL, running_channel = NULL
                       WHERE session_id = %s
                         AND is_running = 1
                         AND running_since < NOW() - INTERVAL %s MINUTE""",
                    (session_id, stale_after_minutes),
                )
                # 2. Atomic acquire: only succeeds if is_running=0
                await cur.execute(
                    """UPDATE sessions
                       SET is_running = 1,
                           running_since = NOW(),
                           running_channel = %s,
                           last_channel = %s
                       WHERE session_id = %s AND is_running = 0""",
                    (channel, channel, session_id),
                )
                return cur.rowcount > 0

    async def release_running_lock(self, session_id: str) -> None:
        """Clear the execution lock for *session_id*."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE sessions
                       SET is_running = 0, running_since = NULL, running_channel = NULL
                       WHERE session_id = %s""",
                    (session_id,),
                )

    async def get_any_running_session(self, user_id: int) -> dict | None:
        """Return the first locked session for a user, or None if none are running."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT session_id, running_channel FROM sessions
                       WHERE user_id = %s AND is_running = 1
                       ORDER BY running_since DESC LIMIT 1""",
                    (user_id,),
                )
                return await cur.fetchone()

    async def get_running_channel(self, session_id: str) -> str | None:
        """Return the channel currently holding the lock, or None if unlocked."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT running_channel FROM sessions WHERE session_id = %s AND is_running = 1",
                    (session_id,),
                )
                row = await cur.fetchone()
                return row["running_channel"] if row else None

    async def reset_running_locks_for_users(self, user_ids: list[int]) -> int:
        """Reset all stale locks for *user_ids* — called at pod startup.

        Clears every session with is_running=1 belonging to these users,
        regardless of age (pod restart implies the execution is gone).
        Returns the number of sessions cleared.
        """
        if not user_ids:
            return 0
        placeholders = ",".join(["%s"] * len(user_ids))
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""UPDATE sessions
                        SET is_running = 0, running_since = NULL, running_channel = NULL
                        WHERE is_running = 1 AND user_id IN ({placeholders})""",
                    user_ids,
                )
                return cur.rowcount

    # --- Session compaction ---

    async def get_session_token_count(self, session_id: str, user_id: int) -> int:
        """Return total input+output tokens for a session (used for display)."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT COALESCE(SUM(input_tokens + output_tokens), 0)
                       FROM messages WHERE session_id = %s AND user_id = %s""",
                    (session_id, user_id),
                )
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def save_compaction_event(
        self,
        session_id: str,
        user_id: int,
        summary: str,
        trigger: str = "auto",
    ) -> None:
        """Record that SDK compaction occurred for this session.

        The session_id stays the same after SDK compaction — we store the
        summary, increment the compact_count, and set compacted_from for audit.
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE sessions
                       SET context_summary = %s,
                           compacted_from  = %s,
                           compact_count   = compact_count + 1
                       WHERE session_id = %s AND user_id = %s""",
                    (summary or None, f"sdk:{trigger}", session_id, user_id),
                )

    # --- Messages ---

    async def save_message(self, session_id: str, user_id: int, prompt: str,
                           response: str | None = None, cost: float = 0.0,
                           duration_ms: int | None = None, error: str | None = None,
                           model: str | None = None, input_tokens: int = 0,
                           output_tokens: int = 0, cache_creation_tokens: int = 0,
                           cache_read_tokens: int = 0,
                           tools_json: list[dict] | None = None) -> int:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO messages
                       (session_id, user_id, prompt, response, cost, duration_ms, error,
                        model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                        tools_json)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (session_id, user_id, prompt, response, cost, duration_ms, error,
                     model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                     json.dumps(tools_json) if tools_json else None),
                )
                return cur.lastrowid

    async def save_message_prompt(self, session_id: str, user_id: int,
                                   prompt: str) -> int:
        """Persist the user prompt immediately (response=NULL).
        Returns message_id for later update via update_message_response()."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO messages (session_id, user_id, prompt)
                       VALUES (%s, %s, %s)""",
                    (session_id, user_id, prompt),
                )
                return cur.lastrowid

    async def update_message_response(self, message_id: int, response: str,
                                      cost: float = 0.0, duration_ms: int | None = None,
                                      model: str | None = None, input_tokens: int = 0,
                                      output_tokens: int = 0,
                                      cache_creation_tokens: int = 0,
                                      cache_read_tokens: int = 0,
                                      error: str | None = None,
                                      session_id: str | None = None,
                                      tools_json: list[dict] | None = None) -> None:
        """Fill in response + stats for a previously saved prompt row."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                tools_str = json.dumps(tools_json) if tools_json else None
                session_clause = ", session_id = %s" if session_id else ""
                tools_clause = ", tools_json = %s" if tools_str is not None else ""
                sql = f"""UPDATE messages SET
                           response = %s,
                           cost = %s,
                           duration_ms = %s,
                           model = %s,
                           input_tokens = %s,
                           output_tokens = %s,
                           cache_creation_tokens = %s,
                           cache_read_tokens = %s,
                           error = %s
                           {tools_clause}
                           {session_clause}
                       WHERE message_id = %s"""
                params = [response, cost, duration_ms, model, input_tokens,
                          output_tokens, cache_creation_tokens, cache_read_tokens,
                          error]
                if tools_str is not None:
                    params.append(tools_str)
                if session_id:
                    params.append(session_id)
                params.append(message_id)
                await cur.execute(sql, tuple(params))

    async def update_user_stats(self, user_id: int, cost: float):
        """Increment total_cost and message_count after each completed request."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE users SET
                           total_cost = total_cost + %s,
                           message_count = message_count + 1,
                           last_active = NOW()
                       WHERE user_id = %s""",
                    (cost, user_id),
                )

    # --- Tool Usage ---

    async def save_tool_usage(self, session_id: str, tool_name: str,
                              tool_input: dict | None = None, success: bool = True,
                              error_message: str | None = None, message_id: int | None = None):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO tool_usage
                       (session_id, message_id, tool_name, tool_input, success, error_message)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (session_id, message_id, tool_name,
                     json.dumps(tool_input) if tool_input else None,
                     success, error_message),
                )

    # --- Cost Tracking ---

    async def track_cost(self, user_id: int, cost: float):
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO cost_tracking (user_id, date, daily_cost, request_count)
                       VALUES (%s, %s, %s, 1)
                       ON DUPLICATE KEY UPDATE
                           daily_cost = daily_cost + %s,
                           request_count = request_count + 1""",
                    (user_id, today, cost, cost),
                )

    # --- Audit ---

    async def log_event(self, user_id: int, event_type: str,
                        event_data: dict | None = None, success: bool = True):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO audit_log (user_id, event_type, event_data, success)
                       VALUES (%s, %s, %s, %s)""",
                    (user_id, event_type,
                     json.dumps(event_data) if event_data else None, success),
                )

    # --- Session Content (JSONL) ---

    async def save_session_content(self, session_id: str, user_id: int,
                                   project_path: str, jsonl_content: str,
                                   metadata: dict | None = None):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO session_content
                       (session_id, user_id, project_path, jsonl_content, metadata)
                       VALUES (%s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           jsonl_content = %s,
                           metadata = %s,
                           updated_at = NOW()""",
                    (session_id, user_id, project_path, jsonl_content,
                     json.dumps(metadata) if metadata else None,
                     jsonl_content,
                     json.dumps(metadata) if metadata else None),
                )

    async def get_session_content(self, session_id: str, user_id: int) -> dict | None:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM session_content WHERE session_id = %s AND user_id = %s",
                    (session_id, user_id),
                )
                return await cur.fetchone()

    async def get_all_session_contents(self, user_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT session_id, project_path, updated_at
                       FROM session_content WHERE user_id = %s
                       ORDER BY updated_at DESC""",
                    (user_id,),
                )
                return await cur.fetchall()

    # --- Stats ---

    async def get_stats(self) -> dict:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT COUNT(DISTINCT user_id) as users,
                              COUNT(DISTINCT CASE WHEN session_id != 'unknown' THEN session_id END) as sessions,
                              COUNT(*) as messages,
                              COALESCE(SUM(cost), 0) as total_cost,
                              COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                              COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                              COALESCE(SUM(cache_creation_tokens), 0) as total_cache_creation_tokens,
                              COALESCE(SUM(cache_read_tokens), 0) as total_cache_read_tokens
                       FROM messages"""
                )
                return await cur.fetchone()

    async def get_model_stats(self, user_id: int | None = None) -> list[dict]:
        """Per-model breakdown: count, cost, tokens. Optionally filtered by user."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                if user_id is not None:
                    await cur.execute(
                        """SELECT
                               COALESCE(NULLIF(model, ''), 'unbekannt') as model,
                               COUNT(*) as messages,
                               COALESCE(SUM(cost), 0) as total_cost,
                               COALESCE(SUM(input_tokens), 0) as input_tokens,
                               COALESCE(SUM(output_tokens), 0) as output_tokens,
                               COALESCE(SUM(cache_creation_tokens), 0) as cache_creation_tokens,
                               COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens
                           FROM messages
                           WHERE user_id = %s
                           GROUP BY model
                           ORDER BY total_cost DESC""",
                        (user_id,),
                    )
                else:
                    await cur.execute(
                        """SELECT
                               COALESCE(NULLIF(model, ''), 'unbekannt') as model,
                               COUNT(*) as messages,
                               COALESCE(SUM(cost), 0) as total_cost,
                               COALESCE(SUM(input_tokens), 0) as input_tokens,
                               COALESCE(SUM(output_tokens), 0) as output_tokens,
                               COALESCE(SUM(cache_creation_tokens), 0) as cache_creation_tokens,
                               COALESCE(SUM(cache_read_tokens), 0) as cache_read_tokens
                           FROM messages
                           GROUP BY model
                           ORDER BY total_cost DESC"""
                    )
                return await cur.fetchall()

    # --- API Keys ---

    async def create_api_key(self, api_key: str, user_id: int, name: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO api_keys (api_key, user_id, name)
                       VALUES (%s, %s, %s)""",
                    (api_key, user_id, name),
                )
                return cur.rowcount > 0

    async def validate_api_key(self, api_key: str) -> dict | None:
        """Validate key and return user info. Updates last_used."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT api_key, user_id, name, permissions, is_active
                       FROM api_keys WHERE api_key = %s""",
                    (api_key,),
                )
                row = await cur.fetchone()
                if not row or not row["is_active"]:
                    return None
                # Update last_used
                await cur.execute(
                    "UPDATE api_keys SET last_used = NOW() WHERE api_key = %s",
                    (api_key,),
                )
                return row

    async def list_api_keys(self, user_id: int) -> list[dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT api_key, name, user_id, created_at, last_used, is_active
                       FROM api_keys WHERE user_id = %s
                       ORDER BY created_at DESC""",
                    (user_id,),
                )
                return await cur.fetchall()

    async def revoke_api_key(self, api_key: str) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE api_keys SET is_active = FALSE WHERE api_key = %s",
                    (api_key,),
                )
                return cur.rowcount > 0

    # --- Telegram Uploads ---

    async def save_upload(
        self,
        upload_id: str,
        user_id: int,
        telegram_file_id: str | None,
        original_filename: str | None,
        media_type: str,
        mime_type: str | None,
        file_size: int,
        storage_path: str | None,
        es_id: str | None,
        caption: str | None = None,
        transcript: str | None = None,
        vision_summary: str | None = None,
    ):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO telegram_uploads
                       (upload_id, user_id, telegram_file_id, original_filename,
                        media_type, mime_type, file_size, storage_path, es_id,
                        caption, transcript, vision_summary)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           es_id = VALUES(es_id),
                           transcript = COALESCE(VALUES(transcript), transcript),
                           vision_summary = COALESCE(VALUES(vision_summary), vision_summary)""",
                    (upload_id, user_id, telegram_file_id, original_filename,
                     media_type, mime_type, file_size, storage_path, es_id,
                     caption, transcript, vision_summary),
                )

    async def save_upload_rows(self, upload_id: str, user_id: int, rows: list[dict]):
        if not rows:
            return
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                for i, row in enumerate(rows):
                    await cur.execute(
                        """INSERT INTO telegram_upload_rows
                           (upload_id, user_id, row_index, row_data)
                           VALUES (%s, %s, %s, %s)""",
                        (upload_id, user_id, i, json.dumps(row, ensure_ascii=False, default=str)),
                    )

    async def query_upload_rows(self, upload_id: str, user_id: int, limit: int = 100) -> list[dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT row_index, row_data FROM telegram_upload_rows
                       WHERE upload_id = %s AND user_id = %s
                       ORDER BY row_index LIMIT %s""",
                    (upload_id, user_id, limit),
                )
                rows = await cur.fetchall()
                return [json.loads(r["row_data"]) for r in rows]

    async def list_uploads(self, user_id: int, limit: int = 500) -> list[dict]:
        """List all uploads for a user, with tabular-index status."""
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT upload_id, original_filename, media_type, mime_type,
                              file_size, storage_path, es_id, memory_id,
                              created_at, caption
                       FROM telegram_uploads
                       WHERE user_id = %s
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (user_id, limit),
                )
                rows = await cur.fetchall()

                if not rows:
                    return []

                # Check which upload_ids have tabular rows
                ids = [r["upload_id"] for r in rows]
                placeholders = ",".join(["%s"] * len(ids))
                await cur.execute(
                    f"SELECT DISTINCT upload_id FROM telegram_upload_rows WHERE upload_id IN ({placeholders})",
                    ids,
                )
                tabular_ids = {r["upload_id"] for r in await cur.fetchall()}

        result = []
        for row in rows:
            result.append({
                "upload_id": row["upload_id"],
                "filename": row.get("original_filename") or row["upload_id"],
                "media_type": row.get("media_type"),
                "mime_type": row.get("mime_type"),
                "file_size": row.get("file_size") or 0,
                "storage_path": row.get("storage_path"),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "caption": row.get("caption"),
                "indexed_es": bool(row.get("es_id")),
                "indexed_mysql": row["upload_id"] in tabular_ids,
                "enriched_memory": row.get("memory_id"),
            })
        return result

    async def link_upload_memory(self, upload_id: str, memory_id: str):
        """Link an upload to its enriched memory after knowledge pipeline."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE telegram_uploads SET memory_id = %s WHERE upload_id = %s",
                    (memory_id, upload_id),
                )
                await conn.commit()

