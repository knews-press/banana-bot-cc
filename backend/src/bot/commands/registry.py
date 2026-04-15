"""Command registry — single source of truth for all slash commands.

Used by both Telegram dispatchers and the Web API /commands endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubcommandDef:
    name: str
    description: str
    args_placeholder: str | None = None


@dataclass
class CommandDef:
    name: str
    icon: str
    description: str
    subcommands: list[SubcommandDef] = field(default_factory=list)

    @property
    def is_dispatcher(self) -> bool:
        return len(self.subcommands) > 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "icon": self.icon,
            "description": self.description,
            "is_dispatcher": self.is_dispatcher,
            "subcommands": [
                {
                    "name": s.name,
                    "description": s.description,
                    "args_placeholder": s.args_placeholder,
                }
                for s in self.subcommands
            ],
        }


COMMAND_REGISTRY: list[CommandDef] = [
    CommandDef(
        name="new",
        icon="🆕",
        description="Start a new session",
    ),
    CommandDef(
        name="session",
        icon="📋",
        description="Manage sessions",
        subcommands=[
            SubcommandDef("list", "List all sessions"),
            SubcommandDef("load", "Resume a session", "id"),
            SubcommandDef("delete", "End current session"),
            SubcommandDef("export", "Export as Markdown"),
        ],
    ),
    CommandDef(
        name="stop",
        icon="⏹",
        description="Abort current execution",
    ),
    CommandDef(
        name="tasks",
        icon="📋",
        description="Background tasks",
    ),
    CommandDef(
        name="status",
        icon="📊",
        description="Session status & context",
    ),
    CommandDef(
        name="model",
        icon="🤖",
        description="Switch model",
        subcommands=[
            SubcommandDef("sonnet", "Sonnet 4.6 (200k, fast)"),
            SubcommandDef("opus", "Opus 4.6 (1M, powerful)"),
            SubcommandDef("haiku", "Haiku 4.5 (200k, cheap)"),
            SubcommandDef("default", "Default model"),
        ],
    ),
    CommandDef(
        name="mode",
        icon="⚙️",
        description="Mode & settings",
        subcommands=[
            SubcommandDef("yolo", "Unrestricted"),
            SubcommandDef("approve", "Confirm Bash/Write"),
            SubcommandDef("plan", "Read-only"),
            SubcommandDef("thinking", "Extended Thinking", "budget"),
            SubcommandDef("turns", "Max turns", "n"),
            SubcommandDef("budget", "Cost limit", "usd"),
            SubcommandDef("verbose", "Detail level", "0-2"),
        ],
    ),
    CommandDef(
        name="me",
        icon="👤",
        description="Profile & language",
        subcommands=[
            SubcommandDef("name", "Display name", "name"),
            SubcommandDef("lang", "Language", "de|en|fr|..."),
            SubcommandDef("github", "GitHub username", "user"),
            SubcommandDef("org", "GitHub organization", "org"),
            SubcommandDef("email", "Email address", "addr"),
            SubcommandDef("instructions", "Custom instructions", "text|clear"),
        ],
    ),
    CommandDef(
        name="memory",
        icon="🧠",
        description="Memories & search",
        subcommands=[
            SubcommandDef("list", "Show all"),
            SubcommandDef("delete", "Delete entry", "id"),
            SubcommandDef("search", "Search conversations", "query"),
            SubcommandDef("recall", "Search memories", "query"),
        ],
    ),
]


def get_registry_dict() -> list[dict]:
    """Return registry as JSON-serializable list of dicts."""
    return [cmd.to_dict() for cmd in COMMAND_REGISTRY]


def find_command(name: str) -> CommandDef | None:
    """Look up a command by name."""
    for cmd in COMMAND_REGISTRY:
        if cmd.name == name:
            return cmd
    return None
