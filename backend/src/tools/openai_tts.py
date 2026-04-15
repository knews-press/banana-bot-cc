"""OpenAI TTS — text-to-speech via OpenAI API."""

import io
import structlog

logger = structlog.get_logger()

# Only gpt-4o-mini-tts supports style instructions via the `instructions`
# parameter — tts-1 / tts-1-hd do not, so we intentionally omit them.
OPENAI_TTS_MODELS = {
    "gpt-4o-mini-tts": [
        "alloy", "ash", "ballad", "coral", "echo",
        "fable", "nova", "onyx", "sage", "shimmer", "verse",
    ],
}

DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "nova"
INSTRUCTIONS_SUPPORTED_MODELS = set(OPENAI_TTS_MODELS.keys())

# Format mapping: desired format → (response_format for API, mime hint)
FORMAT_MAP = {
    "oga": "opus",   # OpenAI outputs opus in ogg container; rename to .oga
    "mp3": "mp3",
    "wav": "wav",
    "flac": "flac",
    "aac": "aac",
}


def generate_tts(
    api_key: str,
    text: str,
    voice: str = DEFAULT_VOICE,
    style_prompt: str | None = None,
    model: str = DEFAULT_MODEL,
    output_format: str = "oga",
) -> bytes:
    """Generate speech audio from text using OpenAI TTS.

    Args:
        api_key: OpenAI API key.
        text: Text to synthesise.
        voice: Voice name. See OPENAI_TTS_MODELS for available voices per model.
        style_prompt: Natural-language style instruction (only effective with
            gpt-4o-mini-tts; silently ignored for other models).
        model: TTS model. Currently only gpt-4o-mini-tts is supported
            (the only OpenAI model with style/instructions support).
        output_format: oga (default), mp3, wav, flac, or aac.

    Returns:
        Audio bytes in the requested format.
    """
    from openai import OpenAI

    if output_format not in FORMAT_MAP:
        raise ValueError(
            f"Unsupported format: {output_format}. "
            f"Choose from: {', '.join(FORMAT_MAP)}"
        )

    api_format = FORMAT_MAP[output_format]

    # Validate model
    if model not in OPENAI_TTS_MODELS:
        logger.warning("unknown_openai_tts_model", model=model, fallback=DEFAULT_MODEL)
        model = DEFAULT_MODEL

    # Validate voice for model
    valid_voices = OPENAI_TTS_MODELS[model]
    if voice not in valid_voices:
        fallback_voice = valid_voices[0]
        logger.warning(
            "invalid_voice_for_model",
            voice=voice, model=model, fallback=fallback_voice,
        )
        voice = fallback_voice

    client = OpenAI(api_key=api_key)

    kwargs: dict = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": api_format,
    }

    # instructions only supported on gpt-4o-mini-tts
    if style_prompt and model in INSTRUCTIONS_SUPPORTED_MODELS:
        kwargs["instructions"] = style_prompt
    elif style_prompt and model not in INSTRUCTIONS_SUPPORTED_MODELS:
        logger.debug(
            "style_prompt_ignored_for_model",
            model=model,
            hint="Use gpt-4o-mini-tts for style instructions",
        )

    response = client.audio.speech.create(**kwargs)

    audio_bytes = response.read()

    # OpenAI returns opus in an ogg container — that is exactly .oga, no conversion needed
    return audio_bytes
