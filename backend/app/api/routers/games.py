from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user, rate_limit
from app.db.session import get_db
from app.schemas import (
    CommentIn,
    CommentListOut,
    CommentOut,
    FavoriteOut,
    GameCardOut,
    GameCollectionOut,
    GameDetailOut,
    GameListOut,
    GameManifestOut,
    GameStatsOut,
    GameUpdateIn,
    GameVersionListOut,
    LeaderboardOut,
    LikeOut,
    OkOut,
    PlayOut,
    ScoreIn,
    TagsOut,
)
from app.services import game_actions
from app.services.errors import ServiceError
from app.services.serialize import comment_out, fmt, game_card, game_detail, score_out
from app.storage import s3  # kept for tests/monkeypatches that patch router.s3

router = APIRouter(tags=["games"])


def _run(action):
    try:
        return action()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _version_out(version, current_version: str) -> dict:
    return {
        "version": version.version,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "size_bytes": version.size_bytes,
        "sha256": version.sha256,
        "is_current": version.version == current_version,
    }


@router.get("/games", response_model=GameListOut, response_model_exclude_unset=True)
def list_games(
    q: str = "",
    tag: str = "All",
    sort: str = "newest",
    limit: int = 24,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    page, total, offset, limit = game_actions.list_games(
        db, q=q, tag=tag, sort=sort, limit=limit, offset=offset
    )
    return {
        "items": [game_card(game) for game in page],
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/stats", response_model=GameStatsOut, response_model_exclude_unset=True)
def stats(db: Session = Depends(get_db)):
    return game_actions.game_stats(db)


@router.get("/tags", response_model=TagsOut, response_model_exclude_unset=True)
def list_tags(db: Session = Depends(get_db)):
    return {"tags": game_actions.list_tag_names(db)}


@router.get("/me/games", response_model=GameCollectionOut, response_model_exclude_unset=True)
def my_games(
    limit: int = 24,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page, total, offset, limit = game_actions.list_user_games(db, user, limit=limit, offset=offset)
    return {
        "items": [game_card(game) for game in page],
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/me/favorites", response_model=GameCollectionOut, response_model_exclude_unset=True)
def my_favorites(
    limit: int = 24,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page, total, offset, limit = game_actions.list_user_favorites(db, user, limit=limit, offset=offset)
    return {
        "items": [game_card(game) for game in page],
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/games/{game_id}", response_model=GameDetailOut, response_model_exclude_unset=True)
def get_game(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    game, liked, favorited = _run(lambda: game_actions.get_game_detail_state(db, game_id, user))
    out = game_detail(game)
    out["liked"] = liked
    out["favorited"] = favorited
    return out


@router.get("/games/{game_id}/preview", response_model=GameDetailOut, response_model_exclude_unset=True)
def preview_game(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return game_detail(_run(lambda: game_actions.preview_game(db, game_id, user)))


@router.get("/games/{game_id}/versions", response_model=GameVersionListOut, response_model_exclude_unset=True)
def list_versions(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows, current_version = _run(lambda: game_actions.list_versions(db, game_id, user))
    return {"items": [_version_out(row, current_version) for row in rows]}


@router.post(
    "/games/{game_id}/versions/{version}/activate",
    response_model=GameDetailOut,
    response_model_exclude_unset=True,
)
def activate_version(
    game_id: str,
    version: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = _run(lambda: game_actions.activate_version(db, game_id, version, user))
    return game_detail(game)


@router.post(
    "/games/{game_id}/play",
    response_model=PlayOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(60, 60, "play"))],
)
def record_play(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    game, counted = _run(lambda: game_actions.record_play(db, game_id, user))
    return {"plays": game.plays_count, "plays_str": fmt(game.plays_count), "counted": counted}


@router.post("/games/{game_id}/like", response_model=LikeOut, response_model_exclude_unset=True)
def like(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    game = _run(lambda: game_actions.set_like(db, game_id, user, True))
    return {"liked": True, "likes": game.likes_count}


@router.delete("/games/{game_id}/like", response_model=LikeOut, response_model_exclude_unset=True)
def unlike(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    game = _run(lambda: game_actions.set_like(db, game_id, user, False))
    return {"liked": False, "likes": game.likes_count}


@router.post("/games/{game_id}/favorite", response_model=FavoriteOut, response_model_exclude_unset=True)
def favorite(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _run(lambda: game_actions.set_favorite(db, game_id, user, True))
    return {"favorited": True}


@router.delete("/games/{game_id}/favorite", response_model=FavoriteOut, response_model_exclude_unset=True)
def unfavorite(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _run(lambda: game_actions.set_favorite(db, game_id, user, False))
    return {"favorited": False}


@router.post("/games/{game_id}/publish", response_model=GameCardOut, response_model_exclude_unset=True)
def publish(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return game_card(_run(lambda: game_actions.publish_game(db, game_id, user)))


@router.post("/games/{game_id}/unpublish", response_model=GameCardOut, response_model_exclude_unset=True)
def unpublish(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return game_card(_run(lambda: game_actions.unpublish_game(db, game_id, user)))


@router.patch("/games/{game_id}", response_model=GameDetailOut, response_model_exclude_unset=True)
def update_game(game_id: str, body: GameUpdateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    game = _run(
        lambda: game_actions.update_game(
            db,
            game_id,
            user,
            title=body.title,
            summary=body.summary,
            tags=body.tags,
        )
    )
    return game_detail(game)


@router.delete("/games/{game_id}", response_model=OkOut, response_model_exclude_unset=True)
def delete_game(game_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _run(lambda: game_actions.delete_game(db, game_id, user))
    return {"ok": True}


@router.get("/games/{game_id}/comments", response_model=CommentListOut, response_model_exclude_unset=True)
def list_comments(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    comments = _run(lambda: game_actions.list_comments(db, game_id, user))
    return {"items": [comment_out(comment) for comment in comments]}


@router.post(
    "/games/{game_id}/comments",
    response_model=CommentOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(30, 3600, "comment"))],
)
def add_comment(game_id: str, body: CommentIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    comment = _run(lambda: game_actions.add_comment(db, game_id, user, body.body))
    return comment_out(comment)


@router.delete("/games/{game_id}/comments/{comment_id}", response_model=OkOut, response_model_exclude_unset=True)
def delete_comment(game_id: str, comment_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _run(lambda: game_actions.delete_comment(db, game_id, comment_id, user))
    return {"ok": True}


@router.get("/games/{game_id}/related", response_model=GameCollectionOut, response_model_exclude_unset=True)
def related_games(game_id: str, limit: int = 6, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    games = _run(lambda: game_actions.related_games(db, game_id, user, limit=limit))
    return {"items": [game_card(game) for game in games]}


@router.post(
    "/games/{game_id}/score",
    response_model=OkOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(60, 3600, "score"))],
)
def submit_score(game_id: str, body: ScoreIn, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    _run(
        lambda: game_actions.submit_score(
            db,
            game_id,
            user,
            player_name=body.player_name,
            points=body.points,
        )
    )
    return {"ok": True}


@router.get("/games/{game_id}/leaderboard", response_model=LeaderboardOut, response_model_exclude_unset=True)
def leaderboard(game_id: str, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    rows = _run(lambda: game_actions.leaderboard(db, game_id, user))
    return {"items": [score_out(score, rank=i + 1) for i, score in enumerate(rows)]}


@router.get("/games/{game_id}/files/{token}/{version}/{file_path:path}")
def game_file(game_id: str, token: str, version: str, file_path: str, db: Session = Depends(get_db)):
    body, media_type = _run(lambda: game_actions.game_file(db, game_id, token, version, file_path))
    return Response(content=body, media_type=media_type)


@router.get("/games/{game_id}/manifest", response_model=GameManifestOut, response_model_exclude_unset=True)
def game_manifest(
    game_id: str,
    version: str | None = None,
    user=Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    return _run(lambda: game_actions.game_manifest(db, game_id, user, version=version))
