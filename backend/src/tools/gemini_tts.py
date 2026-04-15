"""Gemini TTS — text-to-speech via Google Gemini 2.5 Flash."""

import base64
import json
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import structlog

logger = structlog.get_logger()

_MODEL = "gemini-2.5-flash-preview-tts"
_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{_MODEL}:generateContent"
)


def generate_tts(
    api_key: str,
    text: str,
    voice: str = "Puck",
    style_prompt: str | None = None,
    output_format: str = "oga",
) -> bytes:
    """Generate speech audio from text using Gemini TTS.

    Args:
        api_key: Google Gemini API key.
        text: Text to synthesise (German or English).
        voice: One of Aoede, Kore, Puck, Charon, Fenrir. Default: Puck.
        style_prompt: Optional natural-language style instruction,
            e.g. "speak slowly and seriously".
        output_format: oga (default), wav, or mp3.

    Returns:
        Audio bytes in the requested format.
    """
    prompt = f"{style_prompt}: {text}" if style_prompt else text

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice}
                }
            },
        },
    }

    url = f"{_API_URL}?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(req, timeout=30)
        result = json.loads(response.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read().decode())
        raise RuntimeError(
            f"Gemini API error: {err.get('error', {}).get('message', str(e))}"
        )

    try:
        audio_data = result["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm_bytes = base64.b64decode(audio_data["data"])
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Gemini response format: {exc}") from exc

    return _convert_audio(pcm_bytes, output_format)


def _convert_audio(pcm_bytes: bytes, output_format: str) -> bytes:
    """Convert raw PCM L16/24 kHz to the requested container format via ffmpeg."""
    format_map = {
        "oga": ("libopus", "48k", ".oga"),
        "wav": ("pcm_s16le", None, ".wav"),
        "mp3": ("libmp3lame", "128k", ".mp3"),
    }
    if output_format not in format_map:
        raise ValueError(f"Unsupported format: {output_format}")

    codec, bitrate, ext = format_map[output_format]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pcm") as pcm_f:
        pcm_f.write(pcm_bytes)
        pcm_path = pcm_f.name

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as out_f:
        out_path = out_f.name

    try:
        cmd = [
            "ffmpeg",
            "-f", "s16le", "-ar", "24000", "-ac", "1",
            "-i", pcm_path,
            "-c:a", codec,
        ]
        if bitrate:
            cmd += ["-b:a", bitrate]
        cmd += [out_path, "-y", "-loglevel", "error"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg error: {result.stderr}")

        return Path(out_path).read_bytes()
    finally:
        Path(pcm_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)
