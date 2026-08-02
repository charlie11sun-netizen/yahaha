"""persist cache-analysis dimensions and Opik trace correlation

Revision ID: 0018_cache_trace_dimensions
Revises: 0017_design_contract
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_cache_trace_dimensions"
down_revision = "0017_design_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("opik_trace_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_generation_tasks_opik_trace_id",
        "generation_tasks",
        ["opik_trace_id"],
        unique=False,
    )

    columns = (
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("provider_route", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=120), nullable=True),
        sa.Column("contract_hash", sa.String(length=64), nullable=True),
        sa.Column("contract_revision", sa.Integer(), nullable=True),
        sa.Column("prompt_cache_key_hash", sa.String(length=64), nullable=True),
        sa.Column("prompt_cache_namespace", sa.String(length=160), nullable=True),
        sa.Column("prompt_cache_mode", sa.String(length=24), nullable=True),
        sa.Column("prompt_cache_ttl", sa.String(length=24), nullable=True),
        sa.Column("cache_prefix_hash", sa.String(length=64), nullable=True),
        sa.Column("toolset_hash", sa.String(length=64), nullable=True),
        sa.Column("cache_bypass_reason", sa.String(length=120), nullable=True),
        sa.Column(
            "cache_read_reported",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "cache_write_reported",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    for column in columns:
        op.add_column("llm_calls", column)
    op.create_index(
        "ix_llm_calls_prompt_cache_key_hash",
        "llm_calls",
        ["prompt_cache_key_hash"],
        unique=False,
    )
    op.create_index(
        "ix_llm_calls_workflow_request_index",
        "llm_calls",
        ["workflow_name", "request_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_llm_calls_workflow_request_index", table_name="llm_calls")
    op.drop_index("ix_llm_calls_prompt_cache_key_hash", table_name="llm_calls")
    for name in (
        "cache_write_reported",
        "cache_read_reported",
        "cache_bypass_reason",
        "toolset_hash",
        "cache_prefix_hash",
        "prompt_cache_ttl",
        "prompt_cache_mode",
        "prompt_cache_namespace",
        "prompt_cache_key_hash",
        "contract_revision",
        "contract_hash",
        "prompt_version",
        "provider_route",
        "provider",
    ):
        op.drop_column("llm_calls", name)
    op.drop_index("ix_generation_tasks_opik_trace_id", table_name="generation_tasks")
    op.drop_column("generation_tasks", "opik_trace_id")
