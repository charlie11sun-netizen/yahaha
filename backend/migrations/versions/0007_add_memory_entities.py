"""add memory entity index and evidence links

Revision ID: 0007_add_memory_entities
Revises: 0006_add_memory_profiles
Create Date: 2026-07-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_add_memory_entities"
down_revision = "0006_add_memory_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("canonical_name", sa.String(length=240), nullable=False),
        sa.Column("normalized_name", sa.String(length=240), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "entity_type", "normalized_name", name="uq_memory_entity_identity"
        ),
    )
    for name in ("user_id", "entity_type", "normalized_name"):
        op.create_index(f"ix_memory_entities_{name}", "memory_entities", [name])

    op.create_table(
        "memory_entity_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="claim"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["memory_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", "memory_id", name="uq_memory_entity_link"),
    )
    op.create_index("ix_memory_entity_links_entity_id", "memory_entity_links", ["entity_id"])
    op.create_index("ix_memory_entity_links_memory_id", "memory_entity_links", ["memory_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_entity_links_memory_id", table_name="memory_entity_links")
    op.drop_index("ix_memory_entity_links_entity_id", table_name="memory_entity_links")
    op.drop_table("memory_entity_links")
    for name in reversed(("user_id", "entity_type", "normalized_name")):
        op.drop_index(f"ix_memory_entities_{name}", table_name="memory_entities")
    op.drop_table("memory_entities")
