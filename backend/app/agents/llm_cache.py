from __future__ import annotations

"""Prompt-cache key and explicit cache-input construction."""

import hashlib
import json
import re
import uuid
from typing import Any
from urllib.parse import urlparse

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


def stable_hash(value: Any) -> str | None:
    """Hash cache-shaping content without persisting prompts, keys, or tool schemas."""
    if value is None:
        return None
    if isinstance(value, str):
        payload = value
    else:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def provider_route(base_url: str | None) -> str | None:
    """Return a non-secret upstream identity suitable for cache-routing analysis."""
    value = str(base_url or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    host = parsed.hostname
    if not host:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    return f"{host}{port}{path}"[:255]


def cache_request_metadata(
    *,
    cache_key: str | None,
    namespace: str | None,
    mode: str,
    ttl: str | None = None,
    cache_prefix: str | None = None,
    tools: Any = None,
    bypass_reason: str | None = None,
    provider: str = "openai",
    base_url: str | None = None,
) -> dict[str, Any]:
    """Build durable, non-sensitive dimensions that explain cache behavior."""
    return {
        "provider": provider,
        "provider_route": provider_route(base_url),
        "prompt_cache_key_hash": stable_hash(cache_key),
        "prompt_cache_namespace": namespace,
        "prompt_cache_mode": mode,
        "prompt_cache_ttl": ttl,
        "cache_prefix_hash": stable_hash(cache_prefix),
        "toolset_hash": stable_hash(tools),
        "cache_bypass_reason": bypass_reason,
    }


def usage_detail_reported(details: Any, field: str) -> bool:
    """Distinguish a reported zero from a provider that omitted the field."""
    if details is None:
        return False
    if isinstance(details, dict):
        return field in details
    fields_set = getattr(details, "model_fields_set", None)
    if fields_set is not None:
        return field in fields_set
    return hasattr(details, field)


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
