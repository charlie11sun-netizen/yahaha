import json
import os
from datetime import timedelta

from sqlalchemy import case, func, literal
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.models import Comment, Favorite, Game, GameVersion, Like, PlayEvent, Score, Tag
from app.models.common import GameStatus, now_utc
from app.models.game import game_tags
from app.services import content_safety
from app.services.artifacts import content_type_for
from app.services.errors import ServiceError
from app.services.pagination import normalize_pagination
from app.services.runtime_urls import (
    game_file_token,
    game_file_url,
    game_manifest_url,
    normalize_game_file_path,
    verify_game_file_token,
)
from app.storage import s3


_FILE_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
}


def published_games_query(db: Session):
    return db.query(Game).filter(Game.status == GameStatus.PUBLISHED)


def visible_game(db: Session, game_id: str, user=None) -> Game:
    game = db.get(Game, game_id)
    if not game or (game.status != GameStatus.PUBLISHED and (not user or user.id != game.author_id)):
        raise ServiceError(404, "Game not found")
    return game


def owned_game(db: Session, game_id: str, user) -> Game:
    game = db.get(Game, game_id)
    if not game:
        raise ServiceError(404, "Game not found")
    if game.author_id != user.id:
        raise ServiceError(403, "Not your game")
    return game


def list_games(db: Session, *, q: str = "", tag: str = "All", sort: str = "newest", limit: int = 24, offset: int = 0):
    from app.models import User

    query = published_games_query(db)
    if tag and tag != "All":
        query = query.filter(Game.tags.any(Tag.name == tag))
    ql = q.strip()
    if ql:
        like = f"%{ql}%"
        query = query.filter(
            Game.title.ilike(like)
            | Game.summary.ilike(like)
            | Game.tags.any(Tag.name.ilike(like))
            | Game.author.has(User.display_name.ilike(like))
        )
    total = query.count()
    if sort == "popular":
        query = query.order_by(Game.plays_count.desc(), Game.created_at.desc())
    else:
        query = query.order_by(Game.published_at.desc(), Game.created_at.desc())
    limit, offset = normalize_pagination(limit, offset)
    return query.offset(offset).limit(limit).all(), total, offset, limit


def game_stats(db: Session) -> dict:
    count = db.query(func.count(Game.id)).filter(Game.status == GameStatus.PUBLISHED).scalar() or 0
    plays = (
        db.query(func.coalesce(func.sum(Game.plays_count), 0))
        .filter(Game.status == GameStatus.PUBLISHED)
        .scalar()
        or 0
    )
    return {"game_count": int(count), "total_plays": int(plays)}


def list_tag_names(db: Session) -> list[str]:
    from app.models.game import game_tags

    rows = (
        db.query(Tag.name)
        .join(game_tags, game_tags.c.tag_id == Tag.id)
        .join(Game, Game.id == game_tags.c.game_id)
        .filter(Game.status == GameStatus.PUBLISHED)
        .distinct()
        .order_by(Tag.name)
        .all()
    )
    return [name for (name,) in rows]


def list_user_games(db: Session, user, *, limit: int = 24, offset: int = 0) -> tuple[list[Game], int, int, int]:
    limit, offset = normalize_pagination(limit, offset)
    query = db.query(Game).filter(Game.author_id == user.id)
    total = query.count()
    page = query.order_by(Game.created_at.desc()).offset(offset).limit(limit).all()
    return page, total, offset, limit


def list_public_user_games(
    db: Session,
    user_id: str,
    *,
    limit: int = 24,
    offset: int = 0,
) -> tuple[list[Game], int, int, int]:
    limit, offset = normalize_pagination(limit, offset)
    query = db.query(Game).filter(Game.author_id == user_id, Game.status == GameStatus.PUBLISHED)
    total = query.count()
    page = query.order_by(Game.published_at.desc(), Game.created_at.desc()).offset(offset).limit(limit).all()
    return page, total, offset, limit


def list_user_favorites(db: Session, user, *, limit: int = 24, offset: int = 0) -> tuple[list[Game], int, int, int]:
    limit, offset = normalize_pagination(limit, offset)
    query = (
        db.query(Game)
        .join(Favorite, Favorite.game_id == Game.id)
        .filter(Favorite.user_id == user.id, Game.status == GameStatus.PUBLISHED)
    )
    total = query.count()
    page = query.order_by(Favorite.created_at.desc()).offset(offset).limit(limit).all()
    return page, total, offset, limit


def get_game_detail_state(db: Session, game_id: str, user=None) -> tuple[Game, bool, bool]:
    game = visible_game(db, game_id, user)
    liked = bool(user and db.get(Like, {"user_id": user.id, "game_id": game.id}))
    favorited = bool(user and db.get(Favorite, {"user_id": user.id, "game_id": game.id}))
    return game, liked, favorited


def preview_game(db: Session, game_id: str, user) -> Game:
    return owned_game(db, game_id, user)


def _version_number(version: str) -> int:
    value = str(version or "")
    return int(value[1:]) if value.startswith("v") and value[1:].isdigit() else 0


