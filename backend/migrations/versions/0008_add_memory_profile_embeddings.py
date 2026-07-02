"""add memory profile embeddings for semantic key adoption

Revision ID: 0008_add_memory_profile_embeddings
Revises: 0007_add_memory_entities
Create Date: 2026-07-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_add_memory_profile_embeddings"
down_revision = "0007_add_memory_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_profiles", sa.Column("embedding", sa.JSON(), nullable=True))
    op.add_column("memory_profiles", sa.Column("embedding_model", sa.String(length=100), nullable=True))
    op.add_column("memory_profiles", sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_profiles", "embedding_updated_at")
    op.drop_column("memory_profiles", "embedding_model")
    op.drop_column("memory_profiles", "embedding")
