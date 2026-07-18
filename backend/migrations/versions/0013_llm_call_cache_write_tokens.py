"""record prompt cache writes per LLM call

Revision ID: 0013_llm_call_cache_write_tokens
Revises: 0012_llm_call_response_ledger
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_llm_call_cache_write_tokens"
down_revision = "0012_llm_call_response_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_calls",
        sa.Column(
            "cache_write_tokens",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "cache_write_tokens")
