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
MAX_BUNDLE_FILES = 12
# 引擎文件由发布/沙箱环节注入（不属于生成 bundle），但 index.html 可以引用。
ENGINE_FILES = {"three.min.js", "phaser.min.js"}
_BUNDLE_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(?:js|css|html)$")
_SCRIPT_SRC_RE = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)


def script_srcs(html: str) -> list[str]:
    """index.html 里 <script src> 的相对引用，按出现顺序（即浏览器加载顺序）。"""
    out: list[str] = []
    for src in _SCRIPT_SRC_RE.findall(html or ""):
        src = src.strip().split("?")[0].split("#")[0]
        if src.startswith("./"):
            src = src[2:]
        out.append(src)
    return out


_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {value: key for key, value in _OPEN_TO_CLOSE.items()}
_REGEX_PREFIX_KEYWORDS = {
    "await",
    "case",
    "delete",
    "do",
    "else",
    "in",
    "instanceof",
    "new",
    "of",
    "return",
    "throw",
    "typeof",
    "void",
    "yield",
}


def _skip_regex_literal(source: str, start: int) -> int | None:
    i = start + 1
    escaped = False
    in_class = False
    while i < len(source):
        ch = source[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "[":
            in_class = True
        elif ch == "]" and in_class:
            in_class = False
        elif ch == "/" and not in_class:
            i += 1
            while i < len(source) and (source[i].isalpha() or source[i].isdigit()):
                i += 1
            return i
        elif ch in "\r\n":
            return None
        i += 1
    return None


def _js_completeness_error(source: str) -> str | None:
    stack: list[tuple[str, int]] = []
    state = "code"
    opener = ""
    opener_line = 1
    escaped = False
    can_start_regex = True
    line = 1
    i = 0

    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""

        if ch == "\n":
            line += 1

        if state == "line_comment":
            if ch == "\n":
                state = "code"
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
            else:
                i += 1
            continue

        if state in {"string", "template"}:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif state == "string" and ch == opener:
                state = "code"
                can_start_regex = False
            elif state == "template" and ch == "`":
                state = "code"
                can_start_regex = False
            elif state == "string" and ch in "\r\n":
                return f"unterminated string literal at line {opener_line}"
            i += 1
            continue

        if ch == "/" and nxt == "/":
            state = "line_comment"
            i += 2
            continue
        if ch == "/" and nxt == "*":
            state = "block_comment"
            opener_line = line
            i += 2
            continue
        if ch == "/" and can_start_regex:
            end = _skip_regex_literal(source, i)
            if end is None:
                return f"unterminated regular expression literal at line {line}"
            i = end
            can_start_regex = False
            continue
        if ch in {"'", '"'}:
            state = "string"
            opener = ch
            opener_line = line
            escaped = False
            i += 1
            continue
        if ch == "`":
            state = "template"
            opener_line = line
            escaped = False
            i += 1
            continue

        if ch in _OPEN_TO_CLOSE:
            stack.append((ch, line))
            can_start_regex = True
        elif ch in _CLOSE_TO_OPEN:
            if not stack or stack[-1][0] != _CLOSE_TO_OPEN[ch]:
                return f"mismatched closing {ch!r} at line {line}"
            stack.pop()
            can_start_regex = False
        elif ch.isalpha() or ch == "_" or ch == "$":
            start = i
            while i + 1 < len(source) and (source[i + 1].isalnum() or source[i + 1] in {"_", "$"}):
                i += 1
            word = source[start : i + 1]
            can_start_regex = word in _REGEX_PREFIX_KEYWORDS
        elif ch.isdigit():
            can_start_regex = False
        elif ch in "=:+-*!?&|^~<>%,;":
            can_start_regex = True
        elif ch == ".":
            can_start_regex = False
        i += 1

    if state == "block_comment":
        return f"unterminated block comment at line {opener_line}"
    if state == "string":
        return f"unterminated string literal at line {opener_line}"
    if state == "template":
        return f"unterminated template literal at line {opener_line}"
    if stack:
        ch, opened_at = stack[-1]
        return f"unclosed {ch!r} opened at line {opened_at}"
    return None


def validate_files(files: list[dict]) -> dict:
    paths = {f["path"] for f in files}
    errors: list[str] = []

    missing = REQUIRED_FILES - paths
    if missing:
        errors.append(f"missing required files: {sorted(missing)}")
    if len(files) != len(paths):
        errors.append("duplicate file paths in bundle")
    if len(paths) > MAX_BUNDLE_FILES:
        errors.append(f"bundle has {len(paths)} files; max {MAX_BUNDLE_FILES}")

    for f in files:
        path = str(f["path"])
        content = f.get("content", "")
        if not _BUNDLE_PATH_RE.match(path):
            errors.append(f"invalid file path {path!r}: flat filename ending in .js/.css/.html required")
        elif path.endswith(".html") and path != "index.html":
            errors.append(f"unexpected extra html file {path!r}; index.html is the only page")
        for pattern, label in FORBIDDEN_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                errors.append(f"forbidden API in {f['path']}: {label}")
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            errors.append(f"{f['path']} exceeds {MAX_FILE_BYTES // 1000}KB")
        if path.endswith(".js"):
            incomplete = _js_completeness_error(content)
            if incomplete:
                errors.append(f"{f['path']} appears incomplete: {incomplete}")

    idx = next((f for f in files if f["path"] == "index.html"), None)
    if idx and "game.js" not in idx["content"]:
        errors.append("index.html does not reference game.js")
    if idx:
        srcs = script_srcs(idx["content"])
        for src in srcs:
            if src not in paths and src not in ENGINE_FILES:
                errors.append(f"index.html references missing script {src!r}")
        referenced = set(srcs)
        for f in files:
            path = str(f["path"])
            if path.endswith(".js") and path not in referenced:
                errors.append(f"{path} is not referenced by a <script src> in index.html")

    infos = [
        {
            "path": f["path"],
            "sha256": hashlib.sha256(f["content"].encode("utf-8")).hexdigest(),
            "size": len(f["content"].encode("utf-8")),
        }
        for f in files
    ]
    return {"valid": not errors, "errors": errors, "warnings": [], "files": infos}
