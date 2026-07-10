"""Application-level user policy and lifecycle orchestration.

This layer may depend on moderation and object storage; ``app.core.users`` stays
focused on the database adapter and authentication invariants.
"""

from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from app.core.users import SyncSQLAlchemyUserDatabase, UserManager as CoreUserManager, get_user_db
from app.models import Game, User
from app.services import content_safety
from app.storage import s3


class UserManager(CoreUserManager):
    def __init__(self, user_db: SyncSQLAlchemyUserDatabase):
        super().__init__(user_db)
        self._delete_cleanup: tuple[str, list[str]] | None = None

    async def create(self, user_create, safe: bool = False, request: Request | None = None) -> User:
        display_name = getattr(user_create, "display_name", None)
        if display_name:
            await run_in_threadpool(
                content_safety.ensure_allowed,
                self.user_db.session,
                text=display_name,
                surface="auth.register.display_name",
            )
        return await super().create(user_create, safe=safe, request=request)

    async def update(self, user_update, user: User, safe: bool = False, request: Request | None = None) -> User:
        display_name = getattr(user_update, "display_name", None)
        avatar = getattr(user_update, "avatar", None)
        if display_name is not None:
            await run_in_threadpool(
                content_safety.ensure_allowed,
                self.user_db.session,
                text=display_name,
                surface="user.display_name",
                user_id=user.id,
                object_id=user.id,
            )
        if avatar is not None and str(avatar).strip():
            await run_in_threadpool(
                content_safety.ensure_allowed,
                self.user_db.session,
                text=avatar,
                surface="user.avatar",
                user_id=user.id,
                object_id=user.id,
            )
        return await super().update(user_update, user, safe=safe, request=request)

    async def on_before_delete(self, user: User, request: Request | None = None) -> None:
        def load_game_ids():
            return [gid for (gid,) in self.user_db.session.query(Game.id).filter(Game.author_id == user.id)]

        game_ids = await run_in_threadpool(load_game_ids)
        self._delete_cleanup = (user.id, game_ids)

    async def on_after_delete(self, user: User, request: Request | None = None) -> None:
        if not self._delete_cleanup:
            return
        uid, game_ids = self._delete_cleanup

        def cleanup_storage():
            try:
                for game_id in game_ids:
                    s3.delete_prefix(f"games/{game_id}/")
                s3.delete_prefix(f"uploads/{uid}/")
            except Exception:  # noqa: BLE001
                pass

        await run_in_threadpool(cleanup_storage)


async def get_user_manager(
    user_db: SyncSQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)
