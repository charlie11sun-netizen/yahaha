from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.services.artifacts import artifact_bytes

# A transiently unreachable sandbox (restart, cold browser launch, host load
# spike) must not kill a multi-minute generation at its final gate. Retry the
# whole run request a bounded number of times before declaring unavailability.
_RUN_CONNECT_RETRIES = 2
_RUN_RETRY_DELAY_SECONDS = 8.0


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
    screenshot_b64: str | None = None
    input_attempted: bool = False
    inputs_sent: list[str] = field(default_factory=list)
    start_attempts: list[str] = field(default_factory=list)
    input_errors: list[str] = field(default_factory=list)
    visual_probe: str = ""
    visual_before_sha256: str | None = None
    visual_after_sha256: str | None = None
    visual_changed: bool | None = None
    visual_change_ratio: float | None = None
    visual_probe_error: str = ""
    # Runtime behavior counters reported by the game scaffold's Probe system,
    # e.g. {"probe:ready": 1, "scene:start|PlayScene": 1, "anims:play|run": 40}.
    probes: dict[str, int] = field(default_factory=dict)
    # Probe counters sampled at the start of the runner's quiet observation
    # tail (after load + input settle). delta(probes - probes_start) over
    # delta(frames_observed - frames_start) exposes per-frame UI rebuild churn.
    probes_start: dict[str, int] = field(default_factory=dict)
    frames_start: int = 0


@dataclass
class ViteBuildResult:
    ok: bool
    files: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    duration_ms: int = 0
    timed_out: bool = False
    skipped: bool = False
    detail: str = ""


def _payload(
    files: list[dict],
    entry: str,
    timeout_ms: int,
    simulate_input: bool,
    screenshot_always: bool = False,
) -> dict:
    encoded = []
    for item in files:
        path = str(item.get("path") or "").lstrip("/")
        encoded.append(
            {
                "path": path,
                "content_b64": base64.b64encode(artifact_bytes(item)).decode("ascii"),
                "content_type": item.get("content_type"),
            }
        )
    return {
        "files": encoded,
        "entry": entry,
        "timeout_ms": timeout_ms,
        "simulate_input": simulate_input,
        "screenshot_always": screenshot_always,
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
    screenshot_always: bool = False,
) -> SandboxResult:
    url = settings.SANDBOX_URL.strip().rstrip("/")
    if not url:
        return _unavailable("sandbox disabled (SANDBOX_URL is empty)")

    timeout = int(timeout_ms or settings.SANDBOX_TIMEOUT_MS)
    payload = _payload(files, entry, timeout, simulate_input, screenshot_always)
    data = None
    last_error: str | None = None
    for attempt in range(_RUN_CONNECT_RETRIES + 1):
        if attempt:
            time.sleep(_RUN_RETRY_DELAY_SECONDS * attempt)
        try:
            response = httpx.post(
                f"{url}/run",
                json=payload,
                timeout=_request_timeout_seconds(timeout),
            )
            response.raise_for_status()
            data = response.json()
            break
        except httpx.HTTPStatusError as exc:
            last_error = f"sandbox unavailable: {_http_error_detail(exc)}"
            if exc.response.status_code < 500:
                break
        except (httpx.RequestError, ValueError) as exc:
            last_error = f"sandbox unavailable: {exc}"
    if data is None:
        return _unavailable(last_error or "sandbox unavailable")

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
        screenshot_b64=data.get("screenshot_b64"),
        input_attempted=bool(data.get("input_attempted")),
        inputs_sent=[str(item) for item in (data.get("inputs_sent") or [])],
        start_attempts=[str(item) for item in (data.get("start_attempts") or [])],
        input_errors=[str(item) for item in (data.get("input_errors") or [])],
        visual_probe=str(data.get("visual_probe") or ""),
        visual_before_sha256=data.get("visual_before_sha256"),
        visual_after_sha256=data.get("visual_after_sha256"),
        visual_changed=data.get("visual_changed"),
        visual_change_ratio=(
            float(data["visual_change_ratio"])
            if data.get("visual_change_ratio") is not None
            else None
        ),
        visual_probe_error=str(data.get("visual_probe_error") or ""),
        probes=_parse_probes(data.get("probes")),
        probes_start=_parse_probes(data.get("probes_start")),
        frames_start=int(data.get("frames_start") or 0),
    )


def _parse_probes(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    probes: dict[str, int] = {}
    for key, value in list(raw.items())[:300]:
        try:
            probes[str(key)[:120]] = int(value)
        except (TypeError, ValueError):
            continue
    return probes


@dataclass
class WinSimulationResult:
    verdict: str = "skipped"  # won | lost | timeout | error | skipped
    ok: bool = False
    skipped: bool = False
    detail: str = ""
    pump_mode: str = ""
    sim_seconds: float = 0.0
    wall_ms: int = 0
    actions_sent: list[str] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)
    probes: dict[str, int] = field(default_factory=dict)
    missing_stats: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)


