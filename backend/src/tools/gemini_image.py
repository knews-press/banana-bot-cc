"""Gemini Image Generation — Google Generative AI API.

Supports two endpoint families:

  Gemini native (generateContent):
    • gemini-2.5-flash-image       aka Nano Banana
    • gemini-3.1-flash-image-preview  aka Nano Banana 2
    • gemini-3-pro-image-preview   aka Nano Banana Pro

  Imagen 4 (predict):
    • imagen-4.0-fast-generate-001
    • imagen-4.0-generate-001
    • imagen-4.0-ultra-generate-001
"""

import base64
import json
import urllib.error
import urllib.request

import structlog

logger = structlog.get_logger()

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# ── Model catalogue ──────────────────────────────────────────────────────────

GEMINI_MODELS = {
    "gemini-2.5-flash-image":           "Nano Banana — fast, cost-efficient, free tier",
    "gemini-3.1-flash-image-preview":   "Nano Banana 2 — improved quality, up to 4K",
    "gemini-3-pro-image-preview":       "Nano Banana Pro — highest quality Gemini model",
}

IMAGEN_MODELS = {
    "imagen-4.0-fast-generate-001":     "Imagen 4 Fast — cheapest ($0.02), no free tier",
    "imagen-4.0-generate-001":          "Imagen 4 Standard — balanced quality ($0.04)",
    "imagen-4.0-ultra-generate-001":    "Imagen 4 Ultra — best photorealism ($0.06)",
}

ALL_MODELS = {**GEMINI_MODELS, **IMAGEN_MODELS}

DEFAULT_MODEL = "gemini-2.5-flash-image"

# Aspect ratios supported by Imagen 4
IMAGEN_ASPECT_RATIOS = ["1:1", "9:16", "16:9", "4:3", "3:4"]


def generate_image(
    api_key: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    aspect_ratio: str = "1:1",
    style_prompt: str | None = None,
) -> bytes:
    """Generate an image using a Gemini or Imagen 4 model.

    Args:
        api_key:       Google Gemini API key.
        prompt:        Text description of the desired image.
        model:         Model ID. See ALL_MODELS for valid values.
        aspect_ratio:  For Imagen 4 models: one of IMAGEN_ASPECT_RATIOS.
                       Ignored for Gemini native models (always square).
        style_prompt:  Optional style prefix appended to the prompt.

    Returns:
        Raw PNG image bytes.
    """
    if model not in ALL_MODELS:
        logger.warning("unknown_gemini_image_model", model=model, fallback=DEFAULT_MODEL)
        model = DEFAULT_MODEL

    full_prompt = f"{style_prompt}. {prompt}" if style_prompt else prompt

    if model in IMAGEN_MODELS:
        return _generate_imagen(api_key, full_prompt, model, aspect_ratio)
    else:
        return _generate_gemini(api_key, full_prompt, model)


def _generate_gemini(api_key: str, prompt: str, model: str) -> bytes:
    """Generate via the Gemini generateContent endpoint."""
    url = f"{_BASE_URL}/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }

    data = _post_json(url, payload)

    try:
        parts = data["candidates"][0]["content"]["parts"]
        for part in parts:
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])
        raise RuntimeError("No image data in Gemini response")
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Gemini response format: {exc}") from exc


def _generate_imagen(api_key: str, prompt: str, model: str, aspect_ratio: str) -> bytes:
    """Generate via the Imagen 4 predict endpoint."""
    if aspect_ratio not in IMAGEN_ASPECT_RATIOS:
        logger.warning("invalid_aspect_ratio", aspect_ratio=aspect_ratio, fallback="1:1")
        aspect_ratio = "1:1"

    url = f"{_BASE_URL}/{model}:predict?key={api_key}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
        },
    }

    data = _post_json(url, payload)

    try:
        return base64.b64decode(data["predictions"][0]["bytesBase64Encoded"])
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected Imagen response format: {exc}") from exc


def _post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        response = urllib.request.urlopen(req, timeout=60)
        return json.loads(response.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            msg = err.get("error", {}).get("message", str(e))
        except Exception:
            msg = str(e)
        raise RuntimeError(f"Gemini API error: {msg}") from e
