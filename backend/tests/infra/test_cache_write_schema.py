import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite://")

from alembic import command
from alembic.config import Config
from sqlalchemy import BigInteger, create_engine, inspect, text

from app.core.config import settings
from app.models import LLMCall
from app.schemas import AgentUsageEventOut, AgentUsageProgressEventOut


BACKEND_DIR = Path(__file__).resolve().parents[2]


def _migration_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def test_llm_call_cache_write_tokens_model_contract():
    column = LLMCall.__table__.c.cache_write_tokens

    assert isinstance(column.type, BigInteger)
    assert column.nullable is False
    assert column.default.arg == 0
    assert str(column.server_default.arg) == "0"


def test_usage_event_schemas_expose_cache_write_tokens():
    usage_fields = AgentUsageEventOut.model_json_schema()["properties"]
    progress_fields = AgentUsageProgressEventOut.model_json_schema()["properties"]

    assert "cached_tokens" in usage_fields
    assert "cache_write_tokens" in usage_fields
    assert "cached_tokens" in progress_fields
    assert "cache_write_tokens" in progress_fields
    assert AgentUsageEventOut(
        type="usage", cached_tokens=768, cache_write_tokens=1536
    ).model_dump()["cache_write_tokens"] == 1536
    assert AgentUsageProgressEventOut(
        type="usage_progress", cached_tokens=768, cache_write_tokens=1536
    ).model_dump()["cache_write_tokens"] == 1536


def test_cache_write_tokens_migration_backfills_and_defaults(tmp_path, monkeypatch):
    db_path = tmp_path / "cache-write-tokens.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = _migration_config()

    command.upgrade(config, "0012_llm_call_response_ledger")
    engine = create_engine(url)
    existing_id = str(uuid4())
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO llm_calls (
                    id, model, prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, retried, created_at
                ) VALUES (
                    :id, 'gpt-5.6-sol', 100, 20, 120, 10, 0, :created_at
                )
                """
            ),
            {"id": existing_id, "created_at": now},
        )
    engine.dispose()

    command.upgrade(config, "0013_llm_call_cache_write_tokens")
    engine = create_engine(url)
    columns = {column["name"]: column for column in inspect(engine).get_columns("llm_calls")}
    assert isinstance(columns["cache_write_tokens"]["type"], BigInteger)
    assert columns["cache_write_tokens"]["nullable"] is False

    defaulted_id = str(uuid4())
    with engine.begin() as connection:
        existing_value = connection.execute(
            text("SELECT cache_write_tokens FROM llm_calls WHERE id = :id"),
            {"id": existing_id},
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO llm_calls (
                    id, model, prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, retried, created_at
                ) VALUES (
                    :id, 'gpt-5.6-sol', 50, 10, 60, 5, 0, :created_at
                )
                """
            ),
            {"id": defaulted_id, "created_at": now},
        )
        defaulted_value = connection.execute(
            text("SELECT cache_write_tokens FROM llm_calls WHERE id = :id"),
            {"id": defaulted_id},
        ).scalar_one()
    assert existing_value == 0
    assert defaulted_value == 0
    engine.dispose()

    command.downgrade(config, "0012_llm_call_response_ledger")
    engine = create_engine(url)
    assert "cache_write_tokens" not in {
        column["name"] for column in inspect(engine).get_columns("llm_calls")
    }
    engine.dispose()
