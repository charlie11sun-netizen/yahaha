"""persist agent decision-chain and asset provenance fields

Revision ID: 0016_decision_chain_trace
Revises: 0015_agent_trace_retention
Create Date: 2026-07-18
"""

from alembic import context, op
import sqlalchemy as sa


revision = "0016_decision_chain_trace"
down_revision = "0015_agent_trace_retention"
branch_labels = None
depends_on = None


_STEP_COLUMNS = {
    "contract_version": sa.String(length=80),
    "prompt_version": sa.String(length=120),
    "model": sa.String(length=120),
    "provider": sa.String(length=80),
    "input_artifact_id": sa.String(length=255),
    "output_artifact_id": sa.String(length=255),
    "input_artifact_ids_json": sa.Text(),
    "output_artifact_ids_json": sa.Text(),
    "adopted_plan": sa.Text(),
    "rejected_plans_json": sa.Text(),
    "asset_request_count": sa.Integer(),
    "qa_result_json": sa.Text(),
    "repair_reason": sa.Text(),
    "impact_scope_json": sa.Text(),
    "latency_ms": sa.Integer(),
    "cost_usd": sa.Numeric(10, 6),
    "runtime_consumed": sa.Boolean(),
    "decision_json": sa.Text(),
}

_EVENT_COLUMNS = {
    # ``model`` already exists on agent_trace_events since 0011; keep the
    # shared field list for the other decision columns without emitting a
    # duplicate ALTER TABLE in offline SQL generation.
    **{name: column for name, column in _STEP_COLUMNS.items() if name != "model"},
    "asset_id": sa.String(length=255),
    "prompt_hash": sa.String(length=64),
    "requested_states_json": sa.Text(),
    "returned_dimensions": sa.String(length=64),
    "postprocess_checks_json": sa.Text(),
    "frame_count": sa.Integer(),
    "consumer_refs_json": sa.Text(),
    "coverage_result": sa.Text(),
}


def _add_missing(table: str, columns: dict[str, sa.types.TypeEngine]) -> None:
    bind = op.get_bind()
    if context.is_offline_mode():
        existing: set[str] = set()
    else:
        inspector = sa.inspect(bind)
        existing = {column["name"] for column in inspector.get_columns(table)}
    for name, column_type in columns.items():
        if name not in existing:
            kwargs = {"server_default": "0"} if name in {"asset_request_count", "latency_ms"} else {}
            op.add_column(table, sa.Column(name, column_type, nullable=True, **kwargs))


def upgrade() -> None:
    _add_missing("agent_steps", _STEP_COLUMNS)
    _add_missing("agent_trace_events", _EVENT_COLUMNS)
    bind = op.get_bind()
    if context.is_offline_mode():
        indexes: set[str] = set()
    else:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("agent_trace_events")}
    if "ix_agent_trace_events_asset_id" not in indexes:
        op.create_index(
            "ix_agent_trace_events_asset_id",
            "agent_trace_events",
            ["asset_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_agent_trace_events_asset_id", table_name="agent_trace_events")
    for name in reversed(tuple(_EVENT_COLUMNS)):
        op.drop_column("agent_trace_events", name)
    for name in reversed(tuple(_STEP_COLUMNS)):
        op.drop_column("agent_steps", name)
