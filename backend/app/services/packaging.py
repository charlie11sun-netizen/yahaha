"""产物打包上传到对象存储。

- write_bundle：单文件 bundle（seed 示例游戏沿用）
- publish_generated：多文件产物 index.html/style.css/game.js + manifest.json（game-manifest/v1），
  对应 docs/multi-agent_design.md §6.9 PublishArtifactAgent
"""
import hashlib
import json
import os

from app.models.common import now_utc
from app.services.artifacts import (
    artifact_bytes,
    artifact_content_type,
    artifact_text,
    normalize_artifact_path,
    text_artifact,
)
from app.services.runtime_urls import game_manifest_url
from app.storage import s3

_CONTENT_TYPE = {
    "index.html": "text/html; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "game.js": "application/javascript; charset=utf-8",
    "three.min.js": "application/javascript; charset=utf-8",
    "phaser.min.js": "application/javascript; charset=utf-8",
}
# 作者模式的 bundle 可以带 agent 自定名字的模块（shop.js/hud.css 等）：MIME 必须
# 按扩展名兜底——text/plain 的 <script> 会被带 nosniff 的浏览器/CDN 拒绝执行。
_EXT_CONTENT_TYPE = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
}


def _content_type_for(path: str, default: str = "text/plain; charset=utf-8") -> str:
    name = str(path or "")
    if name in _CONTENT_TYPE:
        return _CONTENT_TYPE[name]
    return _EXT_CONTENT_TYPE.get(os.path.splitext(name)[1].lower(), default)


def _prepare_runtime_file(file: dict) -> tuple[str, bytes, str]:
    path = normalize_artifact_path(str(file.get("path") or ""))
    item = dict(file)
    if path == "index.html":
        text = artifact_text(item)
        if text is None:
            raise RuntimeError("index.html must be UTF-8 text")
        item = text_artifact(path, inject_csp(text), "text/html; charset=utf-8")
    return path, artifact_bytes(item), artifact_content_type(item)


def _upload_runtime_files(prefix: str, files: list[dict]) -> tuple[list[dict], int]:
    uploaded: list[dict] = []
    total_bytes = 0
    for file in files:
        path, body, content_type = _prepare_runtime_file(file)
        s3.put_object(f"{prefix}/{path}", body, content_type)
        total_bytes += len(body)
        uploaded.append(
            {
                "path": path,
                "sha256": hashlib.sha256(body).hexdigest(),
                "size": len(body),
                "content_type": content_type,
            }
        )
    return uploaded, total_bytes


def _source_prefix(game_id: str, version: str) -> str:
    return f"game-sources/{game_id}/{version}"


def _upload_source_project(game_id: str, version: str, files: list[dict]) -> None:
    if not files:
        return
    prefix = _source_prefix(game_id, version)
    manifest_files = []
    for file in files:
        path = normalize_artifact_path(str(file.get("path") or ""))
        body = artifact_bytes(file)
        content_type = artifact_content_type(file)
        s3.put_object(f"{prefix}/{path}", body, content_type)
        manifest_files.append(
            {
                "path": path,
                "sha256": hashlib.sha256(body).hexdigest(),
                "size": len(body),
                "content_type": content_type,
            }
        )
    source_manifest = {"schema_version": "game-source/v1", "files": manifest_files}
    s3.put_object(
        f"{prefix}/manifest.json",
        json.dumps(source_manifest, ensure_ascii=False, indent=2),
        "application/json",
    )

# iframe 的 sandbox 属性并不拦网络请求；manifest 承诺的 permissions.network=false
# 靠这里注入的 CSP 在浏览器层强制：default-src 'none' 掐断外链脚本等一切非白名单
# 加载；同前缀相对路径资源（style.css / game.js / three.min.js）经 'self' 放行。
# connect-src 必须是 'self' 而非 'none'：Phaser 3 的 Loader 对图片/图集/tilemap
# JSON 一律走 XHR（拿 blob 再建纹理），'none' 会把生成的 sheet.png/background.png
# 全部拦成 missing-texture 绿框（2026-07-12 实测事故）。'self' 仍然掐断一切跨源
# fetch/XHR/WebSocket/sendBeacon 外呼，防外泄语义不变。
_CSP_META = (
    '<meta http-equiv="Content-Security-Policy" content="'
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'none'; "
    "base-uri 'none'\">"
)


