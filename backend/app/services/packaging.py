"""把游戏 bundle 打包并上传到对象存储，返回远端产物元信息。

pipeline（Create 流程）与 seed（示例数据）共用，保证产物结构一致：
games/{id}/{version}/index.html + manifest.json
"""
import hashlib
import json

from app.models.common import now_utc
from app.storage import s3


def write_bundle(game_id: str, version: str, html: str, title: str, author_name: str) -> dict:
    prefix = s3.game_prefix(game_id, version)
    bundle_key = f"{prefix}/index.html"
    manifest_key = f"{prefix}/manifest.json"

    body = html.encode("utf-8")
    sha = hashlib.sha256(body).hexdigest()

    s3.put_object(bundle_key, html, "text/html; charset=utf-8")

    manifest = {
        "schemaVersion": 1,
        "id": game_id,
        "title": title,
        "version": version,
        "entry": "index.html",
        "runtime": "iframe-sandbox",
        "sandbox": "allow-scripts allow-pointer-lock",
        "assets": ["index.html"],
        "sha256": sha,
        "createdBy": author_name,
        "createdAt": now_utc().isoformat(),
    }
    s3.put_object(manifest_key, json.dumps(manifest, ensure_ascii=False, indent=2), "application/json")

    return {
        "manifest_key": manifest_key,
        "bundle_key": bundle_key,
        "sha256": sha,
        "size": len(body),
    }
