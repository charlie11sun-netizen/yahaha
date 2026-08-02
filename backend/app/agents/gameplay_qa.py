"""Model-first gameplay smoke QA: sandbox replay plus probe reconciliation.

2026-07-26 拆分自 ``validation_nodes.py``:``_gameplay_qa`` 编排静态门禁、V8
冒烟、浏览器沙箱、探针对账与视觉评审;LangGraph 节点接线留在
``validation_nodes``。smoke/sandbox_client/visual_review/settings 经
nodes_common 以模块对象引用——测试在 ``validation_nodes.sandbox_client`` 上打
的补丁改的是同一个模块对象,对本模块的调用同样生效。
"""
# ruff: noqa: F401,F403,F405
import json

from app.agents.nodes_common import *
from app.agents.design_contract import (
    execution_design_from_state,
    execution_spec_from_state,
)
from app.services.vite_projects import phaser_input_binding_errors
from app.services.win_script import extract_win_script
from app.agents.validation_gates import (
    _CAPABILITY_DECLARATION_FILES,
    _MENU_SCENE_KEYS,
    _NON_GAMEPLAY_FILES,
    _dead_runtime_exports,
    _js_method,
    _literal_gameplay_font_sizes,
    _orphan_author_modules,
    _phaser_destroyed_body_issues,
    _phaser_player_overlap_issues,
    _phaser_removed_api_issues,
    _primary_play_source,
    _resolved_entity_lifecycle_issues,
    _runtime_debug_ui_issues,
    _runtime_interaction_probe_issues,
    _sandbox_files_for_qa,
    _spatial_interaction_fidelity_issues,
    _topdown_generated_avatar_rotation_issues,
    _topdown_uncontrolled_facing_issues,
)


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
    if authored_code and uses_vite:
        issues.extend(_spatial_interaction_fidelity_issues(source_files))
        issues.extend(_runtime_debug_ui_issues(source_files))
        issues.extend(_resolved_entity_lifecycle_issues(source_files))
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
                            # 普通 readability 2/5 只在还有最小 patch 预算的生成任务里
                            # 升级为 issue("visual review:" 前缀 → quality 最小 patch
                            # 路径);结构化 essential_text_readable=false 始终是 issue,
                            # 不能在预算耗尽时发布不可玩的文字界面。主观分永远到不了
                            # replan/failed(像素都市计划 2026-07-17:
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
            if probe_ready:
                issues.extend(
                    _runtime_interaction_probe_issues(
                        probe_counts,
                        authored_code=authored_code,
                    )
                )

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
            if probe_ready and "probe.action(" in gameplay_low:
                action_attempts = sum(
                    _probe_total(prefix)
                    for prefix in ("action:attempt", "action:start", "action:triggered")
                )
                if action_attempts == 0:
                    warnings.append(
                        "declared action probes never fired during the sandbox replay: registered controls "
                        "were exercised with bounded holds, but no Probe.action attempt/start/triggered event "
                        "was observed; verify the advertised input reaches its rules-owned action"
                    )
            if (
                probe_ready
                and "probe.outcome(" in gameplay_low
                and sum(
                    _probe_total(prefix)
                    for prefix in ("outcome:success", "outcome:failure", "outcome:blocked")
                )
                == 0
            ):
                warnings.append(
                    "declared interaction outcomes never fired during the sandbox replay: no "
                    "Probe.outcome success/failure/blocked event was observed; verify reachable actions "
                    "produce a rules-owned result instead of only playing an animation"
                )
            # ④ 画布 0×0:游戏在跑但完全不可见(样式竞态/尺寸接线) —— 独立打开
            #    发布包时的隐形黑屏。脚手架已内联关键尺寸样式,此探针是回归哨兵。
            if probe_counts.get("canvas:zerosize", 0) > 0:
                warnings.append(
                    "game canvas measured 0x0 after load — the page runs but renders invisible "
                    "(stylesheet race or scale wiring); keep the inline critical sizing in index.html"
                )
            # ⑤ 通用文字可读性：从实际 canvas CSS 缩放和 Phaser Text 样式取证，
            #    不依赖游戏类型。粗描边吞掉密集字形或关键 HUD 缩到极小，
            #    都是可局部修复但会让游戏不可玩的确定性问题。
            text_blobs = _probe_details("text:blob")
            if probe_ready and text_blobs:
                text_blob_msg = (
                    "essential UI text uses outlines that obscure glyphs or fail to separate fill from "
                    "stroke at the rendered size: [" + ", ".join(text_blobs[:4]) + "]. Keep outline width "
                    "at or below 10% of the font size for dense CJK/Japanese/Korean glyphs and 16% for "
                    "Latin text (prefer 0-1px on 16-24px dense glyphs), use clearly opposite luminance "
                    "for fill and outline, and put text on a solid or translucent contrast panel instead "
                    "of relying on a heavy outline"
                )
                if authored_code:
                    issues.append(text_blob_msg)
                else:
                    warnings.append(text_blob_msg)
            text_tiny = _probe_details("text:tiny")
            if probe_ready and text_tiny:
                text_tiny_msg = (
                    "essential UI text renders below 12 CSS pixels after canvas and container scaling: ["
                    + ", ".join(text_tiny[:4])
                    + "]. Size HUD, instructions, choices, prices, and state controls for their effective "
                    "embedded-page pixels, then measure wrapped text and grow or reflow its panel; raising "
                    "font size inside a fixed-height card is not a complete fix"
                )
                if authored_code:
                    issues.append(text_tiny_msg)
                else:
                    warnings.append(text_tiny_msg)
            # ⑤ 显示比例纪律(像素防线 2026-07-20 "防御塔盖满几格"的机械化门禁)。
            #    scale:conflict:精灵先用 setDisplaySize 归一化,随后又吃到绝对
            #    setScale —— setScale 相对原生素材帧(256px 级)而非归一化尺寸,
            #    实体弹回原始分辨率。确定性 bug,作者产物走最小 patch。
            scale_conflicts = _probe_details("scale:conflict")
            if probe_ready and scale_conflicts:
                conflict_msg = (
                    "sprites lose their normalized display size at runtime: a setScale() call after "
                    "setDisplaySize() is ABSOLUTE (relative to the native art frame, not to the normalized "
                    f"display size), so textures [{', '.join(scale_conflicts[:4])}] snap back toward raw "
                    "sheet resolution and render several times larger than their gameplay footprint. Make "
                    "later size adjustments relative to the normalized base — record it once "
                    "(sprite.setData('baseScale', sprite.scaleX) right after setDisplaySize) and call "
                    "setScale(base * factor) — or re-issue setDisplaySize with the new target size"
                )
                if authored_code:
                    issues.append(conflict_msg)
                else:
                    warnings.append(conflict_msg)
            #    scale:native:可见精灵以接近原生比例渲染大分辨率素材帧 —— 归一化
            #    根本没发生。启发式(截图封面/特写可能合法),软告警进修复简报。
            scale_natives = _probe_details("scale:native")
            if probe_ready and scale_natives:
                warnings.append(
                    "sprites render generated art frames at near-native resolution (scale≈1 on large source "
                    "frames): [" + ", ".join(scale_natives[:6]) + "] — generated frames are source art "
                    "(typically 256px), while a gameplay actor's rendered size must derive from the logical "
                    "footprint it occupies (grid cell / placement slot / collision body, usually 40-90px); "
                    "normalize with setDisplaySize and keep later adjustments relative to that base"
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
            # 空间机制可见性(像素防线 2026-07-20:塔有 range 数据却无任何射程
            # 显示)。玩法数据里反复出现规则消费的 range/radius 数值,但既没有
            # AreaHint、也没有任何 Graphics 圆环绘制,沙箱重放里 hint:area 探针
            # 也为零 —— 玩家只能猜不可见的数字(射程/光环/服务半径)。三路证据
            # 任一即豁免,软告警进修复简报。
            spatial_tokens = re.findall(
                r"\b[a-z_]*(?:range|radius)[a-z_]*\b(?=\s*[:=]\s*\d)", gameplay_low
            )
            meaningful_spatial = [
                token
                for token in spatial_tokens
                if not any(
                    noise in token
                    for noise in (
                        "corner", "border", "blur", "shadow", "glow", "font", "spawn",
                        "despawn", "cull", "camera", "zoom", "scroll", "pad", "pixel",
                        "deadzone",
                    )
                )
            ]
            affordance_evidence = _has_any(
                gameplay_low,
                ["areahint.", "strokecircle(", "strokeellipse(", "fillcircle("],
            )
            if (
                len(meaningful_spatial) >= 3
                and not affordance_evidence
                and _probe_total("hint:area") == 0
            ):
                spatial_sample = ", ".join(sorted(set(meaningful_spatial))[:5])
                warnings.append(
                    f"gameplay rules consult spatial extents ({spatial_sample}) that are never shown to "
                    "the player: no AreaHint usage, no Graphics ring/area drawing, and no hint:area probes "
                    "fired during the sandbox replay — visualize every rule-consulted range/radius/area at "
                    "the moment the player acts on it (selection/hover ring, placement coverage preview) "
                    "via AreaHint.circle()/rect(), and state the number in the inspect/tooltip UI when one exists"
                )
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

    # 胜路模拟:确定性 WinScript 回放,机器证明"按作者剧本真的能赢"。
    # v1 全部走 warning(理由见 _win_path_findings 文档串)。
    win_warnings, win_simulation = _win_path_findings(
        state,
        sandbox_ready=(
            browser_result is not None
            and not getattr(browser_result, "skipped", False)
            and not browser_result.timed_out
            and (
                browser_result.frames_observed > 0
                or browser_result.intervals_observed > 0
            )
        ),
    )
    warnings.extend(win_warnings)

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
                sorted((getattr(browser_result, "probes", {}) or {}).items())[:120]
            ),
            "sandbox_frames_start": None
            if browser_result is None
            else int(getattr(browser_result, "frames_start", 0) or 0),
            "visual_review": visual_verdict,
            "win_simulation": win_simulation,
            ("uses_three_webgl" if is_3d else "uses_gradient_or_glow"): depth_metric,
        },
        "error_code": sandbox_error_code,
    }


