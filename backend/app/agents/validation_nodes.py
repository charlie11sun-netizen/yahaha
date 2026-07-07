"""Build validation and gameplay QA nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *


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
    js = next((f.get("content", "") for f in files if f.get("path") == "game.js"), "")
    html = next((f.get("content", "") for f in files if f.get("path") == "index.html"), "")
    low = (js + "\n" + html).lower()

    issues: list[str] = []
    warnings: list[str] = []

    # Phaser 产物的循环/输入都由引擎驱动：game.js 里不会出现字面 rAF / addEventListener，
    # 按 Canvas 规则会被误杀。识别引擎特征后放行循环检查、补充 Phaser 输入惯用法。
    uses_phaser = any(tok in low for tok in ["phaser.min.js", "new phaser", "phaser.game", "phaser.scene"])

    if not validation_result.get("valid"):
        issues.append("static validation must pass before gameplay QA")
    if len(js) < 400:
        issues.append("game.js is too small to be a real game")
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
        issues.extend(_phaser_removed_api_issues(js))
        issues.extend(_phaser_destroyed_body_issues(js))
    has_restart = any(tok in low for tok in [
        "restart", "reset(", "replay", "again", "location.reload", '"rs"', "'rs'",
    ])
    if not has_restart:
        warnings.append("no obvious restart affordance detected")

    # 运行时冒烟：先用 V8 快速预检，再用真浏览器沙箱观察加载错误和动画帧。
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
            depth_tokens += ["generatetexture", "settint", "tweens.add", "particles", "setblendmode", "postfx"]
        depth_metric = any(tok in low for tok in depth_tokens)
        if not depth_metric:
            warnings.append("art may look flat: no gradient/glow detected")
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
        f"code smoke: game.js={m.get('js_bytes')} bytes, input={m.get('has_input')}, restart={m.get('has_restart')}, {depth_label}={depth_val}",
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
    result = validation.validate_files(state.get("generated_files") or [])
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
