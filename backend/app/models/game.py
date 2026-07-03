from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import GameSource, GameStatus, PkMixin, TimestampMixin

game_tags = Table(
    "game_tags",
    Base.metadata,
    Column("game_id", ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(PkMixin, Base):
    __tablename__ = "tags"
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)


class Game(PkMixin, TimestampMixin, Base):
    __tablename__ = "games"

    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    genre: Mapped[str] = mapped_column(String(80), default="")
    cover: Mapped[str] = mapped_column(String(400), default="")  # 渐变串或封面图 key
    source: Mapped[str] = mapped_column(String(20), default=GameSource.SEED)
    status: Mapped[str] = mapped_column(String(20), default=GameStatus.DRAFT, index=True)
    current_version: Mapped[str] = mapped_column(String(20), default="v1")
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    plays_count: Mapped[int] = mapped_column(BigInteger, default=0)
    likes_count: Mapped[int] = mapped_column(BigInteger, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author = relationship("User", lazy="joined")
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=game_tags, lazy="selectin")
    # 默认惰性加载：列表页（game_card）不用 versions，selectin 会让每次
    # /games 查询连带加载所有游戏的所有版本行；需要版本的场景都在会话内显式访问。
    versions: Mapped[list["GameVersion"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class GameVersion(PkMixin, TimestampMixin, Base):
    __tablename__ = "game_versions"

    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(20), default="v1")
    manifest_key: Mapped[str] = mapped_column(String(400))
    entry: Mapped[str] = mapped_column(String(120), default="index.html")
    bundle_key: Mapped[str] = mapped_column(String(400))
    cover_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    runtime: Mapped[str] = mapped_column(String(40), default="iframe-sandbox")
    sha256: Mapped[str] = mapped_column(String(80), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    source_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    game: Mapped["Game"] = relationship(back_populates="versions")


class Like(TimestampMixin, Base):
    __tablename__ = "likes"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), primary_key=True)


class Favorite(TimestampMixin, Base):
    __tablename__ = "favorites"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), primary_key=True)


class PlayEvent(PkMixin, TimestampMixin, Base):
    __tablename__ = "play_events"
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
