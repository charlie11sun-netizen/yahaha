from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.db.session import get_db
from app.models import Favorite, Game, Like, PlayEvent
from app.models.common import GameStatus, now_utc
from app.services.serialize import fmt, game_card, game_detail

router = APIRouter(tags=["games"])


def _published(db: Session):
    return db.query(Game).filter(Game.status == GameStatus.PUBLISHED)


@router.get("/games")
def list_games(q: str = "", tag: str = "All", db: Session = Depends(get_db)):
    games = _published(db).order_by(Game.published_at.desc(), Game.created_at.desc()).all()
    ql = q.strip().lower()
    items = []
    for g in games:
        tags = [t.name for t in g.tags]
        if tag and tag != "All" and tag not in tags:
            continue
        if ql:
            author = g.author.display_name if g.author else ""
            hay = f"{g.title} {g.summary} {author} {' '.join(tags)}".lower()
            if ql not in hay:
                continue
        items.append(game_card(g))
    return {"items": items, "total": len(items)}


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


@router.get("/games/{game_id}")
def get_game(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g or (g.status != GameStatus.PUBLISHED and (not user or user.id != g.author_id)):
        raise HTTPException(status_code=404, detail="Game not found")
    return game_detail(g)


@router.get("/games/{game_id}/preview")
def preview_game(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    if g.author_id != user.id:
        raise HTTPException(status_code=403, detail="Not your game")
    return game_detail(g)


@router.post("/games/{game_id}/play")
def record_play(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    g = db.get(Game, game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    db.add(PlayEvent(game_id=g.id, user_id=user.id if user else None))
    g.plays_count += 1
    db.commit()
    return {"plays": g.plays_count, "plays_str": fmt(g.plays_count)}


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
