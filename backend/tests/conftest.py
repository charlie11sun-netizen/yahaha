"""测试夹具：SQLite 内存库 + 覆盖 get_db / S3 / Celery / 限流，免起外部依赖。"""
import os

# 必须在导入 app 之前设置，避免 app.db.session 加载 psycopg 方言
os.environ.setdefault("DATABASE_URL", "sqlite://")

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401
from app.api import deps  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.storage import s3  # noqa: E402


class _FakeRedis:
    """限流用：每次 incr 都返回 1，等于不限流。"""

    def incr(self, key):
        return 1

    def expire(self, key, window):
        return True

    def ping(self):
        return True


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client(db_session_factory, monkeypatch):
    def override_get_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(deps, "_get_rl_redis", lambda: _FakeRedis())
    monkeypatch.setattr(s3, "put_object", lambda key, body, content_type: key)
    monkeypatch.setattr(s3, "public_url", lambda key: f"https://oss.test/{key}")
    monkeypatch.setattr(s3, "presigned_url", lambda key, **kwargs: f"https://oss.test/private/{key}?signature=test")
    monkeypatch.setattr(
        s3, "manifest_url",
        lambda gid, ver: f"https://oss.test/games/{gid}/{ver}/manifest.json",
    )
    monkeypatch.setattr(s3, "ensure_bucket", lambda: None)
    monkeypatch.setattr(
        s3, "get_object",
        lambda key: b'{"entry": "index.html", "runtime": "iframe-html", "sha256": "deadbeef"}',
    )
    monkeypatch.setattr(
        "app.api.routers.tasks.generate_game",
        types.SimpleNamespace(delay=lambda *a, **k: None),
    )
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()
