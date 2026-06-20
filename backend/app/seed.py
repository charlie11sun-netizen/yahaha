"""Idempotent database seed for curated PlayForge sample games.

The API container runs this module at startup. It creates tables, prunes any
retired sample games (DB rows + their object-storage artifacts), ensures demo
users exist, uploads playable HTML bundles to object storage, and creates or
refreshes the published sample game rows.

Curated set (3 published games, satisfying "≥3 示例游戏, ≥1 由 Create 流程生成并发布"):
  - Prism Break  — 2D brick-breaker, hand-authored seed (source=seed)
  - Warp Spire   — 3D tunnel flyer, hand-authored seed (source=seed)
  - 火线突围      — 3D arena shooter, **produced by the real Create pipeline (GPT-5.5)**
                   from the prompt below; the generated bundle is curated here and
                   seeded with source=create, so Home shows a Create-origin game out
                   of the box (AI badge + detail "Generated from prompt" light up).

Live Create-flow games published by users (e.g. "Neon Arena: Dronefall") appear on
Home in addition to this curated set; they are not in this seed and not retired here.
"""
from datetime import timedelta

import app.models  # noqa: F401 - registers SQLAlchemy models
from app.agents import bundles
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Game, GameVersion, Tag, User
from app.models.common import GameSource, GameStatus, now_utc
from app.services.packaging import three_engine_bytes, write_bundle
from app.storage import s3
from app.storage.s3 import ensure_bucket


SEED_GAMES = [
    {
        "bundle": "prismbreak",
        "title": "Prism Break",
        "genre": "BRICK BREAKER",
        "summary": "A juicy neon brick-breaker. Bounce the prism, shatter glowing brick fields, "
                   "chain combos for big multipliers, and snag multiball, wide-paddle and slow-mo "
                   "power-ups across escalating waves.",
        "tags": ["Arcade", "Action", "Neon"],
        "cover": "/playforge/covers/prism-break.svg",
        "plays": 48230,
        "likes": 3960,
        "source": GameSource.SEED,
        "prompt": "",
        "age_days": 1,
    },
    {
        "bundle": "warpspire",
        "title": "Warp Spire",
        "genre": "3D TUNNEL FLYER",
        "summary": "A high-speed 3D tunnel flyer. Roll around a glowing spire, thread the gaps in the "
                   "wall-bars and scoop orbs as the run accelerates. Rendered with self-hosted Three.js "
                   "and loaded from object storage like every other game.",
        "tags": ["3D", "Arcade", "Endless"],
        "cover": "/playforge/covers/warp-spire.svg",
        "plays": 41760,
        "likes": 3515,
        "source": GameSource.SEED,
        "prompt": "",
        "age_days": 2,
    },
    {
        "bundle": "huoxiantuwei",
        "title": "火线突围",
        "genre": "3D ARENA SHOOTER",
        "summary": "一款霓虹街区 3D 枪战游戏。在废弃仓库街区利用掩体压制敌人、拾取补给升级武器，"
                   "扛过一波波进攻并击败首领 Iron Gate Captain。自托管 Three.js，和其它游戏一样从对象存储加载。",
        "tags": ["3D", "Shooter", "Action"],
        "cover": "linear-gradient(135deg,#ff8a3d,#ff3ea5)",
        "plays": 920,
        "likes": 74,
        # 真·Create 来源：由真实 Create 流水线（GPT-5.5）按下方 prompt 生成，
        # 产物固化为旗舰 bundle 随 seed 发布。标 create 让首页「AI 生成」角标、
        # 详情页 "Generated from prompt" 与接口 from_create=true 如实反映来源。
        "source": GameSource.CREATE,
        "prompt": "枪战游戏，有障碍物，有道具，枪械可以升级",
        "age_days": 1,
    },
]

