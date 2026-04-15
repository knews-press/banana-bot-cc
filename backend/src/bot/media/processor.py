"""Media processor: handles all Telegram file types and routes to Claude."""

import asyncio
import csv
import io
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiofiles
import structlog

logger = structlog.get_logger()


@dataclass
class MediaResult:
    """Result of processing a media file."""

    upload_id: str
    media_type: str
    original_filename: str | None
    mime_type: str | None
    file_size: int
    storage_path: str | None

    # Extracted content
    content_text: str = ""          # Main text for ES indexing
    transcript: str | None = None   # Audio/video transcript
    vision_summary: str | None = None  # Claude Vision analysis for images/video

    # For tabular data
    table_rows: list[dict] = field(default_factory=list)
    table_headers: list[str] = field(default_factory=list)

    # For voice messages (bypass storage, treat as text prompt)
    is_voice: bool = False
    voice_text: str = ""

    # Human-readable summary for Telegram reply
    summary: str = ""


# ──────────────────────────────────────────────────
# Whisper (OpenAI API)
# ──────────────────────────────────────────────────

async def _transcribe_audio(audio_path: str, openai_api_key: str) -> str:
    """Transcribe audio file via OpenAI Whisper API."""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=openai_api_key)
        async with aiofiles.open(audio_path, "rb") as f:
            audio_bytes = await f.read()
        # Whisper accepts mp3, mp4, mpeg, mpga, m4a, wav, webm
        filename = Path(audio_path).name
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, audio_bytes, "audio/mpeg"),
            response_format="text",
        )
        return str(response).strip()
    except Exception as e:
        logger.error("Whisper transcription failed", error=str(e))
        return ""


# ──────────────────────────────────────────────────
# Video processing
# ──────────────────────────────────────────────────

def _extract_audio_from_video(video_path: str, output_dir: str) -> str | None:
    """Extract audio track from video file as mp3."""
    audio_path = os.path.join(output_dir, "audio.mp3")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.warning("ffmpeg audio extraction failed", stderr=result.stderr[:500])
        return None
    return audio_path


def _extract_video_frames(video_path: str, output_dir: str, segment_seconds: int = 5) -> list[str]:
    """Extract one representative frame per N-second segment."""
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    # Extract 1 frame per segment_seconds seconds, output as JPEG
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{segment_seconds},scale=640:-2",
        "-q:v", "3",
        os.path.join(frames_dir, "frame_%04d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.warning("ffmpeg frame extraction failed", stderr=result.stderr[:500])
        return []
    frames = sorted(Path(frames_dir).glob("frame_*.jpg"))
    return [str(f) for f in frames]


async def _analyze_frames_with_claude(
    frames: list[str],
    segment_seconds: int = 5,
) -> str:
    """Send frame sequence to Claude Vision for analysis.

    Uses anthropic.AsyncAnthropic() which automatically reads ANTHROPIC_API_KEY
    from the environment — the same key Claude Code CLI already uses.
    """
    if not frames:
        return ""
    try:
        import anthropic

        # Reads ANTHROPIC_API_KEY from env automatically
        client = anthropic.AsyncAnthropic()

        # Build content: text instruction + alternating frame labels + images
        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"The following is a sequence of frames extracted from a video, "
                    f"one frame every {segment_seconds} seconds. "
                    "Please describe what is happening in the video, noting any key actions, "
                    "people, objects, text, or scene changes you observe."
                ),
            }
        ]
        # Limit to 20 frames to stay within API limits
        for i, frame_path in enumerate(frames[:20]):
            async with aiofiles.open(frame_path, "rb") as f:
                img_bytes = await f.read()
            b64 = base64.standard_b64encode(img_bytes).decode()
            content.append({"type": "text", "text": f"Frame {i + 1} (at {i * segment_seconds}s):"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })

        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text if response.content else ""
    except Exception as e:
        logger.error("Frame analysis failed", error=str(e))
        return ""