def list_versions(db: Session, game_id: str, user) -> tuple[list[GameVersion], str]:
    game = owned_game(db, game_id, user)
    rows = sorted(game.versions, key=lambda row: (_version_number(row.version), row.created_at), reverse=True)
    return rows, game.current_version


def activate_version(db: Session, game_id: str, version: str, user) -> Game:
    game = owned_game(db, game_id, user)
    row = db.query(GameVersion).filter_by(game_id=game.id, version=version).first()
    if not row:
        raise ServiceError(404, "Version not found")
    if not row.manifest_key or not row.bundle_key:
        raise ServiceError(409, "Version artifact metadata is incomplete")
    game.current_version = row.version
    db.commit()
    db.refresh(game)
    return game


def record_play(db: Session, game_id: str, user=None) -> tuple[Game, bool]:
    game = visible_game(db, game_id, user)
    if game.status != GameStatus.PUBLISHED:
        return game, False

    counted = True
    if user:
        recent = (
            db.query(PlayEvent)
            .filter(
                PlayEvent.game_id == game.id,
                PlayEvent.user_id == user.id,
                PlayEvent.created_at >= now_utc() - timedelta(minutes=30),
            )
            .first()
        )
        counted = recent is None
    db.add(PlayEvent(game_id=game.id, user_id=user.id if user else None))
    if counted:
        game.plays_count = Game.plays_count + 1
    db.commit()
    db.refresh(game)
    return game, counted


def set_like(db: Session, game_id: str, user, liked: bool) -> Game:
    game = visible_game(db, game_id, user)
    row = db.get(Like, {"user_id": user.id, "game_id": game.id})
    if liked and not row:
        db.add(Like(user_id=user.id, game_id=game.id))
        game.likes_count = Game.likes_count + 1
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    elif not liked and row:
        db.delete(row)
        game.likes_count = case((Game.likes_count > 0, Game.likes_count - 1), else_=0)
        try:
            db.commit()
        except (IntegrityError, StaleDataError):
            db.rollback()
    db.refresh(game)
    return game


def set_favorite(db: Session, game_id: str, user, favorited: bool) -> None:
    if favorited:
        game = visible_game(db, game_id, user)
        if not db.get(Favorite, {"user_id": user.id, "game_id": game.id}):
            db.add(Favorite(user_id=user.id, game_id=game.id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        return

    row = db.get(Favorite, {"user_id": user.id, "game_id": game_id})
    if row:
        db.delete(row)
        db.commit()


def publish_game(db: Session, game_id: str, user) -> Game:
    game = owned_game(db, game_id, user)
    content_safety.ensure_allowed(
        db,
        text="\n".join([game.title or "", game.summary or "", " ".join(t.name for t in game.tags)]),
        surface="game.publish.copy",
        user_id=user.id,
        object_id=game.id,
    )
    game.status = GameStatus.PUBLISHED
    if not game.published_at:
        game.published_at = now_utc()
    db.commit()
    return game


def unpublish_game(db: Session, game_id: str, user) -> Game:
    game = owned_game(db, game_id, user)
    game.status = GameStatus.DRAFT
    db.commit()
    return game


def update_game(db: Session, game_id: str, user, *, title=None, summary=None, tags=None) -> Game:
    game = owned_game(db, game_id, user)
    if title is not None:
        content_safety.ensure_allowed(db, text=title, surface="game.title", user_id=user.id, object_id=game.id)
    if summary is not None:
        content_safety.ensure_allowed(db, text=summary, surface="game.summary", user_id=user.id, object_id=game.id)
    if tags is not None:
        content_safety.ensure_allowed(
            db,
            text=" ".join(str(name) for name in tags[:8]),
            surface="game.tags",
            user_id=user.id,
            object_id=game.id,
        )

    if title is not None:
        game.title = title.strip()
    if summary is not None:
        game.summary = summary.strip()
    if tags is not None:
        game.tags.clear()
        for raw_name in tags[:8]:
            name = raw_name.strip()
            if not name:
                continue
            tag = db.query(Tag).filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.add(tag)
                db.flush()
            game.tags.append(tag)
    db.commit()
    return game


def delete_game(db: Session, game_id: str, user) -> None:
    game = owned_game(db, game_id, user)
    gid = game.id
    db.delete(game)
    db.commit()
    try:
        s3.delete_prefix(f"games/{gid}/")
        s3.delete_prefix(f"game-sources/{gid}/")
    except Exception:  # noqa: BLE001
        pass


def list_comments(db: Session, game_id: str, user=None) -> list[Comment]:
    game = visible_game(db, game_id, user)
    return (
        db.query(Comment)
        .filter(Comment.game_id == game.id)
        .order_by(Comment.created_at.desc())
        .limit(100)
        .all()
    )


def add_comment(db: Session, game_id: str, user, body: str) -> Comment:
    visible_game(db, game_id, user)
    content_safety.ensure_allowed(db, text=body, surface="comment", user_id=user.id, object_id=game_id)
    comment = Comment(game_id=game_id, user_id=user.id, body=body.strip())
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(db: Session, game_id: str, comment_id: str, user) -> None:
    comment = db.get(Comment, comment_id)
    if not comment or comment.game_id != game_id:
        raise ServiceError(404, "Comment not found")
    game = db.get(Game, game_id)
    if comment.user_id != user.id and (not game or game.author_id != user.id):
        raise ServiceError(403, "Not allowed")
    db.delete(comment)
    db.commit()


def related_games(db: Session, game_id: str, user=None, *, limit: int = 6) -> list[Game]:
    game = visible_game(db, game_id, user)
    limit, _ = normalize_pagination(limit, 0, max_limit=12)
    tag_ids = [tag.id for tag in game.tags]
    if tag_ids:
        tag_overlap_subq = (
            db.query(
                game_tags.c.game_id.label("game_id"),
                func.count(game_tags.c.tag_id).label("tag_overlap"),
            )
            .filter(game_tags.c.tag_id.in_(tag_ids))
            .group_by(game_tags.c.game_id)
            .subquery()
        )
        tag_overlap = func.coalesce(tag_overlap_subq.c.tag_overlap, 0)
        query = published_games_query(db).outerjoin(tag_overlap_subq, tag_overlap_subq.c.game_id == Game.id)
    else:
        tag_overlap = literal(0)
        query = published_games_query(db)

    genre_match = case((Game.genre == game.genre, 1), else_=0)
    score = tag_overlap + genre_match
    return (
        query.filter(Game.id != game.id)
        .order_by(score.desc(), Game.plays_count.desc(), Game.published_at.desc(), Game.created_at.desc())
        .limit(limit)
        .all()
    )


def submit_score(db: Session, game_id: str, user, *, player_name: str | None, points: int) -> None:
    visible_game(db, game_id, user)
    name = (player_name or (user.display_name if user else "Anonymous")).strip()[:80] or "Anonymous"
    content_safety.ensure_allowed(
        db,
        text=name,
        surface="score.player_name",
        user_id=user.id if user else None,
        object_id=game_id,
    )
    db.add(Score(game_id=game_id, user_id=user.id if user else None, player_name=name, points=points))
    db.commit()


def leaderboard(db: Session, game_id: str, user=None) -> list[Score]:
    game = visible_game(db, game_id, user)
    return (
        db.query(Score)
        .filter(Score.game_id == game.id)
        .order_by(Score.points.desc(), Score.created_at.asc())
        .limit(10)
        .all()
    )


def _content_type_for_game_file(path: str) -> str:
    return _FILE_CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), content_type_for(path))


