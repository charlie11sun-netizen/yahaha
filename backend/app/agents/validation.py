"""BuildValidate —— 生成产物的确定性校验（docs/multi-agent_design.md §6.6）。

文件白名单 + forbidden API 扫描 + 引用检查 + 体积 + sha256。
也作为 repair loop 的 Observation 来源。
"""
import hashlib
import re

from app.services.artifacts import (
    ArtifactError,
    artifact_bytes,
    artifact_size,
    artifact_text,
    normalize_artifact_path,
)
from app.services.vite_projects import (
    MAX_PROJECT_BYTES,
    MAX_PROJECT_FILE_BYTES,
    VITE_PROJECT_FORMAT,
)

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
MAX_RUNTIME_FILE_BYTES = MAX_PROJECT_FILE_BYTES
MAX_RUNTIME_BYTES = MAX_PROJECT_BYTES
MAX_LEGACY_FILES = 12
MAX_BUNDLE_FILES = 120
# 引擎文件由发布/沙箱环节注入（不属于生成 bundle），但 index.html 可以引用。
ENGINE_FILES = {"three.min.js", "phaser.min.js"}
_BUNDLE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
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


def _source_position(source: str, offset: int) -> tuple[int, int]:
    """Return a stable one-based line/column for an offset in generated source."""

    prefix = source[: max(0, offset)]
    line = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    column = len(prefix) + 1 if last_newline < 0 else len(prefix) - last_newline
    return line, column


def _source_diagnostic(
    *,
    code: str,
    path: str,
    message: str,
    rule: str,
    line: int | None = None,
    column: int | None = None,
) -> dict:
    return {
        "code": code,
        "path": path,
        "line": line,
        "column": column,
        "rule": rule,
        "message": message,
    }


def validate_source_edit(
    path: str,
    content: str,
    *,
    max_bytes: int = MAX_FILE_BYTES,
) -> list[dict]:
    """Fast, file-local guard used before an agent edit is committed.

    This deliberately does not typecheck imports or require a complete bundle. Those
    checks remain in ``run_checks`` and the outer build node. The guard only rejects
    defects attributable to the proposed file itself, so a repair agent can still
    fix one failing file at a time.
    """

    raw_path = str(path or "")
    try:
        normalized = normalize_artifact_path(raw_path)
    except ArtifactError as exc:
        return [
            _source_diagnostic(
                code="invalid_path",
                path=raw_path,
                rule="artifact_path",
                message=str(exc),
            )
        ]
    if any(not _BUNDLE_SEGMENT_RE.match(part) for part in normalized.split("/")):
        return [
            _source_diagnostic(
                code="invalid_path",
                path=normalized,
                rule="artifact_path",
                message=f"invalid file path {normalized!r}",
            )
        ]

    source = str(content or "")
    diagnostics: list[dict] = []
    size = len(source.encode("utf-8"))
    if size > max_bytes:
        diagnostics.append(
            _source_diagnostic(
                code="file_too_large",
                path=normalized,
                rule="max_file_bytes",
                message=f"{normalized} would be {size}B, over the {max_bytes // 1000}KB limit",
            )
        )

    if normalized.endswith((".html", ".js", ".mjs", ".ts", ".tsx")):
        for pattern, label in FORBIDDEN_PATTERNS:
            for match in re.finditer(pattern, source, re.IGNORECASE):
                line, column = _source_position(source, match.start())
                diagnostics.append(
                    _source_diagnostic(
                        code="forbidden_api",
                        path=normalized,
                        line=line,
                        column=column,
                        rule=label,
                        message=f"forbidden API in {normalized}: {label}",
                    )
                )

    if normalized.endswith((".js", ".mjs", ".ts", ".tsx")):
        incomplete = _js_completeness_error(source)
        if incomplete:
            line_match = re.search(r"line (\d+)", incomplete)
            diagnostics.append(
                _source_diagnostic(
                    code="incomplete_source",
                    path=normalized,
                    line=int(line_match.group(1)) if line_match else None,
                    rule="delimiter_balance",
                    message=f"{normalized} appears incomplete: {incomplete}",
                )
            )
    return diagnostics


def validate_files(files: list[dict], bundle_type: str = "legacy-bundle/v1") -> dict:
    normalized_files: list[tuple[str, dict]] = []
    errors: list[str] = []
    for item in files:
        try:
            path = normalize_artifact_path(str(item.get("path") or ""))
        except ArtifactError as exc:
            errors.append(str(exc))
            continue
        if any(not _BUNDLE_SEGMENT_RE.match(part) for part in path.split("/")):
            errors.append(f"invalid file path {path!r}")
            continue
        normalized_files.append((path, item))

    paths = {path for path, _ in normalized_files}
    required = {"index.html"} if bundle_type == VITE_PROJECT_FORMAT else REQUIRED_FILES

    missing = required - paths
    if missing:
        errors.append(f"missing required files: {sorted(missing)}")
    if len(normalized_files) != len(paths):
        errors.append("duplicate file paths in bundle")
    max_files = MAX_BUNDLE_FILES if bundle_type == VITE_PROJECT_FORMAT else MAX_LEGACY_FILES
    if len(paths) > max_files:
        errors.append(f"bundle has {len(paths)} files; max {max_files}")

    total_bytes = 0
    for path, f in normalized_files:
        content = artifact_text(f)
        size = artifact_size(f)
        total_bytes += size
        if bundle_type != VITE_PROJECT_FORMAT and path.endswith(".html") and path != "index.html":
            errors.append(f"unexpected extra html file {path!r}; index.html is the only page")
        scan_security = content is not None and (
            bundle_type != VITE_PROJECT_FORMAT or path == "index.html"
        )
        if scan_security:
            patterns = FORBIDDEN_PATTERNS if bundle_type != VITE_PROJECT_FORMAT else FORBIDDEN_PATTERNS[-2:]
            for pattern, label in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    errors.append(f"forbidden API in {path}: {label}")
        limit = MAX_RUNTIME_FILE_BYTES if bundle_type == VITE_PROJECT_FORMAT else MAX_FILE_BYTES
        if size > limit:
            errors.append(f"{path} exceeds {limit // 1000}KB")
        if bundle_type != VITE_PROJECT_FORMAT and path.endswith(".js") and content is not None:
            incomplete = _js_completeness_error(content)
            if incomplete:
                errors.append(f"{path} appears incomplete: {incomplete}")
    if total_bytes > MAX_RUNTIME_BYTES:
        errors.append(f"bundle exceeds {MAX_RUNTIME_BYTES} bytes")

    idx = next((f for path, f in normalized_files if path == "index.html"), None)
    idx_text = artifact_text(idx) if idx else None
    if bundle_type != VITE_PROJECT_FORMAT and idx_text is not None and "game.js" not in idx_text:
        errors.append("index.html does not reference game.js")
    if idx_text is not None:
        srcs = script_srcs(idx_text)
        for src in srcs:
            try:
                normalized_src = normalize_artifact_path(src)
            except ArtifactError:
                normalized_src = src
            if normalized_src not in paths and normalized_src not in ENGINE_FILES:
                errors.append(f"index.html references missing script {src!r}")
        if bundle_type != VITE_PROJECT_FORMAT:
            referenced = set(srcs)
            for path, _ in normalized_files:
                if path.endswith(".js") and path not in referenced:
                    errors.append(f"{path} is not referenced by a <script src> in index.html")

    infos = []
    for path, file in normalized_files:
        raw = artifact_bytes(file)
        infos.append(
            {
                "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )
    return {"valid": not errors, "errors": errors, "warnings": [], "files": infos}