def _win_path_findings(state: dict, sandbox_ready: bool) -> tuple[list[str], dict | None]:
    """Deterministic WinScript replay verdict → warning-level findings.

    Every finding stays a warning on purpose: repair issue routing is
    prefix-matched free text (repair.py), and an unrecognized issue string can
    escalate to a full regeneration. Warnings reach the repair brief without
    touching routing; promotion to a hard gate is a deliberate later step once
    false-positive rates are known.
    """
    source_files = state.get("project_files") or state.get("generated_files") or []
    payload, artifact_errors = extract_win_script(source_files)
    if payload is None and not artifact_errors:
        # No artifact: adoption is prompt-driven; pre-WinScript tasks stay silent.
        return [], None
    if artifact_errors:
        return (
            [
                "win-path: WinScript.json is present but invalid ("
                + _clip("; ".join(artifact_errors[:4]), 240)
                + ") — fix the artifact so QA can machine-verify winnability"
            ],
            {"verdict": "invalid", "errors": artifact_errors[:8]},
        )
    if not settings.WIN_SIMULATION_ENABLED:
        return [], {"verdict": "disabled"}
    if not sandbox_ready:
        return (
            ["win-path: browser sandbox replay unavailable, win-path simulation skipped"],
            {"verdict": "skipped", "detail": "sandbox not ready"},
        )
    result = sandbox_client.simulate_win(
        _sandbox_files_for_qa(state.get("generated_files") or [], state.get("dimension")),
        payload,
        timeout_ms=settings.WIN_SIMULATION_TIMEOUT_MS,
    )
    if result.skipped:
        return (
            [f"win-path simulation skipped: {_clip(result.detail, 180)}"],
            {"verdict": "skipped", "detail": result.detail},
        )
    metrics = {
        "verdict": result.verdict,
        "pump_mode": result.pump_mode,
        "sim_seconds": result.sim_seconds,
        "wall_ms": result.wall_ms,
        "actions_sent": list(result.actions_sent)[:24],
        "stats": dict(sorted(result.stats.items())[:24]),
        "missing_stats": list(result.missing_stats),
        "timeline_tail": list(result.timeline)[-16:],
        "detail": result.detail,
    }
    warnings: list[str] = []
    if result.missing_stats:
        warnings.append(
            "win-path: WinScript rules reference stats the game never published via Probe.stat: "
            + ", ".join(result.missing_stats[:6])
            + " — publish each referenced stat from the rules layer the moment it changes"
        )
    if result.verdict == "won":
        return warnings, metrics
    timeline_digest = _clip(
        "; ".join(f"{item.get('t')}s {item.get('event')}" for item in result.timeline[-8:]),
        420,
    )
    if result.verdict in {"lost", "timeout"}:
        warnings.append(
            f"win-path simulation could not win: verdict={result.verdict} after "
            f"{result.sim_seconds:.0f} simulated seconds following the authored WinScript "
            f"({result.pump_mode} time). Either the game is not winnable as designed, the "
            'WinScript no longer matches the implementation, or Probe.status("won") is never '
            f"wired at the terminal transition. Timeline tail: {timeline_digest}"
        )
    else:
        warnings.append(
            "win-path simulation inconclusive (harness error): "
            + _clip(result.detail or "; ".join(result.page_errors[:2]), 240)
        )
    return warnings, metrics


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
                        if key == prefix
                        or key.startswith(prefix + "|")
                        or key.startswith(prefix + ":")
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
                    f"projectiles={_total('projectile:spawn')}, "
                    f"action_attempts={_total('action:attempt')}, "
                    f"outcome_success={_total('outcome:success')}, "
                    f"outcome_blocked={_total('outcome:blocked')}, "
                    f"despawns={_total('despawn')}"
                )
                lines.append(
                    "input probes: "
                    f"dom_pointer={probes.get('dom:down|pointer', 0)}, "
                    f"processed_downs={_total('input:down')}, "
                    f"interactive_regs={probes.get('ui:interactive', 0)}, "
                    f"invalid_keys={probes.get('key:invalid', 0)}"
                )
                lines.append(
                    "presentation probes: "
                    f"scale_conflicts={_total('scale:conflict')}, "
                    f"scale_native={_total('scale:native')}, "
                    f"area_hints={_total('hint:area')}, "
                    f"text_blobs={_total('text:blob')}, "
                    f"text_tiny={_total('text:tiny')}"
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
