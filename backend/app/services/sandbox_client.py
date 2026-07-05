from __future__ import annotations

import base64
from dataclasses import dataclass, field

import httpx

from app.core.config import settings


class SandboxUnavailableError(RuntimeError):
    """Raised when the build sandbox is required but cannot be reached."""


@dataclass
class SandboxResult:
    ok: bool
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    console_warnings: list[str] = field(default_factory=list)
    requests_aborted: list[str] = field(default_factory=list)
    frames_observed: int = 0
    intervals_observed: int = 0
    load_ms: int = 0
    timed_out: bool = False
    skipped: bool = False
    detail: str = ""


def _payload(files: list[dict], entry: str, timeout_ms: int, simulate_input: bool) -> dict:
    encoded = []
    for item in files:
        path = str(item.get("path") or "").lstrip("/")
        content = str(item.get("content") or "")
        encoded.append(
            {
                "path": path,
                "content_b64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            }
        )
    return {
        "files": encoded,
        "entry": entry,
        "timeout_ms": timeout_ms,
        "simulate_input": simulate_input,
    }


def _skipped(detail: str) -> SandboxResult:
    return SandboxResult(ok=True, skipped=True, detail=detail)


def _unavailable(detail: str) -> SandboxResult:
    if settings.SANDBOX_REQUIRED:
        raise SandboxUnavailableError(detail)
    return _skipped(detail)


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    detail = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            detail = str(data.get("detail") or "")
    except ValueError:
        detail = response.text.strip()
    suffix = f": {detail[:240]}" if detail else ""
    return f"{response.status_code} {response.reason_phrase}{suffix}"


def _request_timeout_seconds(run_timeout_ms: int) -> float:
    overhead_ms = max(1000, int(settings.SANDBOX_HTTP_TIMEOUT_OVERHEAD_MS))
    return (run_timeout_ms + overhead_ms) / 1000


def run_bundle(
    files: list[dict],
    *,
    entry: str = "index.html",
    timeout_ms: int | None = None,
    simulate_input: bool = True,
) -> SandboxResult:
    url = settings.SANDBOX_URL.strip().rstrip("/")
    if not url:
        return _unavailable("sandbox disabled (SANDBOX_URL is empty)")

    timeout = int(timeout_ms or settings.SANDBOX_TIMEOUT_MS)
    try:
        response = httpx.post(
            f"{url}/run",
            json=_payload(files, entry, timeout, simulate_input),
            timeout=_request_timeout_seconds(timeout),
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        return _unavailable(f"sandbox unavailable: {_http_error_detail(exc)}")
    except (httpx.RequestError, ValueError) as exc:
        return _unavailable(f"sandbox unavailable: {exc}")

    return SandboxResult(
        ok=bool(data.get("ok")),
        page_errors=list(data.get("page_errors") or []),
        console_errors=list(data.get("console_errors") or []),
        console_warnings=list(data.get("console_warnings") or []),
        requests_aborted=list(data.get("requests_aborted") or []),
        frames_observed=int(data.get("frames_observed") or 0),
        intervals_observed=int(data.get("intervals_observed") or 0),
        load_ms=int(data.get("load_ms") or 0),
        timed_out=bool(data.get("timed_out")),
    )
