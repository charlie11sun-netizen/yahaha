"""ORM → 前端 DTO 序列化（字段对齐 PlayForge 设计稿）。"""
from datetime import datetime, timezone

from app.core.config import settings
from app.storage import s3


def fmt(n: int) -> str:
    if n >= 10000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def relative_time(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return "just now"
    for unit, sec in (("month", 2592000), ("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= sec:
            v = int(secs // sec)
            return f"{v} {unit}{'s' if v > 1 else ''} ago"
    return "just now"


def game_card(g) -> dict:
    return {
        "id": g.id,
        "title": g.title,
        "summary": g.summary,
        "genre": g.genre,
        "cover": g.cover,
        "version": g.current_version,
        "source": g.source,
        "from_create": g.source == "create",
        "status": g.status,
        "author": g.author.display_name if g.author else "—",
        "author_init": g.author.avatar_initial if g.author else "?",
        "tags": [t.name for t in g.tags],
        "plays": g.plays_count,
        "plays_str": fmt(g.plays_count),
        "likes": g.likes_count,
        "likes_str": fmt(g.likes_count),
        "published_at": g.published_at.isoformat() if g.published_at else None,
        "date": relative_time(g.published_at or g.created_at),
        "manifest_url": s3.manifest_url(g.id, g.current_version),
        "oss_path": f"oss://{settings.S3_BUCKET}/games/{g.id}/{g.current_version}/manifest.json",
    }


def game_detail(g) -> dict:
    d = game_card(g)
    d["prompt"] = g.prompt
    d["bundle_url"] = s3.public_url(f"games/{g.id}/{g.current_version}/index.html")
    return d


def user_out(u) -> dict:
    return {"id": u.id, "name": u.display_name, "email": u.email, "init": u.avatar_initial}


def task_out(t) -> dict:
    return {
        "id": t.id,
        "status": t.status,
        "current_step": t.current_step,
        "tokens": t.tokens_used,
        "error": t.error,
        "idea": t.idea,
        "steps": [
            {
                "seq": s.seq,
                "agent": s.agent,
                "name": s.name,
                "status": s.status,
                "logs": [log.line for log in s.logs],
            }
            for s in t.steps
        ],
        "game": game_card(t.result_game) if t.result_game else None,
    }
