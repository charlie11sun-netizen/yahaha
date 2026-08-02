from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import VECTOR

from app.core.config import settings
from app.models.common import PkMixin, TimestampMixin, now_utc
from app.db.base import Base


def _embedding_type():
    return VECTOR(settings.MEMORY_VECTOR_DIMENSIONS).with_variant(JSON(), "sqlite")


class MemoryScope:
    USER = "user"
    GAME = "game"
    TASK = "task"


class MemoryCategory:
    STYLE = "style"
    MECHANICS = "mechanics"
    CONTROLS = "controls"
    DIFFICULTY = "difficulty"
    CONTENT = "content"
    CONSTRAINTS = "constraints"
    FEEDBACK = "feedback"


class MemorySource:
    IDEA = "idea"
    FEEDBACK = "feedback"
    MANUAL = "manual"
    PUBLISH = "publish"
    SYSTEM = "system"


class MemoryStatus:
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryProfileStatus:
    ACTIVE = "active"
    CANDIDATE = "candidate"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryExplicitness:
    MANUAL = "manual"
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class MemoryProfileOperation:
    CREATED = "created"
    CANDIDATE = "candidate"
    REINFORCED = "reinforced"
    AUTO_PROMOTED = "auto_promoted"
    SUPERSEDED = "superseded"
    CORRECTED = "corrected"
    UTILITY_UPDATED = "utility_updated"
    EXPIRED = "expired"
    DELETED = "deleted"
    RESTORED = "restored"
    EVIDENCE_REMOVED = "evidence_removed"


class MemoryItem(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint("scope_type IN ('user','game','task')", name="ck_memory_item_scope"),
        CheckConstraint(
            "(scope_type = 'user' AND scope_id IS NULL) OR "
            "(scope_type IN ('game','task') AND scope_id IS NOT NULL)",
            name="ck_memory_item_scope_id",
        ),
        CheckConstraint(
            "category IN ('style','mechanics','controls','difficulty','content','constraints','feedback')",
            name="ck_memory_item_category",
        ),
        CheckConstraint(
            "source_type IN ('idea','feedback','manual','publish','system')",
            name="ck_memory_item_source",
        ),
        CheckConstraint("status IN ('active','superseded','deleted')", name="ck_memory_item_status"),
        CheckConstraint("importance BETWEEN 1 AND 5", name="ck_memory_item_importance"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memory_item_confidence"),
        Index(
            "ix_memory_items_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), default=MemoryScope.USER, index=True)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), default=MemoryCategory.FEEDBACK, index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default=MemorySource.MANUAL, index=True)
    source_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_game_id: Mapped[str | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default=MemoryStatus.ACTIVE, index=True)
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(_embedding_type(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MemorySettings(Base):
    __tablename__ = "memory_settings"
    __table_args__ = (
        CheckConstraint("retention_days IS NULL OR retention_days > 0", name="ck_memory_retention"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_cross_game_memory: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_memory_extraction: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MemoryProfile(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), index=True)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    profile_key: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    value_text: Mapped[str] = mapped_column(Text)
    summary_text: Mapped[str] = mapped_column(Text)
    evidence_span: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.8)
    scope_confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.8)
    explicitness: Mapped[str] = mapped_column(String(20), default=MemoryExplicitness.INFERRED)
    status: Mapped[str] = mapped_column(String(20), default=MemoryProfileStatus.ACTIVE, index=True)
    source_memory_id: Mapped[str] = mapped_column(
        ForeignKey("memory_items.id", ondelete="CASCADE"), index=True
    )
    conflicts_with_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    support_count: Mapped[int] = mapped_column(Integer, default=1)
    utility_score: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5)
    utility_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    last_supported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(_embedding_type(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    __table_args__ = (
        CheckConstraint("scope_type IN ('user','game','task')", name="ck_memory_profile_scope"),
        CheckConstraint(
            "(scope_type = 'user' AND scope_id IS NULL) OR "
            "(scope_type IN ('game','task') AND scope_id IS NOT NULL)",
            name="ck_memory_profile_scope_id",
        ),
        CheckConstraint(
            "category IN ('style','mechanics','controls','difficulty','content','constraints','feedback')",
            name="ck_memory_profile_category",
        ),
        CheckConstraint(
            "explicitness IN ('manual','explicit','inferred')",
            name="ck_memory_profile_explicitness",
        ),
        CheckConstraint(
            "status IN ('active','candidate','superseded','deleted')",
            name="ck_memory_profile_status",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memory_profile_confidence"),
        CheckConstraint(
            "scope_confidence BETWEEN 0 AND 1", name="ck_memory_profile_scope_confidence"
        ),
        CheckConstraint("utility_score BETWEEN 0 AND 1", name="ck_memory_profile_utility"),
        CheckConstraint("support_count >= 1", name="ck_memory_profile_support"),
        CheckConstraint(
            "utility_observation_count >= 0", name="ck_memory_profile_utility_observations"
        ),
        CheckConstraint("version >= 1", name="ck_memory_profile_version"),
        Index(
            "uq_memory_profile_active_identity",
            user_id,
            scope_type,
            func.coalesce(scope_id, ""),
            profile_key,
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_memory_profiles_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
    )


class MemoryProfileVersion(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_profile_versions"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("memory_profiles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(30), index=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    source_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemoryProfileEvidence(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_profile_evidence"
    __table_args__ = (
        UniqueConstraint("profile_id", "memory_id", name="uq_memory_profile_evidence"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memory_evidence_confidence"),
        CheckConstraint(
            "scope_confidence BETWEEN 0 AND 1", name="ck_memory_evidence_scope_confidence"
        ),
        CheckConstraint(
            "explicitness IN ('manual','explicit','inferred')",
            name="ck_memory_evidence_explicitness",
        ),
    )

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("memory_profiles.id", ondelete="CASCADE"), index=True
    )
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memory_items.id", ondelete="CASCADE"), index=True
    )
    evidence_span: Mapped[str] = mapped_column(Text)
    value_text: Mapped[str] = mapped_column(Text)
    summary_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.8)
    scope_confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.8)
    explicitness: Mapped[str] = mapped_column(String(20), default=MemoryExplicitness.INFERRED)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class MemoryEntity(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "normalized_name", name="uq_memory_entity_identity"),
        Index(
            "ix_memory_entities_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("embedding IS NOT NULL"),
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    canonical_name: Mapped[str] = mapped_column(String(240))
    normalized_name: Mapped[str] = mapped_column(String(240), index=True)
    embedding: Mapped[list[float] | None] = mapped_column(_embedding_type(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MemoryEntityLink(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_entity_links"
    __table_args__ = (
        UniqueConstraint("entity_id", "memory_id", name="uq_memory_entity_link"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memory_entity_link_confidence"),
    )

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("memory_entities.id", ondelete="CASCADE"), index=True
    )
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memory_items.id", ondelete="CASCADE"), index=True
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    source: Mapped[str] = mapped_column(String(40), default="claim")
