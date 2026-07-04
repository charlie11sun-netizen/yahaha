"""observability and LLM cost tracking

Revision ID: 0003_observability_cost
Revises: 0002_upload_moderation
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_observability_cost"
down_revision = "0002_upload_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generation_tasks", sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True))
    op.add_column("generation_tasks", sa.Column("failed_stage", sa.String(length=80), nullable=True))
    op.add_column(
        "agent_steps",
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("agent_steps", sa.Column("caused_by_step_id", sa.String(length=36), nullable=True))
    op.create_index(
        op.f("ix_agent_steps_caused_by_step_id"),
        "agent_steps",
        ["caused_by_step_id"],
        unique=False,
    )
    op.create_table(
        "llm_calls",
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("step_id", sa.String(length=36), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=False),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("retried", sa.Boolean(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["step_id"], ["agent_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["generation_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_calls_step_id"), "llm_calls", ["step_id"], unique=False)
    op.create_index(op.f("ix_llm_calls_task_id"), "llm_calls", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_calls_task_id"), table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_step_id"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index(op.f("ix_agent_steps_caused_by_step_id"), table_name="agent_steps")
    op.drop_column("agent_steps", "caused_by_step_id")
    op.drop_column("agent_steps", "attempt")
    op.drop_column("generation_tasks", "failed_stage")
    op.drop_column("generation_tasks", "cost_usd")
