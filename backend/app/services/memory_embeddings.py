"""Fail-open embedding adapter used by memory hybrid retrieval."""

import logging
import math
import time

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)
_unavailable_until = 0.0
_FAILURE_BACKOFF_SECONDS = 60


def embedding_model() -> str:
    return settings.MEMORY_EMBEDDING_MODEL.strip()


def vector_values(value) -> list[float]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def cosine_similarity(left, right) -> float | None:
    left = vector_values(left)
    right = vector_values(right)
    if not left or not right or len(left) != len(right):
        return None
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return None
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    global _unavailable_until

    clean = [text.strip()[:8000] for text in texts]
    model = embedding_model()
    api_key = settings.MEMORY_EMBEDDING_API_KEY.strip() or settings.OPENAI_API_KEY.strip()
    base_url = settings.MEMORY_EMBEDDING_BASE_URL.strip() or settings.OPENAI_BASE_URL
    if (
        not clean
        or not any(clean)
        or not settings.MEMORY_VECTOR_ENABLED
        or not api_key
        or not model
        or time.monotonic() < _unavailable_until
    ):
        return None

    try:
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=max(1, settings.MEMORY_EMBEDDING_TIMEOUT),
            default_headers={"User-Agent": "GameWeave/1.0"},
        )
        response = client.embeddings.create(model=model, input=clean)
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [[float(value) for value in item.embedding] for item in ordered]
        if len(vectors) != len(clean) or any(not vector for vector in vectors):
            raise ValueError("embedding response count or dimensions are invalid")
        dimensions = max(1, int(settings.MEMORY_VECTOR_DIMENSIONS))
        if any(len(vector) != dimensions for vector in vectors):
            raise ValueError(
                f"embedding dimensions do not match MEMORY_VECTOR_DIMENSIONS={dimensions}"
            )
        _unavailable_until = 0.0
        return vectors
    except Exception as exc:  # noqa: BLE001
        _unavailable_until = time.monotonic() + _FAILURE_BACKOFF_SECONDS
        logger.warning("Memory embedding request failed; using lexical fallback: %s", exc)
        return None
