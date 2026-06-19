from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user, rate_limit
from app.db.session import get_db
from app.models import Favorite, Game, Like, PlayEvent, Tag
from app.models.common import GameStatus, now_utc
from app.schemas import GameUpdateIn
from app.services.serialize import fmt, game_card, game_detail

router = APIRouter(tags=["games"])


def _published(db: Session):
    return db.query(Game).filter(Game.status == GameStatus.PUBLISHED)


@router.get("/games")
def list_games(
    q: str = "",
    tag: str = "All",
    sort: str = "newest",
    limit: int = 24,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = _published(db)
    if sort == "popular":
        query = query.order_by(Game.plays_count.desc(), Game.created_at.desc())
    else:
        query = query.order_by(Game.published_at.desc(), Game.created_at.desc())
    ql = q.strip().lower()
    matched = []
    for g in query.all():
        tags = [t.name for t in g.tags]
        if tag and tag != "All" and tag not in tags:
            continue
        if ql:
            author = g.author.display_name if g.author else ""
            hay = f"{g.title} {g.summary} {author} {' '.join(tags)}".lower()
            if ql not in hay:
                continue
        matched.append(g)
    limit = max(1, min(limit, 60))
    offset = max(0, offset)
    page = matched[offset:offset + limit]
    return {
        "items": [game_card(g) for g in page],
        "total": len(matched),
        "has_more": offset + limit < len(matched),
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
    names: list[str] = []
    for g in _published(db).all():
        for t in g.tags:
            if t.name not in names:
                names.append(t.name)
    return {"tags": names}


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
    g = db.get(Game, game_id)
    if not g or (g.status != GameStatus.PUBLISHED and (not user or user.id != g.author_id)):
        raise HTTPException(status_code=404, detail="Game not found")
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


@router.post("/games/{game_id}/play", dependencies=[Depends(rate_limit(60, 60, "play"))])
def record_play(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
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
        g.plays_count += 1
    db.commit()
    return {"plays": g.plays_count, "plays_str": fmt(g.plays_count), "counted": counted}


@router.post("/games/{game_id}/like")
def like(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    if not db.get(Like, {"user_id": user.id, "game_id": g.id}):
        db.add(Like(user_id=user.id, game_id=g.id))
        g.likes_count += 1
        db.commit()
    return {"liked": True, "likes": g.likes_count}


@router.delete("/games/{game_id}/like")
def unlike(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    row = db.get(Like, {"user_id": user.id, "game_id": g.id})
    if row:
        db.delete(row)
        g.likes_count = max(0, g.likes_count - 1)
        db.commit()
    return {"liked": False, "likes": g.likes_count}


@router.post("/games/{game_id}/favorite")
def favorite(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    if not db.get(Favorite, {"user_id": user.id, "game_id": g.id}):
        db.add(Favorite(user_id=user.id, game_id=g.id))
        db.commit()
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
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    if g.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not your game")
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
    db.delete(g)
    db.commit()
    return {"ok": True}
