"""Build validation and gameplay QA nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *


# 脚手架自带的品质库文件：判定"游戏是否用了反馈特效/边界处理/素材"时要剔除,
# 否则库本身的实现代码会让检查永真。gameConfig.ts 同理——它的 JSON 里天然含
# "sheet"/"background" 字段名,不剔除的话素材未用检测永真。
_STOCK_KIT_FILES = {
    "src/systems/Juice.ts",
    "src/systems/Sfx.ts",
    "src/systems/Bounds.ts",
    "src/systems/Backdrop.ts",
}
_NON_GAMEPLAY_FILES = _STOCK_KIT_FILES | {"src/config/gameConfig.ts"}


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
    match = re.search(rf"\b{re.escape(name)}\s*\(([^)]*)\)\s*{{", source)
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


def _gameplay_qa(state: dict) -> dict:
    """Model-first smoke QA: prove the artifact is a real, runnable game without
    second-guessing how the model wrote it. Hard-fail only on "this isn't a game";
    quality gaps become warnings that never degrade the bundle to a template."""
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
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
    if uses_phaser:
        issues.extend(_phaser_player_overlap_issues(js))
        # The modular Vite runtime is pinned to Phaser 3.90, where setTintFill
        # remains valid. The removed-API lint only applies to legacy Phaser 4 bundles.
        if not uses_vite:
            issues.extend(_phaser_removed_api_issues(js))
        issues.extend(_phaser_destroyed_body_issues(js))
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
    if smoke_ok and validation_result.get("valid") and files:
        try:
            browser_result = sandbox_client.run_bundle(
                _sandbox_files_for_qa(files, state.get("dimension")),
                entry="index.html",
                timeout_ms=settings.SANDBOX_TIMEOUT_MS,
                simulate_input=True,
            )
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
                has_interval_loop = "setinterval" in low
                loop_observed = browser_result.frames_observed > 0 or browser_result.intervals_observed > 0
                if not loop_observed and has_interval_loop:
                    warnings.append("browser sandbox observed zero animation frames; setInterval loop detected")
                elif not loop_observed:
                    issues.append("browser sandbox observed no game-loop activity")

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
                and str(f.get("path") or "") not in _NON_GAMEPLAY_FILES
            ).lower()
            fx_tokens = ["juice.", "tweens.add", "particles", ".shake(", "settintfill", "floattext(", ".flash("]
            feedback_fx = any(tok in gameplay_low for tok in fx_tokens)
            if not feedback_fx:
                issues.append(
                    "no gameplay feedback effects found: wire hit/score events to the scaffold's Juice helpers "
                    "(hitFlash/burst/shake/floatText) or tweens/particles"
                )
            if "sfx." not in gameplay_low and "audiocontext" not in gameplay_low:
                warnings.append("no audio usage detected (Sfx presets are available at src/systems/Sfx.ts)")
            if state.get("code_source") == "author" and "gw_placeholder_gameplay" in gameplay_low:
                issues.append(
                    "authored project still contains the GW_PLACEHOLDER_GAMEPLAY placeholder; "
                    "replace it with the designed gameplay"
                )
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
                if state.get("code_source") == "author":
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
            has_bg_asset = any(
                isinstance(a, dict) and str(a.get("kind")) == "image" and "background" in str(a.get("key") or "")
                for a in manifest_assets
            )
            if has_sheet_asset and not any(
                tok in gameplay_low for tok in ["gameconfig.sheet", "sheet.frames", "sheet.key", "sheetframe"]
            ):
                sheet_msg = (
                    "generated sprite sheet is preloaded but never used: build sprites and animations "
                    "from gameConfig.sheet frames instead of procedural shapes"
                )
                if state.get("code_source") == "author":
                    issues.append(sheet_msg)
                else:
                    warnings.append(sheet_msg)
            if has_bg_asset and not any(
                tok in gameplay_low
                for tok in ["backdrop.", "assetkeys.background", "'background'", '"background"']
            ):
                warnings.append(
                    "generated background image is preloaded but never displayed (Backdrop.draw keeps it visible)"
                )
            # 阻挡类实体防线:设计声明了 obstacle 桶实体(掩体/墙/平台/砖块...),
            # 玩法代码却毫无对应痕迹 —— 枪战没掩体就退化成空场对枪(2026-07-12
            # 用户实测反馈)。作者产物走修复回环,模板/修订只提示。token 词表须
            # 覆盖各类型的自然命名(platformer 写 platforms、breakout 写 brick)。
            from app.services.game_assets import design_obstacles

            if design_obstacles(state.get("game_design") or {}) and not _has_any(
                gameplay_low,
                ["obstacle", "cover", "barrier", "crate", "barricade", "wall", "platform", "block", "brick", "terrain", "掩体"],
            ):
                obstacle_msg = (
                    "design declares obstacle/blocking entities but gameplay code never creates them: "
                    "spawn them as static or destructible physics bodies (their sheet frames are generated; "
                    "resolve via sheetFrame()) that actually block movement and projectiles"
                )
                if state.get("code_source") == "author":
                    issues.append(obstacle_msg)
                else:
                    warnings.append(obstacle_msg)
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
    if result.get("warnings"):
        lines.append("quality warnings: " + "; ".join(result["warnings"][:4]))
    if result.get("issues"):
        return lines + ["gameplay QA failed:"] + result["issues"][:6]
    return lines + ["gameplay QA passed: runnable game loop with input and restart"]


def build_validation_node(state: dict) -> dict:
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
    result = _gameplay_qa(state)
    failed = not result.get("passed")
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
    '_gameplay_qa',
    '_gameplay_qa_log_lines',
    'build_validation_node',
    'gameplay_qa_node',
    'should_continue_after_validation',
    'should_continue_after_gameplay_qa',
]