def simulate_win(
    files: list[dict],
    script: dict,
    *,
    entry: str = "index.html",
    timeout_ms: int | None = None,
) -> WinSimulationResult:
    """Replay the authored WinScript deterministically in the sandbox.

    Soft dependency by design: the win-path check is warning-level evidence, so
    any infrastructure unavailability degrades to ``skipped`` instead of raising
    ``SandboxUnavailableError`` — a task must never fail because the simulator
    could not run.
    """
    url = settings.SANDBOX_URL.strip().rstrip("/")
    if not url:
        return WinSimulationResult(skipped=True, detail="sandbox disabled (SANDBOX_URL is empty)")
    timeout = int(timeout_ms or settings.WIN_SIMULATION_TIMEOUT_MS)
    encoded = _payload(files, entry, timeout, False)
    try:
        response = httpx.post(
            f"{url}/simulate",
            json={
                "files": encoded["files"],
                "entry": entry,
                "script": script,
                "timeout_ms": timeout,
            },
            timeout=_request_timeout_seconds(timeout + 20_000),
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        return WinSimulationResult(
            skipped=True, detail=f"win simulation unavailable: {_http_error_detail(exc)}"
        )
    except (httpx.RequestError, ValueError) as exc:
        return WinSimulationResult(skipped=True, detail=f"win simulation unavailable: {exc}")
    return WinSimulationResult(
        verdict=str(data.get("verdict") or "error"),
        ok=bool(data.get("ok")),
        detail=str(data.get("detail") or ""),
        pump_mode=str(data.get("pump_mode") or ""),
        sim_seconds=float(data.get("sim_seconds") or 0),
        wall_ms=int(data.get("wall_ms") or 0),
        actions_sent=[str(item) for item in (data.get("actions_sent") or [])][:200],
        timeline=[item for item in (data.get("timeline") or []) if isinstance(item, dict)][:240],
        stats={
            str(key)[:40]: float(value)
            for key, value in (data.get("stats") or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        },
        probes=_parse_probes(data.get("probes")),
        missing_stats=[str(item)[:40] for item in (data.get("missing_stats") or [])][:20],
        page_errors=[str(item) for item in (data.get("page_errors") or [])][:10],
        console_errors=[str(item) for item in (data.get("console_errors") or [])][:10],
    )


def build_vite_project(files: list[dict], *, timeout_ms: int | None = None) -> ViteBuildResult:
    url = settings.SANDBOX_URL.strip().rstrip("/")
    if not url:
        if settings.SANDBOX_REQUIRED:
            raise SandboxUnavailableError("sandbox disabled (SANDBOX_URL is empty)")
        return ViteBuildResult(ok=False, skipped=True, detail="sandbox disabled (SANDBOX_URL is empty)")

    timeout = int(timeout_ms or settings.VITE_BUILD_TIMEOUT_MS)
    payload = _payload(files, "index.html", timeout, False)
    try:
        response = httpx.post(
            f"{url}/build/vite",
            json={"files": payload["files"], "timeout_ms": timeout},
            timeout=(timeout + max(1000, int(settings.SANDBOX_BUILD_TIMEOUT_OVERHEAD_MS))) / 1000,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        detail = f"vite build sandbox unavailable: {_http_error_detail(exc)}"
        if settings.SANDBOX_REQUIRED:
            raise SandboxUnavailableError(detail) from exc
        return ViteBuildResult(ok=False, skipped=True, detail=detail)
    except (httpx.RequestError, ValueError) as exc:
        detail = f"vite build sandbox unavailable: {exc}"
        if settings.SANDBOX_REQUIRED:
            raise SandboxUnavailableError(detail) from exc
        return ViteBuildResult(ok=False, skipped=True, detail=detail)

    output_files = [
        {
            "path": str(item.get("path") or ""),
            "content_b64": str(item.get("content_b64") or ""),
            "content_type": item.get("content_type"),
        }
        for item in (data.get("files") or [])
    ]
    return ViteBuildResult(
        ok=bool(data.get("ok")),
        files=output_files,
        errors=[str(item) for item in (data.get("errors") or [])],
        warnings=[str(item) for item in (data.get("warnings") or [])],
        logs=[str(item) for item in (data.get("logs") or [])],
        duration_ms=int(data.get("duration_ms") or 0),
        timed_out=bool(data.get("timed_out")),
    )
