"""BuildValidate —— 生成产物的确定性校验（docs/multi-agent_design.md §6.6）。

文件白名单 + forbidden API 扫描 + 引用检查 + 体积 + sha256。
也作为 repair loop 的 Observation 来源。
"""
import hashlib
import re

# (正则, 展示名)
FORBIDDEN_PATTERNS = [
    (r"eval\s*\(", "eval()"),
    (r"new\s+Function", "new Function"),
    (r"document\.cookie", "document.cookie"),
    (r"window\.(parent|top)(?!\s*\.\s*postMessage)", "parent/top access"),
    (r"\blocalStorage\b", "localStorage"),
    (r"\bsessionStorage\b", "sessionStorage"),
    (r"fetch\s*\(", "fetch()"),
    (r"XMLHttpRequest", "XMLHttpRequest"),
    (r"\bWebSocket\b", "WebSocket"),
    (r"\bimport\s*\(", "dynamic import()"),
    (r"\bnavigator\.sendBeacon\b", "sendBeacon"),
    (r"\bEventSource\b", "EventSource"),
    (r"<script[^>]+src=[\"']https?://", "external script"),
    (r"https?://(?!www\.w3\.org)", "external URL"),
]

REQUIRED_FILES = {"index.html", "style.css", "game.js"}
MAX_FILE_BYTES = 400_000


def validate_files(files: list[dict]) -> dict:
    paths = {f["path"] for f in files}
    errors: list[str] = []

    missing = REQUIRED_FILES - paths
    if missing:
        errors.append(f"missing required files: {sorted(missing)}")

    for f in files:
        content = f.get("content", "")
        for pattern, label in FORBIDDEN_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                errors.append(f"forbidden API in {f['path']}: {label}")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            errors.append(f"{f['path']} exceeds {MAX_FILE_BYTES // 1000}KB")

    idx = next((f for f in files if f["path"] == "index.html"), None)
    if idx and "game.js" not in idx["content"]:
        errors.append("index.html does not reference game.js")

    infos = [
        {
            "path": f["path"],
            "sha256": hashlib.sha256(f["content"].encode("utf-8")).hexdigest(),
            "size": len(f["content"].encode("utf-8")),
        }
        for f in files
    ]
    return {"valid": not errors, "errors": errors, "warnings": [], "files": infos}
