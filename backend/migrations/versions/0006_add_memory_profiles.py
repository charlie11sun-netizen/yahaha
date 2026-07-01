"""add memory profiles and version history

Revision ID: 0006_add_memory_profiles
Revises: 0005_add_memory_embeddings
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_add_memory_profiles"
down_revision = "0005_add_memory_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("profile_key", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("evidence_span", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("scope_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("explicitness", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_memory_id", sa.String(length=36), nullable=False),
        sa.Column("conflicts_with_id", sa.String(length=36), nullable=True),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("utility_score", sa.Numeric(4, 3), nullable=False, server_default="0.5"),
        sa.Column("utility_observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_supported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conflicts_with_id"], ["memory_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_memory_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_memory_profile_lookup",
        "memory_profiles",
        ["user_id", "scope_type", "scope_id", "status", "category"],
    )
    op.create_index(
        "idx_memory_profile_conflict",
        "memory_profiles",
        ["user_id", "scope_type", "scope_id", "profile_key", "status"],
    )
    for name in (
        "user_id", "scope_type", "scope_id", "profile_key", "category", "status",
        "source_memory_id", "conflicts_with_id",
    ):
        op.create_index(f"ix_memory_profiles_{name}", "memory_profiles", [name])

    op.create_table(
        "memory_profile_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("source_memory_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["memory_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_memory_id"], ["memory_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_profile_versions_profile_id", "memory_profile_versions", ["profile_id"])
    op.create_index("ix_memory_profile_versions_operation", "memory_profile_versions", ["operation"])
    op.create_index(
        "ix_memory_profile_versions_source_memory_id", "memory_profile_versions", ["source_memory_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_profile_versions_source_memory_id", table_name="memory_profile_versions")
    op.drop_index("ix_memory_profile_versions_operation", table_name="memory_profile_versions")
    op.drop_index("ix_memory_profile_versions_profile_id", table_name="memory_profile_versions")
    op.drop_table("memory_profile_versions")
    for name in reversed((
        "user_id", "scope_type", "scope_id", "profile_key", "category", "status",
        "source_memory_id", "conflicts_with_id",
    )):
        op.drop_index(f"ix_memory_profiles_{name}", table_name="memory_profiles")
    op.drop_index("idx_memory_profile_conflict", table_name="memory_profiles")
    op.drop_index("idx_memory_profile_lookup", table_name="memory_profiles")
    op.drop_table("memory_profiles")
