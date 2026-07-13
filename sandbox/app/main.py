from __future__ import annotations

import asyncio
import base64
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
    launch_args: list[str] = ["--disable-dev-shm-usage", "--disable-crash-reporter"]
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


async def _drive_page(
    browser: Browser,
    files: dict[str, bytes],
    entry: str,
    timeout_ms: int,
    simulate_input: bool,
) -> RunResponse:
    page_errors: list[str] = []
    console_errors: list[str] = []
    console_warnings: list[str] = []
    requests_aborted: list[str] = []
    screenshot_b64: str | None = None
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
        await page.goto(f"{ORIGIN}/{entry}", wait_until="load", timeout=timeout_ms)
        if simulate_input:
            for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space"):
                await page.keyboard.press(key)
        await page.wait_for_timeout(min(500, max(120, timeout_ms // 10)))
        try:
            frames_observed = int(await page.evaluate("window.__sandboxFrameCount || 0"))
        except PlaywrightError:
            frames_observed = 0
        try:
            intervals_observed = int(await page.evaluate("window.__sandboxIntervalCount || 0"))
        except PlaywrightError:
            intervals_observed = 0
        load_ms = int((time.perf_counter() - started) * 1000)
        ok = not page_errors and not console_errors and not requests_aborted and (frames_observed > 0 or intervals_observed > 0)
        if not ok and settings.screenshot_on_failure:
            raw = await page.screenshot(type="png", timeout=1000)
            screenshot_b64 = base64.b64encode(raw).decode("ascii")
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
        result = await asyncio.wait_for(
            _drive_page(browser, files, entry, timeout_ms, payload.simulate_input),
            timeout=(timeout_ms + 750) / 1000,
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
