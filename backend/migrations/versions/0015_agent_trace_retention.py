"""index detailed trace events for retention cleanup

Revision ID: 0015_agent_trace_retention
Revises: 0014_llm_call_prev_response_id
Create Date: 2026-07-18
"""

from alembic import context, op
import sqlalchemy as sa


revision = "0015_agent_trace_retention"
down_revision = "0014_llm_call_prev_response_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    offline = context.is_offline_mode()
    inspector = None if offline else sa.inspect(bind)
    index_names = (
        set()
        if inspector is None
        else {
            index["name"]
            for index in inspector.get_indexes("agent_trace_events")
        }
    )
    if offline or "ix_agent_trace_events_created_at" not in index_names:
        op.create_index(
            "ix_agent_trace_events_created_at",
            "agent_trace_events",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_trace_events_created_at",
        table_name="agent_trace_events",
    )
