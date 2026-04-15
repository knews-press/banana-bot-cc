"""Configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str
    telegram_bot_username: str = ""
    allowed_users: str = ""  # comma-separated Telegram user IDs
    owner_email: str = ""   # email for the primary user (enables Web UI login)
    instance_name: str = "banana-bot"

    # Claude Code
    claude_default_model: str = ""  # e.g. "claude-sonnet-4-6", empty = CLI default
    claude_timeout_seconds: int = 1800
    claude_max_turns: int = 50
    approved_directory: str = "/root/workspace"
    uploads_directory: str = "/root/uploads"
    session_timeout_hours: int = 72
    max_sessions_per_user: int = 10

    # MySQL (bot's own data)
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = "claude_code"

    # Elasticsearch (memory + conversation log)
    es_host: str = "elasticsearch:9200"

    # Neo4j (knowledge graph — optional)
    neo4j_host: str = "neo4j"
    neo4j_bolt_port: int = 7687
    neo4j_http_port: int = 7474
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # SearXNG (web search — optional)
    searxng_url: str = "http://searxng:8080"

    # Internal API (for NER/extraction calls to self)
    internal_api_url: str = "http://localhost:8080"
    internal_api_key: str = ""

    # GitHub (optional — enables gh CLI for Claude Code via Bash tool)
    gh_pat: str = ""

    # API Keys (available to Claude as env)
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # TTS instance defaults (overridden by user settings at runtime)
    tts_default_provider: str = "gemini"   # "gemini" | "openai"
    tts_default_voice: str = "Puck"
    tts_default_style_prompt: str = ""     # empty = no style
    tts_default_model: str = ""            # empty = provider default

    # SMTP (optional — for email sending)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # System prompt file (loaded at runtime)
    system_prompt_file: str = "/app/config/system-prompt.md"

    @property
    def allowed_user_ids(self) -> set[int]:
        if not self.allowed_users:
            return set()
        return {int(uid.strip()) for uid in self.allowed_users.split(",") if uid.strip()}

    @property
    def owner_user_id(self) -> int:
        """Primary user ID — used for SSH sessions and non-Telegram contexts."""
        ids = self.allowed_user_ids
        return min(ids) if ids else 0

    @property
    def es_url(self) -> str:
        host = self.es_host
        if not host.startswith("http"):
            host = f"http://{host}"
        return host

    class Config:
        env_file = ".env"
        case_sensitive = False
