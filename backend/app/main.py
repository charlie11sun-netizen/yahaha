import logging
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
from app.core.gate import gate_enabled, verify_gate_token
from app.db.base import Base
from app.db.session import engine
from app.storage.s3 import ensure_bucket

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("playforge")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_bucket()
    yield


app = FastAPI(title="PlayForge API", version="0.1.0", lifespan=lifespan)

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
        exempt = path in _GATE_EXEMPT_EXACT or path.startswith(_GATE_EXEMPT_PREFIXES)
        if not exempt and not verify_gate_token(request.headers.get("X-Gate-Token")):
            return JSONResponse(status_code=401, content={"detail": "Site locked. Unlock the site to continue."})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


@app.middleware("http")
async def access_log(request, call_next):
    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %s %.1fms [%s]",
        request.method, request.url.path, response.status_code, duration_ms, request_id,
    )
    return response


# CORS outermost: answers preflight and adds headers to every response (gate
# 401s included). X-Gate-Token must be allow-listed so the browser may send it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Gate-Token"],
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
