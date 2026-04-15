"""Generate text embeddings via OpenAI API."""

import tiktoken
from openai import AsyncOpenAI

MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
MAX_TOKENS = 8191
ENCODING = tiktoken.get_encoding("cl100k_base")


def truncate_to_token_limit(text: str, max_tokens: int = MAX_TOKENS) -> str:
    """Truncate text to fit within the model's token limit."""
    tokens = ENCODING.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return ENCODING.decode(tokens[:max_tokens])


async def get_embedding(text: str, api_key: str) -> list[float]:
    """Generate embedding for a single text.

    Long texts are truncated to the model's token limit (8191).
    Returns a 1536-dimensional vector (cosine similarity).
    """
    text = truncate_to_token_limit(text.strip())
    if not text:
        return [0.0] * DIMENSIONS

    client = AsyncOpenAI(api_key=api_key)
    response = await client.embeddings.create(
        model=MODEL,
        input=text,
    )
    return response.data[0].embedding


async def get_embeddings(texts: list[str], api_key: str) -> list[list[float]]:
    """Generate embeddings for multiple texts in a single API call.

    Each text is independently truncated to the token limit.
    Returns list of 1536-dimensional vectors in the same order as input.
    """
    truncated = [truncate_to_token_limit(t.strip()) for t in texts]
    # Replace empty strings with a space to avoid API errors
    sanitized = [t if t else " " for t in truncated]

    client = AsyncOpenAI(api_key=api_key)
    response = await client.embeddings.create(
        model=MODEL,
        input=sanitized,
    )
    # API returns embeddings sorted by index
    sorted_data = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]
