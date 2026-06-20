"""产物打包上传到对象存储。

- write_bundle：单文件 bundle（seed 示例游戏沿用）
- publish_generated：多文件产物 index.html/style.css/game.js + manifest.json（game-manifest/v1），
  对应 docs/multi-agent_design.md §6.9 PublishArtifactAgent
"""
import hashlib
import json
import os

from app.models.common import now_utc
from app.storage import s3

_CONTENT_TYPE = {
    "index.html": "text/html; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "game.js": "application/javascript; charset=utf-8",
    "three.min.js": "application/javascript; charset=utf-8",
}

# 自托管的 3D 引擎（vendored Three.js UMD）。发布 3D 游戏时随 bundle 同源注入，
# 用相对路径 <script src="three.min.js"> 引入，绕过外链校验、保持 network=false。
_THREE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "vendor", "three.min.js")
_THREE_CACHE: bytes | None = None


def _three_engine_bytes() -> bytes | None:
    global _THREE_CACHE
    if _THREE_CACHE is None:
        try:
            with open(_THREE_PATH, "rb") as fh:
                _THREE_CACHE = fh.read()
        except OSError:
            _THREE_CACHE = b""
    return _THREE_CACHE or None


def three_engine_bytes() -> bytes | None:
    """Public accessor for the vendored Three.js UMD (seed uploads it for 3D bundles)."""
    return _three_engine_bytes()


def write_bundle(
    game_id: str,
    version: str,
    html: str,
    title: str,
    author_name: str,
    extra_assets: dict[str, bytes] | None = None,
) -> dict:
    prefix = s3.game_prefix(game_id, version)
    bundle_key = f"{prefix}/index.html"
    manifest_key = f"{prefix}/manifest.json"
    body = html.encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()

    s3.put_object(bundle_key, html, "text/html; charset=utf-8")

    assets = ["index.html"]
    # Same-prefix sibling files referenced by the bundle via relative <src>
    # (e.g. three.min.js for 3D games). Uploaded next to index.html so the
    # sandboxed iframe resolves them against its own remote URL.
    for name, data in (extra_assets or {}).items():
        s3.put_object(f"{prefix}/{name}", data, _CONTENT_TYPE.get(name, "application/octet-stream"))
        assets.append(name)

    manifest = {
        "schemaVersion": 1, "id": game_id, "title": title, "version": version, "entry": "index.html",
        "runtime": "iframe-sandbox", "sandbox": "allow-scripts allow-pointer-lock",
        "assets": assets, "sha256": sha, "createdBy": author_name, "createdAt": now_utc().isoformat(),
    }
    s3.put_object(manifest_key, json.dumps(manifest, ensure_ascii=False, indent=2), "application/json")
    return {"manifest_key": manifest_key, "bundle_key": bundle_key, "sha256": sha, "size": len(body)}


def publish_generated(state: dict) -> tuple[str, str, str]:
    """上传多文件产物 + manifest，创建 Game + GameVersion；返回 (game_id, version_id, manifest_url)。"""
    from app.db.session import SessionLocal
    from app.models import Game, GameVersion, Tag
    from app.models.common import GameSource, GameStatus

    spec = state.get("game_spec") or {}
    asset_manifest = state.get("asset_manifest") or {}
    files = state.get("generated_files") or []
    prompt = state.get("normalized_prompt") or state.get("prompt") or ""

    title = str(spec.get("title") or "Untitled Game")[:60]
    genre = str(spec.get("genre") or "arcade").upper()[:80]
    summary = str(spec.get("summary") or prompt)[:200]
    cover = asset_manifest.get("cover") or "linear-gradient(135deg,#ff8a3d,#ff3ea5)"
    tags = [str(t)[:30] for t in (spec.get("tags") or [])][:4] + ["AI"]
    if str(state.get("dimension")) == "3d":
        tags.append("3D")

    db = SessionLocal()
    try:
        game = Game(
            author_id=state.get("user_id"), title=title, summary=summary, genre=genre, cover=cover,
            source=GameSource.CREATE, status=GameStatus.PREVIEW, current_version="v1",
            prompt=prompt, plays_count=0, likes_count=0,
        )
        for name in tags:
            tag = db.query(Tag).filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.add(tag)
            game.tags.append(tag)
        db.add(game)
        db.flush()
        gid = game.id

        prefix = s3.game_prefix(gid, "v1")
        uploaded = []
        for f in files:
            key = f"{prefix}/{f['path']}"
            s3.put_object(key, f["content"], _CONTENT_TYPE.get(f["path"], "text/plain; charset=utf-8"))
            uploaded.append({
                "path": f["path"], "url": s3.public_url(key),
                "sha256": hashlib.sha256(f["content"].encode("utf-8")).hexdigest(),
            })

        # 3D：把自托管引擎放进同一前缀，bundle 内用相对路径加载（不进 validate_files）。
        if str(state.get("dimension")) == "3d":
            engine = _three_engine_bytes()
            if engine:
                ekey = f"{prefix}/three.min.js"
                s3.put_object(ekey, engine, _CONTENT_TYPE["three.min.js"])
                uploaded.append({
                    "path": "three.min.js", "url": s3.public_url(ekey),
                    "sha256": hashlib.sha256(engine).hexdigest(),
                })

        index_sha = next((u["sha256"] for u in uploaded if u["path"] == "index.html"), "")
        version = GameVersion(
            game_id=gid, version="v1", manifest_key=f"{prefix}/manifest.json",
            bundle_key=f"{prefix}/index.html", entry="index.html", runtime="iframe-html",
            sha256=index_sha, size_bytes=sum(len(f["content"].encode("utf-8")) for f in files),
            source_task_id=state.get("task_id"),
        )
        db.add(version)
        db.flush()
        vid = version.id

        manifest = {
            "schema_version": "game-manifest/v1", "game_id": gid, "version_id": vid, "title": title,
            "runtime": "iframe-html", "entry": "index.html", "entry_url": s3.public_url(f"{prefix}/index.html"),
            "files": uploaded, "assets": asset_manifest.get("assets", []),
            "permissions": {"network": False, "storage": False, "cookies": False},
        }
        s3.put_object(f"{prefix}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2), "application/json")
        db.commit()
        return gid, vid, s3.manifest_url(gid, "v1")
    finally:
        db.close()
