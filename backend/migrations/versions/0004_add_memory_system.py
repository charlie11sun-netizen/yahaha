"""add memory system tables

Revision ID: 0004_add_memory_system
Revises: 0003_add_task_revision_context
Create Date: 2026-06-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_add_memory_system"
down_revision = "0003_add_task_revision_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_settings",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_cross_game_memory", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_memory_extraction", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_task_id", sa.String(length=36), nullable=True),
        sa.Column("source_game_id", sa.String(length=36), nullable=True),
        sa.Column("source_version", sa.String(length=20), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_game_id"], ["games.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_task_id"], ["generation_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["memory_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_memory_scope", "memory_items", ["user_id", "scope_type", "scope_id", "status"])
    op.create_index("idx_memory_category", "memory_items", ["user_id", "category", "status"])
    op.create_index("ix_memory_items_user_id", "memory_items", ["user_id"])
    op.create_index("ix_memory_items_scope_type", "memory_items", ["scope_type"])
    op.create_index("ix_memory_items_scope_id", "memory_items", ["scope_id"])
    op.create_index("ix_memory_items_category", "memory_items", ["category"])
    op.create_index("ix_memory_items_source_type", "memory_items", ["source_type"])
    op.create_index("ix_memory_items_source_task_id", "memory_items", ["source_task_id"])
    op.create_index("ix_memory_items_source_game_id", "memory_items", ["source_game_id"])
    op.create_index("ix_memory_items_pinned", "memory_items", ["pinned"])
    op.create_index("ix_memory_items_status", "memory_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_memory_items_status", table_name="memory_items")
    op.drop_index("ix_memory_items_pinned", table_name="memory_items")
    op.drop_index("ix_memory_items_source_game_id", table_name="memory_items")
    op.drop_index("ix_memory_items_source_task_id", table_name="memory_items")
    op.drop_index("ix_memory_items_source_type", table_name="memory_items")
    op.drop_index("ix_memory_items_category", table_name="memory_items")
    op.drop_index("ix_memory_items_scope_id", table_name="memory_items")
    op.drop_index("ix_memory_items_scope_type", table_name="memory_items")
    op.drop_index("ix_memory_items_user_id", table_name="memory_items")
    op.drop_index("idx_memory_category", table_name="memory_items")
    op.drop_index("idx_memory_scope", table_name="memory_items")
    op.drop_table("memory_items")
    op.drop_table("memory_settings")
