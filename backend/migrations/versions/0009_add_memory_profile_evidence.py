"""add explicit memory evidence to profile links

Revision ID: 0009_add_memory_profile_evidence
Revises: 0008_add_memory_profile_embeddings
Create Date: 2026-07-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_add_memory_profile_evidence"
down_revision = "0008_add_memory_profile_embeddings"
branch_labels = None
depends_on = None

_SUPPORTING_OPERATIONS = {"created", "candidate", "reinforced", "auto_promoted", "corrected"}


def upgrade() -> None:
    op.create_table(
        "memory_profile_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_span", sa.Text(), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("scope_confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("explicitness", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["memory_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "memory_id", name="uq_memory_profile_evidence"),
    )
    op.create_index(
        "ix_memory_profile_evidence_profile_id", "memory_profile_evidence", ["profile_id"]
    )
    op.create_index(
        "ix_memory_profile_evidence_memory_id", "memory_profile_evidence", ["memory_id"]
    )
    op.create_index(
        "ix_memory_profile_evidence_is_active", "memory_profile_evidence", ["is_active"]
    )

    bind = op.get_bind()
    profiles = sa.table(
        "memory_profiles",
        sa.column("id", sa.String),
        sa.column("source_memory_id", sa.String),
        sa.column("evidence_span", sa.Text),
        sa.column("value_text", sa.Text),
        sa.column("summary_text", sa.Text),
        sa.column("confidence", sa.Numeric),
        sa.column("scope_confidence", sa.Numeric),
        sa.column("explicitness", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    versions = sa.table(
        "memory_profile_versions",
        sa.column("profile_id", sa.String),
        sa.column("source_memory_id", sa.String),
        sa.column("operation", sa.String),
        sa.column("snapshot_json", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    evidence = sa.table(
        "memory_profile_evidence",
        sa.column("id", sa.String),
        sa.column("profile_id", sa.String),
        sa.column("memory_id", sa.String),
        sa.column("evidence_span", sa.Text),
        sa.column("value_text", sa.Text),
        sa.column("summary_text", sa.Text),
        sa.column("confidence", sa.Numeric),
        sa.column("scope_confidence", sa.Numeric),
        sa.column("explicitness", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    import uuid

    rows: dict[tuple[str, str], dict] = {}
    for row in bind.execute(sa.select(profiles)).mappings():
        if not row["source_memory_id"]:
            continue
        rows[(row["id"], row["source_memory_id"])] = {
            "id": str(uuid.uuid4()),
            "profile_id": row["id"],
            "memory_id": row["source_memory_id"],
            "evidence_span": row["evidence_span"],
            "value_text": row["value_text"],
            "summary_text": row["summary_text"],
            "confidence": row["confidence"],
            "scope_confidence": row["scope_confidence"],
            "explicitness": row["explicitness"],
            "is_active": True,
            "created_at": row["created_at"],
        }
    version_rows = list(bind.execute(sa.select(versions)).mappings())
    last_correction = {}
    for row in version_rows:
        if row["operation"] == "corrected" and row["created_at"]:
            current = last_correction.get(row["profile_id"])
            if not current or row["created_at"] > current:
                last_correction[row["profile_id"]] = row["created_at"]
    for row in version_rows:
        if not row["source_memory_id"] or row["operation"] not in _SUPPORTING_OPERATIONS:
            continue
        snapshot = row["snapshot_json"] or {}
        key = (row["profile_id"], row["source_memory_id"])
        rows.setdefault(
            key,
            {
                "id": str(uuid.uuid4()),
                "profile_id": row["profile_id"],
                "memory_id": row["source_memory_id"],
                "evidence_span": snapshot.get("evidence_span") or snapshot.get("summary_text") or "",
                "value_text": snapshot.get("value_text") or "",
                "summary_text": snapshot.get("summary_text") or snapshot.get("evidence_span") or "",
                "confidence": snapshot.get("confidence", 0.8),
                "scope_confidence": snapshot.get("scope_confidence", 0.8),
                "explicitness": snapshot.get("explicitness") or "inferred",
                "is_active": not last_correction.get(row["profile_id"])
                or not row["created_at"]
                or row["created_at"] >= last_correction[row["profile_id"]],
                "created_at": row["created_at"],
            },
        )
    if rows:
        op.bulk_insert(evidence, list(rows.values()))


def downgrade() -> None:
    op.drop_index("ix_memory_profile_evidence_is_active", table_name="memory_profile_evidence")
    op.drop_index("ix_memory_profile_evidence_memory_id", table_name="memory_profile_evidence")
    op.drop_index("ix_memory_profile_evidence_profile_id", table_name="memory_profile_evidence")
    op.drop_table("memory_profile_evidence")
