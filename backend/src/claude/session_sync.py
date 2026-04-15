"""Session sync: Claude Code JSONL files ↔ MySQL.

Claude Code stores sessions as JSONL files on disk under:
    ~/.claude/projects/{project-slug}/{session-uuid}.jsonl

where {project-slug} is the cwd with all '/' replaced by '-':
    /root/workspace  →  -root-workspace

After each interaction we copy the JSONL to MySQL as a DR backup.
On startup we restore from MySQL if the JSONL is missing from disk.
"""

import json
from pathlib import Path

from ..utils.session_names import short_name

import structlog

from ..storage.mysql import MySQLStorage

logger = structlog.get_logger()

CLAUDE_DIR = Path.home() / ".claude"


def _cwd_to_slug(cwd: str) -> str:
    """Convert a working directory path to Claude Code's project slug.

    /root/workspace  →  -root-workspace
    /app             →  -app
    """
    return cwd.replace("/", "-")


def _find_jsonl(session_id: str, cwd: str | None = None) -> Path | None:
    """Locate the JSONL file for a session on disk.

    Tries the cwd-derived project directory first, then searches all projects.
    """
    projects = CLAUDE_DIR / "projects"
    if not projects.exists():
        return None

    # Fast path: known project directory
    if cwd:
        slug = _cwd_to_slug(cwd)
        candidate = projects / slug / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate

    # Fallback: search every project directory
    for project_dir in projects.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate

    return None


def _project_dir_for_cwd(cwd: str) -> Path:
    """Return (and create if needed) the project directory for cwd."""
    slug = _cwd_to_slug(cwd)
    project_dir = CLAUDE_DIR / "projects" / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


class SessionSync:
    """Sync Claude Code session JSONL files with MySQL (DR backup)."""

    def __init__(self, mysql: MySQLStorage):
        self.mysql = mysql

    async def save_to_mysql(self, session_id: str, user_id: int, project_path: str):
        """After a Claude interaction: copy JSONL from disk to MySQL."""
        jsonl_file = _find_jsonl(session_id, project_path)
        if not jsonl_file:
            logger.debug("Session JSONL not found on disk", session_id=short_name(session_id))
            return

        try:
            jsonl_content = jsonl_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Could not read JSONL", session_id=short_name(session_id), error=str(e))
            return

        await self.mysql.save_session_content(
            session_id=session_id,
            user_id=user_id,
            project_path=project_path,
            jsonl_content=jsonl_content,
        )
        logger.info("Session synced to MySQL", session_id=short_name(session_id),
                    size=len(jsonl_content))

    async def restore_from_mysql(self, user_id: int, cwd: str | None = None):
        """On startup: restore missing JSONL files from MySQL to disk."""
        session_rows = await self.mysql.get_all_session_contents(user_id)
        if not session_rows:
            return

        restored = 0
        for row in session_rows:
            sid = row["session_id"]
            ppath = row.get("project_path") or cwd or str(Path.home() / "workspace")

            # Skip if already on disk
            if _find_jsonl(sid):
                continue

            content_row = await self.mysql.get_session_content(sid, user_id)
            if not content_row or not content_row.get("jsonl_content"):
                continue

            project_dir = _project_dir_for_cwd(ppath)
            jsonl_file = project_dir / f"{sid}.jsonl"
            jsonl_file.write_text(content_row["jsonl_content"], encoding="utf-8")
            restored += 1

        if restored:
            logger.info("Sessions restored from MySQL to disk", count=restored)
