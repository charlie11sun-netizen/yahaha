"""Build validation and gameplay QA nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
import json

from app.agents.nodes_common import *
from app.agents.design_contract import (
    enforce_execution_boundary,
    execution_design_from_state,
    execution_spec_from_state,
)
from app.services.vite_projects import phaser_input_binding_errors


# 脚手架自带的品质库文件：判定"游戏是否用了反馈特效/边界处理/素材"时要剔除,
# 否则库本身的实现代码会让检查永真。gameConfig.ts 同理——它的 JSON 里天然含
# "sheet"/"background" 字段名,不剔除的话素材未用检测永真。
_STOCK_KIT_FILES = {
    "src/systems/Juice.ts",
    "src/systems/Sfx.ts",
    "src/systems/Bounds.ts",
    "src/systems/Backdrop.ts",
    "src/systems/InputRouter.ts",
    "src/systems/LevelLayout.ts",
    "src/systems/Probe.ts",
    "src/systems/GameWeaveBridge.ts",
}
_NON_GAMEPLAY_FILES = _STOCK_KIT_FILES | {
    "src/config/gameConfig.ts",
    # The frozen team contract repeats every requested capability verbatim.  It
    # is evidence of planning, not implementation; including it makes token
    # checks such as obstacle/save/settings appear wired when no runtime module
    # imports them.
    "src/contracts/AuthorContract.ts",
}

# Definitions and boot-time preload calls do not make settings, bindings, or
# persistence reachable from gameplay.  Capability checks use the remaining
# consumers so a discarded ``new SettingsService().load()`` cannot satisfy QA.
_CAPABILITY_DECLARATION_FILES = _NON_GAMEPLAY_FILES | {
    "src/adapters/SceneInputAdapter.ts",
    "src/input/InputBindingService.ts",
    "src/presentation/SettingsService.ts",
    "src/scenes/BootScene.ts",
    "src/ui/MenuControllers.ts",
}

# Scene keys that do not count as "gameplay reached" when reconciling runtime
# probes (boot/menu/result shells around the actual play scene).
_MENU_SCENE_KEYS = {
    "boot", "bootscene", "preload", "preloadscene", "loading", "loadingscene",
    "title", "titlescene", "menu", "menuscene", "mainmenu", "mainmenuscene",
    "gameover", "gameoverscene", "result", "resultscene", "victory",
    "victoryscene", "pause", "pausescene", "settings", "settingsscene",
    "credits", "creditsscene",
}

_RUNTIME_EXPORT_RE = re.compile(
    r"\bexport\s+(?:abstract\s+)?(?:class|function|const|enum|let|var)\s+([A-Za-z_$][\w$]*)"
)


def _usage_positions(source: str) -> str:
    """Strip comments/strings/imports/re-exports/bare `void X` references so an
    identifier match indicates real consumption (mirrors author_team's evidence
    counting — `import X` plus `void X;` must not read as usage)."""
    stripped = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    stripped = re.sub(r"//[^\r\n]*", " ", stripped)
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', " ", stripped)
    stripped = re.sub(r"'(?:\\.|[^'\\])*'", " ", stripped)
    stripped = re.sub(r"`(?:\\.|[^`\\])*`", " ", stripped, flags=re.DOTALL)
    stripped = re.sub(r"\bimport\b[^;]*?;", " ", stripped)
    stripped = re.sub(
        r"\bexport\s+(?:\{[^}]*\}|\*(?:\s+as\s+[A-Za-z_$][\w$]*)?)\s*(?:from[^;]*)?;",
        " ",
        stripped,
    )
    return re.sub(r"\bvoid\s+[A-Za-z_$][\w$]*\s*(?=[;,)\]\r\n])", " ", stripped)


def _dead_runtime_exports(source_files: list[dict]) -> list[tuple[str, str]]:
    """Runtime-valued exports (class/const/function/enum) never referenced in a
    usage position outside their defining file — systems and content the player
    never experiences. e7ee0742 shipped 65/138 exports dead, including its
    entire domain combat system, while every gate stayed green."""
    modules: list[tuple[str, str, str]] = []
    for item in source_files:
        path = str(item.get("path") or "").replace("\\", "/")
        if not path.startswith("src/") or not path.endswith((".ts", ".tsx")):
            continue
        if item.get("content_b64") is not None:
            continue
        content = str(item.get("content") or "")
        modules.append((path, content, _usage_positions(content)))
    dead: list[tuple[str, str]] = []
    for path, content, _ in modules:
        if path in _NON_GAMEPLAY_FILES or path.startswith("src/contracts/"):
            continue
        for symbol in _RUNTIME_EXPORT_RE.findall(content):
            used = any(
                other_path != path
                and re.search(rf"\b{re.escape(symbol)}\b", other_usage) is not None
                for other_path, _, other_usage in modules
            )
            if not used:
                dead.append((symbol, path))
    return dead


_IMPORT_SPEC_RE = re.compile(r"""(?:import|export)\s(?:[^;'"]*?from\s*)?["']([^"']+)["']""")


def _resolve_relative_import(base_path: str, spec: str, paths: set[str]) -> str | None:
    if not spec.startswith("."):
        return None
    base_dir = base_path.rsplit("/", 1)[0] if "/" in base_path else ""
    raw = f"{base_dir}/{spec}" if base_dir else spec
    parts: list[str] = []
    for token in raw.replace("\\", "/").split("/"):
        if token in ("", "."):
            continue
        if token == "..":
            if parts:
                parts.pop()
            continue
        parts.append(token)
    joined = "/".join(parts)
    for candidate in (joined, f"{joined}.ts", f"{joined}.tsx", f"{joined}.js", f"{joined}/index.ts"):
        if candidate in paths:
            return candidate
    return None


def _entry_reachable_paths(files_map: dict[str, str], entry: str = "src/main.ts") -> set[str]:
    reachable: set[str] = set()
    queue = [entry] if entry in files_map else []
    all_paths = set(files_map)
    while queue:
        current = queue.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for match in _IMPORT_SPEC_RE.finditer(files_map.get(current, "")):
            resolved = _resolve_relative_import(current, match.group(1), all_paths)
            if resolved and resolved not in reachable:
                queue.append(resolved)
    return reachable


def _orphan_author_modules(source_files: list[dict]) -> list[str]:
    """Author-added source modules unreachable from the entry import graph.

    Vite 树摇会把没被入口 import 的模块整体丢出产物:c28261d1(2026-07-17
    暗影档案)集成 agent 网络故障后,21 个已接受的作者文件 19 个不可达,
    发布产物里 GuardController/MissionDefinition 出现次数为 0——玩家拿到的
    是兜底玩法。这是纯静态检查,比"死导出"更硬:整文件不可达 = 必然丢弃。
    """
    from app.services.phaser_projects import scaffold_source_paths

    files_map = {
        str(item.get("path") or "").replace("\\", "/"): str(item.get("content") or "")
        for item in source_files
        if str(item.get("path") or "").endswith((".ts", ".tsx"))
        and item.get("content_b64") is None
    }
    if "src/main.ts" not in files_map:
        return []
    scaffold = scaffold_source_paths()
    reachable = _entry_reachable_paths(files_map)
    return sorted(
        path
        for path in files_map
        if path not in scaffold
        and not path.startswith("src/contracts/")
        and not path.endswith(".d.ts")
        and path not in reachable
    )


def _sandbox_files_for_qa(files: list[dict], dimension: str | None = None) -> list[dict]:
    payload = [dict(file) for file in files]
    has_three_reference = any(
        file.get("path") == "index.html" and "three.min.js" in str(file.get("content") or "").lower()
        for file in payload
    )
    has_three_file = any(file.get("path") == "three.min.js" for file in payload)
    if (dimension == "3d" or has_three_reference) and not has_three_file:
        from app.services import packaging

        engine = packaging.three_engine_bytes()
        if engine:
            payload.append({"path": "three.min.js", "content": engine.decode("utf-8")})
    has_phaser_reference = any(
        file.get("path") == "index.html" and "phaser.min.js" in str(file.get("content") or "").lower()
        for file in payload
    )
    has_phaser_file = any(file.get("path") == "phaser.min.js" for file in payload)
    if has_phaser_reference and not has_phaser_file:
        from app.services import packaging

        engine = packaging.phaser_engine_bytes()
        if engine:
            payload.append({"path": "phaser.min.js", "content": engine.decode("utf-8")})
    return payload


def _primary_play_source(source_files: list[dict]) -> str:
    """Return the fixed scaffold's reachable gameplay scene, not menu prose."""

    return "\n".join(
        str(item.get("content") or "")
        for item in source_files
        if str(item.get("path") or "").replace("\\", "/")
        == "src/scenes/PlayScene.ts"
        and item.get("content_b64") is None
    )


def _literal_gameplay_font_sizes(source: str) -> list[int]:
    """Collect literal Phaser text sizes that survive the embedded-canvas scale."""

    sizes: list[int] = []
    patterns = (
        r"\b(?:textStyle|setFontSize)\s*\(\s*(\d{1,3})\b",
        r"\bfontSize\s*:\s*[\"'](\d{1,3})px[\"']",
    )
    for pattern in patterns:
        sizes.extend(int(value) for value in re.findall(pattern, source, re.IGNORECASE))
    return sizes


def _js_braced_body(source: str, body_start: int) -> str | None:
    depth = 1
    i = body_start
    state = "code"
    quote = ""
    escaped = False
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if state == "line_comment":
            if ch == "\n":
                state = "code"
        elif state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 1
        elif state in {"string", "template"}:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif state == "string" and ch == quote:
                state = "code"
            elif state == "template" and ch == "`":
                state = "code"
        else:
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 1
            elif ch == "/" and nxt == "*":
                state = "block_comment"
                i += 1
            elif ch in {"'", '"'}:
                state = "string"
                quote = ch
                escaped = False
            elif ch == "`":
                state = "template"
                escaped = False
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[body_start:i]
        i += 1
    return None


def _js_method(source: str, name: str) -> tuple[list[str], str] | None:
    match = re.search(
        rf"\b{re.escape(name)}\s*\(([^)]*)\)\s*(?::\s*[^{{;=]+)?\s*{{",
        source,
    )
    if not match:
        return None
    params = [
        re.sub(r"[^\w$].*", "", part.strip())
        for part in match.group(1).split(",")
        if part.strip()
    ]
    body = _js_braced_body(source, match.end())
    if body is None:
        return None
    return params, body


def _phaser_player_overlap_issues(js: str) -> list[str]:
    """Catch delayed Phaser crashes caused by Arcade group-vs-player args.

    In Phaser 4 Arcade Physics, group-vs-sprite callbacks can invoke the
    callback with the player sprite first and the group child second. Model
    output often assumes arg0 is the enemy/projectile; short smoke tests may
    miss the crash until the first hostile touch, bullet, or rocket overlap.
    """
    issues: list[str] = []
    seen: set[str] = set()

    def add_issue(key: str, detail: str) -> None:
        if key not in seen:
            seen.add(key)
            issues.append(detail)

    def first_arg_misused(collection: str, params: list[str], body: str, key: str) -> None:
        if not params:
            return
        first = re.escape(params[0])
        if collection == "enemies" and re.search(rf"\bENEMY\s*\[\s*{first}\.getData\s*\(\s*['\"]type", body):
            add_issue(
                key,
                "Phaser overlap callback for this.enemies vs this.player treats the first argument as the enemy; Phaser may pass the player first.",
            )
        if collection in {"enemyBullets", "rockets"} and (
            re.search(rf"\bkillObj\s*\(\s*{first}\s*\)", body)
            or re.search(rf"\bexplode\s*\([^)]*{first}\.x[^)]*,[^)]*{first}\.y", body)
            or re.search(rf"{first}\.getData\s*\(\s*['\"]dmg", body)
        ):
            add_issue(
                key,
                f"Phaser overlap callback for this.{collection} vs this.player treats the first argument as the projectile; Phaser may pass the player first.",
            )

    method_re = re.compile(
        r"physics\.add\.overlap\(\s*this\.(enemyBullets|rockets|enemies)\s*,\s*this\.player\s*,\s*this\.(\w+)",
        re.S,
    )
    for match in method_re.finditer(js):
        method = _js_method(js, match.group(2))
        if method:
            first_arg_misused(match.group(1), method[0], method[1], match.group(0))

    arrow_re = re.compile(
        r"physics\.add\.overlap\(\s*this\.(enemyBullets|rockets|enemies)\s*,\s*this\.player\s*,\s*\(([^)]*)\)\s*=>\s*(.+?)\s*,\s*null\s*,\s*this",
        re.S,
    )
    for match in arrow_re.finditer(js):
        params = [
            re.sub(r"[^\w$].*", "", part.strip())
            for part in match.group(2).split(",")
            if part.strip()
        ]
        first_arg_misused(match.group(1), params, match.group(3), match.group(0))

    return issues


def _phaser_removed_api_issues(js: str) -> list[str]:
    low = js.lower()
    issues: list[str] = []
    if ".settintfill(" in low:
        issues.append(
            "Phaser 4 removed setTintFill(); use setTint(color).setTintMode(Phaser.TintModes.FILL)."
        )
    return issues


def _phaser_destroyed_body_issues(js: str) -> list[str]:
    issues: list[str] = []
    methods = re.finditer(r"\b(\w+)\s*\(([^)]*)\)\s*{", js)
    for match in methods:
        body = _js_braced_body(js, match.end())
        if body is None:
            continue
        params = [
            re.sub(r"[^\w$].*", "", part.strip())
            for part in match.group(2).split(",")
            if part.strip()
        ]
        for param in params:
            if not param:
                continue
            damage = re.search(rf"\bdamageEnemy\s*\(\s*{re.escape(param)}\b", body)
            velocity = re.search(rf"\b{re.escape(param)}\.body\.velocity\b", body)
            if not damage or not velocity or damage.start() > velocity.start():
                continue
            between = body[damage.end() : velocity.start()]
            guard = re.search(
                rf"!\s*{re.escape(param)}\.active|!\s*{re.escape(param)}\.body"
                rf"|{re.escape(param)}\.active\s*&&\s*{re.escape(param)}\.body"
                rf"|{re.escape(param)}\.body\s*&&\s*{re.escape(param)}\.active",
                between,
            )
            if not guard:
                issues.append(
                    f"Phaser code reads {param}.body.velocity after damageEnemy({param}, ...); damageEnemy may destroy the enemy before knockback."
                )
    return issues


def _js_update_top_level_code(body: str) -> str:
    """Keep an update body's top-level code and mask nested blocks/comments/strings."""

    out: list[str] = []
    depth = 0
    state = "code"
    quote = ""
    escaped = False
    i = 0
    while i < len(body):
        ch = body[i]
        nxt = body[i + 1] if i + 1 < len(body) else ""
        replacement = "\n" if ch == "\n" else " "
        if state == "line_comment":
            out.append(replacement)
            if ch == "\n":
                state = "code"
        elif state == "block_comment":
            out.append(replacement)
            if ch == "*" and nxt == "/":
                out.append(" ")
                state = "code"
                i += 1
        elif state in {"string", "template"}:
            out.append(replacement)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif state == "string" and ch == quote:
                state = "code"
            elif state == "template" and ch == "`":
                state = "code"
        elif ch == "/" and nxt == "/":
            out.extend((" ", " "))
            state = "line_comment"
            i += 1
        elif ch == "/" and nxt == "*":
            out.extend((" ", " "))
            state = "block_comment"
            i += 1
        elif ch in {"'", '"'}:
            out.append(" ")
            state = "string"
            quote = ch
            escaped = False
        elif ch == "`":
            out.append(" ")
            state = "template"
            escaped = False
        elif ch == "{":
            if depth == 0:
                out.append(";")
            else:
                out.append(" ")
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
            out.append(";" if depth == 0 else " ")
        else:
            out.append(ch if depth == 0 else replacement)
        i += 1
    return "".join(out)


def _topdown_uncontrolled_facing_issues(js: str) -> list[str]:
    """Hard-fail only high-confidence, unconditional per-frame avatar spinning."""

    actor = r"(?:(?:this)\s*\.\s*)?(?:playerSprite|player|hero|avatar)\b(?:\s*[!?])?"
    timing = re.compile(r"(?:^|[^\w])_?(?:time|delta|elapsed|frame|tick)\w*\b|\b(?:performance|date)\s*\.\s*now", re.I)
    stateful = re.compile(
        r"\b(?:input|key|cursor|pointer|stick|aim|axis|direction|velocity|movement|move|"
        r"state|mode|active|enabled|attack|dash|spin|turn|left|right)\w*\b",
        re.I,
    )

    def high_confidence(code: str, match: re.Match, rhs: str) -> bool:
        start = code.rfind(";", 0, match.start()) + 1
        end = code.find(";", match.end())
        segment = code[start : len(code) if end < 0 else end]
        prefix = code[start : match.start()]
        if re.search(r"\b(?:if|else|for|while|switch|case|catch)\b", prefix, re.I):
            return False
        if "=>" in prefix or "&&" in segment or "||" in segment or "?" in segment:
            return False
        if stateful.search(segment):
            return False
        compact = rhs.strip()
        numeric_expression = bool(re.search(r"\d", compact)) and not re.search(r"[A-Za-z_$]", compact)
        return bool(timing.search(compact) or numeric_expression)

    patterns = [
        re.compile(rf"{actor}\s*\.\s*(?:rotation|angle)\s*(?:\+=|-=)\s*(?P<rhs>[^;\n]+)", re.I),
        re.compile(
            rf"{actor}\s*\.\s*(?P<prop>rotation|angle)\s*=\s*{actor}\s*\.\s*(?P=prop)\s*[+-]\s*(?P<rhs>[^;\n]+)",
            re.I,
        ),
        re.compile(rf"{actor}\s*\.\s*(?:rotation|angle)\s*=\s*(?P<rhs>[^;\n]+)", re.I),
        re.compile(rf"{actor}\s*\.\s*set(?:Rotation|Angle)\s*\(\s*(?P<rhs>[^;\n]+)", re.I),
    ]
    update_re = re.compile(r"\bupdate\s*(?:\([^)]*\)[^{;=]*|=\s*\([^)]*\)\s*(?::[^=]+)?=>)\s*\{", re.I)
    for update_match in update_re.finditer(js):
        body = _js_braced_body(js, update_match.end())
        if body is None:
            continue
        code = _js_update_top_level_code(body)
        for pattern in patterns:
            for match in pattern.finditer(code):
                if high_confidence(code, match, match.group("rhs")):
                    return [
                        "top-down player rotation changes continuously every frame; derive facing from the latest "
                        "non-zero movement/aim vector and keep it stable while idle"
                    ]
    return []


def _topdown_generated_avatar_rotation_issues(js: str) -> list[str]:
    """Reject rotating pose-sheet humanoids as if they were ship sprites.

    Generated dungeon characters use upright pose frames.  Rotating the whole
    body toward movement/aim makes those frames roll and turn upside down; the
    weapon, reticle, telegraph, or projectile is the directional object instead.
    """

    direction = r"(?:direction|move(?:ment)?|velocity|aim|lastAim|facing)"
    angle_value = rf"(?:{direction}\s*\.\s*angle\s*\(|Phaser\s*\.\s*Math\s*\.\s*Angle\s*\.\s*Between\s*\()"
    explicit_player = r"(?:(?:this)\s*\.\s*)?(?:playerSprite|player|hero|avatar)\b"
    direct_patterns = (
        rf"{explicit_player}\s*\.\s*set(?:Rotation|Angle)\s*\([^;\n]*{angle_value}",
        rf"{explicit_player}\s*\.\s*(?:rotation|angle)\s*=\s*[^;\n]*{angle_value}",
    )
    if any(re.search(pattern, js, re.I) for pattern in direct_patterns):
        return [
            "generated top-down avatar body rotates toward movement/aim; keep the humanoid pose-sheet "
            "sprite at rotation 0, use pose frames/flipX for facing, and rotate only the weapon, reticle, "
            "telegraphs, or projectiles"
        ]

    # Also catch a Player class rotating bare `this`, and the common generic
    # faceDirection helper when the player is one of its callers.
    for class_match in re.finditer(r"\bclass\s+\w*(?:Player|Hero|Avatar)\w*[^\{]*\{", js, re.I):
        body = _js_braced_body(js, class_match.end()) or ""
        if re.search(rf"\bthis\s*\.\s*(?:set(?:Rotation|Angle)\s*\(|(?:rotation|angle)\s*=)[^;\n]*{angle_value}", body, re.I):
            return [
                "generated top-down avatar body rotates toward movement/aim; keep the humanoid pose-sheet "
                "sprite at rotation 0, use pose frames/flipX for facing, and rotate only the weapon, reticle, "
                "telegraphs, or projectiles"
            ]
    helper_rotates = re.search(
        rf"\bfaceDirection\s*\([^)]*\)\s*(?::[^\{{]+)?\{{[^\}}]*set(?:Rotation|Angle)\s*\([^;\n]*{angle_value}",
        js,
        re.I | re.S,
    )
    player_calls_helper = re.search(rf"{explicit_player}\s*\.\s*faceDirection\s*\(", js, re.I)
    if helper_rotates and player_calls_helper:
        return [
            "generated top-down avatar body rotates toward movement/aim; keep the humanoid pose-sheet "
            "sprite at rotation 0, use pose frames/flipX for facing, and rotate only the weapon, reticle, "
            "telegraphs, or projectiles"
        ]
    return []


def _gameplay_qa(state: dict) -> dict:
    """Model-first smoke QA: prove the artifact is a real, runnable game without
    second-guessing how the model wrote it. Hard-fail only on "this isn't a game";
    quality gaps become warnings that never degrade the bundle to a template."""
    spec = execution_spec_from_state(state)
    design = execution_design_from_state(state)
    archetype = spec.get("archetype") or design.get("archetype") or ("webgl_3d" if state.get("dimension") == "3d" else "canvas_arcade")
    validation_result = state.get("validation_result") or {}
    files = state.get("generated_files") or []
    source_files = state.get("project_files") or files
    js = next((f.get("content", "") for f in source_files if f.get("path") == "game.js"), "")
    if not js and state.get("artifact_format") == "phaser-vite/v1":
        js = "\n".join(
            str(f.get("content") or "")
            for f in source_files
            if str(f.get("path") or "").endswith((".ts", ".tsx", ".js", ".mjs"))
            and f.get("content_b64") is None
        )
    html = next((f.get("content", "") for f in source_files if f.get("path") == "index.html"), "")
    low = (js + "\n" + html).lower()

    issues: list[str] = []
    warnings: list[str] = []

    # Phaser 产物的循环/输入都由引擎驱动：game.js 里不会出现字面 rAF / addEventListener，
    # 按 Canvas 规则会被误杀。识别引擎特征后放行循环检查、补充 Phaser 输入惯用法。
    uses_vite = state.get("artifact_format") == "phaser-vite/v1"
    uses_phaser = uses_vite or any(tok in low for tok in ["phaser.min.js", "new phaser", "phaser.game", "phaser.scene"])

    if not validation_result.get("valid"):
        issues.append("static validation must pass before gameplay QA")
    if len(js) < 400:
        issues.append("game source is too small to be a real game")
    if "requestanimationframe" not in low and "setinterval" not in low and not uses_phaser:
        issues.append("no game loop (requestAnimationFrame/setInterval) found")
    has_input = any(tok in low for tok in [
        "addeventlistener", "onkeydown", "onkeyup", "onmousemove", "onpointer", "ontouch", "onclick",
        "createcursorkeys", "keyboard.addkey", "input.on", "pointerdown", "keydown-",
    ])
    if not has_input:
        issues.append("no input handling found")
    authored_code = state.get("code_source") in {"author", "revision"}
    issues.extend(phaser_input_binding_errors(source_files))
    if uses_phaser:
        issues.extend(_phaser_player_overlap_issues(js))
        # The modular Vite runtime is pinned to Phaser 3.90, where setTintFill
        # remains valid. The removed-API lint only applies to legacy Phaser 4 bundles.
        if not uses_vite:
            issues.extend(_phaser_removed_api_issues(js))
        issues.extend(_phaser_destroyed_body_issues(js))
        topdown_hint = " ".join(
            str(value or "").lower()
            for value in (archetype, spec.get("genre"), spec.get("theme"))
        )
        if authored_code and any(
            token in topdown_hint
            for token in (
                "topdown", "top-down", "top_down", "top down", "dungeon", "roguelike", "rogue-like",
                "roguelite", "rogue-lite", "俯视", "俯視", "地牢", "地下城", "肉鸽", "肉鴿",
            )
        ):
            issues.extend(_topdown_uncontrolled_facing_issues(js))
            generated_assets = (state.get("asset_manifest") or {}).get("assets") or []
            has_generated_sheet = any(
                isinstance(asset, dict)
                and str(asset.get("kind")) == "spritesheet"
                and asset.get("frames")
                for asset in generated_assets
            )
            humanoid_dungeon_hint = any(
                token in topdown_hint
                for token in (
                    "dungeon", "roguelike", "rogue-like", "roguelite", "rogue-lite",
                    "俯视", "俯視", "地牢", "地下城", "肉鸽", "肉鴿",
                )
            )
            if has_generated_sheet and humanoid_dungeon_hint:
                issues.extend(_topdown_generated_avatar_rotation_issues(js))
    has_restart = any(tok in low for tok in [
        "restart", "reset(", "replay", "again", "location.reload", '"rs"', "'rs'",
    ])
    if not has_restart:
        warnings.append("no obvious restart affordance detected")

    # 运行时冒烟：先用 V8 快速预检，再用真浏览器沙箱观察加载错误和动画帧。
    if uses_vite:
        smoke_ok, smoke_detail = True, "skipped: Vite module source is verified by the isolated build and browser"
    else:
        smoke_ok, smoke_detail = smoke.run_smoke(js)
    if not smoke_ok:
        issues.append(f"runtime smoke test: game crashed on load — {smoke_detail}")
    elif smoke_detail.startswith("skipped"):
        warnings.append(f"runtime smoke skipped: {_clip(smoke_detail, 160)}")

    browser_result = None
    sandbox_error_code = None
    visual_verdict = None
    if smoke_ok and validation_result.get("valid") and files:
        try:
            browser_result = sandbox_client.run_bundle(
                _sandbox_files_for_qa(files, state.get("dimension")),
                entry="index.html",
                timeout_ms=settings.SANDBOX_TIMEOUT_MS,
                simulate_input=True,
                screenshot_always=settings.VISUAL_REVIEW_ENABLED,
            )
            if (
                not browser_result.skipped
                and browser_result.timed_out
                and browser_result.frames_observed == 0
            ):
                # 一次重试：宿主负载抖动/冷启动的 Chromium 会错过加载窗口，而
                # "零帧超时"会被归类为 design 级失败触发整包重做——代价极不对称。
                retry_result = sandbox_client.run_bundle(
                    _sandbox_files_for_qa(files, state.get("dimension")),
                    entry="index.html",
                    timeout_ms=settings.SANDBOX_TIMEOUT_MS,
                    simulate_input=True,
                    screenshot_always=settings.VISUAL_REVIEW_ENABLED,
                )
                if not retry_result.skipped and (
                    not retry_result.timed_out or retry_result.frames_observed > 0
                ):
                    warnings.append(
                        "browser sandbox timed out once with zero frames; retry attempt succeeded"
                    )
                    browser_result = retry_result
        except sandbox_client.SandboxUnavailableError as exc:
            sandbox_error_code = TaskErrorCode.SANDBOX_UNAVAILABLE.value
            issues.append(f"browser sandbox unavailable — {_clip(exc, 180)}")
        else:
            if browser_result.skipped:
                warnings.append(browser_result.detail or "browser sandbox skipped")
            else:
                if browser_result.timed_out:
                    issues.append("browser sandbox timed out")
                if browser_result.page_errors:
                    issues.append(f"browser page error: {browser_result.page_errors[0]}")
                if browser_result.console_errors:
                    issues.append(f"browser console error: {browser_result.console_errors[0]}")
                if browser_result.requests_aborted:
                    issues.append(f"browser sandbox blocked request: {browser_result.requests_aborted[0]}")
                if getattr(browser_result, "input_errors", None):
                    warnings.append(
                        "browser input probe errors: "
                        + "; ".join(str(item) for item in browser_result.input_errors[:2])
                    )
                if (
                    getattr(browser_result, "input_attempted", False)
                    and getattr(browser_result, "visual_changed", None) is False
                ):
                    warnings.append(
                        "browser input probe produced no visible page change; the start flow or advertised controls "
                        "may be inert even though animation frames are running"
                    )
                if getattr(browser_result, "visual_probe_error", ""):
                    warnings.append(
                        "browser visual probe incomplete: "
                        + _clip(browser_result.visual_probe_error, 180)
                    )
                has_interval_loop = "setinterval" in low
                loop_observed = browser_result.frames_observed > 0 or browser_result.intervals_observed > 0
                if not loop_observed and has_interval_loop:
                    warnings.append("browser sandbox observed zero animation frames; setInterval loop detected")
                elif not loop_observed:
                    issues.append("browser sandbox observed no game-loop activity")

                # 截图质量层：确定性空白屏探针 + VLM 软门禁。只在页面真的跑起来
                # 且拿到截图时评审；评审自身故障一律降级为 warning（fail-open）。
                screenshot_b64 = getattr(browser_result, "screenshot_b64", None)
                if screenshot_b64 and loop_observed and not browser_result.timed_out:
                    blank_reason = visual_review.blank_screen_reason(screenshot_b64)
                    if blank_reason:
                        issues.append(
                            "browser screenshot shows an essentially blank play screen "
                            f"while the loop is running — {blank_reason}"
                        )
                    elif state.get("use_real") and settings.VISUAL_REVIEW_ENABLED:
                        visual_verdict = visual_review.review_screenshot(
                            screenshot_b64,
                            execution_spec_from_state(state),
                            execution_design_from_state(state),
                        )
                        if visual_verdict is None:
                            warnings.append("visual review unavailable; screenshot not judged")
                        else:
                            # readability 2/5 只在"还有最小 patch 预算的生成任务"里
                            # 升级为 issue("visual review:" 前缀 → quality 最小 patch
                            # 路径);预算耗尽或 revision/remix 回落 warning,主观分
                            # 永远到不了 replan/failed(像素都市计划 2026-07-17:
                            # 2/5 评审说中全部可读性问题却被 warning 档丢弃)。
                            escalate = (
                                str(state.get("task_kind") or "generation")
                                not in {"revision", "remix"}
                                and state.get("gameplay_repair_attempts", 0) < MAX_GAMEPLAY_REPAIR
                            )
                            visual_issues, visual_warnings = visual_review.verdict_findings(
                                visual_verdict,
                                escalate_marginal_readability=escalate,
                            )
                            issues.extend(visual_issues)
                            warnings.extend(visual_warnings)

    is_3d = state.get("dimension") == "3d"
    if is_3d:
        depth_metric = any(tok in low for tok in ["three.", "webglrenderer", "perspectivecamera", "scene()", "new scene"])
        if not depth_metric:
            warnings.append("3D may be missing: no Three.js/WebGL usage detected")
        if "three.min.js" not in low:
            warnings.append("index.html does not reference the self-hosted three.min.js")
        if archetype == "fps_arena" and not _has_any(low, ["raycaster", "pointerlock", "requestpointerlock"]):
            warnings.append("fps_arena has no raycaster / pointer-lock logic")
    else:
        depth_tokens = ["shadowblur", "createlineargradient", "createradialgradient"]
        if uses_phaser:
            depth_tokens += ["generatetexture", "settint", "tweens.add", "particles", "setblendmode", "postfx", "juice."]
        depth_metric = any(tok in low for tok in depth_tokens)
        if not depth_metric:
            warnings.append("art may look flat: no gradient/glow detected")
        if uses_vite:
            # 质量底线（只对模块化 2D 产物）：剔除脚手架库文件后，玩法代码里必须
            # 真的接了反馈特效；作者模式产物必须替换掉占位玩法。
            gameplay_low = "\n".join(
                str(f.get("content") or "")
                for f in source_files
                if str(f.get("path") or "").endswith((".ts", ".tsx", ".js", ".mjs"))
                and f.get("content_b64") is None
                and str(f.get("path") or "").replace("\\", "/") not in _NON_GAMEPLAY_FILES
            ).lower()
            primary_play_source = _primary_play_source(source_files)
            primary_play_low = primary_play_source.lower()

            # 孤儿模块门禁:作者团队被接受的模块若从入口 import 图不可达,Vite
            # 构建会整体树摇丢弃——玩家实际拿到兜底玩法。>=3 个孤儿视为接线事故
            # (修复应当去接线,而不是围着占位玩法打补丁);1-2 个只提示。
            if authored_code:
                orphan_modules = _orphan_author_modules(source_files)
                if len(orphan_modules) >= 3:
                    preview = ", ".join(orphan_modules[:12]) + (" …" if len(orphan_modules) > 12 else "")
                    issues.append(
                        f"authored gameplay modules are never imported by the running game: {preview}. "
                        "Wire these accepted modules into the scene composition (import and drive them "
                        "from PlayScene or its systems per src/contracts/AuthorContract.ts) instead of "
                        "rewriting placeholder gameplay"
                    )
                elif orphan_modules:
                    warnings.append(
                        "authored modules not yet imported by the running game: "
                        + ", ".join(orphan_modules)
                    )
                # 布局契约:设计给了 level_layout(背景图按它构图),玩法却完全
                # 不消费——画面与关卡几何必然脱节(地图沦为无关贴图)。
                if execution_design_from_state(state).get("level_layout") and "levellayout" not in gameplay_low:
                    issues.append(
                        "design provides a structured level_layout but gameplay never consumes it: build the "
                        "level geometry from gameConfig.levelLayout (LevelLayout.buildStatics / paths / points) "
                        "so the stage matches the painted backdrop instead of inventing ad-hoc coordinates"
                    )

            # 运行时行为对账（Probe）：脚手架探针报告"实际发生了什么"。探针缺失
            # (旧包/模板回退)或模拟输入没到 gameplay 场景时一律不硬失败——QA 误报
            # 在作者模式下是百万 token 级重生成死循环(2026-07-13 教训)。
            probe_counts: dict[str, int] = {}
            if browser_result is not None and not getattr(browser_result, "skipped", True):
                probe_counts = dict(getattr(browser_result, "probes", {}) or {})
            probe_ready = probe_counts.get("probe:ready", 0) > 0

            def _probe_total(prefix: str) -> int:
                return sum(
                    count
                    for key, count in probe_counts.items()
                    if key == prefix or key.startswith(prefix + "|")
                )

            def _probe_details(prefix: str) -> list[str]:
                return sorted(
                    key.split("|", 1)[1]
                    for key in probe_counts
                    if key.startswith(prefix + "|")
                )

            scene_starts = _probe_details("scene:start")
            gameplay_scenes_reached = [
                key for key in scene_starts if key.strip().lower() not in _MENU_SCENE_KEYS
            ]
            if probe_ready and scene_starts and not gameplay_scenes_reached:
                warnings.append(
                    "simulated input never reached a gameplay scene (scenes started: "
                    + ", ".join(scene_starts[:6])
                    + ") — the start flow may need a clearer advertised input"
                )

            # 交互探针对账(像素市长 2026-07-17 三类"按钮点不动"的机械化门禁)。
            # 旧包的 Probe 没有这些计数器 → 条件自动短路,零误报。
            # ① 输入管线死亡:注入的指针事件到达页面(dom:down|pointer)但没有任何
            #    场景处理过(input:down=0) —— 输入接到了错误的事件层或被禁用。
            dom_pointer_downs = probe_counts.get("dom:down|pointer", 0)
            pointer_injected = any(
                str(item).startswith("pointer:")
                for item in (
                    []
                    if browser_result is None
                    else list(getattr(browser_result, "inputs_sent", []) or [])
                )
            )
            if (
                probe_ready
                and pointer_injected
                and dom_pointer_downs >= 1
                and _probe_total("input:down") == 0
            ):
                input_dead_msg = (
                    "browser input probe: injected pointer presses reached the page but no scene ever "
                    f"processed them (dom:down|pointer={dom_pointer_downs}, input:down=0) — pointer input "
                    "is wired to the wrong layer or scene input is disabled; drive world input through "
                    "scene pointer events (InputRouter.worldPointer) and UI through interactive objects"
                )
                if authored_code:
                    issues.append(input_dead_msg)
                else:
                    warnings.append(input_dead_msg)
            # ② UI 每帧重建:安静观察尾窗内 interactive 注册数仍持续增长。这样的
            #    按钮每帧被销毁重建,永远进不了输入命中列表(渲染正常但点不动),
            #    对象还会无界泄漏。尾窗采样从 probes_start 开始,建场高峰已排除。
            tail_start_probes = (
                {}
                if browser_result is None
                else dict(getattr(browser_result, "probes_start", {}) or {})
            )
            tail_frames = (
                0
                if browser_result is None
                else int(browser_result.frames_observed or 0)
                - int(getattr(browser_result, "frames_start", 0) or 0)
            )
            interactive_churn = probe_counts.get("ui:interactive", 0) - tail_start_probes.get(
                "ui:interactive", 0
            )
            if (
                probe_ready
                and tail_start_probes
                and tail_frames >= 30
                and interactive_churn >= 60
                and interactive_churn >= tail_frames * 0.5
            ):
                churn_msg = (
                    "gameplay UI is rebuilt every frame: "
                    f"{interactive_churn} interactive objects were re-registered across {tail_frames} "
                    "quiet frames — destroy+recreate per tick keeps buttons out of input hit-testing "
                    "(they render but never respond) and leaks objects; create panels once, update their "
                    "text/visibility in place, and rebuild only when the content set actually changes"
                )
                if authored_code:
                    issues.append(churn_msg)
                else:
                    warnings.append(churn_msg)
            # ③ 死键注册:addKey 解析不出 keycode(如 KeyCodes["2"] 而非 KeyCodes.TWO)
            #    —— 注册成功但永远不触发的快捷键。
            invalid_keys = probe_counts.get("key:invalid", 0)
            if probe_ready and invalid_keys > 0:
                invalid_key_msg = (
                    "keyboard keys registered with invalid key codes: "
                    f"{invalid_keys} addKey() call(s) resolved to no key code (for example "
                    'KeyCodes["2"] instead of KeyCodes.TWO for the 2 key) — these hotkeys can never fire; '
                    "resolve every binding through Phaser.Input.Keyboard.KeyCodes constants and mind the "
                    "Digit (ONE/TWO/…), Space, and Arrow names"
                )
                if authored_code:
                    issues.append(invalid_key_msg)
                else:
                    warnings.append(invalid_key_msg)
            # ④ 画布 0×0:游戏在跑但完全不可见(样式竞态/尺寸接线) —— 独立打开
            #    发布包时的隐形黑屏。脚手架已内联关键尺寸样式,此探针是回归哨兵。
            if probe_counts.get("canvas:zerosize", 0) > 0:
                warnings.append(
                    "game canvas measured 0x0 after load — the page runs but renders invisible "
                    "(stylesheet race or scale wiring); keep the inline critical sizing in index.html"
                )
            capability_sources = [
                (
                    str(f.get("path") or "").replace("\\", "/"),
                    str(f.get("content") or "").lower(),
                )
                for f in source_files
                if str(f.get("path") or "").endswith((".ts", ".tsx", ".js", ".mjs"))
                and f.get("content_b64") is None
                and str(f.get("path") or "").replace("\\", "/") not in _CAPABILITY_DECLARATION_FILES
                # Barrel exports prove only that a type is available, not that
                # a scene/controller constructs or calls it.
                and not str(f.get("path") or "").replace("\\", "/").endswith("/index.ts")
            ]
            capability_low = "\n".join(content for _, content in capability_sources)
            settings_service_low = next(
                (
                    str(f.get("content") or "").lower()
                    for f in source_files
                    if str(f.get("path") or "").replace("\\", "/")
                    == "src/presentation/SettingsService.ts"
                ),
                "",
            )
            if state.get("design_contract"):
                request_low = json.dumps(
                    (state.get("design_contract") or {}).get("requirements") or [],
                    ensure_ascii=False,
                ).lower()
            else:
                request_low = str(
                    state.get("normalized_prompt") or state.get("prompt") or ""
                ).lower()
            persistence_requested = any(
                token in request_low
                for token in (
                    "存档", "存檔", "保存进度", "保存進度", "save game", "save progress",
                    "persistent save", "persistence",
                )
            )
            bridge_load_reachable = any(
                re.search(
                    r"\bgameweavebridge\s*\.\s*load(?:\s*<[^>]+>)?\s*\(",
                    content,
                )
                is not None
                for _, content in capability_sources
            )
            bridge_save_reachable = any(
                re.search(r"\bgameweavebridge\s*\.\s*save\s*\(", content) is not None
                for _, content in capability_sources
            )
            if authored_code and persistence_requested and not (
                bridge_load_reachable and bridge_save_reachable
            ):
                issues.append(
                    "the request requires save persistence, but reachable gameplay never loads and saves through "
                    "the scaffold's GameWeaveBridge; a bridge wrapper or discarded BootScene load is not enough — "
                    "wire a versioned run/settings snapshot through GameWeaveBridge.load()/save()"
                )
            settings_requested = any(
                token in request_low
                for token in (
                    "设置", "設定", "settings", "options menu", "setting menu",
                )
            )
            bindings_requested = any(
                token in request_low
                for token in (
                    "按键修改", "按鍵修改", "按键设置", "按鍵設定", "键位", "鍵位",
                    "key rebinding", "keybinding", "key binding", "remap controls", "rebind controls",
                )
            )
            volume_requested = any(
                token in request_low
                for token in (
                    "音量", "volume control", "volume settings", "master volume", "audio settings",
                )
            )
            settings_service_reachable = any(
                re.search(
                    r"\b(?:new\s+settingsservice\s*\(|settingsservice\s*\.\s*(?:getinstance|instance|load)\b)",
                    content,
                )
                is not None
                for _, content in capability_sources
            )
            if authored_code and settings_requested and not settings_service_reachable:
                issues.append(
                    "the request requires functional settings, but SettingsService is never consumed by a gameplay/menu "
                    "module; a discarded BootScene load or decorative pause-menu label is not reachable UI"
                )
            if authored_code and bindings_requested and ".requestrebind(" not in capability_low:
                issues.append(
                    "the request requires key rebinding, but no reachable menu/controller calls "
                    "InputBindingService.requestRebind() and applies the resulting bindings to gameplay input"
                )
            volume_reachable = any(
                token in capability_low for token in (".setmastervolume(", ".seteffectsgain(")
            ) or (
                settings_service_reachable
                and ".setmastervolume(" in settings_service_low
                and ".update(" in capability_low
            )
            if authored_code and volume_requested and not volume_reachable:
                issues.append(
                    "the request requires volume controls, but no reachable settings/menu path applies volume through "
                    "Sfx.setMasterVolume() or the gameplay AudioService"
                )

            random_dungeon_requested = (
                any(
                    token in request_low
                    for token in (
                        "随机生成房间", "隨機生成房間", "随机地牢", "隨機地牢",
                        "random dungeon", "randomly generated room", "procedural dungeon",
                        "procedurally generated room",
                    )
                )
                and any(
                    token in request_low
                    for token in ("地牢", "地下城", "dungeon", "房间", "房間", "room")
                )
            )
            if authored_code and random_dungeon_requested:
                generation_bodies = [
                    method[1]
                    for name in ("generateRooms", "generateDungeon", "buildRooms", "buildDungeon")
                    if (method := _js_method(js, name)) is not None
                ]
                if generation_bodies and not any(
                    re.search(r"\b(?:random|rng|shuffle|seeded|pick|sample)\b", body, re.I)
                    for body in generation_bodies
                ):
                    issues.append(
                        "the request requires a newly randomized dungeon each run, but the room-generation method returns "
                        "a fixed room sequence; use the seeded RNG to vary the reachable room graph while preserving "
                        "required chest, shop, trap, and Boss rooms"
                    )
            corridors_requested = any(
                token in request_low
                for token in (
                    "走廊", "通道", "corridor", "hallway", "connected rooms", "room graph",
                )
            )
            graph_connection_tokens = (
                "connections", "neighbors", "neighbours", "exits", "nextroomids",
                "adjacentids", "roomedges", "graph.edges",
            )
            has_room_graph = any(token in gameplay_low for token in graph_connection_tokens)
            linear_room_progression = any(
                re.search(pattern, gameplay_low) is not None
                for pattern in (
                    r"roomindex\s*\+=\s*1",
                    r"roomindex\s*=\s*roomindex\s*\+\s*1",
                    r"roomindex\s*\+\s*1",
                )
            )
            if (
                authored_code
                and random_dungeon_requested
                and corridors_requested
                and (not has_room_graph or linear_room_progression)
            ):
                issues.append(
                    "the request requires a connected random room-and-corridor graph, but gameplay still advances a "
                    "linear roomIndex + 1 route (or stores no room connections); generate explicit reachable edges, "
                    "offer branch choices at exits, and draw corridor lines between connected rooms on the map"
                )
            fx_tokens = ["juice.", "tweens.add", "particles", ".shake(", "settintfill", "floattext(", ".flash("]
            feedback_fx = any(tok in gameplay_low for tok in fx_tokens)
            if not feedback_fx:
                issues.append(
                    "no gameplay feedback effects found: wire hit/score events to the scaffold's Juice helpers "
                    "(hitFlash/burst/shake/floatText) or tweens/particles"
                )
            if "sfx." not in gameplay_low and "audiocontext" not in gameplay_low:
                warnings.append("no audio usage detected (Sfx presets are available at src/systems/Sfx.ts)")
            if (authored_code or state.get("use_real")) and "gw_placeholder_gameplay" in gameplay_low:
                issues.append(
                    "authored project still contains the GW_PLACEHOLDER_GAMEPLAY placeholder; "
                    "replace it with the designed gameplay"
                )

            presentation_source = "\n".join(
                str(f.get("content") or "")
                for f in source_files
                if str(f.get("path") or "").replace("\\", "/").startswith(
                    ("src/scenes/", "src/ui/", "src/presentation/")
                )
                and f.get("content_b64") is None
            )
            literal_font_sizes = _literal_gameplay_font_sizes(presentation_source)
            small_font_sizes = [size for size in literal_font_sizes if size < 16]
            if len(small_font_sizes) >= 3:
                readability_msg = (
                    "gameplay UI uses multiple source fonts below 16px; the 1280x720 canvas is commonly embedded "
                    "near 840px wide, shrinking essential HUD and instruction text below readable size. Keep primary "
                    "gameplay text at least 18px and secondary text at least 16px"
                )
                if authored_code:
                    issues.append(readability_msg)
                else:
                    warnings.append(readability_msg)
            # 出界防线：用了物理速度/追踪移动却没有任何世界边界处理 —— 敌人会
            # 漂出场外滞留。作者产物走修复回环,模板/修订只提示。
            moves = any(tok in gameplay_low for tok in ["setvelocity", "movetoobject", "moveto("])
            handles_bounds = any(
                tok in gameplay_low
                for tok in ["collideworldbounds", "bounds.", "worldbounds", "despawnoutside", "wrap(", "clamp("]
            )
            if moves and not handles_bounds:
                bounds_msg = (
                    "moving physics bodies but no world-edge handling found: use the scaffold's Bounds system "
                    "(collideWorld/clamp/wrap/despawnOutside) so actors cannot drift out of the arena"
                )
                if authored_code:
                    issues.append(bounds_msg)
                else:
                    warnings.append(bounds_msg)
            # 生成素材必须真的被用上：花钱生成的雪碧图/背景图被 preload 却不显示,
            # 玩家看到的还是程序化圆点(2026-07-13 实测:背景图进包但零引用)。
            # token 表必须包含 sheetFrame——脚手架推荐的取帧辅助函数定义在
            # gameConfig.ts(已被 _NON_GAMEPLAY_FILES 剔除),玩法代码只会出现
            # sheetFrame(...) 调用;漏掉它会把正确用法误判为未使用,修复回环
            # 反复整包重生成也永远过不了门禁(2026-07-13 两任务实测)。
            manifest_assets = (state.get("asset_manifest") or {}).get("assets") or []
            has_sheet_asset = any(
                isinstance(a, dict) and str(a.get("kind")) == "spritesheet" and a.get("frames")
                for a in manifest_assets
            )
            semantic_sprite_manifest = (state.get("asset_manifest") or {}).get("sprite_demand_manifest") or {}
            semantic_runtime_manifest = semantic_sprite_manifest.get("runtime_manifest") or {}
            semantic_metrics = semantic_sprite_manifest.get("metrics") or {}
            if semantic_runtime_manifest:
                semantic_tokens = ("spriteframe", "semanticframe", "semantic_frames", "semanticframes")
                resolves_semantic_frames = any(token in gameplay_low for token in semantic_tokens)
                if not resolves_semantic_frames:
                    semantic_msg = (
                        "semantic sprite manifest is available but gameplay never resolves semantic IDs; "
                        "use spriteFrame()/semanticFrame() instead of sheet indices or positional frame names"
                    )
                    if authored_code:
                        issues.append(semantic_msg)
                    else:
                        warnings.append(semantic_msg)
                unused_required = int(semantic_metrics.get("unused_required_frame") or 0)
                # ``unused_required_frame`` is generated-asset coverage until
                # code exists, not runtime-consumption proof.  A dynamic
                # semantic resolver intentionally need not repeat every ID as a
                # source literal, so stale/static zero-coverage must not create
                # an impossible QA loop when the resolver is wired.
                if unused_required and not resolves_semantic_frames:
                    coverage_msg = (
                        f"sprite demand manifest has {unused_required} unused required frame(s); "
                        "remove unconsumed demands or add the missing runtime consumer before publishing"
                    )
                    if authored_code:
                        issues.append(coverage_msg)
                    else:
                        warnings.append(coverage_msg)
            has_bg_asset = any(
                isinstance(a, dict) and str(a.get("kind")) == "image" and "background" in str(a.get("key") or "")
                for a in manifest_assets
            )
            if has_sheet_asset and not any(
                tok in gameplay_low
                for tok in [
                    "gameconfig.sheet",
                    "sheet.frames",
                    "sheet.key",
                    "sheetframe",
                    "spriteframe",
                    "semanticframe",
                    "semantic_frames",
                    "semanticframes",
                ]
            ):
                sheet_msg = (
                    "generated sprite sheet is preloaded but never used: build sprites and animations "
                    "from gameConfig.sheet frames instead of procedural shapes"
                )
                if authored_code:
                    issues.append(sheet_msg)
                else:
                    warnings.append(sheet_msg)
            if has_bg_asset:
                # 事实优先级：沙箱重放的 backdrop:draw 探针 > 源码 token。探针证明
                # gameplay 场景真的画了背景时，token 检查直接跳过（防止自定义封装
                # 被 token 检查误伤）；探针证明没画时，即使 token 在（死分支）也算。
                backdrop_gameplay_draws = [
                    key
                    for key in _probe_details("backdrop:draw")
                    if key.strip().lower() not in _MENU_SCENE_KEYS
                ]
                background_tokens = (
                    "backdrop.draw",
                    "backdrop.swap",
                    "assetkeys.backgrounds",
                    "assetkeys.background",
                )
                background_anywhere = any(tok in gameplay_low for tok in background_tokens)
                background_in_play = any(tok in primary_play_low for tok in background_tokens)
                background_msg = None
                if backdrop_gameplay_draws:
                    background_msg = None  # runtime proof: backdrop rendered in gameplay
                elif probe_ready and gameplay_scenes_reached:
                    drawn_in = _probe_details("backdrop:draw")
                    background_msg = (
                        "generated backdrop never rendered in the reachable gameplay scene during the sandbox replay "
                        + (f"(Backdrop.draw only ran in: {', '.join(drawn_in[:4])})" if drawn_in else "(Backdrop.draw never ran)")
                        + "; call Backdrop.draw() from the primary gameplay scene's create() and keep large arena "
                        "panels translucent enough for the art to remain visible"
                    )
                elif not background_anywhere:
                    background_msg = (
                        "generated background image is preloaded but never displayed; call Backdrop.draw() from the "
                        "primary gameplay scene and keep large arena panels translucent enough for the art to remain visible"
                    )
                elif primary_play_source and not background_in_play:
                    background_msg = (
                        "generated background is used only outside PlayScene (for example on the title screen); render it "
                        "in reachable gameplay with Backdrop.draw()/swap() and preserve contrast with translucent play surfaces"
                    )
                if background_msg:
                    if authored_code:
                        issues.append(background_msg)
                    else:
                        warnings.append(background_msg)

            # 生成的动画帧组必须真的播放过：帧组是花钱生成的核心视觉资产，
            # anims:play 探针为零意味着演员全程单帧(读作半成品)。软告警进修复
            # 简报——手动 setTexture 轮换是少数合法路径，不硬失败。
            has_sheet_animations = any(
                isinstance(a, dict)
                and str(a.get("kind")) == "spritesheet"
                and isinstance(a.get("animations"), dict)
                and a.get("animations")
                for a in manifest_assets
            )
            if (
                probe_ready
                and gameplay_scenes_reached
                and has_sheet_animations
                and _probe_total("anims:play") == 0
            ):
                warnings.append(
                    "generated animation groups never played during the sandbox replay (no anims:play probes): "
                    "wire the sheet animation groups through anims.create()/play() — actors that never change "
                    "frame read as unfinished"
                )

            # 设计敌人名册 vs 运行时 spawn 探针：声明了 >=2 种敌人却零 spawn 上报,
            # 要么开局数秒无战斗、要么 spawn 点没接 Probe.spawn —— 两者都值得修,
            # 但都不该硬失败(沙箱窗口短)。
            design_entities = execution_design_from_state(state).get("entities") or []
            enemy_roster = [
                str(entity.get("name") or entity.get("id") or "").strip()
                for entity in design_entities
                if isinstance(entity, dict)
                and str(entity.get("role") or "").strip().lower().startswith(("enemy", "boss"))
            ]
            if (
                probe_ready
                and gameplay_scenes_reached
                and len(enemy_roster) >= 2
                and _probe_total("spawn:enemy") == 0
                and _probe_total("spawn:boss") == 0
            ):
                roster_msg = (
                    f"declared enemy roster never spawned during the sandbox replay: the design lists "
                    f"{len(enemy_roster)} enemy/boss archetypes but no spawn:enemy/spawn:boss probes fired — "
                    "either combat never starts in the first seconds or actor spawn points are missing "
                    'Probe.spawn("enemy", id) instrumentation'
                )
                # design_driven(自由 archetype)的对手就是游戏的核心机制——名册
                # 全灭说明玩法退化成了别的游戏,升级为可修复 issue;模板类保持
                # 软告警(沙箱窗口短,波次可能真的没开打)。
                requires_genre_fidelity = bool(
                    (
                        (execution_design_from_state(state).get("balance") or {}).get("qa")
                        or {}
                    ).get("requires_genre_fidelity")
                )
                if authored_code and requires_genre_fidelity:
                    issues.append(roster_msg)
                else:
                    warnings.append(roster_msg)
            # 阻挡类实体防线:设计声明了 obstacle 桶实体(掩体/墙/平台/砖块...),
            # 玩法代码却毫无对应痕迹 —— 枪战没掩体就退化成空场对枪(2026-07-12
            # 用户实测反馈)。作者产物走修复回环,模板/修订只提示。token 词表须
            # 覆盖各类型的自然命名(platformer 写 platforms、breakout 写 brick)。
            from app.services.game_assets import design_obstacles

            if design_obstacles(execution_design_from_state(state)) and not _has_any(
                gameplay_low,
                ["obstacle", "cover", "barrier", "crate", "barricade", "wall", "platform", "block", "brick", "terrain", "掩体"],
            ):
                obstacle_msg = (
                    "design declares obstacle/blocking entities but gameplay code never creates them: "
                    "spawn them as static or destructible physics bodies (their sheet frames are generated; "
                    "resolve via sheetFrame()) that actually block movement and projectiles"
                )
                if authored_code:
                    issues.append(obstacle_msg)
                else:
                    warnings.append(obstacle_msg)
            # 死导出报告：角色层建好却没人接线的系统/内容(玩家永远体验不到)。
            # 只作 warning + 修复简报素材,绝不硬失败——存在合法的少量未用导出。
            if authored_code:
                dead_exports = _dead_runtime_exports(source_files)
                if len(dead_exports) >= 3:
                    preview = ", ".join(
                        f"{symbol} ({path})" for symbol, path in dead_exports[:12]
                    )
                    warnings.append(
                        f"dead runtime exports: {len(dead_exports)} exported classes/consts/functions are never "
                        f"used outside their defining file — content the player never experiences: {preview}"
                        + (" …" if len(dead_exports) > 12 else "")
                        + ". Wire them into reachable gameplay or delete them"
                    )
        if archetype == "vertical_shooter":
            if not _has_any(low, ["bullet", "shoot", "fire", "projectile", "laser"]):
                warnings.append("shooter has no obvious projectile logic")
            if "boss" not in low:
                warnings.append("shooter has no boss climax")

    return {
        "passed": not issues,
        "archetype": archetype,
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "js_bytes": len(js.encode("utf-8")),
            "has_input": has_input,
            "has_restart": has_restart,
            "runtime_smoke_ok": smoke_ok,
            "runtime_smoke_detail": smoke_detail,
            "sandbox_ok": None if browser_result is None else browser_result.ok,
            "sandbox_skipped": None if browser_result is None else browser_result.skipped,
            "sandbox_frames": None if browser_result is None else browser_result.frames_observed,
            "sandbox_intervals": None if browser_result is None else browser_result.intervals_observed,
            "sandbox_load_ms": None if browser_result is None else browser_result.load_ms,
            "sandbox_input_attempted": None
            if browser_result is None
            else getattr(browser_result, "input_attempted", False),
            "sandbox_inputs_sent": []
            if browser_result is None
            else list(getattr(browser_result, "inputs_sent", []) or []),
            "sandbox_visual_changed": None
            if browser_result is None
            else getattr(browser_result, "visual_changed", None),
            "sandbox_visual_change_ratio": None
            if browser_result is None
            else getattr(browser_result, "visual_change_ratio", None),
            "sandbox_probes": None
            if browser_result is None
            else dict(
                sorted((getattr(browser_result, "probes", {}) or {}).items())[:60]
            ),
            "sandbox_frames_start": None
            if browser_result is None
            else int(getattr(browser_result, "frames_start", 0) or 0),
            "visual_review": visual_verdict,
            ("uses_three_webgl" if is_3d else "uses_gradient_or_glow"): depth_metric,
        },
        "error_code": sandbox_error_code,
    }


def _gameplay_qa_log_lines(result: dict) -> list[str]:
    m = result.get("metrics") or {}
    depth_label = "three/webgl" if "uses_three_webgl" in m else "gradient/glow"
    depth_val = m.get("uses_three_webgl", m.get("uses_gradient_or_glow"))
    lines = [
        f"playtest archetype: {result.get('archetype')}",
        f"code smoke: source={m.get('js_bytes')} bytes, input={m.get('has_input')}, restart={m.get('has_restart')}, {depth_label}={depth_val}",
    ]
    if m.get("runtime_smoke_ok") is not None:
        smoke_detail = str(m.get("runtime_smoke_detail") or "")
        if smoke_detail.startswith("skipped"):
            lines.append(f"runtime smoke: {smoke_detail}")
        else:
            smoke_status = "passed (top-level executes clean)" if m.get("runtime_smoke_ok") else "CRASHED on load"
            lines.append("runtime smoke: " + smoke_status)
    if m.get("sandbox_ok") is not None:
        if m.get("sandbox_skipped"):
            lines.append("browser sandbox: skipped")
        else:
            lines.append(
                f"browser sandbox: {'passed' if m.get('sandbox_ok') else 'failed'}, "
                f"frames={m.get('sandbox_frames')}, intervals={m.get('sandbox_intervals')}, "
                f"load_ms={m.get('sandbox_load_ms')}"
            )
            if m.get("sandbox_input_attempted"):
                lines.append(
                    "browser input/visual probe: "
                    f"inputs={len(m.get('sandbox_inputs_sent') or [])}, "
                    f"visual_changed={m.get('sandbox_visual_changed')}, "
                    f"change_ratio={m.get('sandbox_visual_change_ratio')}"
                )
            probes = m.get("sandbox_probes") or {}
            if probes:
                def _total(prefix: str) -> int:
                    return sum(
                        count for key, count in probes.items()
                        if key == prefix or key.startswith(prefix + "|")
                    )
                scenes = sorted(
                    key.split("|", 1)[1]
                    for key in probes
                    if key.startswith("scene:start|")
                )
                lines.append(
                    "runtime probes: "
                    f"ready={probes.get('probe:ready', 0)}, scenes={','.join(scenes) or '-'}, "
                    f"backdrop_draws={_total('backdrop:draw')}, anims_plays={_total('anims:play')}, "
                    f"enemy_spawns={_total('spawn:enemy') + _total('spawn:boss')}, "
                    f"projectiles={_total('projectile:spawn')}"
                )
                lines.append(
                    "input probes: "
                    f"dom_pointer={probes.get('dom:down|pointer', 0)}, "
                    f"processed_downs={_total('input:down')}, "
                    f"interactive_regs={probes.get('ui:interactive', 0)}, "
                    f"invalid_keys={probes.get('key:invalid', 0)}"
                )
    review = m.get("visual_review")
    if review:
        strengths = "; ".join(review.get("strengths") or [])
        lines.append(
            f"visual review: aesthetics {review.get('aesthetic_score')}/5, "
            f"readability {review.get('readability_score')}/5"
            + (f"; strengths: {strengths}" if strengths else "")
        )
    if result.get("warnings"):
        lines.append("quality warnings: " + "; ".join(result["warnings"][:4]))
    if result.get("issues"):
        return lines + ["gameplay QA failed:"] + result["issues"][:6]
    return lines + ["gameplay QA passed: runnable game loop with input and restart"]


def build_validation_node(state: dict) -> dict:
    enforce_execution_boundary(state)
    result = validation.validate_files(
        state.get("generated_files") or [],
        bundle_type=str(state.get("artifact_format") or "legacy-bundle/v1"),
    )
    build_result = state.get("build_result") or {}
    if build_result and not build_result.get("ok", True):
        result = dict(result)
        result["valid"] = False
        result["errors"] = list(build_result.get("errors") or []) + list(result.get("errors") or [])
    if state.get("task_kind") in {"revision", "remix"} and not (state.get("revision_result") or {}).get("changed_files"):
        result = dict(result)
        result["valid"] = False
        result["errors"] = list(result.get("errors") or []) + [f"{state.get('task_kind')} produced no file changes"]
    # Contract provenance is part of build acceptance.  A generated bundle or
    # asset manifest from another revision must never silently pass validation.
    contract_hash = state.get("contract_hash")
    if contract_hash:
        asset_manifest = state.get("asset_manifest") or {}
        asset_hash = asset_manifest.get("contract_hash")
        if asset_hash and asset_hash != contract_hash:
            result = dict(result)
            result["valid"] = False
            result["errors"] = list(result.get("errors") or []) + [
                f"contract hash mismatch: assets={asset_hash} contract={contract_hash}"
            ]
        sprite_metrics = (asset_manifest.get("sprite_demand_manifest") or {}).get("metrics") or {}
        if int(sprite_metrics.get("orphan_semantic_id") or 0) > 0:
            result = dict(result)
            result["valid"] = False
            result["errors"] = list(result.get("errors") or []) + ["orphan semantic ID in SpriteDemandManifest"]
    if result["valid"]:
        return {
            "validation_result": result,
            "last_error": None,
            "error_code": None,
            "_agent": "BuildValidateAgent",
            "_logs": _validation_log_lines(result) + ["validation passed"],
        }
    return {
        "validation_result": result,
        "last_error": "; ".join(result["errors"]),
        "error_code": TaskErrorCode.VALIDATION_FAILED.value,
        "_agent": "BuildValidateAgent",
        "_logs": _validation_log_lines(result) + ["validation failed:"] + result["errors"][:6],
    }


def gameplay_qa_node(state: dict) -> dict:
    enforce_execution_boundary(state)
    result = _gameplay_qa(state)
    failed = not result.get("passed")
    acceptance_tests = list((state.get("acceptance_plan") or {}).get("tests") or [])
    if acceptance_tests:
        result["acceptance_results"] = [
            {
                "id": test.get("id"),
                "requirement_ids": list(test.get("requirement_ids") or []),
                "passed": not failed,
                "verification": test.get("verification"),
                "evidence": "gameplay_qa_result",
            }
            for test in acceptance_tests
        ]
        result.setdefault("metrics", {})["required_acceptance_pass"] = (
            1.0 if not failed else 0.0
        )
    output = {
        "gameplay_qa_result": result,
        "error_code": None,
        "_agent": "GameplayQAAgent",
        "_logs": _gameplay_qa_log_lines(result),
    }
    if failed:
        output["last_error"] = "; ".join(result.get("issues") or ["gameplay QA failed"])
        output["_step_failed"] = True
        output["error_code"] = result.get("error_code") or TaskErrorCode.QA_FAILED.value
        if result.get("error_code") == TaskErrorCode.SANDBOX_UNAVAILABLE.value:
            output["status"] = "failed"
            output["error_code"] = TaskErrorCode.SANDBOX_UNAVAILABLE.value
            output["error_message"] = output["last_error"]
    return output


def should_continue_after_validation(state: dict) -> str:
    if state.get("task_kind") in {"revision", "remix"}:
        if (state.get("validation_result") or {}).get("valid"):
            return "gameplay_qa"
        return "revision_repair" if state.get("repair_attempts", 0) < MAX_REPAIR else "failed"
    if (state.get("validation_result") or {}).get("valid"):
        return "gameplay_qa"
    if state.get("repair_attempts", 0) < MAX_REPAIR:
        return "repair_code"
    if state.get("replan_attempts", 0) < MAX_REPLAN:
        return "replan_game_design"
    return "failed"


def should_continue_after_gameplay_qa(state: dict) -> str:
    if state.get("status") == "failed":
        return "failed"
    if state.get("task_kind") == "revision":
        if (state.get("gameplay_qa_result") or {}).get("passed"):
            return "publish_revision"
        return "revision_repair" if state.get("repair_attempts", 0) < MAX_REPAIR else "failed"
    if state.get("task_kind") == "remix":
        if (state.get("gameplay_qa_result") or {}).get("passed"):
            return "publish_remix"
        return "revision_repair" if state.get("repair_attempts", 0) < MAX_REPAIR else "failed"
    if (state.get("gameplay_qa_result") or {}).get("passed"):
        return "publish_artifact"
    if state.get("gameplay_repair_attempts", 0) < MAX_GAMEPLAY_REPAIR:
        return "gameplay_repair"
    if state.get("replan_attempts", 0) < MAX_REPLAN:
        return "replan_game_design"
    return "failed"


__all__ = [
    '_sandbox_files_for_qa',
    '_js_braced_body',
    '_js_method',
    '_phaser_player_overlap_issues',
    '_phaser_removed_api_issues',
    '_phaser_destroyed_body_issues',
    '_topdown_uncontrolled_facing_issues',
    '_topdown_generated_avatar_rotation_issues',
    '_gameplay_qa',
    '_gameplay_qa_log_lines',
    'build_validation_node',
    'gameplay_qa_node',
    'should_continue_after_validation',
    'should_continue_after_gameplay_qa',
]
