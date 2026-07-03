"""公开作者主页 + 关注。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.db.session import get_db
from app.models import Follow, Game, User
from app.models.common import GameStatus
from app.services.serialize import game_card

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}")
def get_profile(user_id: str, viewer=Depends(get_optional_user), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    published = db.query(Game).filter(Game.author_id == u.id, Game.status == GameStatus.PUBLISHED)
    total_plays = (
        db.query(func.coalesce(func.sum(Game.plays_count), 0))
        .filter(Game.author_id == u.id, Game.status == GameStatus.PUBLISHED)
        .scalar()
        or 0
    )
    followers = db.query(func.count()).select_from(Follow).filter(Follow.following_id == u.id).scalar() or 0
    following = db.query(func.count()).select_from(Follow).filter(Follow.follower_id == u.id).scalar() or 0
    return {
        "id": u.id,
        "name": u.display_name,
        "init": u.avatar_initial,
        "game_count": published.count(),
        "total_plays": int(total_plays),
        "followers": int(followers),
        "following": int(following),
        "is_following": bool(viewer and db.get(Follow, {"follower_id": viewer.id, "following_id": u.id})),
        "is_self": bool(viewer and viewer.id == u.id),
    }


@router.get("/{user_id}/games")
def get_user_games(user_id: str, db: Session = Depends(get_db)):
    games = (
        db.query(Game)
        .filter(Game.author_id == user_id, Game.status == GameStatus.PUBLISHED)
        .order_by(Game.published_at.desc(), Game.created_at.desc())
        .all()
    )
    return {"items": [game_card(g) for g in games]}


@router.post("/{user_id}/follow")
def follow(user_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not db.get(Follow, {"follower_id": user.id, "following_id": user_id}):
        db.add(Follow(follower_id=user.id, following_id=user_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # 并发双击：复合主键兜底，当作已关注
    return {"following": True}


@router.delete("/{user_id}/follow")
def unfollow(user_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(Follow, {"follower_id": user.id, "following_id": user_id})
    if row:
        db.delete(row)
        db.commit()
    return {"following": False}
