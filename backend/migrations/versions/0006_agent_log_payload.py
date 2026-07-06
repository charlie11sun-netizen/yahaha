"""agent logs: structured payload for live activity events

Revision ID: 0006_agent_log_payload
Revises: 0005_resume_snapshot
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_agent_log_payload"
down_revision = "0005_resume_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_logs") as batch_op:
        batch_op.add_column(sa.Column("payload_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_logs") as batch_op:
        batch_op.drop_column("payload_json")
