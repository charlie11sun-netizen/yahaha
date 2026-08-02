from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from playwright.async_api import Browser, Error as PlaywrightError, Page, async_playwright

# Relative import on purpose: this module is loaded both as `app.main` (uvicorn
# in the sandbox container) and as `sandbox.app.main` (backend test suite), and
# an absolute `app` would resolve to the backend package in the latter.
from . import winscript


ORIGIN_HOST = "bundle.sandbox"
ORIGIN = f"https://{ORIGIN_HOST}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANDBOX_RUNNER_", extra="ignore")

    concurrency: int = 1
    browser_recycle_runs: int = 100
    default_timeout_ms: int = 5000
    screenshot_on_failure: bool = False
    chromium_no_sandbox: bool = False
    max_file_bytes: int = 16_000_000
    max_total_bytes: int = 64_000_000
    max_build_files: int = 120
    vite_runtime_root: str = "/opt/gameweave-vite"


settings = Settings()


class BundleFile(BaseModel):
    path: str = Field(min_length=1, max_length=240)
    content_b64: str = Field(min_length=1)
    content_type: str | None = None


class RunRequest(BaseModel):
    files: list[BundleFile] = Field(min_length=1, max_length=120)
    entry: str = "index.html"
    timeout_ms: int | None = Field(default=None, ge=500, le=30_000)
    simulate_input: bool = False
    # Return the after-input screenshot even on success so the caller can run
    # visual quality review; screenshot_on_failure only covers debugging.
    screenshot_always: bool = False


class RunResponse(BaseModel):
    ok: bool
    page_errors: list[str]
    console_errors: list[str]
    console_warnings: list[str] = []
    requests_aborted: list[str] = []
    frames_observed: int
    intervals_observed: int = 0
    load_ms: int
    timed_out: bool = False
    screenshot_b64: str | None = None
    input_attempted: bool = False
    inputs_sent: list[str] = Field(default_factory=list)
    start_attempts: list[str] = Field(default_factory=list)
    input_errors: list[str] = Field(default_factory=list)
    visual_probe: str = ""
    visual_before_sha256: str | None = None
    visual_after_sha256: str | None = None
    visual_changed: bool | None = None
    visual_change_ratio: float | None = None
    visual_probe_error: str = ""
    # Aggregated runtime behavior probes reported by the game's scaffold
    # (window.__GW_PROBES__.counts): "scene:start|PlayScene" -> 3 etc.
    probes: dict[str, int] = Field(default_factory=dict)
    # Probe counters sampled at the START of the quiet observation tail (after
    # load + input simulation settle). The delta to `probes` covers a window
    # with no scene transitions, so a large `ui:interactive` delta there means
    # UI is being rebuilt every frame rather than built once.
    probes_start: dict[str, int] = Field(default_factory=dict)
    frames_start: int = 0


class ViteBuildRequest(BaseModel):
    files: list[BundleFile] = Field(min_length=1, max_length=120)
    timeout_ms: int | None = Field(default=None, ge=1_000, le=300_000)


class ViteBuildResponse(BaseModel):
    ok: bool
    files: list[BundleFile] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    timed_out: bool = False


class SimulateRequest(BaseModel):
    files: list[BundleFile] = Field(min_length=1, max_length=120)
    entry: str = "index.html"
    # WinScript payload; validated by winscript.parse_script before any browser work.
    script: dict
    # Wall-clock budget. Virtual-time pumping typically finishes an 8-minute
    # game in well under a minute; realtime fallback needs the headroom.
    timeout_ms: int | None = Field(default=None, ge=5_000, le=240_000)


class SimulateResponse(BaseModel):
    verdict: str  # won | lost | timeout | error
    ok: bool = False
    pump_mode: str = "virtual"  # virtual (game.loop.step) | realtime (no __GW_GAME__)
    sim_seconds: float = 0.0
    wall_ms: int = 0
    actions_sent: list[str] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    stats: dict[str, float] = Field(default_factory=dict)
    probes: dict[str, int] = Field(default_factory=dict)
    # WinScript-referenced stats the game never published via Probe.stat.
    missing_stats: list[str] = Field(default_factory=list)
    page_errors: list[str] = Field(default_factory=list)
    console_errors: list[str] = Field(default_factory=list)
    detail: str = ""
    screenshot_b64: str | None = None


@dataclass
class RunnerState:
    playwright: object | None = None
    browser: Browser | None = None
    semaphore: asyncio.Semaphore | None = None
    runs: int = 0


state = RunnerState()


def _normalize_path(path: str) -> str:
    normalized = unquote(path).replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=422, detail=f"invalid bundle path: {path}")
    return "/".join(parts) or "index.html"


def _mime(path: str) -> str:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "html": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "js": "application/javascript; charset=utf-8",
        "json": "application/json; charset=utf-8",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "svg": "image/svg+xml",
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "mp4": "video/mp4",
        "webm": "video/webm",
        "woff": "font/woff",
        "woff2": "font/woff2",
        "wasm": "application/wasm",
    }.get(suffix, "application/octet-stream")