def _manifest_with_runtime_urls(data: dict, *, game: Game, version: str) -> dict:
    out = dict(data)
    token = game_file_token(game.id, version)
    try:
        entry = normalize_game_file_path(str(out.get("entry") or "index.html"))
    except ValueError:
        entry = "index.html"
    out["entry"] = entry
    out["entry_url"] = game_file_url(game.id, version, entry, token=token)
    out["_url"] = game_manifest_url(game.id, version)

    signed_files = []
    for item in out.get("files") or []:
        if not isinstance(item, dict):
            continue
        try:
            path = normalize_game_file_path(str(item.get("path") or ""))
        except ValueError:
            continue
        signed = dict(item)
        signed["path"] = path
        signed["url"] = game_file_url(game.id, version, path, token=token)
        signed_files.append(signed)
    if signed_files:
        out["files"] = signed_files
    return out


def game_manifest(db: Session, game_id: str, user=None, *, version: str | None = None) -> dict:
    game = visible_game(db, game_id, user)
    selected_version = version or game.current_version
    if version and (not user or user.id != game.author_id):
        raise ServiceError(403, "Only the owner can preview a specific version")

    key = f"games/{game.id}/{selected_version}/manifest.json"
    raw = s3.get_object(key)
    if raw:
        try:
            data = json.loads(raw.decode("utf-8"))
            data["_source"] = "oss"
            return _manifest_with_runtime_urls(data, game=game, version=selected_version)
        except Exception:  # noqa: BLE001
            pass

    row = db.query(GameVersion).filter_by(game_id=game.id, version=selected_version).first()
    if not row:
        raise ServiceError(404, "Manifest not found")
    return {
        "entry": row.entry,
        "runtime": row.runtime,
        "sha256": row.sha256,
        "size": row.size_bytes,
        "entry_url": game_file_url(game.id, selected_version, row.entry or "index.html"),
        "_source": "db",
        "_url": game_manifest_url(game.id, selected_version),
    }


def game_file(db: Session, game_id: str, token: str, version: str, file_path: str) -> tuple[bytes, str]:
    if not verify_game_file_token(token, game_id, version):
        raise ServiceError(403, "Invalid or expired file token")
    game = db.get(Game, game_id)
    if not game:
        raise ServiceError(404, "Game not found")
    row = db.query(GameVersion).filter_by(game_id=game.id, version=version).first()
    if not row:
        raise ServiceError(404, "Version not found")
    try:
        path = normalize_game_file_path(file_path)
    except ValueError as exc:
        raise ServiceError(404, "File not found") from exc
    raw = s3.get_object(f"games/{game.id}/{version}/{path}")
    if raw is None:
        raise ServiceError(404, "File not found")
    return raw, _content_type_for_game_file(path)
