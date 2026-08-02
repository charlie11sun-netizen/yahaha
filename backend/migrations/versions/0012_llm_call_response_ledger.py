"""make llm_calls an idempotent per-response usage ledger

Revision ID: 0012_llm_call_response_ledger
Revises: 0011_agent_trace_events
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_llm_call_response_ledger"
down_revision = "0011_agent_trace_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # COUNT-based allocation historically produced duplicate sequence numbers
    # when heartbeat and tool threads logged concurrently.  Normalize first so
    # the database can enforce a durable, monotonic cursor per step.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY step_id ORDER BY created_at, id
                   ) - 1 AS normalized_seq
            FROM agent_logs
        )
        UPDATE agent_logs AS target
        SET seq = ranked.normalized_seq
        FROM ranked
        WHERE target.id = ranked.id
        """
    )
    with op.batch_alter_table(
        "agent_logs", table_kwargs={"sqlite_autoincrement": True}
    ) as batch_op:
        batch_op.create_unique_constraint("uq_agent_logs_step_seq", ["step_id", "seq"])
    op.add_column("llm_calls", sa.Column("run_id", sa.String(length=36), nullable=True))
    op.add_column("llm_calls", sa.Column("agent", sa.String(length=120), nullable=True))
    op.add_column("llm_calls", sa.Column("workflow_name", sa.String(length=160), nullable=True))
    op.add_column(
        "llm_calls", sa.Column("provider_response_id", sa.String(length=160), nullable=True)
    )
    op.add_column("llm_calls", sa.Column("request_index", sa.Integer(), nullable=True))
    op.add_column(
        "llm_calls",
        sa.Column("status", sa.String(length=24), nullable=False, server_default="completed"),
    )
    op.add_column("llm_calls", sa.Column("error_code", sa.String(length=80), nullable=True))
    op.create_index(op.f("ix_llm_calls_run_id"), "llm_calls", ["run_id"], unique=False)
    with op.batch_alter_table("llm_calls") as batch_op:
        batch_op.create_unique_constraint(
            "uq_llm_calls_provider_response_id", ["provider_response_id"]
        )
        batch_op.create_unique_constraint(
            "uq_llm_calls_run_request", ["run_id", "request_index"]
        )


def downgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch_op:
        batch_op.drop_constraint("uq_llm_calls_run_request", type_="unique")
        batch_op.drop_constraint("uq_llm_calls_provider_response_id", type_="unique")
    op.drop_index(op.f("ix_llm_calls_run_id"), table_name="llm_calls")
    op.drop_column("llm_calls", "error_code")
    op.drop_column("llm_calls", "status")
    op.drop_column("llm_calls", "request_index")
    op.drop_column("llm_calls", "provider_response_id")
    op.drop_column("llm_calls", "workflow_name")
    op.drop_column("llm_calls", "agent")
    op.drop_column("llm_calls", "run_id")
    with op.batch_alter_table("agent_logs") as batch_op:
        batch_op.drop_constraint("uq_agent_logs_step_seq", type_="unique")
