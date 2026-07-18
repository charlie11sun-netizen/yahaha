from __future__ import annotations

"""Prompt-cache key and explicit cache-input construction."""

import hashlib
import re
import uuid

from app.core.config import settings
from app.core.telemetry import get_context


def prompt_cache_key(namespace: str, *, task_scoped: bool = True) -> str | None:
    """Return a stable routing key accepted by the Responses API."""
    prefix = str(settings.CODE_AGENT_PROMPT_CACHE_KEY_PREFIX or "").strip().rstrip(":")
    if not prefix:
        return None
    namespace = str(namespace or "default").strip() or "default"
    if not task_scoped:
        raw = f"{prefix}:{namespace}"
        if len(raw) <= 64:
            return raw
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        namespace_budget = max(1, 64 - len(prefix[:32]) - len(digest) - 2)
        return f"{prefix[:32]}:{namespace[:namespace_budget]}:{digest}"
    task_scope = str(get_context().get("task_id") or "").replace("-", "")[:12]
    scope = task_scope or uuid.uuid4().hex[:12]
    raw = f"{prefix}:{namespace}:{scope}"
    if len(raw) <= 64:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    prefix_part = prefix[:16]
    fixed = len(prefix_part) + len(scope) + len(digest) + 3
    namespace_budget = max(1, 64 - fixed)
    return f"{prefix_part}:{namespace[:namespace_budget]}:{scope}:{digest}"


def supports_explicit_prompt_cache(model: str) -> bool:
    match = re.search(r"gpt-(\d+)(?:\.(\d+))?", str(model or "").lower())
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2) or 0)) >= (5, 6)


def explicit_cache_input(system: str, input_text: str, cache_prefix: str) -> list[dict]:
    if not cache_prefix:
        raise ValueError("cache_prefix must not be empty")
    if not system.startswith(cache_prefix):
        raise ValueError("system prompt must begin with the exact cache_prefix")
    node_instructions = system[len(cache_prefix) :].lstrip()
    if not node_instructions:
        raise ValueError("node-specific instructions must follow cache_prefix")
    return [
        {
            "type": "message",
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": cache_prefix,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            ],
        },
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": node_instructions}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": input_text}],
        },
    ]
