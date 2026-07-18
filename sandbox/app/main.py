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

    for key in ("Enter", "Space", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "a", "d", "w", "s"):
        action = f"keyboard:{key}"
        if key in {"Enter", "Space"}:
            start_attempts.append(action)
        try:
            await page.keyboard.press(key, delay=35)
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


@app.post("/build/vite", response_model=ViteBuildResponse)
async def build_vite(payload: ViteBuildRequest):
    if state.semaphore is None:
        raise HTTPException(status_code=503, detail="runner not ready")
    async with state.semaphore:
        return await asyncio.to_thread(_build_vite_sync, payload)
