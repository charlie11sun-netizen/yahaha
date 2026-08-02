"""record the conversation predecessor of each LLM call

Revision ID: 0014_llm_call_prev_response_id
Revises: 0013_llm_call_cache_write_tokens
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


# NB: alembic_version.version_num is VARCHAR(32) — keep revision ids short.
revision = "0014_llm_call_prev_response_id"
down_revision = "0013_llm_call_cache_write_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_calls",
        sa.Column("previous_response_id", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "previous_response_id")
