"""Safe Phaser/Vite source scaffolding and pre-build validation."""
from __future__ import annotations

import json
import re

from app.services.artifacts import (
    ArtifactError,
    artifact_size,
    artifact_text,
    normalize_artifact_path,
    text_artifact,
)

VITE_PROJECT_FORMAT = "phaser-vite/v1"
ALLOWED_DEPENDENCIES = {"phaser": "3.90.0"}
ALLOWED_DEV_DEPENDENCIES = {"typescript": "5.8.3", "vite": "6.4.3"}
MAX_PROJECT_FILES = 120
MAX_PROJECT_FILE_BYTES = 16_000_000
MAX_PROJECT_BYTES = 64_000_000

_SCRIPT_TAG_RE = re.compile(r"<script\b(?P<attrs>[^>]*)></script>", re.IGNORECASE)
_MODULE_TYPE_RE = re.compile(r"\s+type\s*=\s*([\"'])module\1", re.IGNORECASE)
_CROSSORIGIN_RE = re.compile(
    r"\s+crossorigin(?:\s*=\s*(?:[\"'][^\"']*[\"']|[^\s>]+))?",
    re.IGNORECASE,
)
_STATIC_MODULE_RE = re.compile(r"(?:^|[;\n])\s*(?:import\s|export(?:\s|\{))")
_DOM_KEYBOARD_CODE_RE = re.compile(
    r"(?:Keyboard:)?(?:Key[A-Z0-9]|Digit[0-9]|Arrow(?:Up|Down|Left|Right)|Space|Escape|Tab|Enter)\b",
    re.IGNORECASE,
)
_BINDING_SUFFIX_ASSIGN_RE = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<expr>[^;\n]*?\.slice\(\s*9\s*\)[^;\n]*)",
    re.IGNORECASE,
)


def phaser_input_binding_errors(files: list[dict] | None) -> list[str]:
    """Reject DOM ``KeyboardEvent.code`` names passed raw to Phaser ``addKey``.

    Rebindable controls commonly persist values such as ``KeyW`` and
    ``ArrowUp``. Phaser 3.90's string API instead indexes ``KeyCodes`` with
    names such as ``W``, ``UP``, ``SPACE`` and ``ESC``. Passing the DOM value
    through unchanged silently creates an undefined key, so the bundle builds
    and animates while every keyboard control remains inert.
    """

    errors: list[str] = []
    for item in files or []:
        path = str(item.get("path") or "").replace("\\", "/")
        if not path.endswith((".js", ".mjs", ".ts", ".tsx")):
            continue
        source = artifact_text(item) or ""
        if not re.search(r"\.\s*addKey\s*\(", source, re.IGNORECASE):
            continue
        if not (_DOM_KEYBOARD_CODE_RE.search(source) or re.search(r"\bevent\s*\.\s*code\b", source, re.IGNORECASE)):
            continue

        unsafe = bool(
            re.search(
                r"\.\s*addKey\s*\(\s*(?:[^,;\n]*?\.slice\(\s*9\s*\)|event\s*\.\s*code)",
                source,
                re.IGNORECASE,
            )
        )
        if not unsafe:
            for match in _BINDING_SUFFIX_ASSIGN_RE.finditer(source):
                expression = match.group("expr")
                # A visibly named conversion or inline replacement is enough
                # to show the DOM code is not being passed through unchanged.
                if re.search(r"(?:normaliz|toPhaser|keyCodes|\.replace\s*\()", expression, re.IGNORECASE):
                    continue
                name = re.escape(match.group("name"))
                if re.search(rf"\.\s*addKey\s*\(\s*{name}\b", source, re.IGNORECASE):
                    unsafe = True
                    break
        if unsafe:
            errors.append(
                "Phaser input adapter passes DOM KeyboardEvent.code values (KeyW/ArrowUp) directly to "
                f"keyboard.addKey() in {path}; "
                "normalize them to Phaser names such as W/UP/SPACE/ESC or numeric KeyCodes before registration"
            )
    return errors


def is_vite_project(files: list[dict] | None) -> bool:
    paths = {str(item.get("path") or "") for item in (files or [])}
    has_entry = "game.js" in paths or "src/main.ts" in paths or "src/main.js" in paths
    return "package.json" in paths and "index.html" in paths and has_entry


def prepare_vite_runtime_files(files: list[dict]) -> list[dict]:
    """Convert Vite's module entry into a classic script for opaque sandbox origins."""

    prepared = [dict(item) for item in files]
    index_item = next((item for item in prepared if item.get("path") == "index.html"), None)
    if index_item is None:
        raise ArtifactError("built Vite dist is missing index.html")

    for item in prepared:
        path = str(item.get("path") or "")
        if not path.endswith((".js", ".mjs")):
            continue
        source = artifact_text(item) or ""
        if "import.meta" in source or _STATIC_MODULE_RE.search(source):
            raise ArtifactError(
                f"built Vite script {path} still contains module syntax and cannot run in the opaque iframe sandbox"
            )

    html = artifact_text(index_item)
    if html is None:
        raise ArtifactError("built Vite index.html must be UTF-8 text")

    def classic_script(match: re.Match) -> str:
        attrs = match.group("attrs")
        if not _MODULE_TYPE_RE.search(attrs):
            return match.group(0)
        attrs = _MODULE_TYPE_RE.sub("", attrs)
        attrs = _CROSSORIGIN_RE.sub("", attrs)
        attrs = " ".join(attrs.split())
        if not re.search(r"(?:^|\s)defer(?:\s|$)", attrs, re.IGNORECASE):
            attrs = f"defer {attrs}".strip()
        return f"<script {attrs}></script>"

    runtime_html = _SCRIPT_TAG_RE.sub(classic_script, html)
    runtime_html = _CROSSORIGIN_RE.sub("", runtime_html)
    if runtime_html == html and "type=\"module\"" in html.lower():
        raise ArtifactError("could not convert the Vite module entry for sandbox playback")

    replacement = text_artifact("index.html", runtime_html, index_item.get("content_type"))
    return [replacement if item is index_item else item for item in prepared]


