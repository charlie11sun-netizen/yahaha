"""add database-enforced memory invariants

Revision ID: 0010_add_memory_integrity_constraints
Revises: 0009_add_memory_profile_evidence
Create Date: 2026-07-02
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_add_memory_integrity_constraints"
down_revision = "0009_add_memory_profile_evidence"
branch_labels = None
depends_on = None


def _deduplicate_active_profiles() -> None:
    bind = op.get_bind()
    profiles = sa.table(
        "memory_profiles",
        sa.column("id", sa.String),
        sa.column("user_id", sa.String),
        sa.column("scope_type", sa.String),
        sa.column("scope_id", sa.String),
        sa.column("profile_key", sa.String),
        sa.column("status", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    rows = bind.execute(
        sa.select(profiles)
        .where(profiles.c.status == "active")
        .order_by(profiles.c.updated_at.desc(), profiles.c.id.desc())
    ).mappings()
    seen = set()
    duplicate_ids = []
    for row in rows:
        identity = (
            row["user_id"],
            row["scope_type"],
            row["scope_id"] or "",
            row["profile_key"],
        )
        if identity in seen:
            duplicate_ids.append(row["id"])
        else:
            seen.add(identity)
    if duplicate_ids:
        bind.execute(
            profiles.update()
            .where(profiles.c.id.in_(duplicate_ids))
            .values(status="superseded")
        )


def upgrade() -> None:
    _deduplicate_active_profiles()

    with op.batch_alter_table("memory_settings") as batch:
        batch.create_check_constraint(
            "ck_memory_retention", "retention_days IS NULL OR retention_days > 0"
        )

    with op.batch_alter_table("memory_items") as batch:
        batch.create_check_constraint("ck_memory_item_scope", "scope_type IN ('user','game','task')")
        batch.create_check_constraint(
            "ck_memory_item_scope_id",
            "(scope_type = 'user' AND scope_id IS NULL) OR "
            "(scope_type IN ('game','task') AND scope_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_memory_item_category",
            "category IN ('style','mechanics','controls','difficulty','content','constraints','feedback')",
        )
        batch.create_check_constraint(
            "ck_memory_item_source",
            "source_type IN ('idea','feedback','manual','publish','system')",
        )
        batch.create_check_constraint(
            "ck_memory_item_status", "status IN ('active','superseded','deleted')"
        )
        batch.create_check_constraint("ck_memory_item_importance", "importance BETWEEN 1 AND 5")
        batch.create_check_constraint("ck_memory_item_confidence", "confidence BETWEEN 0 AND 1")

    with op.batch_alter_table("memory_profiles") as batch:
        batch.create_check_constraint(
            "ck_memory_profile_scope", "scope_type IN ('user','game','task')"
        )
        batch.create_check_constraint(
            "ck_memory_profile_scope_id",
            "(scope_type = 'user' AND scope_id IS NULL) OR "
            "(scope_type IN ('game','task') AND scope_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_memory_profile_category",
            "category IN ('style','mechanics','controls','difficulty','content','constraints','feedback')",
        )
        batch.create_check_constraint(
            "ck_memory_profile_explicitness",
            "explicitness IN ('manual','explicit','inferred')",
        )
        batch.create_check_constraint(
            "ck_memory_profile_status",
            "status IN ('active','candidate','superseded','deleted')",
        )
        batch.create_check_constraint(
            "ck_memory_profile_confidence", "confidence BETWEEN 0 AND 1"
        )
        batch.create_check_constraint(
            "ck_memory_profile_scope_confidence", "scope_confidence BETWEEN 0 AND 1"
        )
        batch.create_check_constraint(
            "ck_memory_profile_utility", "utility_score BETWEEN 0 AND 1"
        )
        batch.create_check_constraint("ck_memory_profile_support", "support_count >= 1")
        batch.create_check_constraint(
            "ck_memory_profile_utility_observations", "utility_observation_count >= 0"
        )
        batch.create_check_constraint("ck_memory_profile_version", "version >= 1")

    with op.batch_alter_table("memory_profile_evidence") as batch:
        batch.create_check_constraint(
            "ck_memory_evidence_confidence", "confidence BETWEEN 0 AND 1"
        )
        batch.create_check_constraint(
            "ck_memory_evidence_scope_confidence", "scope_confidence BETWEEN 0 AND 1"
        )
        batch.create_check_constraint(
            "ck_memory_evidence_explicitness",
            "explicitness IN ('manual','explicit','inferred')",
        )

    with op.batch_alter_table("memory_entity_links") as batch:
        batch.create_check_constraint(
            "ck_memory_entity_link_confidence", "confidence BETWEEN 0 AND 1"
        )

    op.execute(
        "CREATE UNIQUE INDEX uq_memory_profile_active_identity "
        "ON memory_profiles (user_id, scope_type, COALESCE(scope_id, ''), profile_key) "
        "WHERE status = 'active'"
    )


def downgrade() -> None:
    op.drop_index("uq_memory_profile_active_identity", table_name="memory_profiles")

    with op.batch_alter_table("memory_entity_links") as batch:
        batch.drop_constraint("ck_memory_entity_link_confidence", type_="check")

    with op.batch_alter_table("memory_profile_evidence") as batch:
        batch.drop_constraint("ck_memory_evidence_explicitness", type_="check")
        batch.drop_constraint("ck_memory_evidence_scope_confidence", type_="check")
        batch.drop_constraint("ck_memory_evidence_confidence", type_="check")

    with op.batch_alter_table("memory_profiles") as batch:
        batch.drop_constraint("ck_memory_profile_version", type_="check")
        batch.drop_constraint("ck_memory_profile_utility_observations", type_="check")
        batch.drop_constraint("ck_memory_profile_support", type_="check")
        batch.drop_constraint("ck_memory_profile_utility", type_="check")
        batch.drop_constraint("ck_memory_profile_scope_confidence", type_="check")
        batch.drop_constraint("ck_memory_profile_confidence", type_="check")
        batch.drop_constraint("ck_memory_profile_status", type_="check")
        batch.drop_constraint("ck_memory_profile_explicitness", type_="check")
        batch.drop_constraint("ck_memory_profile_category", type_="check")
        batch.drop_constraint("ck_memory_profile_scope_id", type_="check")
        batch.drop_constraint("ck_memory_profile_scope", type_="check")

    with op.batch_alter_table("memory_items") as batch:
        batch.drop_constraint("ck_memory_item_confidence", type_="check")
        batch.drop_constraint("ck_memory_item_importance", type_="check")
        batch.drop_constraint("ck_memory_item_status", type_="check")
        batch.drop_constraint("ck_memory_item_source", type_="check")
        batch.drop_constraint("ck_memory_item_category", type_="check")
        batch.drop_constraint("ck_memory_item_scope_id", type_="check")
        batch.drop_constraint("ck_memory_item_scope", type_="check")

    with op.batch_alter_table("memory_settings") as batch:
        batch.drop_constraint("ck_memory_retention", type_="check")
