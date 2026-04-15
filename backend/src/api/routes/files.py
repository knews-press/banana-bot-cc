"""File explorer endpoints — uploads list + workspace browser."""

import asyncio
import mimetypes
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from ..auth import get_api_user

EXPORT_DIR = Path("/root/creations")

logger = structlog.get_logger()

router = APIRouter()


def _safe_path(base: str, rel: str) -> Path:
    """Resolve rel path under base; raise 400 if it escapes."""
    base_path = Path(base).resolve()
    candidate = (base_path / rel.lstrip("/")).resolve()
    if not str(candidate).startswith(str(base_path)):
        raise HTTPException(status_code=400, detail="Ungültiger Pfad.")
    return candidate


def _classify_file(filename: str, mime_type: str | None) -> dict:
    """Classify a file for frontend rendering."""
    ext = Path(filename).suffix.lower()
    CODE_EXTS = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "typescript", ".jsx": "javascript", ".json": "json",
        ".yaml": "yaml", ".yml": "yaml", ".sh": "shell", ".bash": "shell",
        ".zsh": "shell", ".html": "html", ".htm": "html", ".css": "css",
        ".scss": "scss", ".sql": "sql", ".go": "go", ".rs": "rust",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
        ".tf": "hcl", ".toml": "toml", ".ini": "ini", ".env": "ini",
        ".xml": "xml", ".txt": "plaintext", ".lock": "plaintext",
        ".graphql": "graphql", ".proto": "protobuf", ".kt": "kotlin",
        ".swift": "swift", ".r": "r", ".rb": "ruby", ".dockerfile": "dockerfile",
        ".log": "plaintext",
    }
    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
    AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".oga"}
    VIDEO_EXTS = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
    BINARY_EXTS = {
        ".dxf", ".dwg", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
        ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".exe", ".bin",
        ".wasm", ".ttf", ".otf", ".woff", ".woff2", ".eot",
        ".db", ".sqlite", ".so", ".dylib", ".dll",
        ".class", ".jar", ".pyc", ".pyo",
    }
    if filename.lower() in ("dockerfile", "makefile", "jenkinsfile"):
        return {"render_type": "code", "language": "dockerfile", "previewable": True}
    if ext == ".md":
        return {"render_type": "markdown", "language": "markdown", "previewable": True}
    if ext == ".csv":
        return {"render_type": "csv", "language": None, "previewable": True}
    if ext == ".pdf":
        return {"render_type": "pdf", "language": None, "previewable": True}
    if ext in IMAGE_EXTS:
        return {"render_type": "image", "language": None, "previewable": True}
    if ext in AUDIO_EXTS:
        return {"render_type": "audio", "language": None, "previewable": True}
    if ext in VIDEO_EXTS:
        return {"render_type": "video", "language": None, "previewable": True}
    if ext in BINARY_EXTS:
        return {"render_type": "binary", "language": None, "previewable": False}
    if ext in CODE_EXTS:
        return {"render_type": "code", "language": CODE_EXTS[ext], "previewable": True}
    if mime_type and mime_type.startswith("text/"):
        return {"render_type": "code", "language": "plaintext", "previewable": True}
    return {"render_type": "binary", "language": None, "previewable": False}


# ─── Uploads ─────────────────────────────────────────────────────────────────

@router.get("/files/uploads")
async def list_uploads(request: Request, user: dict = Depends(get_api_user)):
    """List all uploads for this user with ES + MySQL tabular index status."""
    mysql = request.app.state.mysql
    uploads = await mysql.list_uploads(user["user_id"])

    # Annotate with on-disk existence
    for u in uploads:
        sp = u.get("storage_path")
        u["exists_on_disk"] = bool(sp and Path(sp).exists())

    return uploads


# ─── Upload ──────────────────────────────────────────────────────────────────

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


