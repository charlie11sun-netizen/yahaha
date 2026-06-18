from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  注册所有表到 Base.metadata
from app.api.routers import auth, games, tasks, uploads
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.storage.s3 import ensure_bucket


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_bucket()
    yield


app = FastAPI(title="PlayForge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(games.router)
app.include_router(tasks.router)
app.include_router(uploads.router)


@app.get("/health")
def health():
    return {"status": "ok"}
