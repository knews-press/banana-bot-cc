"""OpenAI Image Generation — via OpenAI Python SDK.

Supported models:
  • gpt-image-1.5    — current flagship, best instruction following & editing
  • gpt-image-1      — previous generation
  • gpt-image-1-mini — budget option, good for high-volume
  • dall-e-3         — legacy, deprecated May 2026; still functional
"""

import base64

import structlog

logger = structlog.get_logger()

# ── Model catalogue ──────────────────────────────────────────────────────────

GPT_IMAGE_MODELS = {
    "gpt-image-1.5":    "Current flagship — best quality & instruction following",
    "gpt-image-1":      "Previous generation",
    "gpt-image-1-mini": "Budget model — cost-efficient for high volume",
}

DALLE_MODELS = {
    "dall-e-3": "Legacy DALL-E 3 (deprecated May 2026)",
}

ALL_MODELS = {**GPT_IMAGE_MODELS, **DALLE_MODELS}

DEFAULT_MODEL = "gpt-image-1.5"

# ── Size constraints per model family ────────────────────────────────────────

GPT_IMAGE_SIZES = ["1024x1024", "1536x1024", "1024x1536", "auto"]
DALLE3_SIZES    = ["1024x1024", "1792x1024", "1024x1792"]

# Quality options differ between families
GPT_IMAGE_QUALITIES  = ["low", "medium", "high", "auto"]
DALLE3_QUALITIES     = ["standard", "hd"]


def generate_image(
    api_key: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    size: str = "1024x1024",
    quality: str = "medium",
    style_prompt: str | None = None,
) -> bytes:
    """Generate an image using an OpenAI model.

    Args:
        api_key:       OpenAI API key.
        prompt:        Text description of the desired image.
        model:         One of ALL_MODELS. Default: gpt-image-1.5.
        size:          Resolution string. GPT: 1024x1024 / 1536x1024 / 1024x1536 / auto.
                       DALL-E 3: 1024x1024 / 1792x1024 / 1024x1792.
        quality:       GPT models: low / medium / high / auto.
                       DALL-E 3: standard / hd.
        style_prompt:  Optional prefix prepended to the prompt.

    Returns:
        Raw PNG image bytes.
    """
    from openai import OpenAI

    if model not in ALL_MODELS:
        logger.warning("unknown_openai_image_model", model=model, fallback=DEFAULT_MODEL)
        model = DEFAULT_MODEL

    full_prompt = f"{style_prompt}. {prompt}" if style_prompt else prompt
    is_dalle3   = model in DALLE_MODELS

    # Normalise size
    valid_sizes = DALLE3_SIZES if is_dalle3 else GPT_IMAGE_SIZES
    if size not in valid_sizes:
        fallback = valid_sizes[0]
        logger.warning("invalid_image_size", size=size, model=model, fallback=fallback)
        size = fallback

    # Normalise quality
    valid_qualities = DALLE3_QUALITIES if is_dalle3 else GPT_IMAGE_QUALITIES
    if quality not in valid_qualities:
        fallback_q = valid_qualities[1] if len(valid_qualities) > 1 else valid_qualities[0]
        logger.warning("invalid_image_quality", quality=quality, model=model, fallback=fallback_q)
        quality = fallback_q

    client = OpenAI(api_key=api_key)

    response = client.images.generate(
        model=model,
        prompt=full_prompt,
        size=size,          # type: ignore[arg-type]
        quality=quality,    # type: ignore[arg-type]
        n=1,
        response_format="b64_json",
    )

    b64_data = response.data[0].b64_json
    if not b64_data:
        raise RuntimeError("OpenAI returned no image data")

    return base64.b64decode(b64_data)