@router.post("/files/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(get_api_user),
):
    """Upload a file, run it through MediaProcessor, index in ES + MySQL."""
    settings = request.app.state.settings
    mysql = request.app.state.mysql
    uploads_storage = request.app.state.uploads_storage

    if uploads_storage is None:
        raise HTTPException(status_code=503, detail="Upload-Storage nicht verfügbar.")

    # Size guard — read Content-Length header if present
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Datei zu groß (max. 100 MB).")

    upload_id = str(uuid.uuid4())
    original_filename = file.filename or f"upload_{upload_id}"
    mime_type = file.content_type or mimetypes.guess_type(original_filename)[0]
    user_id = user["user_id"]

    # Determine final storage path
    uploads_dir = settings.uploads_directory
    ext = Path(original_filename).suffix
    storage_path = os.path.join(uploads_dir, f"{upload_id}{ext}")

    # Stream to a temp file first, then move to final location
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            total = 0
            while True:
                chunk = await file.read(256 * 1024)  # 256 KB chunks
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_SIZE:
                    os.unlink(tmp_path)
                    raise HTTPException(status_code=413, detail="Datei zu groß (max. 100 MB).")
                tmp.write(chunk)

        # Move to permanent location
        shutil.move(tmp_path, storage_path)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("File upload failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Upload-Fehler: {exc}")

    # Process via MediaProcessor
    try:
        from ...bot.media.processor import MediaProcessor
        processor = MediaProcessor(
            uploads_dir=uploads_dir,
            openai_api_key=getattr(settings, "openai_api_key", "") or "",
        )
        result = await processor.process_file(
            local_path=storage_path,
            upload_id=upload_id,
            original_filename=original_filename,
            mime_type=mime_type,
            caption=None,
        )
    except Exception as exc:
        logger.error("MediaProcessor failed", upload_id=upload_id, error=str(exc))
        # Still store the raw file even if processing fails
        from ...bot.media.processor import MediaResult
        result = MediaResult(
            upload_id=upload_id,
            media_type="binary",
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=total,
            storage_path=storage_path,
            content_text="",
            summary=f"📎 Datei empfangen: {original_filename}",
        )

    # Index in Elasticsearch
    try:
        es_id = await uploads_storage.index_upload(
            upload_id=upload_id,
            user_id=user_id,
            media_type=result.media_type,
            mime_type=result.mime_type,
            original_filename=result.original_filename,
            content=result.content_text,
            transcript=result.transcript,
            vision_summary=result.vision_summary,
        )
    except Exception as exc:
        logger.warning("ES indexing failed", upload_id=upload_id, error=str(exc))
        es_id = None

    # Save to MySQL
    await mysql.save_upload(
        upload_id=upload_id,
        user_id=user_id,
        telegram_file_id=None,
        original_filename=result.original_filename,
        media_type=result.media_type,
        mime_type=result.mime_type,
        file_size=result.file_size,
        storage_path=result.storage_path,
        es_id=es_id,
        caption=None,
        transcript=result.transcript,
        vision_summary=result.vision_summary,
    )

    # Store tabular rows if present
    if result.table_rows:
        await mysql.save_upload_rows(upload_id, user_id, result.table_rows)

    logger.info(
        "File uploaded via API",
        upload_id=upload_id,
        user_id=user_id,
        filename=original_filename,
        media_type=result.media_type,
        size=result.file_size,
    )

    # Knowledge enrichment: classify upload → save as memory → graph
    neo4j = getattr(request.app.state, "neo4j", None)

    async def _enrich():
        try:
            from ...knowledge.upload_enrichment import enrich_upload
            await enrich_upload(
                es=request.app.state.es, neo4j=neo4j, settings=settings,
                user_id=user_id, upload_id=upload_id,
                original_filename=original_filename,
                media_type=result.media_type,
                content_text=result.content_text,
                caption=None,
                transcript=result.transcript,
                vision_summary=result.vision_summary,
                mysql=mysql,
            )
        except Exception as exc:
            logger.error("Upload enrichment failed", upload_id=upload_id, error=str(exc))

    asyncio.create_task(_enrich())

    return {
        "upload_id": upload_id,
        "media_type": result.media_type,
        "original_filename": result.original_filename,
        "mime_type": result.mime_type,
        "file_size": result.file_size,
        "summary": result.summary,
        "has_transcript": bool(result.transcript),
        "has_vision": bool(result.vision_summary),
        "is_tabular": bool(result.table_rows),
        "row_count": len(result.table_rows) if result.table_rows else 0,
    }


# ─── Workspace browser ────────────────────────────────────────────────────────

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".next", ".tox", "venv", ".venv"}


