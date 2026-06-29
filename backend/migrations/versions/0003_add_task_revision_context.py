"""add revision context to generation tasks

Revision ID: 0003_add_task_revision_context
Revises: 0002_add_task_dimension
Create Date: 2026-06-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_add_task_revision_context"
down_revision = "0002_add_task_dimension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("task_kind", sa.String(length=20), nullable=False, server_default="generation"),
    )
    op.add_column("generation_tasks", sa.Column("base_game_id", sa.String(length=36), nullable=True))
    op.add_column("generation_tasks", sa.Column("base_version", sa.String(length=20), nullable=True))
    op.add_column("generation_tasks", sa.Column("feedback_text", sa.Text(), nullable=True))
    op.add_column("generation_tasks", sa.Column("feedback_brief", sa.Text(), nullable=True))
    op.create_index("ix_generation_tasks_base_game_id", "generation_tasks", ["base_game_id"])
    op.create_foreign_key(
        "fk_generation_tasks_base_game_id_games",
        "generation_tasks",
        "games",
        ["base_game_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_generation_tasks_base_game_id_games", "generation_tasks", type_="foreignkey")
    op.drop_index("ix_generation_tasks_base_game_id", table_name="generation_tasks")
    op.drop_column("generation_tasks", "feedback_brief")
    op.drop_column("generation_tasks", "feedback_text")
    op.drop_column("generation_tasks", "base_version")
    op.drop_column("generation_tasks", "base_game_id")
    op.drop_column("generation_tasks", "task_kind")
