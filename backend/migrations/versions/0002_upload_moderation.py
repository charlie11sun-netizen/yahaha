"""upload hardening and moderation events

Revision ID: 0002_upload_moderation
Revises: 0001_baseline
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_upload_moderation"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_generation_tasks_user_id_status",
        "generation_tasks",
        ["user_id", "status"],
        unique=False,
    )
    op.add_column(
        "assets",
        sa.Column("scan_status", sa.String(length=20), server_default="skipped", nullable=False),
    )
    op.create_table(
        "moderation_events",
        sa.Column("surface", sa.String(length=80), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_excerpt", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_moderation_events_user_id"), "moderation_events", ["user_id"], unique=False)
    op.create_index(
        "ix_moderation_events_surface_created_at",
        "moderation_events",
        ["surface", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_events_surface_created_at", table_name="moderation_events")
    op.drop_index(op.f("ix_moderation_events_user_id"), table_name="moderation_events")
    op.drop_table("moderation_events")
    op.drop_column("assets", "scan_status")
    op.drop_index("ix_generation_tasks_user_id_status", table_name="generation_tasks")
