"""Deterministic static-analysis gates for build validation and gameplay QA.

2026-07-26 拆分自 ``validation_nodes.py``:纯函数门禁——死导出/孤儿模块/几何
保真/调试文案泄漏/实体生命周期/运行时探针对账,以及支撑它们的 JS 轻量解析
(_js_braced_body/_js_method)。不接沙箱、不接模型、无状态。
``validation_nodes`` 回导这里的全部名字,测试与调用方的导入路径不变。
"""
from __future__ import annotations

import re


# 脚手架自带的品质库文件：判定"游戏是否用了反馈特效/边界处理/素材"时要剔除,
# 否则库本身的实现代码会让检查永真。gameConfig.ts 同理——它的 JSON 里天然含
# "sheet"/"background" 字段名,不剔除的话素材未用检测永真。
_STOCK_KIT_FILES = {
    "src/systems/AreaHint.ts",
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


def _spatial_interaction_fidelity_issues(source_files: list[dict]) -> list[str]:
    """Detect authored spatial outcomes that never consult spatial geometry.

    A common generated-game shortcut is to wait for two sprites' center points
    to cross and then decide success from a semantic label such as
    ``posture == "jumping"``.  That can make the rules say "cleared" while the
    rendered bodies visibly overlap.  Keep this gate genre-agnostic: it looks
    for action/kind-dispatched spatial resolvers and accepts either engine
    intersection APIs or an explicit bounds/hitbox/window calculation.
    """

    sources = [
        (
            str(item.get("path") or "").replace("\\", "/"),
            str(item.get("content") or ""),
        )
        for item in source_files
        if str(item.get("path") or "").endswith((".ts", ".tsx", ".js", ".mjs"))
        and item.get("content_b64") is None
        and str(item.get("path") or "").replace("\\", "/") not in _NON_GAMEPLAY_FILES
    ]
    method_re = re.compile(
        r"(?:\b(?:private|protected|public|static|async)\s+)*"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::[^{=]+)?\{",
        re.I,
    )
    resolver_name = re.compile(
        r"(?:resolve|collid|overlap|contact|cross|intersect|impact|hit|avoid|clear)",
        re.I,
    )
    branch_field = re.compile(
        r"\b(?:kind|type|requiredAction|requiredPosture|posture|action|state)\b"
        r"\s*(?:={2,3}|!==?)\s*[\"'][^\"']+[\"']",
        re.I,
    )
    single_axis_crossing = re.compile(
        r"(?:\.\s*[xy]\b|\b[xy]\b)\s*(?:<=|>=|<|>)|"
        r"Math\s*\.\s*abs\s*\([^)]*(?:\.\s*[xy]\b|\b[xy]\b)",
        re.I,
    )
    spatial_subject = re.compile(
        r"\b(?:actor|avatar|body|enemy|hazard|obstacle|player|projectile|sprite|target|unit)\b",
        re.I,
    )
    outcome_effect = re.compile(
        r"\b(?:collid|damage|fail|hit|hurt|miss|outcome|resolve|score|success|avoid|clear)\w*\s*\(",
        re.I,
    )
    canonical_geometry = re.compile(
        r"(?:physics\s*\.\s*add\s*\.\s*(?:overlap|collider)|"
        r"Phaser\s*\.\s*Geom\s*\.[\w.]*Intersects|"
        r"\b(?:getBounds|overlapRect|overlapCirc|hitTest|contains)\s*\(|"
        r"\bbody\s*\.\s*(?:touching|blocked|embedded|overlap)|"
        r"\b(?:hitbox|collisionWindow|interactionWindow|clearance)\b)",
        re.I,
    )
    manual_extents = re.compile(
        r"\b(?:displayWidth|displayHeight|width|height|radius|halfWidth|halfHeight)\b",
        re.I,
    )

    for path, source in sources:
        for match in method_re.finditer(source):
            name = match.group("name")
            if not resolver_name.search(name):
                continue
            body = _js_braced_body(source, match.end())
            if not body:
                continue
            semantic_branches = branch_field.findall(body)
            if (
                len(semantic_branches) < 2
                or not spatial_subject.search(body)
                or not single_axis_crossing.search(body)
                or not outcome_effect.search(body)
            ):
                continue
            has_geometry = bool(canonical_geometry.search(body))
            if not has_geometry:
                # Manual AABB/swept-window code must at least consume both
                # horizontal and vertical extents; a bare x/y threshold is not
                # a collision volume.
                extent_names = {
                    token.lower() for token in manual_extents.findall(body)
                }
                has_geometry = bool(
                    extent_names
                    and any("width" in token or "radius" in token for token in extent_names)
                    and any("height" in token or "radius" in token for token in extent_names)
                )
            if has_geometry:
                continue
            return [
                "spatial interaction outcomes are resolved from semantic labels or a center-line crossing "
                f"without consuming actor and target geometry ({path}:{name}). Derive visual size, collision "
                "body, clearance, and the valid timing/interaction window from one content-owned profile; "
                "resolve success/failure with body overlap, bounds intersection, or a swept window that uses "
                "both extents. Different actions must have visibly distinct spatial affordances rather than "
                "sharing one placement and changing only a kind/posture string"
            ]
    return []


_RUNTIME_UI_PATH_PREFIXES = (
    "src/scenes/",
    "src/ui/",
    "src/presentation/",
    "src/composition/",
    "src/adapters/",
)
_RUNTIME_UI_LITERAL_RE = re.compile(
    r"""(?P<quote>["'`])(?P<body>(?:\\.|(?!(?P=quote)).)*)(?P=quote)""",
    re.DOTALL,
)
_DEBUG_UI_MARKER_RE = re.compile(
    r"(?:"
    r"\b(?:debug|qa|probe|hitbox|collision body|rules layer|state machine|"
    r"acceptance (?:test|evidence)|test harness)\b"
    r"|规则层|碰撞包络|调试(?:信息|模式)?|测试探针"
    r"|(?:梁底|净空|峰值|跨度)[^\"'`\r\n]{0,48}(?:px|像素)"
    r")",
    re.IGNORECASE,
)


def _runtime_debug_ui_issues(source_files: list[dict]) -> list[str]:
    """Reject implementation evidence accidentally rendered as player copy.

    This deliberately scans only presentation/integration modules and only
    string literals. Numeric game state is legitimate; the high-confidence
    markers describe collision geometry, QA, or architecture that belongs in
    Probe rather than a production HUD.
    """

    findings: list[str] = []
    for item in source_files:
        path = str(item.get("path") or "").replace("\\", "/")
        if (
            item.get("content_b64") is not None
            or not path.endswith((".ts", ".tsx", ".js", ".mjs"))
            or not (path.startswith(_RUNTIME_UI_PATH_PREFIXES) or path == "src/main.ts")
        ):
            continue
        source = str(item.get("content") or "")
        for match in _RUNTIME_UI_LITERAL_RE.finditer(source):
            text = match.group("body").strip()
            if not text or not _DEBUG_UI_MARKER_RE.search(text):
                continue
            compact = re.sub(r"\s+", " ", text)
            findings.append(f"{path}: {compact[:120]}")
            if len(findings) >= 4:
                break
        if len(findings) >= 4:
            break
    if not findings:
        return []
    return [
        "player-visible runtime copy exposes debug, collision, QA, or implementation evidence: "
        + "; ".join(findings)
        + ". Replace it with player-facing state/instructions and keep diagnostics in Probe or an "
        "explicit debug-only surface that is disabled in published builds"
    ]


_TERMINAL_ENTITY_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:coin|gem|token|loot|pickup|collectible|consumable|powerup|power_up|"
    r"projectile|bullet|spent_card|defeated|destroyed)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_LIFECYCLE_HANDLER_RE = re.compile(
    r"(?:consume|feedback|outcome|event|pickup|collect|resolve|handle|apply|process)",
    re.IGNORECASE,
)
_LIFECYCLE_TRANSITION_RE = re.compile(
    r"(?:"
    r"\.\s*(?:destroy|disableBody|killAndHide|remove|removeAt|splice)\s*\("
    r"|\.\s*set(?:Visible|Active|Interactive)\s*\(\s*false"
    r"|\b(?:despawn|deactivate|removeEntity|removeActor|removeItem)\s*\("
    r"|\b(?:actors|entities|items|pickups|projectiles)\s*=\s*"
    r"(?:this\.)?(?:actors|entities|items|pickups|projectiles)\s*\.\s*filter\s*\("
    r")",
    re.IGNORECASE,
)


def _resolved_entity_lifecycle_issues(source_files: list[dict]) -> list[str]:
    """Find integration handlers that acknowledge a terminal entity but keep it alive."""

    method_re = re.compile(
        r"(?:\b(?:private|protected|public|static|async)\s+)*"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::[^{=]+)?\{",
        re.IGNORECASE,
    )
    for item in source_files:
        path = str(item.get("path") or "").replace("\\", "/")
        if (
            item.get("content_b64") is not None
            or not path.endswith((".ts", ".tsx", ".js", ".mjs"))
            or not (
                path.startswith(("src/scenes/", "src/composition/", "src/adapters/"))
                or path == "src/main.ts"
            )
        ):
            continue
        source = str(item.get("content") or "")
        for match in method_re.finditer(source):
            name = match.group("name")
            body = _js_braced_body(source, match.end())
            if not body:
                continue
            consumes_resolution = (
                _LIFECYCLE_HANDLER_RE.search(name) is not None
                or re.search(r"\bdrain(?:Feedback|Events|Outcomes)\s*\(", body, re.I)
                is not None
            )
            if (
                not consumes_resolution
                or _TERMINAL_ENTITY_TOKEN_RE.search(body) is None
                or _LIFECYCLE_TRANSITION_RE.search(body) is not None
            ):
                continue
            if not re.search(
                r"\b(?:kind|type|category|event|cue|result|outcome|feedback)\b",
                body,
                re.IGNORECASE,
            ):
                continue
            return [
                "resolved transient entities do not complete their render/physics lifecycle "
                f"({path}:{name}). Carry the stable entity id in the rules result, remove or deactivate "
                "the matching renderer and collision/input body in the same logical tick, remove it from "
                "future interaction queries, then emit Probe.despawn; off-screen cleanup and a resolved-id "
                "set do not make a collected or destroyed entity disappear"
            ]
    return []


def _runtime_interaction_probe_issues(
    probe_counts: dict[str, int], *, authored_code: bool
) -> list[str]:
    """Turn conclusive runtime evidence gaps into authored-game release blockers."""

    if not authored_code or probe_counts.get("probe:ready", 0) <= 0:
        return []

    def total(prefix: str) -> int:
        return sum(
            count
            for key, count in probe_counts.items()
            if key == prefix
            or key.startswith(prefix + "|")
            or key.startswith(prefix + ":")
        )

    action_attempts = sum(
        total(prefix)
        for prefix in ("action:attempt", "action:start", "action:triggered")
    )
    successes = total("outcome:success")
    failures = total("outcome:failure")
    blocked = total("outcome:blocked")
    issues: list[str] = []
    if action_attempts >= 2 and blocked >= 2 and successes == 0 and failures == 0:
        issues.append(
            "runtime interaction replay reached the rules repeatedly but every resolved result was blocked "
            f"(actions={action_attempts}, blocked={blocked}, success=0, failure=0). A declared control is "
            "not runtime-accepted in the exercised flow; align input semantics, actionable cue/window, "
            "current-frame action state, and contact resolution, then demonstrate at least one real success"
        )

    terminal_successes = sum(
        count
        for key, count in probe_counts.items()
        if key.startswith("outcome:success|")
        and _TERMINAL_ENTITY_TOKEN_RE.search(key.split("|", 1)[1])
    )
    despawns = total("despawn")
    if terminal_successes > despawns:
        issues.append(
            "runtime reports successful pickup/consumable resolution without matching entity removal "
            f"(terminal successes={terminal_successes}, despawns={despawns}). Remove/deactivate the stable-id "
            "renderer and collision/input body in the same logical tick and emit Probe.despawn afterward"
        )
    return issues
