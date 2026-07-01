"""Fail-open embedding adapter used by memory hybrid retrieval."""

import logging
import time

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)
_unavailable_until = 0.0
_FAILURE_BACKOFF_SECONDS = 60


def embedding_model() -> str:
    return settings.MEMORY_EMBEDDING_MODEL.strip()


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
        )
        response = client.embeddings.create(model=model, input=clean)
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [[float(value) for value in item.embedding] for item in ordered]
        if len(vectors) != len(clean) or any(not vector for vector in vectors):
            raise ValueError("embedding response count or dimensions are invalid")
        _unavailable_until = 0.0
        return vectors
    except Exception as exc:  # noqa: BLE001
        _unavailable_until = time.monotonic() + _FAILURE_BACKOFF_SECONDS
        logger.warning("Memory embedding request failed; using lexical fallback: %s", exc)
        return None