async def process_video(
    local_path: str,
    upload_id: str,
    openai_api_key: str,
) -> tuple[str | None, str | None]:
    """Process video: extract audio → Whisper + extract frames → Claude Vision.

    Returns (transcript, vision_summary).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Run audio extraction + frame extraction in parallel
        loop = asyncio.get_event_loop()

        audio_path = await loop.run_in_executor(
            None, _extract_audio_from_video, local_path, tmpdir
        )
        frames = await loop.run_in_executor(
            None, _extract_video_frames, local_path, tmpdir
        )

        async def _noop() -> str:
            return ""

        # Transcribe audio + analyze frames in parallel
        tasks = []
        if audio_path and openai_api_key:
            tasks.append(_transcribe_audio(audio_path, openai_api_key))
        else:
            tasks.append(_noop())

        if frames:
            tasks.append(_analyze_frames_with_claude(frames))
        else:
            tasks.append(_noop())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        transcript = results[0] if isinstance(results[0], str) else ""
        vision_summary = results[1] if isinstance(results[1], str) else ""

    return transcript or None, vision_summary or None


# ──────────────────────────────────────────────────
# PDF processing
# ──────────────────────────────────────────────────

async def process_pdf(local_path: str) -> str:
    """Extract text from PDF using pdfplumber."""
    try:
        import pdfplumber
        loop = asyncio.get_event_loop()

        def _extract():
            text_parts = []
            with pdfplumber.open(local_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n\n".join(text_parts)

        return await loop.run_in_executor(None, _extract)
    except Exception as e:
        logger.error("PDF extraction failed", error=str(e))
        return ""


# ──────────────────────────────────────────────────
# DOCX processing
# ──────────────────────────────────────────────────

async def process_docx(local_path: str) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        import docx
        loop = asyncio.get_event_loop()

        def _extract():
            doc = docx.Document(local_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

        return await loop.run_in_executor(None, _extract)
    except Exception as e:
        logger.error("DOCX extraction failed", error=str(e))
        return ""


# ──────────────────────────────────────────────────
# XLSX processing
# ──────────────────────────────────────────────────

async def process_xlsx(local_path: str) -> tuple[list[str], list[dict], str]:
    """Extract rows from XLSX. Returns (headers, rows, text_preview)."""
    try:
        import openpyxl
        loop = asyncio.get_event_loop()

        def _extract():
            wb = openpyxl.load_workbook(local_path, data_only=True)
            ws = wb.active
            rows_iter = list(ws.iter_rows(values_only=True))
            if not rows_iter:
                return [], [], ""
            headers = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(rows_iter[0])]
            data_rows = []
            for row in rows_iter[1:]:
                row_dict = {}
                for h, v in zip(headers, row):
                    row_dict[h] = v
                data_rows.append(row_dict)
            # Text preview: first 20 rows as TSV
            preview_lines = ["\t".join(headers)]
            for r in data_rows[:20]:
                preview_lines.append("\t".join(str(v) if v is not None else "" for v in r.values()))
            return headers, data_rows, "\n".join(preview_lines)

        return await loop.run_in_executor(None, _extract)
    except Exception as e:
        logger.error("XLSX extraction failed", error=str(e))
        return [], [], ""


# ──────────────────────────────────────────────────
# CSV processing
# ──────────────────────────────────────────────────

async def process_csv(local_path: str) -> tuple[list[str], list[dict], str]:
    """Parse CSV. Returns (headers, rows, text_preview)."""
    try:
        async with aiofiles.open(local_path, "r", encoding="utf-8", errors="replace") as f:
            content = await f.read()

        reader = csv.DictReader(io.StringIO(content))
        headers = reader.fieldnames or []
        rows = list(reader)

        preview_lines = [",".join(str(h) for h in headers)]
        for r in rows[:20]:
            preview_lines.append(",".join(str(v) for v in r.values()))
        return list(headers), rows, "\n".join(preview_lines)
    except Exception as e:
        logger.error("CSV extraction failed", error=str(e))
        return [], [], ""


# ──────────────────────────────────────────────────
# Plain text / code / JSON / YAML
# ──────────────────────────────────────────────────

async def process_text_file(local_path: str) -> str:
    """Read plain text file (text, code, JSON, YAML, MD, etc.)."""
    try:
        async with aiofiles.open(local_path, "r", encoding="utf-8", errors="replace") as f:
            return await f.read()
    except Exception as e:
        logger.error("Text file read failed", error=str(e))
        return ""


# ──────────────────────────────────────────────────
# Main processor class
# ──────────────────────────────────────────────────

TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".env",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go",
    ".rs", ".cpp", ".c", ".h", ".cs", ".rb", ".php",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".html", ".htm", ".css", ".scss", ".sql",
    ".xml", ".svg",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac", ".opus"}


class MediaProcessor:
    """Routes Telegram media to the appropriate processor."""

    def __init__(self, uploads_dir: str, openai_api_key: str = ""):
        self.uploads_dir = uploads_dir
        self.openai_api_key = openai_api_key

    def _classify(self, filename: str | None, mime_type: str | None) -> str:
        """Return media_type string for a file."""
        ext = Path(filename).suffix.lower() if filename else ""

        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in VIDEO_EXTENSIONS:
            return "video"
        if ext in AUDIO_EXTENSIONS:
            return "audio"
        if ext == ".pdf":
            return "pdf"
        if ext == ".docx":
            return "docx"
        if ext == ".xlsx":
            return "xlsx"
        if ext == ".csv":
            return "csv"
        if ext in TEXT_EXTENSIONS:
            return "text"

        # Fall back to MIME type
        if mime_type:
            m = mime_type.lower()
            if m.startswith("image/"):
                return "image"
            if m.startswith("video/"):
                return "video"
            if m.startswith("audio/"):
                return "audio"
            if m == "application/pdf":
                return "pdf"
            if "word" in m or "docx" in m:
                return "docx"
            if "excel" in m or "spreadsheet" in m or "xlsx" in m:
                return "xlsx"
            if m == "text/csv":
                return "csv"
            if m.startswith("text/"):
                return "text"
            if "json" in m or "yaml" in m:
                return "text"

        return "binary"

    async def process_voice(self, local_path: str, upload_id: str) -> MediaResult:
        """Voice message: transcribe only, treat as text prompt."""
        transcript = ""
        if self.openai_api_key:
            transcript = await _transcribe_audio(local_path, self.openai_api_key)

        return MediaResult(
            upload_id=upload_id,
            media_type="voice",
            original_filename=None,
            mime_type="audio/ogg",
            file_size=os.path.getsize(local_path),
            storage_path=None,  # Voice messages not persisted
            is_voice=True,
            voice_text=transcript,
            summary=f"🎤 Sprachnachricht transkribiert ({len(transcript)} Zeichen)",
        )

    async def process_file(
        self,
        local_path: str,
        upload_id: str,
        original_filename: str | None,
        mime_type: str | None,
        caption: str | None = None,
    ) -> MediaResult:
        """Process any non-voice file."""
        media_type = self._classify(original_filename, mime_type)
        file_size = os.path.getsize(local_path)

        result = MediaResult(
            upload_id=upload_id,
            media_type=media_type,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            storage_path=local_path,
        )

        if media_type == "image":
            # No in-process Vision processing needed — Claude Code reads images
            # natively via the Read tool using the local storage path.
            result.content_text = caption or f"Image: {original_filename}"
            result.summary = f"🖼 Bild empfangen ({file_size // 1024} KB)"

        elif media_type == "video":
            result.summary = f"🎬 Video wird verarbeitet ({file_size // (1024 * 1024)} MB)..."
            transcript, vision_summary = await process_video(
                local_path, upload_id, self.openai_api_key
            )
            result.transcript = transcript
            result.vision_summary = vision_summary
            parts = []
            if transcript:
                parts.append(f"Transcript:\n{transcript}")
            if vision_summary:
                parts.append(f"Visual description:\n{vision_summary}")
            result.content_text = "\n\n".join(parts) or (caption or f"Video: {original_filename}")
            result.summary = (
                f"🎬 Video analysiert — "
                f"{'Transkript ✓' if transcript else 'kein Audio'}, "
                f"{'Vision ✓' if vision_summary else 'keine Frames'}"
            )

        elif media_type == "audio":
            transcript = ""
            if self.openai_api_key:
                transcript = await _transcribe_audio(local_path, self.openai_api_key)
            result.transcript = transcript or None
            result.content_text = transcript or (caption or f"Audio: {original_filename}")
            result.summary = f"🎵 Audio transkribiert ({len(transcript)} Zeichen)"

        elif media_type == "pdf":
            text = await process_pdf(local_path)
            result.content_text = text
            result.summary = f"📄 PDF extrahiert ({len(text)} Zeichen)"

        elif media_type == "docx":
            text = await process_docx(local_path)
            result.content_text = text
            result.summary = f"📝 DOCX extrahiert ({len(text)} Zeichen)"

        elif media_type == "xlsx":
            headers, rows, preview = await process_xlsx(local_path)
            result.table_headers = headers
            result.table_rows = rows
            result.content_text = preview
            result.summary = f"📊 XLSX: {len(rows)} Zeilen, {len(headers)} Spalten"

        elif media_type == "csv":
            headers, rows, preview = await process_csv(local_path)
            result.table_headers = headers
            result.table_rows = rows
            result.content_text = preview
            result.summary = f"📊 CSV: {len(rows)} Zeilen, {len(headers)} Spalten"

        elif media_type == "text":
            text = await process_text_file(local_path)
            result.content_text = text
            result.summary = f"📃 Datei gelesen ({len(text)} Zeichen): {original_filename}"

        else:
            result.content_text = caption or f"Binary file: {original_filename}"
            result.summary = f"📎 Datei empfangen: {original_filename} ({file_size // 1024} KB)"

        return result

    def build_prompt_from_result(
        self, result: MediaResult, user_caption: str | None = None
    ) -> str:
        """Build a plain-text prompt for Claude from a processed media result.

        Images are passed as a file path — Claude Code's Read tool handles
        JPG/PNG natively as Vision input. All other types embed their
        extracted content directly in the prompt string.
        """
        caption_part = ""
        if user_caption:
            caption_part = f"\n\nUser caption: {user_caption}"

        if result.media_type == "image" and result.storage_path:
            # Claude Code's Read tool handles images natively (PNG/JPG → Vision).
            # Pass the local file path so Claude can read it directly.
            text = (
                f"Ich habe dir ein Bild gesendet.{caption_part}\n"
                f"Bitte lies und analysiere es: {result.storage_path}"
            )
            return text

        elif result.media_type == "video":
            parts = [f"Ich habe dir ein Video gesendet: {result.original_filename}"]
            if result.transcript:
                parts.append(f"\n**Transkript (Audio):**\n{result.transcript}")
            if result.vision_summary:
                parts.append(f"\n**Visuelle Analyse:**\n{result.vision_summary}")
            if not result.transcript and not result.vision_summary:
                parts.append("(Keine Audio/Video-Analyse verfügbar)")
            if caption_part:
                parts.append(caption_part)
            parts.append(f"\nUpload-ID: {result.upload_id}")
            return "\n".join(parts)

        elif result.media_type in ("audio",):
            text = f"Ich habe dir eine Audiodatei gesendet: {result.original_filename}"
            if result.transcript:
                text += f"\n\n**Transkript:**\n{result.transcript}"
            text += caption_part
            text += f"\nUpload-ID: {result.upload_id}"
            return text

        elif result.media_type in ("pdf", "docx", "text"):
            max_chars = 8000
            content_preview = result.content_text[:max_chars]
            if len(result.content_text) > max_chars:
                content_preview += f"\n\n... (truncated, {len(result.content_text)} total chars)"
            text = (
                f"Ich habe dir ein Dokument gesendet: **{result.original_filename}**"
                f"{caption_part}\n\n"
                f"**Inhalt:**\n{content_preview}\n\n"
                f"Upload-ID: {result.upload_id}"
            )
            return text

        elif result.media_type in ("xlsx", "csv"):
            preview = result.content_text[:3000]
            text = (
                f"Ich habe dir eine Tabelle gesendet: **{result.original_filename}**"
                f"{caption_part}\n\n"
                f"**{len(result.table_rows)} Zeilen, {len(result.table_headers)} Spalten.**\n"
                f"Spalten: {', '.join(result.table_headers[:20])}\n\n"
                f"**Vorschau (erste 20 Zeilen):**\n```\n{preview}\n```\n\n"
                f"Alle Zeilen sind in MySQL gespeichert (upload_id: {result.upload_id}) "
                f"und können mit dem `query_table` MCP-Tool abgefragt werden."
            )
            return text

        else:
            return (
                f"Ich habe dir eine Datei gesendet: {result.original_filename} "
                f"({result.media_type}, {result.file_size // 1024} KB){caption_part}\n"
                f"Upload-ID: {result.upload_id}"
            )
