"""add memory embeddings for hybrid retrieval

Revision ID: 0005_add_memory_embeddings
Revises: 0004_add_memory_system
Create Date: 2026-06-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_add_memory_embeddings"
down_revision = "0004_add_memory_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_items", sa.Column("embedding", sa.JSON(), nullable=True))
    op.add_column("memory_items", sa.Column("embedding_model", sa.String(length=100), nullable=True))
    op.add_column("memory_items", sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_items", "embedding_updated_at")
    op.drop_column("memory_items", "embedding_model")
    op.drop_column("memory_items", "embedding")
