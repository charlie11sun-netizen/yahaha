"""测试夹具：SQLite 内存库 + 覆盖 get_db / S3 / Celery / 限流，免起外部依赖。"""
import os

# 必须在导入 app 之前设置，避免 app.db.session 加载 psycopg 方言
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("TASK_EVENTS_ENABLED", "false")

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _TESTS_DIR.parent
_REPO_ROOT = _BACKEND_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_BACKEND_DIR))

import app.models  # noqa: E402,F401
from app.api import deps  # noqa: E402
from app.core.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_asset_review_settings(monkeypatch):
    """单测默认关闭语义评审,与部署 .env 解耦。

    容器 .env 开着 ASSET_SEMANTIC_REVIEW_ENABLED=true 时,generate_game_assets
    流程测试会对着 stub 画布发起真实 VLM/图像网关调用并被判全格失败(2026-07-19
    第十二轮套件排查)。需要评审路径的测试自行 monkeypatch 开启。
    """
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", False)


@pytest.fixture(autouse=True)
def _isolated_telemetry_context():
    """每个测试后强制清空 telemetry contextvars,测试间禁互相污染。

    事件发布/步骤上下文等应用路径会在进程内 bind_context;生产由 worker 按任务
    生命周期清理,单测进程里无人负责——泄漏的 task/step/workflow 标签会把后续
    测试的 llm 账本行打错(2026-07-26 tests 分域换序后暴露:test_task_events
    跑完后,test_observability 记账行的 workflow_name 变成 'Code Generation')。
    """
    yield
    from app.core.telemetry import clear_context

    clear_context()


from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Game, GameVersion, User  # noqa: E402
from app.models.common import GameSource, GameStatus, now_utc  # noqa: E402
from app.storage import s3  # noqa: E402


def _register_user(
    client,
    email: str = "test@test.com",
    password: str = "secret1",
    display_name: str = "Test",
):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )


def _session_headers(response):
    session = response.cookies.get(settings.AUTH_COOKIE_NAME)
    assert session
    return {
        "Cookie": f"{settings.AUTH_COOKIE_NAME}={session}",
        "Origin": "http://localhost:3000",
    }


def auth_headers(
    client,
    email: str = "test@test.com",
    password: str = "secret1",
    display_name: str = "Test",
):
    reg = _register_user(client, email=email, password=password, display_name=display_name)
    return _session_headers(reg)


def auth_user(
    client,
    email: str = "test@test.com",
    password: str = "secret1",
    display_name: str = "Test",
):
    reg = _register_user(client, email=email, password=password, display_name=display_name)
    return _session_headers(reg), reg.json()["user"]["id"]


def seed_game(
    factory,
    title: str = "Test Game",
    status=GameStatus.PUBLISHED,
    plays: int = 5,
    author_id: str | None = None,
    *,
    summary: str = "a summary",
    genre: str = "arcade",
    source=GameSource.SEED,
    current_version: str = "v1",
    likes: int = 0,
    author_email: str | None = None,
    author_name: str = "Author",
    author_initial: str = "A",
    with_version: bool = True,
    return_author: bool = False,
):
    db = factory()
    try:
        if author_id is None:
            user = User(
                email=author_email or f"{title}@seed.com",
                display_name=author_name,
                avatar_initial=author_initial,
            )
            db.add(user)
            db.flush()
            author_id = user.id

        game = Game(
            author_id=author_id,
            title=title,
            summary=summary,
            genre=genre,
            status=status,
            current_version=current_version,
            source=source,
            plays_count=plays,
            likes_count=likes,
            published_at=now_utc(),
        )
        db.add(game)
        db.flush()

        if with_version:
            db.add(
                GameVersion(
                    game_id=game.id,
                    version=current_version,
                    manifest_key=f"games/{game.id}/{current_version}/manifest.json",
                    bundle_key=f"games/{game.id}/{current_version}/index.html",
                    sha256=f"sha-{current_version}",
                    size_bytes=111,
                )
            )

        db.commit()
        result = (game.id, author_id) if return_author else game.id
        return result
    finally:
        db.close()


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
    test_client = TestClient(app, headers={"Origin": "http://localhost:3000"})
    yield test_client
    app.dependency_overrides.clear()
