"""opt-in full-fidelity code-agent trace events

Revision ID: 0011_agent_trace_events
Revises: 0010_llm_call_cached_tokens
Create Date: 2026-07-13
"""

from alembic import context, op
import sqlalchemy as sa


revision = "0011_agent_trace_events"
down_revision = "0010_llm_call_cached_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    offline = context.is_offline_mode()
    inspector = None if offline else sa.inspect(bind)
    table_existed = (
        False if inspector is None else "agent_trace_events" in inspector.get_table_names()
    )
    if offline or not table_existed:
        op.create_table(
            "agent_trace_events",
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("step_id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column("agent", sa.String(length=120), nullable=False),
            sa.Column("model", sa.String(length=120), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("payload_chars", sa.BigInteger(), nullable=False),
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["task_id"], ["generation_tasks.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["step_id"], ["agent_steps.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    index_names = (
        set()
        if inspector is None or not table_existed
        else {
            index["name"] for index in inspector.get_indexes("agent_trace_events")
        }
    )
    indexes = (
        (
            "ix_agent_trace_events_step_id_seq",
            ["step_id", "seq"],
        ),
        (
            "ix_agent_trace_events_task_id_created_at",
            ["task_id", "created_at"],
        ),
        (
            "ix_agent_trace_events_run_id_seq",
            ["run_id", "seq"],
        ),
    )
    for index_name, columns in indexes:
        if offline or index_name not in index_names:
            op.create_index(
                index_name,
                "agent_trace_events",
                columns,
                unique=False,
            )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_trace_events_run_id_seq", table_name="agent_trace_events"
    )
    op.drop_index(
        "ix_agent_trace_events_task_id_created_at",
        table_name="agent_trace_events",
    )
    op.drop_index(
        "ix_agent_trace_events_step_id_seq", table_name="agent_trace_events"
    )
    op.drop_table("agent_trace_events")