# Previously-seeded sample games that are no longer part of the curated set.
# Pruned (DB row + OSS prefix) on every seed run so the home feed stays exactly
# the curated set + live Create games. Idempotent: a no-op once they are gone.
RETIRED_TITLES = [
    "Moonlit Koi",
    "Rune Circuit",
    "Neon Drift Dodge",
    "Cloud Courier",
    "Orbit Bloom",
    "Color Echo",
    "Star Catcher",
]


def _get_or_create_tag(db, name: str) -> Tag:
    tag = db.query(Tag).filter_by(name=name).first()
    if not tag:
        tag = Tag(name=name)
        db.add(tag)
        db.flush()
    return tag


def _get_or_create_user(db, email: str, name: str, initial: str, with_password: bool = False) -> User:
    user = db.query(User).filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            password_hash=hash_password("password") if with_password else None,
            display_name=name,
            avatar_initial=initial,
        )
        db.add(user)
        db.flush()
    return user


def _sync_tags(db, game: Game, names: list[str]) -> None:
    game.tags.clear()
    for name in names:
        game.tags.append(_get_or_create_tag(db, name))


def _sync_version(db, game: Game, seed: dict, author_name: str) -> None:
    html = bundles.BUNDLES[seed["bundle"]]
    # 3D bundles reference three.min.js via a same-prefix relative <script src>.
    # Ship the vendored engine alongside index.html so the sandboxed iframe can
    # resolve it against its own remote URL (no external network, no CDN).
    extra_assets = None
    if seed["bundle"] in bundles.NEEDS_ENGINE:
        engine_bytes = three_engine_bytes()
        if engine_bytes:
            extra_assets = {"three.min.js": engine_bytes}

    info = write_bundle(game.id, "v1", html, seed["title"], author_name, extra_assets=extra_assets)
    version = db.query(GameVersion).filter_by(game_id=game.id, version="v1").first()
    if not version:
        version = GameVersion(game_id=game.id, version="v1")
        db.add(version)
    version.manifest_key = info["manifest_key"]
    version.bundle_key = info["bundle_key"]
    version.entry = "index.html"
    version.runtime = "iframe-sandbox"
    version.sha256 = info["sha256"]
    version.size_bytes = info["size"]


def _prune_retired(db) -> int:
    """Remove retired sample games and their remote artifacts. Idempotent."""
    removed = 0
    for title in RETIRED_TITLES:
        for game in db.query(Game).filter(Game.title == title).all():
            s3.delete_prefix(f"games/{game.id}/")  # bundle + manifest + any assets
            db.delete(game)                          # cascades versions / likes / scores / ...
            removed += 1
    if removed:
        db.commit()
    return removed


def run() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_bucket()
    db = SessionLocal()
    try:
        pruned = _prune_retired(db)

        demo = _get_or_create_user(db, "demo@playforge.dev", "PlayForge Demo", "P", with_password=True)
        created = 0
        refreshed = 0

        for seed in SEED_GAMES:
            author = demo
            game = db.query(Game).filter_by(title=seed["title"]).first()
            if game:
                refreshed += 1
            else:
                created += 1
                game = Game(
                    author_id=author.id,
                    title=seed["title"],
                    published_at=now_utc() - timedelta(days=seed["age_days"]),
                )
                db.add(game)
                db.flush()

            game.author_id = author.id
            game.summary = seed["summary"]
            game.genre = seed["genre"]
            game.cover = seed["cover"]
            game.source = seed["source"]
            game.status = GameStatus.PUBLISHED
            game.current_version = "v1"
            game.prompt = seed.get("prompt") or None
            game.plays_count = max(game.plays_count or 0, seed["plays"])
            game.likes_count = max(game.likes_count or 0, seed["likes"])
            if not game.published_at:
                game.published_at = now_utc() - timedelta(days=seed["age_days"])

            _sync_tags(db, game, seed["tags"])
            _sync_version(db, game, seed, author.display_name)

        db.commit()
        print(
            f"seed: pruned {pruned} retired, created {created}, refreshed {refreshed} "
            f"curated game(s) (bundles uploaded to OSS)"
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
