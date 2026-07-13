"""record prompt cache reads per LLM call

Revision ID: 0010_llm_call_cached_tokens
Revises: 0009_langgraph_checkpoints
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_llm_call_cached_tokens"
down_revision = "0009_langgraph_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_calls",
        sa.Column("cached_tokens", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "cached_tokens")
