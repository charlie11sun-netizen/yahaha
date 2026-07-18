"""align decision trace counters with non-null ORM defaults

Revision ID: 0019_trace_counter_nonnull
Revises: 0018_cache_trace_dimensions
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_trace_counter_nonnull"
down_revision = "0018_cache_trace_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("agent_steps", "agent_trace_events"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET asset_request_count = 0 "
                "WHERE asset_request_count IS NULL"
            )
        )
        op.execute(
            sa.text(f"UPDATE {table} SET latency_ms = 0 WHERE latency_ms IS NULL")
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "asset_request_count",
                existing_type=sa.Integer(),
                nullable=False,
                server_default="0",
            )
            batch.alter_column(
                "latency_ms",
                existing_type=sa.Integer(),
                nullable=False,
                server_default="0",
            )


def downgrade() -> None:
    for table in ("agent_trace_events", "agent_steps"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "latency_ms",
                existing_type=sa.Integer(),
                nullable=True,
                server_default="0",
            )
            batch.alter_column(
                "asset_request_count",
                existing_type=sa.Integer(),
                nullable=True,
                server_default="0",
            )
