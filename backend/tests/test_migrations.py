"""迁移链健康测试。

守住两条底线（旧 0001 基线曾用 create_all 引用当前模型，导致全新库
`alembic upgrade head` 在 0002 撞列 —— 生产 migrate 服务对新主机首次部署即失败）：
1. 空库可以从零重放整条迁移链；
2. 重放结果与 ORM 模型（create_all）的 schema 完全一致，防止两轨漂移。
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_upgrade_head(db_path: Path, revision: str = "head") -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, revision)


def _schema_snapshot(engine) -> dict:
    """表 → (列名/可空/类型串, 索引名/唯一性)。类型串在同方言下双方应渲染一致。"""
    insp = inspect(engine)
    snapshot = {}
    for table in insp.get_table_names():
        if table == "alembic_version":
            continue
        columns = {
            c["name"]: (bool(c["nullable"]), str(c["type"]).upper())
            for c in insp.get_columns(table)
        }
        indexes = {(ix["name"], bool(ix["unique"])) for ix in insp.get_indexes(table)}
        snapshot[table] = {"columns": columns, "indexes": indexes}
    return snapshot


def test_upgrade_head_replays_on_fresh_db_and_matches_orm(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    _run_upgrade_head(db_path)

    migrated = create_engine(f"sqlite:///{db_path.as_posix()}")
    orm = create_engine("sqlite://")
    Base.metadata.create_all(bind=orm)

    migrated_schema = _schema_snapshot(migrated)
    orm_schema = _schema_snapshot(orm)

    assert set(migrated_schema) == set(orm_schema), (
        f"表集合不一致: 迁移多出 {set(migrated_schema) - set(orm_schema)}, "
        f"缺少 {set(orm_schema) - set(migrated_schema)}"
    )
    for table in orm_schema:
        assert migrated_schema[table]["columns"] == orm_schema[table]["columns"], (
            f"{table} 列不一致:\n迁移: {migrated_schema[table]['columns']}\nORM: {orm_schema[table]['columns']}"
        )
        assert migrated_schema[table]["indexes"] == orm_schema[table]["indexes"], (
            f"{table} 索引不一致:\n迁移: {migrated_schema[table]['indexes']}\nORM: {orm_schema[table]['indexes']}"
        )

    # 表达式部分唯一索引不会被 inspector 反射（上面双方都跳过），单独确认迁移真的建了它
    with migrated.connect() as conn:
        from sqlalchemy import text

        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_memory_profile_active_identity'")
        ).fetchone()
    assert row is not None and "UNIQUE" in row[0].upper() and "status = 'active'" in row[0]


def test_outbox_migration_backfills_only_pending_tasks(tmp_path, monkeypatch):
    db_path = tmp_path / "outbox-backfill.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    _run_upgrade_head(db_path, "0007_fastapi_users")

    user_id = str(uuid4())
    task_ids = {status: str(uuid4()) for status in ("pending", "running", "failed")}
    now = datetime.now(timezone.utc)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (
                    id, email, display_name, avatar_initial, is_active, created_at
                ) VALUES (
                    :id, :email, :display_name, :avatar_initial, :is_active, :created_at
                )
                """
            ),
            {
                "id": user_id,
                "email": "migration@example.com",
                "display_name": "Migration",
                "avatar_initial": "M",
                "is_active": True,
                "created_at": now,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO generation_tasks (
                    id, user_id, idea, status, current_step, tokens_used,
                    repair_attempts, max_repair_attempts, replan_attempts,
                    max_replan_attempts, created_at
                ) VALUES (
                    :id, :user_id, :idea, :status, 0, 0, 0, 2, 0, 1, :created_at
                )
                """
            ),
            [
                {
                    "id": task_id,
                    "user_id": user_id,
                    "idea": status,
                    "status": status,
                    "created_at": now,
                }
                for status, task_id in task_ids.items()
            ],
        )
    engine.dispose()

    _run_upgrade_head(db_path)

    engine = create_engine(url)
    with engine.connect() as conn:
        generations = dict(
            conn.execute(text("SELECT id, dispatch_generation FROM generation_tasks")).all()
        )
        outbox_rows = conn.execute(
            text(
                """
                SELECT task_id, dispatch_generation, request_id, attempts,
                       available_at, last_attempt_at, published_at, last_error, created_at
                FROM generation_dispatch_outbox
                """
            )
        ).mappings().all()
    engine.dispose()

    assert generations == {
        task_ids["pending"]: 1,
        task_ids["running"]: 0,
        task_ids["failed"]: 0,
    }
    assert len(outbox_rows) == 1
    event = outbox_rows[0]
    assert event["task_id"] == task_ids["pending"]
    assert event["dispatch_generation"] == 1
    assert event["request_id"].startswith("migration:")
    assert event["attempts"] == 0
    assert event["available_at"] is not None and event["created_at"] is not None
    assert event["last_attempt_at"] is None
    assert event["published_at"] is None
    assert event["last_error"] is None


def test_outbox_migration_renders_postgresql_offline_sql(monkeypatch, capsys):
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql+psycopg://user:pass@localhost/gameweave",
    )
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    command.upgrade(
        cfg,
        "0007_fastapi_users:0008_generation_dispatch_outbox",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "CREATE TABLE generation_dispatch_outbox" in sql
    assert "gen_random_uuid()" in sql
    assert "SET dispatch_generation = 1" in sql
