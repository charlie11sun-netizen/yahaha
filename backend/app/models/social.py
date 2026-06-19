"""社交/互动模型：评论、分数（排行榜）、关注。"""
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import PkMixin, TimestampMixin


class Comment(PkMixin, TimestampMixin, Base):
    __tablename__ = "comments"

    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)

    user = relationship("User", lazy="joined")


class Score(PkMixin, TimestampMixin, Base):
    __tablename__ = "scores"

    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    player_name: Mapped[str] = mapped_column(String(80), default="Anonymous")
    points: Mapped[int] = mapped_column(Integer, default=0)

    user = relationship("User", lazy="joined")


class Follow(TimestampMixin, Base):
    __tablename__ = "follows"

    follower_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    following_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