@router.get("/files/workspace")
async def list_workspace(
    request: Request,
    path: str = Query(default="", description="Relative path within workspace"),
    user: dict = Depends(get_api_user),
):
    """List directory contents within the approved workspace."""
    settings = request.app.state.settings
    base = settings.approved_directory

    target = _safe_path(base, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Pfad nicht gefunden.")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Pfad ist kein Verzeichnis.")

    entries = []
    try:
        items = sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in items:
            # Skip noisy dirs
            if entry.is_dir() and entry.name in SKIP_DIRS:
                continue
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "path": str(entry.relative_to(Path(base))),
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if not entry.is_dir() else None,
                    "modified": stat.st_mtime,
                })
            except Exception:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    rel = str(target.relative_to(Path(base))) if target != Path(base) else ""
    return {"path": rel, "entries": entries}


# ─── File reader ──────────────────────────────────────────────────────────────

MAX_FILE_SIZE = 1_000_000  # 1 MB


@router.get("/files/read")
async def read_file(
    request: Request,
    path: str = Query(..., description="Relative path within workspace"),
    user: dict = Depends(get_api_user),
):
    """Read a text file from the workspace. Returns content + language hint."""
    settings = request.app.state.settings
    base = settings.approved_directory

    target = _safe_path(base, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Pfad ist ein Verzeichnis.")

    size = target.stat().st_size
    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Datei zu groß ({size // 1024} KB). Maximum: 1 MB.",
        )

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Lesefehler: {exc}")

    mime_type, _ = mimetypes.guess_type(str(target))
    classification = _classify_file(target.name, mime_type)
    if not classification["previewable"]:
        raise HTTPException(status_code=415, detail="Datei kann nicht als Text angezeigt werden.")
    return {
        "path": str(target.relative_to(Path(base))),
        "name": target.name,
        "content": content,
        "size": size,
        "mime_type": mime_type,
        **classification,
    }


# ─── Generated file download ──────────────────────────────────────────────────

@router.get("/files/download")
async def download_file(
    request: Request,
    path: str = Query(..., description="Absolute path or filename within the export dir"),
    workspace: bool = Query(False, description="Treat path as relative to workspace"),
    inline: bool = Query(False, description="Serve inline (for browser image display) instead of as attachment"),
    user: dict = Depends(get_api_user),
):
    """Download a generated file (Word, Excel, CSV, …) by path.

    Accepts either an absolute path inside /root/creations/ or a plain
    filename (basename).  Paths outside the export directory are rejected.
    When workspace=True, resolves path relative to the approved workspace directory.
    """
    if workspace:
        settings = request.app.state.settings
        candidate = _safe_path(settings.approved_directory, path)
    else:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = EXPORT_DIR / candidate
        try:
            candidate = candidate.resolve()
            if not str(candidate).startswith(str(EXPORT_DIR.resolve())):
                raise HTTPException(status_code=403, detail="Zugriff verweigert.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Ungültiger Pfad.")

    if not candidate.exists():
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {candidate.name}")

    mime_type, _ = mimetypes.guess_type(str(candidate))
    disposition = "inline" if inline else f'attachment; filename="{candidate.name}"'
    return FileResponse(
        path=str(candidate),
        filename=candidate.name,
        media_type=mime_type or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@router.get("/files/creations")
async def list_creations(user: dict = Depends(get_api_user)):
    """List all files in /root/creations/."""
    creations_dir = Path("/root/creations")
    creations_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(creations_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            stat = f.stat()
            files.append({
                "filename": f.name,
                "path": str(f),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
    return files


@router.get("/files/upload-download")
async def download_upload(
    upload_id: str = Query(...),
    request: Request = None,
    user: dict = Depends(get_api_user),
):
    """Download an uploaded file by upload_id."""
    mysql = request.app.state.mysql
    uploads = await mysql.list_uploads(user["user_id"])
    upload = next((u for u in uploads if u["upload_id"] == upload_id), None)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload nicht gefunden.")
    sp = upload.get("storage_path")
    if not sp or not Path(sp).exists():
        raise HTTPException(status_code=404, detail="Datei nicht mehr auf Disk vorhanden.")
    p = Path(sp)
    mime_type, _ = mimetypes.guess_type(str(p))
    return FileResponse(
        path=str(p),
        filename=upload.get("filename") or p.name,
        media_type=mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{upload.get("filename") or p.name}"'},
    )