def _module_index(index: str, title: str) -> str:
    index = re.sub(
        r"<script[^>]+src=[\"'](?:\./)?phaser\.min\.js[\"'][^>]*>\s*</script>",
        "",
        index or "",
        flags=re.IGNORECASE,
    )
    index = re.sub(
        r"<script[^>]+src=[\"'](?:\./)?game\.js[\"'][^>]*>\s*</script>",
        '<script type="module" src="./game.js"></script>',
        index,
        flags=re.IGNORECASE,
    )
    if "game.js" not in index:
        index = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{title}</title>"
            '<link rel="stylesheet" href="./style.css"></head><body>'
            '<div id="game"></div><script type="module" src="./game.js"></script></body></html>'
        )
    elif "type=\"module\"" not in index and "type='module'" not in index:
        index = index.replace("<script src=\"game.js\"", '<script type="module" src="./game.js"')
    return index


def create_phaser_vite_project(
    bundle_files: list[dict],
    generated_assets: list[dict] | None = None,
    *,
    title: str = "GameWeave Game",
) -> list[dict]:
    by_path = {str(item.get("path") or ""): str(item.get("content") or "") for item in bundle_files}
    game_js = by_path.get("game.js", "")
    if not re.search(r"^\s*import\s+Phaser\s+from\s+[\"']phaser[\"']", game_js, re.MULTILINE):
        game_js = 'import Phaser from "phaser";\n' + game_js
    package = {
        "name": "gameweave-generated-game",
        "private": True,
        "version": "0.0.0",
        "type": "module",
        "scripts": {"build": "vite build"},
        "dependencies": dict(ALLOWED_DEPENDENCIES),
        "devDependencies": dict(ALLOWED_DEV_DEPENDENCIES),
    }
    project = [
        text_artifact("package.json", json.dumps(package, indent=2)),
        text_artifact("index.html", _module_index(by_path.get("index.html", ""), title)),
        text_artifact("style.css", by_path.get("style.css", "")),
        text_artifact("game.js", game_js),
    ]
    project.extend(dict(item) for item in (generated_assets or []))
    return project


def validate_vite_project(files: list[dict]) -> list[str]:
    from app.agents.validation import FORBIDDEN_PATTERNS

    errors: list[str] = []
    if len(files) > MAX_PROJECT_FILES:
        errors.append(f"vite project has {len(files)} files; max {MAX_PROJECT_FILES}")
    total = 0
    seen: set[str] = set()
    for item in files:
        try:
            path = normalize_artifact_path(str(item.get("path") or ""))
            size = artifact_size(item)
        except ArtifactError as exc:
            errors.append(str(exc))
            continue
        total += size
        if size > MAX_PROJECT_FILE_BYTES:
            errors.append(f"{path} exceeds {MAX_PROJECT_FILE_BYTES} bytes")
        if path in seen:
            errors.append(f"duplicate project path: {path}")
        seen.add(path)
        if path.startswith("node_modules/") or path.startswith("dist/"):
            errors.append(f"generated project may not include {path}")
        if path in {"vite.config.js", "vite.config.mjs", "vite.config.ts"}:
            errors.append("custom Vite config is not allowed; the sandbox uses a fixed config")
        text = artifact_text(item)
        if text is not None and path.endswith((".html", ".js", ".mjs", ".ts", ".tsx")):
            patterns = FORBIDDEN_PATTERNS
            if path == "src/systems/GameWeaveBridge.ts":
                # This immutable scaffold is the sole capability boundary for
                # host persistence. It must compare MessageEvent.source with
                # window.parent before accepting an ACK; generated modules are
                # still forbidden from reading parent/top themselves.
                patterns = [
                    (pattern, label)
                    for pattern, label in patterns
                    if label != "parent/top access"
                ]
            for pattern, label in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    errors.append(f"forbidden API in Vite source {path}: {label}")
    if total > MAX_PROJECT_BYTES:
        errors.append(f"vite project exceeds {MAX_PROJECT_BYTES} bytes")
    for required in ("package.json", "index.html"):
        if required not in seen:
            errors.append(f"vite project is missing {required}")
    if not ({"game.js", "src/main.ts", "src/main.js"} & seen):
        errors.append("vite project is missing an entry module (game.js or src/main.ts)")

    package_item = next((item for item in files if item.get("path") == "package.json"), None)
    if package_item:
        try:
            package = json.loads(artifact_text(package_item) or "{}")
        except json.JSONDecodeError:
            errors.append("package.json is invalid JSON")
        else:
            dependencies = package.get("dependencies") or {}
            dev_dependencies = package.get("devDependencies") or {}
            allowed = {**ALLOWED_DEPENDENCIES, **ALLOWED_DEV_DEPENDENCIES}
            declared = {**dependencies, **dev_dependencies}
            unexpected = sorted(set(declared) - set(allowed))
            if unexpected:
                errors.append(f"unsupported Vite dependencies: {unexpected}")
            for name, version in allowed.items():
                if name in declared and declared[name] != version:
                    errors.append(f"unsupported version for {name}: {declared[name]!r}; expected {version!r}")
    errors.extend(phaser_input_binding_errors(files))
    return errors
