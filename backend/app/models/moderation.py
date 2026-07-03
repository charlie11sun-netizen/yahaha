from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import PkMixin, TimestampMixin


class ModerationEvent(PkMixin, TimestampMixin, Base):
    __tablename__ = "moderation_events"
    __table_args__ = (Index("ix_moderation_events_surface_created_at", "surface", "created_at"),)

    surface: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(20))
    categories: Mapped[dict] = mapped_column(JSON, default=dict)
    provider: Mapped[str] = mapped_column(String(20))
    input_sha256: Mapped[str] = mapped_column(String(64))
    input_excerpt: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
