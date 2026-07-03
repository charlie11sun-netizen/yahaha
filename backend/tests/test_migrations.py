"""迁移链健康测试。

守住两条底线（旧 0001 基线曾用 create_all 引用当前模型，导致全新库
`alembic upgrade head` 在 0002 撞列 —— 生产 migrate 服务对新主机首次部署即失败）：
1. 空库可以从零重放整条迁移链；
2. 重放结果与 ORM 模型（create_all）的 schema 完全一致，防止两轨漂移。
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_upgrade_head(db_path: Path) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")


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