def _decode_files(files: list[BundleFile]) -> dict[str, bytes]:
    decoded: dict[str, bytes] = {}
    total = 0
    for item in files:
        path = _normalize_path(item.path)
        try:
            content = base64.b64decode(item.content_b64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"invalid base64 for {path}") from exc
        if len(content) > settings.max_file_bytes:
            raise HTTPException(status_code=413, detail=f"{path} exceeds {settings.max_file_bytes} bytes")
        total += len(content)
        if total > settings.max_total_bytes:
            raise HTTPException(status_code=413, detail=f"bundle exceeds {settings.max_total_bytes} bytes")
        decoded[path] = content
    return decoded


async def _launch_browser() -> Browser:
    if state.playwright is None:
        state.playwright = await async_playwright().start()
    launch_args: list[str] = [
        "--disable-dev-shm-usage",
        "--disable-crash-reporter",
        # Keep rAF/timers running even when Chromium considers the page hidden
        # or occluded. A throttled page freezes WebGL games mid-run: frames stop,
        # every compositor screenshot waits forever, and the input→visual-change
        # probe silently dies (像素市长 2026-07-17: both QA visual checks skipped
        # because the first screenshot timed out).
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    if settings.chromium_no_sandbox:
        launch_args.append("--no-sandbox")
    return await state.playwright.chromium.launch(headless=True, args=launch_args)  # type: ignore[union-attr]


async def _ensure_browser() -> Browser:
    if state.browser is None or not state.browser.is_connected():
        state.browser = await _launch_browser()
        state.runs = 0
    return state.browser


async def _recycle_if_needed() -> None:
    if settings.browser_recycle_runs <= 0:
        return
    if state.runs < settings.browser_recycle_runs:
        return
    browser = state.browser
    state.browser = None
    state.runs = 0
    if browser and browser.is_connected():
        await browser.close()


async def _install_routes(page: Page, files: dict[str, bytes], requests_aborted: list[str]) -> None:
    async def handler(route):
        request_url = route.request.url
        parsed = urlparse(request_url)
        path = _normalize_path(parsed.path)
        if parsed.scheme == "https" and parsed.netloc == ORIGIN_HOST and path in files:
            await route.fulfill(status=200, body=files[path], content_type=_mime(path))
            return
        requests_aborted.append(request_url[:300])
        await route.abort()

    await page.route("**/*", handler)


_INIT_SCRIPT = r"""
(() => {
  window.__sandboxFrameCount = 0;
  window.__sandboxIntervalCount = 0;
  const original = window.requestAnimationFrame ? window.requestAnimationFrame.bind(window) : null;
  window.requestAnimationFrame = (callback) => {
    if (!original) return 0;
    return original((timestamp) => {
      window.__sandboxFrameCount += 1;
      return callback(timestamp);
    });
  };
  const originalSetInterval = window.setInterval ? window.setInterval.bind(window) : null;
  if (originalSetInterval) {
    window.setInterval = (callback, delay, ...args) => originalSetInterval((...cbArgs) => {
      window.__sandboxIntervalCount += 1;
      if (typeof callback === "function") return callback(...cbArgs);
      return undefined;
    }, delay, ...args);
  }
})();
"""


def _visual_metrics(
    before: bytes | None, after: bytes | None, method: str = "page-screenshot"
) -> dict[str, object]:
    if before is None or after is None:
        return {}
    size = max(len(before), len(after))
    mismatches = abs(len(before) - len(after))
    mismatches += sum(left != right for left, right in zip(before, after, strict=False))
    return {
        "visual_probe": f"{method or 'page-screenshot'}-png-byte-diff",
        "visual_before_sha256": hashlib.sha256(before).hexdigest(),
        "visual_after_sha256": hashlib.sha256(after).hexdigest(),
        "visual_changed": before != after,
        "visual_change_ratio": round(mismatches / size, 6) if size else 0.0,
    }


# Reads the last rendered WebGL buffer directly, so it works even when the
# compositor never produces a frame (hidden/occluded/GPU-starved pages make
# CDP screenshots time out). Capturing inside a rAF callback keeps the grab in
# the same animation-frame task as the game's render, where the drawing buffer
# (preserveDrawingBuffer:false) is still valid; the timeout fallback covers
# pages whose rAF is stalled entirely.
_CANVAS_CAPTURE_JS = """() => new Promise((resolve) => {
  const canvas = document.querySelector("canvas");
  if (!canvas) { resolve(null); return; }
  let settled = false;
  const grab = () => {
    if (settled) return;
    settled = true;
    try { resolve(canvas.toDataURL("image/png")); } catch (error) { resolve(null); }
  };
  try { requestAnimationFrame(() => grab()); } catch (error) { grab(); }
  setTimeout(grab, 1200);
})"""


async def _capture_page(page: Page, prefer: str | None = None) -> tuple[bytes | None, str, str]:
    """Capture the page as PNG. Returns (bytes, error, method). `prefer` pins
    the method that produced the before-shot so before/after byte diffs stay
    comparable."""
    errors: list[str] = []

    async def _cdp() -> bytes | None:
        # CDP first: Page.captureScreenshot does not wait for
        # document.fonts.ready, which never resolves on some generated bundles
        # and made page.screenshot() time out forever.
        try:
            session = await page.context.new_cdp_session(page)
            try:
                data = await asyncio.wait_for(
                    session.send("Page.captureScreenshot", {"format": "png"}),
                    timeout=4.0,
                )
                return base64.b64decode(data.get("data") or "") or None
            finally:
                try:
                    await session.detach()
                except PlaywrightError:
                    pass
        except (PlaywrightError, TimeoutError, ValueError, KeyError) as exc:
            errors.append(f"cdp: {' '.join(str(exc).split())[:160]}")
            return None

    async def _canvas() -> bytes | None:
        try:
            data_url = await asyncio.wait_for(page.evaluate(_CANVAS_CAPTURE_JS), timeout=3.0)
        except (PlaywrightError, TimeoutError) as exc:
            errors.append(f"canvas: {' '.join(str(exc).split())[:160]}")
            return None
        if isinstance(data_url, str) and data_url.startswith("data:image/png;base64,"):
            try:
                return base64.b64decode(data_url.split(",", 1)[1]) or None
            except ValueError:
                return None
        return None

    methods: list[tuple[str, object]] = [
        ("cdp-screenshot", _cdp),
        ("canvas-todataurl", _canvas),
    ]
    if prefer:
        methods.sort(key=lambda item: 0 if item[0] == prefer else 1)
    for name, capture in methods:
        raw = await capture()  # type: ignore[operator]
        if raw:
            return raw, "", name
    return None, "; ".join(errors)[:300], ""


def _playwright_key_from_probe(name: object) -> str | None:
    """Translate a Phaser KeyCodes name into a safe Playwright key."""

    raw = str(name or "").strip().upper()
    aliases = {
        "UP": "ArrowUp",
        "DOWN": "ArrowDown",
        "LEFT": "ArrowLeft",
        "RIGHT": "ArrowRight",
        "SPACE": "Space",
        "ENTER": "Enter",
        "RETURN": "Enter",
        "ESC": "Escape",
        "ESCAPE": "Escape",
        "SHIFT": "Shift",
        "CTRL": "Control",
        "CONTROL": "Control",
        "ALT": "Alt",
        "TAB": "Tab",
        "BACKSPACE": "Backspace",
    }
    digit_names = {
        "ZERO": "0",
        "ONE": "1",
        "TWO": "2",
        "THREE": "3",
        "FOUR": "4",
        "FIVE": "5",
        "SIX": "6",
        "SEVEN": "7",
        "EIGHT": "8",
        "NINE": "9",
    }
    if raw in aliases:
        return aliases[raw]
    if raw in digit_names:
        return digit_names[raw]
    if len(raw) == 1 and raw.isalnum():
        return raw.lower()
    return None


async def _simulate_game_inputs(page: Page) -> tuple[list[str], list[str], list[str]]:
    sent: list[str] = []
    start_attempts: list[str] = []
    errors: list[str] = []
    try:
        target = await page.evaluate(
            """() => {
              const canvases = [...document.querySelectorAll('canvas')]
                .map((canvas) => ({ canvas, rect: canvas.getBoundingClientRect() }))
                .filter(({ rect }) => rect.width > 0 && rect.height > 0)
                .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
              const rect = canvases[0]?.rect;
              return rect
                ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, scope: 'canvas' }
                : { x: innerWidth / 2, y: innerHeight / 2, scope: 'page' };
            }"""
        )
        pointer = f"pointer:{target['scope']}-center"
        start_attempts.append(pointer)
        await page.mouse.click(float(target["x"]), float(target["y"]))
        sent.append(pointer)
    except (PlaywrightError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"pointer: {' '.join(str(exc).split())[:240]}")

    for key in ("Enter", "Space"):
        action = f"keyboard:{key}"
        start_attempts.append(action)
        try:
            await page.keyboard.press(key, delay=35)
            sent.append(action)
        except PlaywrightError as exc:
            errors.append(f"{action}: {' '.join(str(exc).split())[:240]}")

    # Canvas games frequently use an in-canvas map/character/difficulty menu,
    # so center-click + Enter/Space never reaches their core loop. The Phaser
    # scaffold exposes live interactive objects; explore a bounded set of their
    # current centers without depending on labels, language, or game genre.
    # Re-query between attempts because each click can replace the current
    # menu with the next selection screen. A page-local WeakSet ensures every
    # attempt explores a distinct live control without retaining game objects.
    for round_index in range(6):
        try:
            target = await page.evaluate(
                """() => {
                  const canvases = [...document.querySelectorAll('canvas')]
                    .map((canvas) => ({ canvas, rect: canvas.getBoundingClientRect() }))
                    .filter(({ rect }) => rect.width > 0 && rect.height > 0)
                    .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
                  const chosen = canvases[0];
                  if (!chosen) return null;
                  const raw = Array.isArray(window.__GW_INTERACTIVE_TARGETS__)
                    ? window.__GW_INTERACTIVE_TARGETS__
                    : [];
                  if (!(window.__GW_QA_CLICKED_TARGETS__ instanceof WeakSet)) {
                    window.__GW_QA_CLICKED_TARGETS__ = new WeakSet();
                  }
                  const clicked = window.__GW_QA_CLICKED_TARGETS__;
                  const projected = [];
                  for (const object of raw.slice(0, 80)) {
                    try {
                      const scene = object?.scene;
                      if (clicked.has(object)) continue;
                      if (!object || object.active === false || object.visible === false) continue;
                      if (!object.input || object.input.enabled === false) continue;
                      if (!scene?.sys?.isActive?.()) continue;
                      const bounds = object.getBounds?.();
                      if (!bounds || bounds.width <= 1 || bounds.height <= 1) continue;
                      const camera = scene.cameras?.main;
                      const fixed = object.scrollFactorX === 0 && object.scrollFactorY === 0;
                      const zoom = Number(camera?.zoom || 1);
                      const gameWidth = Number(scene.scale?.width || chosen.canvas.width || 1);
                      const gameHeight = Number(scene.scale?.height || chosen.canvas.height || 1);
                      let gameX = Number(bounds.centerX);
                      let gameY = Number(bounds.centerY);
                      if (!fixed && camera) {
                        gameX = (gameX - Number(camera.scrollX || 0)) * zoom + Number(camera.x || 0);
                        gameY = (gameY - Number(camera.scrollY || 0)) * zoom + Number(camera.y || 0);
                      }
                      const x = chosen.rect.left + (gameX / gameWidth) * chosen.rect.width;
                      const y = chosen.rect.top + (gameY / gameHeight) * chosen.rect.height;
                      if (
                        Number.isFinite(x) && Number.isFinite(y)
                        && x >= chosen.rect.left && x <= chosen.rect.right
                        && y >= chosen.rect.top && y <= chosen.rect.bottom
                      ) {
                        projected.push({
                          object,
                          x,
                          y,
                          depth: Number(object.depth || 0),
                          area: Number(bounds.width * bounds.height),
                        });
                      }
                    } catch {}
                  }
                  projected.sort((a, b) => b.depth - a.depth || b.y - a.y || b.area - a.area);
                  const target = projected[0];
                  if (!target) return null;
                  clicked.add(target.object);
                  return { x: target.x, y: target.y };
                }"""
            )
            if not isinstance(target, dict):
                break
            action = f"pointer:interactive-hold-{round_index + 1}"
            start_attempts.append(action)
            await page.mouse.move(float(target["x"]), float(target["y"]))
            await page.mouse.down()
            await page.wait_for_timeout(220)
            await page.mouse.up()
            sent.append(action)
            await page.wait_for_timeout(120)
        except (PlaywrightError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"pointer:interactive: {' '.join(str(exc).split())[:240]}")
            break

    registered_keys: list[str] = []
    try:
        raw_keys = await page.evaluate(
            """() => Object.keys(window.__GW_PROBES__?.counts || {})
              .filter((key) => key.startsWith("key:registered|"))
              .map((key) => key.split("|", 2)[1])
              .slice(0, 20)"""
        )
        if isinstance(raw_keys, list):
            registered_keys = [
                mapped
                for item in raw_keys
                if (mapped := _playwright_key_from_probe(item)) is not None
            ]
    except PlaywrightError as exc:
        errors.append(f"keyboard:discover: {' '.join(str(exc).split())[:240]}")

    keys_to_try: list[str] = []
    for key in registered_keys + [
        "Space",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
        "a",
        "d",
        "w",
        "s",
    ]:
        if key not in keys_to_try:
            keys_to_try.append(key)

    for key in keys_to_try[:16]:
        action = f"keyboard-hold:{key}"
        try:
            await page.keyboard.down(key)
            await page.wait_for_timeout(180)
            await page.keyboard.up(key)
            sent.append(action)
        except PlaywrightError as exc:
            errors.append(f"{action}: {' '.join(str(exc).split())[:240]}")
    return sent, start_attempts, errors


async def _collect_probes(page: Page) -> dict[str, int]:
    """Read the game scaffold's runtime behavior counters (best-effort)."""
    try:
        raw = await page.evaluate(
            "(window.__GW_PROBES__ && window.__GW_PROBES__.counts) || {}"
        )
    except PlaywrightError:
        return {}
    if not isinstance(raw, dict):
        return {}
    probes: dict[str, int] = {}
    for key, value in list(raw.items())[:300]:
        try:
            probes[str(key)[:120]] = int(value)
        except (TypeError, ValueError):
            continue
    return probes


async def _drive_page(
    browser: Browser,
    files: dict[str, bytes],
    entry: str,
    timeout_ms: int,
    simulate_input: bool,
    screenshot_always: bool = False,
) -> RunResponse:
    page_errors: list[str] = []
    console_errors: list[str] = []
    console_warnings: list[str] = []
    requests_aborted: list[str] = []
    screenshot_b64: str | None = None
    inputs_sent: list[str] = []
    start_attempts: list[str] = []
    input_errors: list[str] = []
    visual_probe_errors: list[str] = []
    started = time.perf_counter()
    context = await browser.new_context(viewport={"width": 1280, "height": 720})
    await context.add_init_script(_INIT_SCRIPT)
    try:
        page = await context.new_page()
        page.on("pageerror", lambda exc: page_errors.append(" ".join(str(exc).split())[:500]))

        def on_console(msg):
            text = " ".join(msg.text.split())[:500]
            if msg.type == "error":
                console_errors.append(text)
            elif msg.type == "warning":
                console_warnings.append(text)

        page.on("console", on_console)
        await _install_routes(page, files, requests_aborted)
        # domcontentloaded + first-frame polling instead of the full load event:
        # one straggling subresource (a pending FontFace, a slow decode) used to
        # keep `load` from firing and misreported a running game as frames=0.
        await page.goto(
            f"{ORIGIN}/{entry}", wait_until="domcontentloaded", timeout=timeout_ms
        )
        # Total in-page budget stays ~timeout_ms from navigation start so the
        # +8s outer headroom remains reserved for input simulation and capture.
        frame_deadline = started + timeout_ms / 1000
        while time.perf_counter() < frame_deadline:
            try:
                if int(await page.evaluate("window.__sandboxFrameCount || 0")) > 0:
                    break
            except PlaywrightError:
                break
            await page.wait_for_timeout(250)
        await page.wait_for_timeout(min(180, max(60, timeout_ms // 30)))
        before_screenshot, before_error, capture_method = await _capture_page(page)
        if before_error:
            visual_probe_errors.append(f"before: {before_error}")
        if simulate_input:
            inputs_sent, start_attempts, input_errors = await _simulate_game_inputs(page)
        # Let input effects finish (scene starts, one-time UI builds), then
        # sample probes and observe a quiet tail: interactive registrations
        # accumulating DURING the tail expose per-frame UI rebuild churn
        # without misreading a legitimate scene-build burst.
        await page.wait_for_timeout(min(700, max(120, timeout_ms // 10)))
        probes_start = await _collect_probes(page)
        try:
            frames_start = int(await page.evaluate("window.__sandboxFrameCount || 0"))
        except PlaywrightError:
            frames_start = 0
        await page.wait_for_timeout(min(1400, max(600, timeout_ms // 16)))
        after_screenshot, after_error, _after_method = await _capture_page(
            page, prefer=capture_method or None
        )
        if after_error:
            visual_probe_errors.append(f"after: {after_error}")
        try:
            frames_observed = int(await page.evaluate("window.__sandboxFrameCount || 0"))
        except PlaywrightError:
            frames_observed = 0
        try:
            intervals_observed = int(await page.evaluate("window.__sandboxIntervalCount || 0"))
        except PlaywrightError:
            intervals_observed = 0
        probes = await _collect_probes(page)
        load_ms = int((time.perf_counter() - started) * 1000)
        ok = not page_errors and not console_errors and not requests_aborted and (frames_observed > 0 or intervals_observed > 0)
        if screenshot_always or (not ok and settings.screenshot_on_failure):
            raw = after_screenshot or before_screenshot
            if raw is not None:
                screenshot_b64 = base64.b64encode(raw).decode("ascii")
        visual_metrics = _visual_metrics(before_screenshot, after_screenshot, capture_method)
        return RunResponse(
            ok=ok,
            page_errors=page_errors,
            console_errors=console_errors,
            console_warnings=console_warnings,
            requests_aborted=requests_aborted,
            frames_observed=frames_observed,
            intervals_observed=intervals_observed,
            load_ms=load_ms,
            screenshot_b64=screenshot_b64,
            input_attempted=simulate_input,
            inputs_sent=inputs_sent,
            start_attempts=start_attempts,
            input_errors=input_errors,
            visual_probe_error="; ".join(visual_probe_errors),
            probes=probes,
            probes_start=probes_start,
            frames_start=frames_start,
            **visual_metrics,
        )
    finally:
        await context.close()


async def _run_with_timeout(payload: RunRequest) -> RunResponse:
    files = _decode_files(payload.files)
    entry = _normalize_path(payload.entry)
    if entry not in files:
        raise HTTPException(status_code=422, detail=f"entry file not found: {entry}")
    timeout_ms = payload.timeout_ms or settings.default_timeout_ms
    browser = await _ensure_browser()
    try:
        # Post-load work (input simulation, two screenshot fallback chains, the
        # churn-observation tail) can take ~10s on WebGL pages; a tight headroom
        # flagged slow-but-successful loads as timeouts.
        result = await asyncio.wait_for(
            _drive_page(
                browser,
                files,
                entry,
                timeout_ms,
                payload.simulate_input,
                payload.screenshot_always,
            ),
            timeout=(timeout_ms + 12_000) / 1000,
        )
    except TimeoutError:
        result = RunResponse(
            ok=False,
            page_errors=[f"timed out after {timeout_ms}ms"],
            console_errors=[],
            frames_observed=0,
            load_ms=timeout_ms,
            timed_out=True,
        )
    except PlaywrightError as exc:
        result = RunResponse(
            ok=False,
            page_errors=[" ".join(str(exc).split())[:500]],
            console_errors=[],
            frames_observed=0,
            load_ms=timeout_ms,
        )
        if state.browser is not None and not state.browser.is_connected():
            state.browser = None
    state.runs += 1
    await _recycle_if_needed()
    return result


# Stops Phaser's own rAF loop and exposes a manual pump so the simulation can
# run minutes of game time in seconds of wall time. Every pumped frame advances
# a fixed 1000/60 ms virtual clock, so tweens, timers, physics and update(dt)
# stay mutually consistent. Falls back to realtime when the scaffold handle is
# missing (bundles generated before __GW_GAME__ existed).
_SIM_SETUP_JS = """() => {
  const game = window.__GW_GAME__;
  if (!game || !game.loop || typeof game.loop.step !== "function") return "realtime";
  if (window.__GW_SIM__) return window.__GW_SIM__.mode;
  try { game.loop.stop(); } catch (error) { return "realtime"; }
  window.__GW_SIM__ = {
    mode: "virtual",
    now: (typeof performance !== "undefined" && performance.now()) || 0,
    frames: 0,
    error: "",
    pump(count) {
      const n = Math.max(0, Math.min(1200, count | 0));
      for (let i = 0; i < n; i += 1) {
        this.now += 1000 / 60;
        try { game.loop.step(this.now); } catch (error) {
          this.error = String(error).slice(0, 300);
          return -1;
        }
        this.frames += 1;
      }
      return this.frames;
    },
  };
  return "virtual";
}"""

_SIM_READ_JS = """() => ({
  stats: window.__GW_STATS__ || {},
  counts: (window.__GW_PROBES__ && window.__GW_PROBES__.counts) || {},
  pumpError: (window.__GW_SIM__ && window.__GW_SIM__.error) || "",
})"""

# Maps WinScript design-space coordinates onto the on-page canvas rect. With
# Scale.FIT the whole game surface maps linearly to the canvas box, so no
# camera math is needed for screen-space targets.
_SIM_POINTER_JS = """(pos) => {
  const canvases = [...document.querySelectorAll("canvas")]
    .map((canvas) => ({ canvas, rect: canvas.getBoundingClientRect() }))
    .filter(({ rect }) => rect.width > 0 && rect.height > 0)
    .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
  const chosen = canvases[0];
  if (!chosen) return null;
  const game = window.__GW_GAME__;
  const gameWidth = Number((game && game.scale && game.scale.width) || chosen.canvas.width || 1);
  const gameHeight = Number((game && game.scale && game.scale.height) || chosen.canvas.height || 1);
  return {
    x: chosen.rect.left + (Number(pos.x) / gameWidth) * chosen.rect.width,
    y: chosen.rect.top + (Number(pos.y) / gameHeight) * chosen.rect.height,
  };
}"""

_SIM_TICK_SECONDS = 0.5
_SIM_TIMELINE_LIMIT = 240


def _timeline_add(timeline: list[dict], sim_seconds: float, event: str) -> None:
    if len(timeline) < _SIM_TIMELINE_LIMIT:
        timeline.append({"t": round(sim_seconds, 1), "event": event[:200]})


def _describe_sim_action(action: dict, source: str) -> str:
    kind = action.get("action")
    if kind == "pointer":
        label = f"pointer({action.get('x')},{action.get('y')})"
    elif kind == "key":
        hold = int(action.get("hold_ms") or 0)
        label = f"key {action.get('key')}" + (f" hold {hold}ms" if hold else "")
    else:
        label = f"wait {action.get('seconds')}s"
    named = action.get("label")
    return f"{source}: {label}" + (f" [{named}]" if named else "")


async def _execute_sim_action(page: Page, action: dict) -> tuple[bool, str]:
    try:
        kind = action.get("action")
        if kind == "pointer":
            target = await page.evaluate(
                _SIM_POINTER_JS, {"x": action.get("x"), "y": action.get("y")}
            )
            if not isinstance(target, dict):
                return False, "no visible canvas to project the pointer onto"
            await page.mouse.click(float(target["x"]), float(target["y"]))
        elif kind == "key":
            key = str(action.get("key") or "Space")
            hold = int(action.get("hold_ms") or 0)
            if hold > 0:
                await page.keyboard.down(key)
                await page.wait_for_timeout(min(hold, 2000))
                await page.keyboard.up(key)
            else:
                await page.keyboard.press(key, delay=30)
        # "wait" needs no page work: the driver pumps the extra virtual time.
        return True, ""
    except (PlaywrightError, KeyError, TypeError, ValueError) as exc:
        return False, " ".join(str(exc).split())[:200]


async def _drive_simulation(
    browser: Browser,
    files: dict[str, bytes],
    entry: str,
    script: dict,
    timeout_ms: int,
) -> SimulateResponse:
    page_errors: list[str] = []
    console_errors: list[str] = []
    requests_aborted: list[str] = []
    actions_sent: list[str] = []
    timeline: list[dict] = []
    started = time.perf_counter()
    context = await browser.new_context(viewport={"width": 1280, "height": 720})
    await context.add_init_script(_INIT_SCRIPT)
    try:
        page = await context.new_page()
        page.on("pageerror", lambda exc: page_errors.append(" ".join(str(exc).split())[:500]))
        page.on(
            "console",
            lambda msg: console_errors.append(" ".join(msg.text.split())[:500])
            if msg.type == "error"
            else None,
        )
        await _install_routes(page, files, requests_aborted)
        await page.goto(f"{ORIGIN}/{entry}", wait_until="domcontentloaded", timeout=15_000)
        first_frame_deadline = time.perf_counter() + 15
        frames_seen = 0
        while time.perf_counter() < first_frame_deadline:
            try:
                frames_seen = int(await page.evaluate("window.__sandboxFrameCount || 0"))
            except PlaywrightError:
                break
            if frames_seen > 0:
                break
            await page.wait_for_timeout(200)
        if frames_seen <= 0:
            return SimulateResponse(
                verdict="error",
                detail="game never produced an animation frame; cannot simulate",
                page_errors=page_errors,
                console_errors=console_errors,
                wall_ms=int((time.perf_counter() - started) * 1000),
            )
        # Give the boot/title flow a moment before freezing the loop.
        await page.wait_for_timeout(250)
        pump_mode = str(await page.evaluate(_SIM_SETUP_JS) or "realtime")

        progress = winscript.SimProgress()
        sim_seconds = 0.0
        budget = float(script.get("sim_seconds") or 300)
        wall_deadline = started + timeout_ms / 1000
        last_stats_log = -1e9
        stats: dict = {}
        verdict = "timeout"
        detail = ""
        while True:
            try:
                snapshot = await page.evaluate(_SIM_READ_JS)
            except PlaywrightError as exc:
                verdict = "error"
                detail = " ".join(str(exc).split())[:300]
                break
            stats = snapshot.get("stats") or {}
            counts = snapshot.get("counts") or {}
            if snapshot.get("pumpError"):
                verdict = "error"
                detail = f"game crashed during pumped frame: {snapshot['pumpError']}"
                break
            terminal = winscript.terminal_verdict(counts)
            if terminal:
                verdict = terminal
                break
            if sim_seconds >= budget:
                verdict = "timeout"
                detail = f"no terminal Probe.status within {budget:.0f} simulated seconds"
                break
            if time.perf_counter() >= wall_deadline:
                verdict = "timeout"
                detail = "wall-clock budget exhausted"
                break
            action, source = winscript.next_action(script, stats, counts, sim_seconds, progress)
            extra_wait = 0.0
            if action:
                description = _describe_sim_action(action, source)
                ok_action, action_error = await _execute_sim_action(page, action)
                if ok_action:
                    if len(actions_sent) < 200:
                        actions_sent.append(description)
                    _timeline_add(timeline, sim_seconds, description)
                else:
                    _timeline_add(timeline, sim_seconds, f"{description} FAILED: {action_error}")
                if action.get("action") == "wait":
                    extra_wait = float(action.get("seconds") or 1.0)
            if sim_seconds - last_stats_log >= 15:
                last_stats_log = sim_seconds
                snap = ", ".join(
                    f"{key}={round(float(value), 2)}"
                    for key, value in sorted(stats.items())[:8]
                    if isinstance(value, (int, float))
                )
                _timeline_add(timeline, sim_seconds, f"stats: {snap or 'none published'}")
            advance = _SIM_TICK_SECONDS + extra_wait
            if pump_mode == "virtual":
                pumped = await page.evaluate(
                    f"window.__GW_SIM__ ? window.__GW_SIM__.pump({int(advance * 60)}) : -2"
                )
                if pumped == -2:
                    pump_mode = "realtime"
            else:
                await page.wait_for_timeout(int(min(advance, 5.0) * 1000))
            sim_seconds += advance
        _timeline_add(
            timeline, sim_seconds, f"terminal: {verdict}" + (f" ({detail})" if detail else "")
        )
        probes = await _collect_probes(page)
        screenshot_raw, _shot_error, _method = await _capture_page(page)
        clean_stats = {
            str(key)[:40]: float(value)
            for key, value in list(stats.items())[:60]
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        return SimulateResponse(
            verdict=verdict,
            ok=verdict == "won",
            pump_mode=pump_mode,
            sim_seconds=round(sim_seconds, 1),
            wall_ms=int((time.perf_counter() - started) * 1000),
            actions_sent=actions_sent,
            timeline=timeline,
            stats=clean_stats,
            probes=probes,
            missing_stats=winscript.missing_stats(script, clean_stats),
            page_errors=page_errors,
            console_errors=console_errors,
            detail=detail,
            screenshot_b64=(
                base64.b64encode(screenshot_raw).decode("ascii") if screenshot_raw else None
            ),
        )
    finally:
        await context.close()


async def _simulate_with_timeout(payload: SimulateRequest) -> SimulateResponse:
    script, errors = winscript.parse_script(payload.script)
    if errors:
        raise HTTPException(
            status_code=422, detail=("invalid WinScript: " + "; ".join(errors[:6]))[:400]
        )
    files = _decode_files(payload.files)
    entry = _normalize_path(payload.entry)
    if entry not in files:
        raise HTTPException(status_code=422, detail=f"entry file not found: {entry}")
    timeout_ms = payload.timeout_ms or 120_000
    browser = await _ensure_browser()
    try:
        result = await asyncio.wait_for(
            _drive_simulation(browser, files, entry, script, timeout_ms),
            timeout=(timeout_ms + 20_000) / 1000,
        )
    except TimeoutError:
        result = SimulateResponse(
            verdict="timeout",
            detail=f"simulation exceeded {timeout_ms}ms wall budget",
            wall_ms=timeout_ms,
        )
    except PlaywrightError as exc:
        result = SimulateResponse(verdict="error", detail=" ".join(str(exc).split())[:400])
        if state.browser is not None and not state.browser.is_connected():
            state.browser = None
    state.runs += 1
    await _recycle_if_needed()
    return result


def _materialize_project(root: Path, files: dict[str, bytes]) -> None:
    for relative, content in files.items():
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _collect_dist(dist: Path) -> list[BundleFile]:
    if not dist.is_dir():
        raise RuntimeError("Vite did not create a dist directory")
    collected: list[BundleFile] = []
    total = 0
    for path in sorted(item for item in dist.rglob("*") if item.is_file()):
        relative = path.relative_to(dist).as_posix()
        content = path.read_bytes()
        if len(content) > settings.max_file_bytes:
            raise RuntimeError(f"built file {relative} exceeds {settings.max_file_bytes} bytes")
        total += len(content)
        if total > settings.max_total_bytes:
            raise RuntimeError(f"built dist exceeds {settings.max_total_bytes} bytes")
        collected.append(
            BundleFile(
                path=relative,
                content_b64=base64.b64encode(content).decode("ascii"),
                content_type=_mime(relative),
            )
        )
    if not any(item.path == "index.html" for item in collected):
        raise RuntimeError("built dist is missing index.html")
    return collected


def _build_vite_sync(payload: ViteBuildRequest) -> ViteBuildResponse:
    started = time.perf_counter()
    files = _decode_files(payload.files)
    if len(files) > settings.max_build_files:
        raise HTTPException(status_code=413, detail="too many Vite project files")
    runtime = Path(settings.vite_runtime_root)
    vite_bin = runtime / "node_modules" / ".bin" / ("vite.cmd" if os.name == "nt" else "vite")
    tsc_bin = runtime / "node_modules" / ".bin" / ("tsc.cmd" if os.name == "nt" else "tsc")
    config_path = runtime / "vite.config.mjs"
    needs_typecheck = "tsconfig.json" in files
    if not vite_bin.is_file() or not config_path.is_file() or (needs_typecheck and not tsc_bin.is_file()):
        raise HTTPException(status_code=503, detail="Vite build runtime is unavailable")
    timeout_ms = payload.timeout_ms or 120_000
    temp_root = "/tmp" if Path("/tmp").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="gameweave-build-", dir=temp_root) as tmp:
        root = Path(tmp)
        _materialize_project(root, files)
        node_modules = root / "node_modules"
        try:
            os.symlink(runtime / "node_modules", node_modules, target_is_directory=True)
        except OSError:
            # Windows development environments may not allow directory symlinks;
            # the production Linux container always takes the cheap symlink path.
            shutil.copytree(runtime / "node_modules", node_modules)
        dist = root / "dist"
        env = {
            "HOME": "/tmp",
            "PATH": os.environ.get("PATH", ""),
            "NODE_ENV": "production",
            "NO_UPDATE_NOTIFIER": "1",
        }
        logs: list[str] = []
        if needs_typecheck:
            typecheck_command = [str(tsc_bin), "--noEmit", "--project", str(root / "tsconfig.json")]
            try:
                checked = subprocess.run(
                    typecheck_command,
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_ms / 1000,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return ViteBuildResponse(
                    ok=False,
                    errors=[f"TypeScript check timed out after {timeout_ms}ms"],
                    duration_ms=timeout_ms,
                    timed_out=True,
                )
            type_stdout = [line[:1000] for line in (checked.stdout or "").splitlines()[-30:]]
            type_stderr = [line[:1000] for line in (checked.stderr or "").splitlines()[-30:]]
            logs.extend(type_stdout)
            if checked.returncode != 0:
                return ViteBuildResponse(
                    ok=False,
                    errors=type_stdout + type_stderr or [f"TypeScript exited with code {checked.returncode}"],
                    logs=["TypeScript typecheck failed"],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        remaining_ms = max(1_000, timeout_ms - elapsed_ms)
        # The bundled loader writes .vite-temp beside runtime node_modules, which
        # is intentionally read-only for the sandbox user. This config is plain ESM.
        command = [
            str(vite_bin),
            "build",
            "--config",
            str(config_path),
            "--configLoader",
            "native",
            "--outDir",
            str(dist),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=remaining_ms / 1000,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ViteBuildResponse(
                ok=False,
                errors=[f"Vite build timed out after {timeout_ms}ms"],
                duration_ms=timeout_ms,
                timed_out=True,
            )
        logs.extend(line[:1000] for line in (completed.stdout or "").splitlines()[-30:])
        stderr = [line[:1000] for line in (completed.stderr or "").splitlines()[-30:]]
        if completed.returncode != 0:
            return ViteBuildResponse(
                ok=False,
                errors=stderr or [f"Vite exited with code {completed.returncode}"],
                logs=logs,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        try:
            built = _collect_dist(dist)
        except RuntimeError as exc:
            return ViteBuildResponse(
                ok=False,
                errors=[str(exc)],
                logs=logs + stderr,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        return ViteBuildResponse(
            ok=True,
            files=built,
            warnings=stderr,
            logs=logs,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.semaphore = asyncio.Semaphore(max(1, int(settings.concurrency)))
    state.browser = await _launch_browser()
    try:
        yield
    finally:
        if state.browser and state.browser.is_connected():
            await state.browser.close()
        if state.playwright is not None:
            await state.playwright.stop()  # type: ignore[attr-defined]


app = FastAPI(title="GameWeave sandbox runner", lifespan=lifespan)


@app.get("/health")
async def health():
    try:
        browser = await _ensure_browser()
        browser_ok = browser.is_connected()
    except Exception:  # noqa: BLE001
        browser_ok = False
    return {"status": "ok" if browser_ok else "degraded"}


@app.post("/run", response_model=RunResponse)
async def run_bundle(payload: RunRequest):
    if state.semaphore is None:
        raise HTTPException(status_code=503, detail="runner not ready")
    async with state.semaphore:
        return await _run_with_timeout(payload)


@app.post("/simulate", response_model=SimulateResponse)
async def simulate_win_path(payload: SimulateRequest):
    if state.semaphore is None:
        raise HTTPException(status_code=503, detail="runner not ready")
    async with state.semaphore:
        return await _simulate_with_timeout(payload)


@app.post("/build/vite", response_model=ViteBuildResponse)
async def build_vite(payload: ViteBuildRequest):
    if state.semaphore is None:
        raise HTTPException(status_code=503, detail="runner not ready")
    async with state.semaphore:
        return await asyncio.to_thread(_build_vite_sync, payload)
