import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import app.models  # noqa: F401  注册所有表到 Base.metadata
from app.api.routers import auth, games, memory, oauth, tasks, uploads, users
from app.core.config import settings
from app.core.gate import game_file_request, gate_enabled, public_browse_request, verify_gate_token
from app.core.telemetry import (
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    init_otel,
    init_sentry,
    log_info,
)
from app.db.base import Base
from app.db.session import engine
from app.storage.s3 import ensure_bucket

configure_logging()
init_sentry("gameweave-api")
logger = get_logger("gameweave")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.AUTO_CREATE_ALL:
        Base.metadata.create_all(bind=engine)
    ensure_bucket()
    yield


app = FastAPI(title="GameWeave API", version="0.1.0", lifespan=lifespan)
init_otel(service_name="gameweave-api", fastapi_app=app, sqlalchemy_engine=engine)

# Front-door site gate: when SITE_PASSWORD is set, every request must carry a
# valid X-Gate-Token (the web front-end attaches it after unlock). Exempts CORS
# preflight, health checks, and the OAuth redirect flow (browser top-level
# navigation / provider callback can't carry a custom header). Kept innermost so
# CORS (added last, below) still wraps its 401 responses.
_GATE_EXEMPT_EXACT = {"/health", "/health/ready"}
_GATE_EXEMPT_PREFIXES = ("/auth/oauth",)


@app.middleware("http")
async def site_gate(request, call_next):
    if gate_enabled() and request.method != "OPTIONS":
        path = request.url.path
        exempt = (
            path in _GATE_EXEMPT_EXACT
            or path.startswith(_GATE_EXEMPT_PREFIXES)
            or game_file_request(request.method, path)
            or public_browse_request(request.method, path)
        )
        if not exempt and not verify_gate_token(request.headers.get("X-Gate-Token")):
            return JSONResponse(status_code=401, content={"detail": "Site locked. Unlock the site to continue."})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if not game_file_request(request.method, request.url.path):
        response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


@app.middleware("http")
async def access_log(request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    bind_context(request_id=request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        log_info(
            logger,
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 1),
        )
        return response
    finally:
        clear_context()


# CORS outermost: answers preflight and adds headers to every response (gate
# 401s included). X-Gate-Token must be allow-listed so the browser may send it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Gate-Token", "X-Request-ID"],
)

app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(games.router)
app.include_router(tasks.router)
app.include_router(memory.router)
app.include_router(uploads.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    checks = {"db": False, "redis": False, "s3": False}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.api.deps import _get_rl_redis

        _get_rl_redis().ping()
        checks["redis"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.storage.s3 import client

        client().head_bucket(Bucket=settings.S3_BUCKET)
        checks["s3"] = True
    except Exception:  # noqa: BLE001
        pass
    ok = all(checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "degraded", "checks": checks},
    )
