"""resume snapshot: per-node state checkpoint for retry-from-failed-node

Revision ID: 0005_resume_snapshot
Revises: 0004_product_loop
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_resume_snapshot"
down_revision = "0004_product_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_tasks") as batch_op:
        batch_op.add_column(sa.Column("state_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("generation_tasks") as batch_op:
        batch_op.drop_column("state_json")
