"""migrate memory embeddings from JSON to pgvector

Revision ID: 0011_memory_pgvector
Revises: 0010_add_memory_integrity_constraints
Create Date: 2026-07-02
"""

from alembic import op

revision = "0011_memory_pgvector"
down_revision = "0010_add_memory_integrity_constraints"
branch_labels = None
depends_on = None

DIMENSIONS = 1536
TABLES = (
    ("memory_items", "ix_memory_items_embedding_hnsw"),
    ("memory_profiles", "ix_memory_profiles_embedding_hnsw"),
    ("memory_entities", "ix_memory_entities_embedding_hnsw"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for table, index_name in TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN embedding_vector vector({DIMENSIONS})")
        op.execute(
            f"UPDATE {table} SET embedding_vector = embedding::text::vector({DIMENSIONS}) "
            f"WHERE embedding IS NOT NULL AND json_array_length(embedding) = {DIMENSIONS}"
        )
        op.execute(f"ALTER TABLE {table} DROP COLUMN embedding")
        op.execute(f"ALTER TABLE {table} RENAME COLUMN embedding_vector TO embedding")
        op.execute(
            f"CREATE INDEX {index_name} ON {table} USING hnsw "
            "(embedding vector_cosine_ops) WHERE embedding IS NOT NULL"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, index_name in reversed(TABLES):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
        op.execute(f"ALTER TABLE {table} ADD COLUMN embedding_json JSON")
        op.execute(
            f"UPDATE {table} SET embedding_json = embedding::text::json "
            "WHERE embedding IS NOT NULL"
        )
        op.execute(f"ALTER TABLE {table} DROP COLUMN embedding")
        op.execute(f"ALTER TABLE {table} RENAME COLUMN embedding_json TO embedding")
