"""add dimension to generation_tasks

Revision ID: 0002_add_task_dimension
Revises: 0001_initial
Create Date: 2026-06-20

给生成任务加 2d/3d 维度列；既有行回填 "2d"。
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_add_task_dimension"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("dimension", sa.String(length=8), nullable=False, server_default="2d"),
    )


def downgrade() -> None:
    op.drop_column("generation_tasks", "dimension")
