from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.deps import get_current_user, get_optional_user, rate_limit
from app.db.session import get_db
from app.models import Comment, Favorite, Game, GameVersion, Like, PlayEvent, Score, Tag
from app.models.common import GameStatus, now_utc
from app.schemas import CommentIn, GameUpdateIn, ScoreIn
from app.services import content_safety
from app.services.serialize import comment_out, fmt, game_card, game_detail, score_out
from app.storage import s3

router = APIRouter(tags=["games"])


def _published(db: Session):
    return db.query(Game).filter(Game.status == GameStatus.PUBLISHED)


def _visible_game(game_id: str, user, db: Session) -> Game:
    """详情 / 评论 / 排行 / 计分 / manifest / play 共用的可见性规则：
    PUBLISHED 对所有人可见；draft / preview 只有作者可见。
    否则拿到 id 就能读草稿内容、给未发布的预览灌互动数据。"""
    g = db.get(Game, game_id)
    if not g or (g.status != GameStatus.PUBLISHED and (not user or user.id != g.author_id)):
        raise HTTPException(status_code=404, detail="Game not found")
    return g


@router.get("/games")
def list_games(
    q: str = "",
    tag: str = "All",
    sort: str = "newest",
    limit: int = 24,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    # 过滤/排序/分页全部下推 SQL —— 旧实现把全表拉进内存再切片，
    # 数据量增长后每个列表请求都是全表载入。
    from app.models import User

    query = _published(db)
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
    limit = max(1, min(limit, 60))
    offset = max(0, offset)
    page = query.offset(offset).limit(limit).all()
    return {
        "items": [game_card(g) for g in page],
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    count = db.query(func.count(Game.id)).filter(Game.status == GameStatus.PUBLISHED).scalar() or 0
    plays = (
        db.query(func.coalesce(func.sum(Game.plays_count), 0))
        .filter(Game.status == GameStatus.PUBLISHED)
        .scalar()
        or 0
    )
    return {"game_count": int(count), "total_plays": int(plays)}


@router.get("/tags")
def list_tags(db: Session = Depends(get_db)):
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
    return {"tags": [name for (name,) in rows]}


@router.get("/me/games")
def my_games(user=Depends(get_current_user), db: Session = Depends(get_db)):
    games = db.query(Game).filter(Game.author_id == user.id).order_by(Game.created_at.desc()).all()
    return {"items": [game_card(g) for g in games]}


@router.get("/me/favorites")
def my_favorites(user=Depends(get_current_user), db: Session = Depends(get_db)):
    games = (
        db.query(Game)
        .join(Favorite, Favorite.game_id == Game.id)
        .filter(Favorite.user_id == user.id, Game.status == GameStatus.PUBLISHED)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    return {"items": [game_card(g) for g in games]}


@router.get("/games/{game_id}")
def get_game(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    g = _visible_game(game_id, user, db)
    d = game_detail(g)
    d["liked"] = bool(user and db.get(Like, {"user_id": user.id, "game_id": g.id}))
    d["favorited"] = bool(user and db.get(Favorite, {"user_id": user.id, "game_id": g.id}))
    return d


@router.get("/games/{game_id}/preview")
def preview_game(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    if g.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not your game")
    return game_detail(g)


def _version_number(version: str) -> int:
    value = str(version or "")
    return int(value[1:]) if value.startswith("v") and value[1:].isdigit() else 0


def _version_out(version: GameVersion, current_version: str) -> dict:
    return {
        "version": version.version,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "size_bytes": version.size_bytes,
        "sha256": version.sha256,
        "is_current": version.version == current_version,
    }


@router.get("/games/{game_id}/versions")
def list_versions(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _owned_game(game_id, user, db)
    rows = sorted(g.versions, key=lambda row: (_version_number(row.version), row.created_at), reverse=True)
    return {"items": [_version_out(row, g.current_version) for row in rows]}


@router.post("/games/{game_id}/versions/{version}/activate")
def activate_version(
    game_id: str,
    version: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _owned_game(game_id, user, db)
    row = db.query(GameVersion).filter_by(game_id=g.id, version=version).first()
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    if not row.manifest_key or not row.bundle_key:
        raise HTTPException(status_code=409, detail="Version artifact metadata is incomplete")
    g.current_version = row.version
    db.commit()
    db.refresh(g)
    return game_detail(g)


@router.post("/games/{game_id}/play", dependencies=[Depends(rate_limit(60, 60, "play"))])
def record_play(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    g = _visible_game(game_id, user, db)
    # 作者预览（非 PUBLISHED）不产生事件也不计数，避免污染正式数据
    if g.status != GameStatus.PUBLISHED:
        return {"plays": g.plays_count, "plays_str": fmt(g.plays_count), "counted": False}
    # 防刷：同一登录用户对同一游戏 30 分钟内只累计一次（匿名仅靠 IP 限流兜底）
    counted = True
    if user:
        recent = (
            db.query(PlayEvent)
            .filter(
                PlayEvent.game_id == g.id,
                PlayEvent.user_id == user.id,
                PlayEvent.created_at >= now_utc() - timedelta(minutes=30),
            )
            .first()
        )
        counted = recent is None
    db.add(PlayEvent(game_id=g.id, user_id=user.id if user else None))
    if counted:
        # SQL 原子自增：读-改-写在并发下会丢失更新
        g.plays_count = Game.plays_count + 1
    db.commit()
    db.refresh(g)
    return {"plays": g.plays_count, "plays_str": fmt(g.plays_count), "counted": counted}


@router.post("/games/{game_id}/like")
def like(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _visible_game(game_id, user, db)
    if not db.get(Like, {"user_id": user.id, "game_id": g.id}):
        db.add(Like(user_id=user.id, game_id=g.id))
        g.likes_count = Game.likes_count + 1  # SQL 原子自增
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # 并发双击：另一请求已插入（复合主键兜底），当作已点赞
    db.refresh(g)
    return {"liked": True, "likes": g.likes_count}


@router.delete("/games/{game_id}/like")
def unlike(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _visible_game(game_id, user, db)
    row = db.get(Like, {"user_id": user.id, "game_id": g.id})
    if row:
        db.delete(row)
        # SQL 原子自减，CASE 兜底不为负（历史漂移时不再被 max() 静默掩盖成负数）
        g.likes_count = case((Game.likes_count > 0, Game.likes_count - 1), else_=0)
        try:
            db.commit()
        except (IntegrityError, StaleDataError):
            db.rollback()  # 并发双删：另一请求已处理
    db.refresh(g)
    return {"liked": False, "likes": g.likes_count}


@router.post("/games/{game_id}/favorite")
def favorite(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _visible_game(game_id, user, db)
    if not db.get(Favorite, {"user_id": user.id, "game_id": g.id}):
        db.add(Favorite(user_id=user.id, game_id=g.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"favorited": True}


@router.delete("/games/{game_id}/favorite")
def unfavorite(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(Favorite, {"user_id": user.id, "game_id": game_id})
    if row:
        db.delete(row)
        db.commit()
    return {"favorited": False}


@router.post("/games/{game_id}/publish")
def publish(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _owned_game(game_id, user, db)
    content_safety.ensure_allowed(
        db,
        text="\n".join([g.title or "", g.summary or "", " ".join(t.name for t in g.tags)]),
        surface="game.publish.copy",
        user_id=user.id,
        object_id=g.id,
    )
    g.status = GameStatus.PUBLISHED
    if not g.published_at:
        g.published_at = now_utc()
    db.commit()
    return game_card(g)


def _owned_game(game_id: str, user, db: Session) -> Game:
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    if g.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not your game")
    return g


@router.post("/games/{game_id}/unpublish")
def unpublish(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _owned_game(game_id, user, db)
    g.status = GameStatus.DRAFT
    db.commit()
    return game_card(g)


@router.patch("/games/{game_id}")
def update_game(game_id: str, body: GameUpdateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _owned_game(game_id, user, db)
    if body.title is not None:
        content_safety.ensure_allowed(
            db, text=body.title, surface="game.title", user_id=user.id, object_id=g.id
        )
    if body.summary is not None:
        content_safety.ensure_allowed(
            db, text=body.summary, surface="game.summary", user_id=user.id, object_id=g.id
        )
    if body.tags is not None:
        content_safety.ensure_allowed(
            db,
            text=" ".join(str(name) for name in body.tags[:8]),
            surface="game.tags",
            user_id=user.id,
            object_id=g.id,
        )
    if body.title is not None:
        g.title = body.title.strip()
    if body.summary is not None:
        g.summary = body.summary.strip()
    if body.tags is not None:
        g.tags.clear()
        for name in body.tags[:8]:
            name = name.strip()
            if not name:
                continue
            tag = db.query(Tag).filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.add(tag)
                db.flush()
            g.tags.append(tag)
    db.commit()
    return game_detail(g)


@router.delete("/games/{game_id}")
def delete_game(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = _owned_game(game_id, user, db)
    gid = g.id
    db.delete(g)
    db.commit()
    # DB 删除已生效；bundle/manifest 是公网可读对象，必须跟着清（尽力而为，
    # OSS 暂不可用时残留只是不可发现的垃圾，不阻塞删除本身）。
    try:
        s3.delete_prefix(f"games/{gid}/")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


# ---------- comments ----------
@router.get("/games/{game_id}/comments")
def list_comments(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    g = _visible_game(game_id, user, db)
    rows = (
        db.query(Comment)
        .filter(Comment.game_id == g.id)
        .order_by(Comment.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [comment_out(c) for c in rows]}


@router.post("/games/{game_id}/comments", dependencies=[Depends(rate_limit(30, 3600, "comment"))])
def add_comment(game_id: str, body: CommentIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _visible_game(game_id, user, db)
    content_safety.ensure_allowed(
        db,
        text=body.body,
        surface="comment",
        user_id=user.id,
        object_id=game_id,
    )
    c = Comment(game_id=game_id, user_id=user.id, body=body.body.strip())
    db.add(c)
    db.commit()
    db.refresh(c)
    return comment_out(c)


@router.delete("/games/{game_id}/comments/{comment_id}")
def delete_comment(game_id: str, comment_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Comment, comment_id)
    if not c or c.game_id != game_id:
        raise HTTPException(status_code=404, detail="Comment not found")
    game = db.get(Game, game_id)
    if c.user_id != user.id and (not game or game.author_id != user.id):
        raise HTTPException(status_code=403, detail="Not allowed")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------- related ----------
@router.get("/games/{game_id}/related")
def related_games(game_id: str, limit: int = 6, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    g = _visible_game(game_id, user, db)
    tag_names = {t.name for t in g.tags}
    scored = []
    for c in _published(db).filter(Game.id != g.id).all():
        overlap = len(tag_names & {t.name for t in c.tags}) + (1 if c.genre == g.genre else 0)
        scored.append((overlap, c.plays_count, c))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    picks = [c for _, _, c in scored[: max(1, min(limit, 12))]]
    return {"items": [game_card(c) for c in picks]}


# ---------- scores / leaderboard ----------
@router.post("/games/{game_id}/score", dependencies=[Depends(rate_limit(60, 3600, "score"))])
def submit_score(game_id: str, body: ScoreIn, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    _visible_game(game_id, user, db)
    name = (body.player_name or (user.display_name if user else "Anonymous")).strip()[:80] or "Anonymous"
    content_safety.ensure_allowed(
        db,
        text=name,
        surface="score.player_name",
        user_id=user.id if user else None,
        object_id=game_id,
    )
    db.add(Score(game_id=game_id, user_id=user.id if user else None, player_name=name, points=body.points))
    db.commit()
    return {"ok": True}


@router.get("/games/{game_id}/leaderboard")
def leaderboard(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Score)
        .filter(Score.game_id == _visible_game(game_id, user, db).id)
        .order_by(Score.points.desc(), Score.created_at.asc())
        .limit(10)
        .all()
    )
    return {"items": [score_out(s, rank=i + 1) for i, s in enumerate(rows)]}


@router.get("/games/{game_id}/manifest")
def game_manifest(
    game_id: str,
    version: str | None = None,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """从对象存储真实读取 manifest.json（证明远端产物），失败回退 DB 版本元信息。"""
    import json as _json

    g = _visible_game(game_id, user, db)
    selected_version = version or g.current_version
    if version and (not user or user.id != g.author_id):
        raise HTTPException(status_code=403, detail="Only the owner can preview a specific version")
    key = f"games/{g.id}/{selected_version}/manifest.json"
    raw = s3.get_object(key)
    if raw:
        try:
            data = _json.loads(raw.decode("utf-8"))
            data["_source"] = "oss"
            data["_url"] = s3.public_url(key)
            return data
        except Exception:  # noqa: BLE001
            pass
    v = db.query(GameVersion).filter_by(game_id=g.id, version=selected_version).first()
    if not v:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return {
        "entry": v.entry, "runtime": v.runtime, "sha256": v.sha256, "size": v.size_bytes,
        "_source": "db", "_url": s3.public_url(key),
    }