def inject_csp(html: str) -> str:
    """幂等地把 CSP <meta> 插到 <head> 开头（无 <head> 时置于文档最前）。"""
    if 'http-equiv="Content-Security-Policy"' in html:
        return html
    head_at = html.lower().find("<head")
    if head_at != -1:
        close = html.find(">", head_at)
        if close != -1:
            return html[: close + 1] + _CSP_META + html[close + 1:]
    return _CSP_META + html

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


# Historical self-hosted Phaser UMD engine retained only for legacy bundle playback.
# Legacy bundles that reference phaser.min.js still receive the same-origin engine.
_PHASER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", "vendor", "phaser.min.js")
_PHASER_CACHE: bytes | None = None


def _phaser_engine_bytes() -> bytes | None:
    global _PHASER_CACHE
    if _PHASER_CACHE is None:
        try:
            with open(_PHASER_PATH, "rb") as fh:
                _PHASER_CACHE = fh.read()
        except OSError:
            _PHASER_CACHE = b""
    return _PHASER_CACHE or None


def phaser_engine_bytes() -> bytes | None:
    """Public accessor for the vendored Phaser 4 UMD (QA sandbox / seed reuse)."""
    return _phaser_engine_bytes()


def _bundle_references(files: list[dict], name: str) -> bool:
    """产物 index.html 是否用相对路径引用了指定引擎文件（决定是否随包发布）。"""
    index = next(
        (str(f.get("content") or "") for f in files if str(f.get("path") or "") == "index.html"),
        "",
    )
    return name in index


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
    html = inject_csp(html)
    body = html.encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()

    s3.put_object(bundle_key, html, "text/html; charset=utf-8")

    files = [{"path": "index.html", "sha256": sha}]
    # Same-prefix sibling files referenced by the bundle via relative <src>
    # (e.g. three.min.js for 3D games). Uploaded next to index.html so the
    # sandboxed iframe resolves them against its own remote URL.
    for name, data in (extra_assets or {}).items():
        s3.put_object(f"{prefix}/{name}", data, _content_type_for(name, default="application/octet-stream"))
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})

    manifest = {
        "schemaVersion": 1, "id": game_id, "title": title, "version": version, "entry": "index.html",
        "runtime": "iframe-sandbox", "sandbox": "allow-scripts allow-pointer-lock",
        "files": files, "sha256": sha, "createdBy": author_name, "createdAt": now_utc().isoformat(),
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
        # 幂等：崩溃重投递会整图重跑到这里。该任务已发布过就复用既有产物，
        # 不再新建第二个 Game / 重传 bundle。
        existing = db.query(GameVersion).filter_by(source_task_id=state.get("task_id")).first()
        if existing:
            return existing.game_id, existing.id, game_manifest_url(existing.game_id, existing.version)

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
        uploaded, total_bytes = _upload_runtime_files(prefix, files)
        _upload_source_project(gid, "v1", state.get("project_files") or [])

        # 引擎随包发布：把自托管引擎放进同一前缀，bundle 内用相对路径加载（不进 validate_files）。
        if str(state.get("dimension")) == "3d":
            engine = _three_engine_bytes()
            if engine:
                ekey = f"{prefix}/three.min.js"
                s3.put_object(ekey, engine, _CONTENT_TYPE["three.min.js"])
                uploaded.append({
                    "path": "three.min.js",
                    "sha256": hashlib.sha256(engine).hexdigest(),
                })
        elif _bundle_references(files, "phaser.min.js"):
            engine = _phaser_engine_bytes()
            if engine:
                ekey = f"{prefix}/phaser.min.js"
                s3.put_object(ekey, engine, _CONTENT_TYPE["phaser.min.js"])
                uploaded.append({
                    "path": "phaser.min.js",
                    "sha256": hashlib.sha256(engine).hexdigest(),
                })

        index_sha = next((u["sha256"] for u in uploaded if u["path"] == "index.html"), "")
        runtime = "phaser-vite-dist" if state.get("artifact_format") == "phaser-vite/v1" else "iframe-html"
        version = GameVersion(
            game_id=gid, version="v1", manifest_key=f"{prefix}/manifest.json",
            bundle_key=f"{prefix}/index.html", entry="index.html", runtime=runtime,
            sha256=index_sha, size_bytes=total_bytes,
            source_task_id=state.get("task_id"),
        )
        db.add(version)
        db.flush()
        vid = version.id

        manifest = {
            "schema_version": "game-manifest/v1", "game_id": gid, "version_id": vid, "title": title,
            "runtime": runtime, "entry": "index.html",
            "files": uploaded, "assets": asset_manifest.get("assets", []),
            "permissions": {"network": False, "storage": False, "cookies": False},
            "artifact_format": state.get("artifact_format") or "legacy-bundle/v1",
            "build": state.get("build_result") or {},
        }
        s3.put_object(f"{prefix}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2), "application/json")
        db.commit()
        return gid, vid, game_manifest_url(gid, "v1")
    finally:
        db.close()


def publish_revision(state: dict) -> tuple[str, str, str, str]:
    """Upload a full vN+1 bundle assembled from incremental edits.

    Existing versions are immutable. The base-version check prevents two
    revision tasks from silently overwriting each other.
    """
    from app.db.session import SessionLocal
    from app.models import Game, GameVersion
    from app.models.common import GameStatus

    game_id = state.get("base_game_id")
    base_version = state.get("base_version")
    files = state.get("generated_files") or []
    db = SessionLocal()
    try:
        # 幂等：同 publish_generated —— 重投递重跑时直接复用该任务已产出的版本
        # （此时 current_version 已前进，继续往下走会被 stale-base 检查误杀）。
        existing = db.query(GameVersion).filter_by(source_task_id=state.get("task_id")).first()
        if existing:
            return (
                existing.game_id,
                existing.id,
                existing.version,
                game_manifest_url(existing.game_id, existing.version),
            )

        game = db.get(Game, game_id)
        if not game or game.author_id != state.get("user_id"):
            raise RuntimeError("revision target is missing or not owned by the user")
        if game.status == GameStatus.PUBLISHED:
            raise RuntimeError("published games cannot be revised in the preview workflow")
        if game.current_version != base_version:
            raise RuntimeError(
                f"stale revision base: expected {base_version}, current is {game.current_version}"
            )

        version_numbers = []
        for row in game.versions:
            value = str(row.version or "")
            if value.startswith("v") and value[1:].isdigit():
                version_numbers.append(int(value[1:]))
        version_name = f"v{max(version_numbers or [0]) + 1}"
        prefix = s3.game_prefix(game.id, version_name)
        uploaded, size_bytes = _upload_runtime_files(prefix, files)
        _upload_source_project(game.id, version_name, state.get("project_files") or [])

        if str(state.get("dimension")) == "3d":
            engine = _three_engine_bytes()
            if engine:
                engine_key = f"{prefix}/three.min.js"
                s3.put_object(engine_key, engine, _CONTENT_TYPE["three.min.js"])
                uploaded.append({
                    "path": "three.min.js",
                    "sha256": hashlib.sha256(engine).hexdigest(),
                })
        elif _bundle_references(files, "phaser.min.js"):
            engine = _phaser_engine_bytes()
            if engine:
                engine_key = f"{prefix}/phaser.min.js"
                s3.put_object(engine_key, engine, _CONTENT_TYPE["phaser.min.js"])
                uploaded.append({
                    "path": "phaser.min.js",
                    "sha256": hashlib.sha256(engine).hexdigest(),
                })

        index_sha = next((item["sha256"] for item in uploaded if item["path"] == "index.html"), "")
        runtime = "phaser-vite-dist" if state.get("artifact_format") == "phaser-vite/v1" else "iframe-html"
        version = GameVersion(
            game_id=game.id,
            version=version_name,
            manifest_key=f"{prefix}/manifest.json",
            bundle_key=f"{prefix}/index.html",
            entry="index.html",
            runtime=runtime,
            sha256=index_sha,
            size_bytes=size_bytes,
            source_task_id=state.get("task_id"),
        )
        db.add(version)
        db.flush()
        manifest = {
            "schema_version": "game-manifest/v1",
            "game_id": game.id,
            "version_id": version.id,
            "title": game.title,
            "runtime": runtime,
            "entry": "index.html",
            "files": uploaded,
            "permissions": {"network": False, "storage": False, "cookies": False},
            "artifact_format": state.get("artifact_format") or "legacy-bundle/v1",
            "build": state.get("build_result") or {},
            "revision": {
                "base_version": base_version,
                "changed_files": (state.get("revision_result") or {}).get("changed_files") or [],
            },
        }
        s3.put_object(
            f"{prefix}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
            "application/json",
        )
        game.current_version = version_name
        game.status = GameStatus.PREVIEW
        db.commit()
        return game.id, version.id, version_name, game_manifest_url(game.id, version_name)
    finally:
        db.close()


def publish_remix(state: dict) -> tuple[str, str, str]:
    """Publish a remix as a brand-new preview game with immutable v1 artifacts."""
    from app.db.session import SessionLocal
    from app.models import Game, GameVersion, Tag
    from app.models.common import GameSource, GameStatus

    source_game_id = state.get("base_game_id")
    source_version = state.get("base_version")
    files = state.get("generated_files") or []
    spec = state.get("game_spec") or {}
    feedback = state.get("source_feedback") or state.get("prompt") or ""

    db = SessionLocal()
    try:
        existing = db.query(GameVersion).filter_by(source_task_id=state.get("task_id")).first()
        if existing:
            return existing.game_id, existing.id, game_manifest_url(existing.game_id, existing.version)

        source = db.get(Game, source_game_id)
        if not source or (source.status != GameStatus.PUBLISHED and source.author_id != state.get("user_id")):
            raise RuntimeError("remix source is missing or not visible")

        title = str(spec.get("title") or f"{source.title} Remix")[:60]
        if title == source.title:
            title = f"{title} Remix"[:60]
        summary_seed = spec.get("summary") or feedback or source.summary
        summary = str(summary_seed)[:200]
        genre = str(spec.get("genre") or source.genre or "arcade").upper()[:80]
        cover = source.cover or "linear-gradient(135deg,#7c5cff,#2dd4bf)"
        tags = [str(tag.name)[:30] for tag in source.tags[:3]]
        for tag in [*(spec.get("tags") or [])[:3], "Remix", "AI"]:
            tag_name = str(tag)[:30]
            if tag_name and tag_name not in tags:
                tags.append(tag_name)

        game = Game(
            author_id=state.get("user_id"),
            title=title,
            summary=summary,
            genre=genre,
            cover=cover,
            source=GameSource.CREATE,
            status=GameStatus.PREVIEW,
            current_version="v1",
            prompt=feedback,
            plays_count=0,
            likes_count=0,
            remixed_from_game_id=source.id,
            remixed_from_version=source_version,
        )
        for name in tags[:6]:
            tag = db.query(Tag).filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.add(tag)
            game.tags.append(tag)
        db.add(game)
        db.flush()

        prefix = s3.game_prefix(game.id, "v1")
        uploaded, size_bytes = _upload_runtime_files(prefix, files)
        _upload_source_project(game.id, "v1", state.get("project_files") or [])

        if str(state.get("dimension")) == "3d":
            engine = _three_engine_bytes()
            if engine:
                key = f"{prefix}/three.min.js"
                s3.put_object(key, engine, _CONTENT_TYPE["three.min.js"])
                uploaded.append({
                    "path": "three.min.js",
                    "sha256": hashlib.sha256(engine).hexdigest(),
                })
        elif _bundle_references(files, "phaser.min.js"):
            engine = _phaser_engine_bytes()
            if engine:
                key = f"{prefix}/phaser.min.js"
                s3.put_object(key, engine, _CONTENT_TYPE["phaser.min.js"])
                uploaded.append({
                    "path": "phaser.min.js",
                    "sha256": hashlib.sha256(engine).hexdigest(),
                })

        index_sha = next((item["sha256"] for item in uploaded if item["path"] == "index.html"), "")
        runtime = "phaser-vite-dist" if state.get("artifact_format") == "phaser-vite/v1" else "iframe-html"
        version = GameVersion(
            game_id=game.id,
            version="v1",
            manifest_key=f"{prefix}/manifest.json",
            bundle_key=f"{prefix}/index.html",
            entry="index.html",
            runtime=runtime,
            sha256=index_sha,
            size_bytes=size_bytes,
            source_task_id=state.get("task_id"),
        )
        db.add(version)
        db.flush()
        manifest = {
            "schema_version": "game-manifest/v1",
            "game_id": game.id,
            "version_id": version.id,
            "title": title,
            "runtime": runtime,
            "entry": "index.html",
            "files": uploaded,
            "permissions": {"network": False, "storage": False, "cookies": False},
            "artifact_format": state.get("artifact_format") or "legacy-bundle/v1",
            "build": state.get("build_result") or {},
            "remix": {
                "source_game_id": source.id,
                "source_version": source_version,
                "changed_files": (state.get("revision_result") or {}).get("changed_files") or [],
            },
        }
        s3.put_object(
            f"{prefix}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
            "application/json",
        )
        db.commit()
        return game.id, version.id, game_manifest_url(game.id, "v1")
    finally:
        db.close()
