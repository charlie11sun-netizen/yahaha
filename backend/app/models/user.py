from sqlalchemy import BigInteger, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.db.base import Base
from app.models.common import PkMixin, TimestampMixin


class User(PkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    _hashed_password: Mapped[str | None] = mapped_column("password_hash", String(255), nullable=True)
    hashed_password = synonym("_hashed_password")
    password_hash = synonym("_hashed_password")
    display_name: Mapped[str] = mapped_column(String(120))
    avatar_initial: Mapped[str] = mapped_column(String(4), default="?")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def name(self) -> str:
        return self.display_name

    @property
    def init(self) -> str:
        return self.avatar_initial


class OAuthAccount(PkMixin, TimestampMixin, Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_account_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    _oauth_name: Mapped[str] = mapped_column("provider", String(20))
    oauth_name = synonym("_oauth_name")
    provider = synonym("_oauth_name")
    _account_id: Mapped[str] = mapped_column("provider_account_id", String(255))
    account_id = synonym("_account_id")
    provider_account_id = synonym("_account_id")
    account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="oauth_accounts")
