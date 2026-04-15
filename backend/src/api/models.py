"""Pydantic models for API request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- Chat ---

class ChatRequest(BaseModel):
    message: str = Field(..., description="The prompt to send to Claude")
    session_id: str | None = Field(None, description="Resume existing session (null = auto-detect or new)")
    force_new: bool = Field(False, description="Skip active-session lookup and always start a new session")
    mode: str | None = Field(None, pattern="^(yolo|plan|approve)$", description="Permission mode (null = use user preference)")
    model: str | None = Field(None, description="Model override for this request (null = use user preference)")
    cwd: str | None = Field(None, description="Working directory (default: /root/workspace)")
    stream: bool = Field(False, description="Stream response via SSE")
    hidden: bool = Field(False, description="Mark session as inactive after completion (hidden from sidebar)")


class ChatResponse(BaseModel):
    content: str
    session_id: str | None = None
    cost: float = 0.0
    duration_ms: int = 0
    tools_used: list[str] = []


class ToolEvent(BaseModel):
    """SSE event for tool execution progress."""
    event: str  # tool_start, tool_result, text, done, error
    tool: str | None = None
    input: dict[str, Any] | None = None
    success: bool | None = None
    duration: float | None = None
    preview: str | None = None
    content: str | None = None
    # Final event fields
    session_id: str | None = None
    cost: float | None = None
    duration_ms: int | None = None


# --- Sessions ---

class SessionInfo(BaseModel):
    session_id: str
    project_path: str
    last_used: datetime | None = None
    total_turns: int = 0
    total_cost: float = 0.0
    compact_count: int = 0
    context_tokens: int = 0
    last_channel: str | None = None
    running_channel: str | None = None
    display_name: str | None = None


class SessionDetail(SessionInfo):
    created_at: datetime | None = None
    message_count: int = 0
    is_active: bool = True


class SessionExport(BaseModel):
    session_id: str
    markdown: str


# --- Admin ---

class BotStatus(BaseModel):
    instance_name: str
    uptime_seconds: float
    claude_cli: bool
    active_sessions: int
    total_messages: int
    total_cost: float


class ApiKeyCreate(BaseModel):
    name: str = Field(..., description="Descriptive name for this key")
    user_id: int | None = Field(None, description="User ID to bind to (default: owner)")


class ApiKeyInfo(BaseModel):
    api_key: str
    name: str
    user_id: int
    created_at: datetime | None = None
    last_used: datetime | None = None
    is_active: bool = True


class ApiKeyResponse(BaseModel):
    api_key: str
    name: str
    message: str = "Key created. Store it safely — it won't be shown again."


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# --- Commands ---

class CommandRequest(BaseModel):
    command: str = Field(..., description="The slash command name (without /)")
    args: list[str] = Field(default_factory=list, description="Command arguments")


class CommandResponse(BaseModel):
    success: bool = True
    title: str = ""
    content: str = ""
    data: dict[str, Any] | None = None
    error: str | None = None
