"""Repair and replan nodes for the GameWeave LangGraph pipeline."""
from app.agents.codegen import _generate_code, _generate_revision_code, _prepare_generated_artifacts
from app.agents.design_contract import execution_design_from_state, execution_spec_from_state
from app.agents.nodes_common import (
    MAX_GAMEPLAY_REPAIR,
    MAX_REPAIR,
    MAX_REPLAN,
    _clip,
    _file_log_lines,
    _parse_json,
    _real_model_fallback_or_raise,
    code_agent,
    llm,
    prompts,
    settings,
)
from app.agents.planning_logs import _balance_log_lines, _design_log_lines
from app.agents.planning_routing import _merge_balance_into_design
from app.agents.planning_spec import (
    _coerce_design,
    _heuristic_design,
    _simplify_design,
    _simplify_design_3d,
)
from app.services.vite_projects import VITE_PROJECT_FORMAT


def _nodes_facade_attr(name: str, fallback):
    import sys

    facade = sys.modules.get("app.agents.nodes")
    return getattr(facade, name, fallback) if facade is not None else fallback


def _repair_input_files(state: dict) -> list[dict]:
    if state.get("artifact_format") == VITE_PROJECT_FORMAT:
        return [
            dict(item)
            for item in (state.get("project_files") or [])
            if item.get("path") and item.get("content_b64") is None
        ]
    return list(state.get("generated_files") or state.get("existing_files") or [])


def _prepared_repair_files(state: dict, repaired: list[dict]) -> dict:
    if state.get("artifact_format") != VITE_PROJECT_FORMAT:
        return {"generated_files": repaired}
    replacements = {str(item.get("path")): dict(item) for item in repaired if item.get("path")}
    original = state.get("project_files") or state.get("existing_files") or []
    original_paths = {str(item.get("path")) for item in original if item.get("path")}
    project = [
        replacements.get(str(item.get("path")), dict(item))
        for item in original
    ]
    # Repair agents may add a small typed service/module required by QA. The
    # previous replacement-only merge silently discarded every new path when
    # returning to LangGraph, making successful persistence/settings repairs
    # disappear before the isolated build.
    project.extend(
        dict(item)
        for item in repaired
        if item.get("path") and str(item.get("path")) not in original_paths
    )
    return {"generated_files": [], "project_files": project, "build_result": {}}


_RUNTIME_QA_PATCHABLE = (
    "runtime smoke test:",
    "browser page error:",
    "browser console error:",
    "browser sandbox blocked request:",
)


_RUNTIME_QA_SYMPTOMS = (
    "browser sandbox observed no game-loop activity",
    "browser sandbox timed out",
)


# 作者产物的质量门禁（素材未接线/占位玩法/无反馈特效/无边界/无障碍物）都是局部
# 接线问题：包能跑、烟测过。整包重生成一轮 author ≈ 百万 token 且对失因一无所知,
# 最小 patch 把缺的线接上才收敛（2026-07-13 两任务各烧两轮重生成的教训）。
_QUALITY_QA_PATCHABLE = (
    "Phaser overlap callback for ",
    "Phaser 4 removed setTintFill()",
    "Phaser code reads ",
    "Phaser input adapter passes DOM KeyboardEvent.code values",
    "top-down player rotation changes continuously every frame",
    "generated top-down avatar body rotates toward movement/aim",
    "the request requires save persistence, but reachable gameplay never loads and saves through",
    "the request requires functional settings, but SettingsService is never consumed",
    "the request requires key rebinding, but no reachable menu/controller calls",
    "the request requires volume controls, but no reachable settings/menu path applies volume",
    "the request requires a newly randomized dungeon each run, but the room-generation method returns",
    "the request requires a connected random room-and-corridor graph, but gameplay still advances",
    "generated sprite sheet is preloaded but never used",
    "generated background image is preloaded but never displayed",
    "generated background is used only outside PlayScene",
    # 运行时对账（Probe）：沙箱重放证明 gameplay 场景没画生成背景 —— 接线级
    # 缺陷，最小 patch 即可（在 PlayScene.create 调 Backdrop.draw）。
    "generated backdrop never rendered in the reachable gameplay scene",
    "gameplay UI uses multiple source fonts below 16px",
    "no gameplay feedback effects found",
    "authored project still contains the GW_PLACEHOLDER_GAMEPLAY placeholder",
    "moving physics bodies but no world-edge handling found",
    "design declares obstacle/blocking entities but gameplay code never creates them",
    # 孤儿模块/布局契约/名册全灭:都是接线级缺陷——作者内容已存在或契约已给
    # 出几何,最小 patch 把它们接进运行图即可,整包重生成反而会丢掉好内容。
    "authored gameplay modules are never imported by the running game",
    "design provides a structured level_layout but gameplay never consumes it",
    "declared enemy roster never spawned during the sandbox replay",
    # 截图质量层（visual_review）：呈现问题可以用小 patch 修（接 Juice/调 HUD/
    # 画背景），不值得整包重生成。
    "browser screenshot shows an essentially blank play screen",
    "visual review:",
    # 交互探针门禁(像素市长 2026-07-17):输入接线死亡/每帧重建 UI/死键注册,
    # 全是局部接线缺陷 —— 最小 patch(改事件层/面板建一次/换 KeyCodes 常量)。
    "browser input probe: injected pointer presses reached the page",
    "gameplay UI is rebuilt every frame",
    "keyboard keys registered with invalid key codes",
)


# 软性运行时观察（QA warning 而非 issue）：不构成失败，但修复/重生成时应当看到。
# 前缀须与 validation_nodes 产出的 warning 文案保持同步。
_ADVISORY_QA_PREFIXES = (
    "dead runtime exports:",
    "generated animation groups never played",
    "declared enemy roster never spawned",
    "simulated input never reached a gameplay scene",
)


def _advisory_qa_feedback(qa_result: dict) -> list[str]:
    return [
        str(item)
        for item in (qa_result or {}).get("warnings") or []
        if str(item).startswith(_ADVISORY_QA_PREFIXES)
    ]


def _classify_gameplay_failure(qa_result: dict) -> tuple[str, list[str]]:
    """"runtime"：全部 issue 都是运行时报错或其伴随症状（崩溃后零帧/超时），且至少
    一条报错——这是局部代码 bug（如 Phaser API 误用），适合最小 patch。"quality"：
    全部 issue 都是质量门禁（生成素材未用/占位玩法/无反馈特效……），同样是局部
    接线问题，走最小 patch。其余（太难/无输入/无循环等玩法指标）返回 "design"，
    走 balance 调参 + 整包重生成。"""
    issues = [str(item) for item in (qa_result or {}).get("issues") or []]
    runtime = [item for item in issues if item.startswith(_RUNTIME_QA_PATCHABLE)]
    symptoms = [item for item in issues if item.startswith(_RUNTIME_QA_SYMPTOMS)]
    quality = [item for item in issues if item.startswith(_QUALITY_QA_PATCHABLE)]
    if runtime and len(runtime) + len(symptoms) + len(quality) == len(issues):
        return "runtime", runtime + quality
    if quality and len(quality) == len(issues):
        return "quality", quality
    return "design", runtime


def _repair_balance(balance: dict, archetype: str, attempt: int) -> dict:
    repaired = dict(balance or {})
    repaired["round_seconds"] = min(90, int((repaired.get("round_seconds") or 55) + 8))
    repaired["target_score"] = max(40, int((repaired.get("target_score") or 180) * 0.86))
    repaired["lives"] = min(5, int(repaired.get("lives") or 3) + 1)
    if archetype == "logic_grid":
        repaired["round_seconds"] = min(90, int((repaired.get("round_seconds") or 70) + 12))
    else:
        repaired["player_speed"] = int((repaired.get("player_speed") or 280) * 1.08)
        repaired["hazard_speed"] = int((repaired.get("hazard_speed") or 140) * 0.78)
        repaired["hazard_spawn_ms"] = min(2600, int((repaired.get("hazard_spawn_ms") or 1200) * 1.35))
        repaired["max_hazards"] = max(4, int(repaired.get("max_hazards") or 8) - 2)
    repaired["repair_attempt"] = attempt
    return repaired


def repair_code_node(state: dict) -> dict:
    attempts = state.get("repair_attempts", 0) + 1
    logs = [
        f"repair attempt: {attempts}/{MAX_REPAIR}",
        f"previous validation error: {_clip(state.get('last_error'), 180)}",
    ]
    # 内层工具循环 agent（CODE_AGENT_ENABLED）：read/write/run_checks 最小修复，
    # 自测通过才提交；不可用/不收敛回落下面的整体重生成。外层 build_validation
    # 仍会独立复检，agent 的自测不作数。
    agent_tokens = 0
    project_author_repair = (
        state.get("artifact_format") == VITE_PROJECT_FORMAT
        and code_agent.author_enabled(state)
    )
    if code_agent.enabled(state) or project_author_repair:
        outcome = code_agent.run_repair(
            _repair_input_files(state),
            error=str(state.get("last_error") or "build validation failed"),
            dimension=str(state.get("dimension") or "2d"),
        )
        if outcome is not None:
            agent_tokens = outcome.tokens
            logs += [f"repair mode: agent tool loop ({outcome.turns} model turn(s))"] + outcome.logs
            if outcome.checks_ok:
                return {
                    **_prepared_repair_files(state, outcome.files),
                    "repair_attempts": attempts,
                    "_agent": "GameCodeAgentRepair",
                    "_tokens_delta": agent_tokens,
                    "_logs": logs
                    + _file_log_lines(outcome.files)
                    + ["agent self-checks passed", "queued validation retry"],
                }
            if state.get("artifact_format") == VITE_PROJECT_FORMAT:
                return {
                    **_prepared_repair_files(state, outcome.files),
                    "repair_attempts": attempts,
                    "_agent": "GameCodeAgentRepair",
                    "_tokens_delta": agent_tokens,
                    "_logs": logs
                    + _file_log_lines(outcome.files)
                    + [
                        f"agent self-checks still failing ({_clip(outcome.note, 120)})",
                        "preserved repaired project for isolated build validation",
                    ],
                }
            logs.append(
                f"agent loop did not converge ({_clip(outcome.note, 120)}); falling back to full regeneration"
            )
        else:
            logs.append("agent loop unavailable; falling back to full regeneration")
    generate_code = _nodes_facade_attr("_generate_code", _generate_code)
    files, tokens, mode, regen_agent_logs = generate_code({**state, "repair_attempts": attempts}, repair_error=state.get("last_error"))
    prepared = _prepare_generated_artifacts(files, state)
    return {
        **prepared,
        "repair_attempts": attempts,
        "_agent": "GameCodeAgentRepair",
        "_tokens_delta": tokens + agent_tokens,
        "_logs": logs
        + [f"regenerated game.js using {mode}"]
        + regen_agent_logs
        + _file_log_lines(files)
        + ["queued validation retry"],
    }


def revision_repair_node(state: dict) -> dict:
    attempts = state.get("repair_attempts", 0) + 1
    logs = [
        f"revision repair attempt: {attempts}/{MAX_REPAIR}",
        f"previous error: {_clip(state.get('last_error'), 180)}",
    ]
    agent_tokens = 0
    if code_agent.enabled(state):
        outcome = code_agent.run_repair(
            _repair_input_files(state),
            error=str(state.get("last_error") or "revision validation failed"),
            dimension=str(state.get("dimension") or "2d"),
            task_note=(
                f"This bundle is a user-requested {state.get('task_kind', 'revision')} of an existing game; "
                "apply the smallest fix and keep unrelated behavior identical."
            ),
        )
        if outcome is not None:
            agent_tokens = outcome.tokens
            logs += [f"repair mode: agent tool loop ({outcome.turns} model turn(s))"] + outcome.logs
            # 外层门禁要求 revision/remix 至少改动一个文件，空编辑等于没修
            if outcome.checks_ok and outcome.changed:
                return {
                    **_prepared_repair_files(state, outcome.files),
                    "revision_result": {"changed_files": outcome.changed, "base_version": state.get("base_version")},
                    "validation_result": {},
                    "gameplay_qa_result": {},
                    "repair_attempts": attempts,
                    "_agent": "CodeRevisionRepairAgent",
                    "_tokens_delta": agent_tokens,
                    "_logs": logs
                    + [
                        "changed files: " + ", ".join(outcome.changed),
                        "agent self-checks passed",
                        "queued validation retry",
                    ],
                }
            logs.append(
                f"agent loop did not converge ({_clip(outcome.note, 120)}); falling back to single-shot revision repair"
            )
        else:
            logs.append("agent loop unavailable; falling back to single-shot revision repair")
    try:
        generate_revision_code = _nodes_facade_attr("_generate_revision_code", _generate_revision_code)
        files, tokens, changed, mode = generate_revision_code(state, repair_error=state.get("last_error"))
    except Exception as exc:  # noqa: BLE001
        if state.get("use_real"):
            _real_model_fallback_or_raise("CodeRevisionRepairAgent", exc, exc)
        files, tokens, changed, mode = state.get("generated_files") or state.get("existing_files") or [], 0, [], f"revision repair failed: {_clip(exc, 160)}"
    vite_revision = state.get("artifact_format") == VITE_PROJECT_FORMAT
    return {
        "generated_files": [] if vite_revision else files,
        "project_files": files if vite_revision else [],
        "build_result": {},
        "revision_result": {"changed_files": changed, "base_version": state.get("base_version")},
        "validation_result": {},
        "gameplay_qa_result": {},
        "repair_attempts": attempts,
        "_agent": "CodeRevisionRepairAgent",
        "_tokens_delta": tokens + agent_tokens,
        "_logs": logs
        + [
            f"revision mode: {mode}",
            "changed files: " + (", ".join(changed) if changed else "none"),
            "queued validation retry",
        ],
    }


def gameplay_repair_node(state: dict) -> dict:
    attempts = state.get("gameplay_repair_attempts", 0) + 1
    qa_result = state.get("gameplay_qa_result") or {}
    issues = qa_result.get("issues") or []
    logs = [
        f"gameplay repair attempt: {attempts}/{MAX_GAMEPLAY_REPAIR}",
        "QA issues: " + ("; ".join(issues[:3]) if issues else "balance threshold miss"),
    ]
    # 运行时报错（页面崩溃/console error/Phaser API 误用）和质量门禁（生成素材
    # 未接线/占位玩法/无反馈特效）都是局部 bug：优先内层工具循环 agent 做最小
    # patch，保住已生成的玩法，避免整包重生把好的部分改坏。patch 成功回
    # build_validation 外层门禁复检（agent 自测不作数），再进 gameplay_qa；
    # 玩法指标问题或 agent 不可用/不收敛，仍走 balance 调参 + 重生成。
    agent_tokens = 0
    failure_kind, patch_issues = _classify_gameplay_failure(qa_result)
    if failure_kind in ("runtime", "quality") and code_agent.enabled(state):
        if failure_kind == "runtime":
            failure_label = "Browser gameplay QA"
            task_note = (
                "This bundle already passes static build validation and the V8 smoke test; the error(s) above "
                "came from a real headless-browser run. run_checks may therefore report ALL CHECKS PASSED before "
                "you change anything — that alone does NOT mean the bug is fixed. Locate the root cause of the "
                "reported browser error (usually a wrong engine/API call in game.js), apply the smallest fix, "
                "then re-verify with run_checks. Do not redesign gameplay, difficulty or balance."
            )
        else:
            failure_label = "Gameplay quality QA"
            task_note = (
                "This bundle builds, passes static validation and the headless-browser smoke run; the finding(s) "
                "above are QUALITY gate failures from inspecting the gameplay modules. run_checks will report ALL "
                "CHECKS PASSED regardless — that does NOT satisfy the findings. Make the smallest coherent edits that "
                "resolve every named finding. This may mean keeping a top-down body upright while rotating only its "
                "weapon, wiring generated sheets through gameConfig.sheet / sheetFrame() and Juice/Sfx, connecting "
                "GameWeaveBridge-backed settings and bindings "
                "to an actually reachable menu, converting DOM codes such as KeyW/ArrowUp to Phaser key names before "
                "addKey(), applying volume changes, making a seeded room generator genuinely vary the room graph, "
                "rendering generated backdrops inside PlayScene with translucent arena surfaces, raising embedded HUD "
                "text to readable sizes, spawning declared obstacles, or routing moving actors through Bounds — follow the "
                "specific findings rather than rewriting unrelated gameplay. Findings prefixed 'visual review:' or "
                "'browser screenshot' come from an actual gameplay screenshot: fix them by drawing the generated "
                "Backdrop, building actors from sheet frames instead of bare shapes, adding contrast/spacing to the "
                "flagged HUD, and wiring Juice feedback — not by tweaking logic. Re-read the flagged modules to confirm each "
                "finding is addressed. Do not change difficulty or balance unless the finding explicitly requires it."
            )
        advisory = _advisory_qa_feedback(qa_result)
        if advisory:
            task_note += (
                " Secondary runtime observations from the same sandbox replay (advisories, not gates — "
                "address them when your edits already touch the same code, otherwise leave them): "
                + " | ".join(advisory[:4])
            )
        outcome = code_agent.run_repair(
            _repair_input_files(state),
            error="; ".join(patch_issues),
            dimension=str(state.get("dimension") or "2d"),
            failure_label=failure_label,
            task_note=task_note,
        )
        if outcome is not None:
            agent_tokens = outcome.tokens
            logs += [f"repair mode: agent tool loop ({outcome.turns} model turn(s))"] + outcome.logs
            # 浏览器 bug 在 run_checks 里本就不复现，空编辑等于没修，必须有实际改动
            if outcome.checks_ok and outcome.changed:
                return {
                    **_prepared_repair_files(state, outcome.files),
                    "validation_result": {},
                    "gameplay_qa_result": {},
                    "gameplay_repair_attempts": attempts,
                    "last_error": None,
                    "_agent": "GameplayRepairAgent",
                    "_tokens_delta": agent_tokens,
                    "_logs": logs
                    + [
                        "patched files: " + ", ".join(outcome.changed),
                        "agent self-checks passed",
                        "kept design and balance untouched; queued build validation recheck",
                    ],
                }
            if (
                outcome.changed
                and state.get("artifact_format") == VITE_PROJECT_FORMAT
            ):
                # A bounded quality repair may make a final small edit after its
                # last successful run_checks and then hit the turn limit. Keep
                # that real modular candidate and let the outer isolated build +
                # gameplay QA gates decide it; regenerating the whole project
                # discards verified work and commonly repeats the same defects.
                return {
                    **_prepared_repair_files(state, outcome.files),
                    "validation_result": {},
                    "gameplay_qa_result": {},
                    "gameplay_repair_attempts": attempts,
                    "last_error": None,
                    "_agent": "GameplayRepairAgent",
                    "_tokens_delta": agent_tokens,
                    "_logs": logs
                    + [
                        "patched files: " + ", ".join(outcome.changed),
                        f"agent stopped after edits ({_clip(outcome.note, 120)})",
                        "preserved modular repair candidate for isolated build and gameplay QA",
                    ],
                }
            logs.append(
                f"agent loop did not converge ({_clip(outcome.note, 120)}); falling back to balance repair + regeneration"
            )
        else:
            logs.append("agent loop unavailable; falling back to balance repair + regeneration")
    elif failure_kind in ("runtime", "quality"):
        logs.append(
            "code agent disabled (needs CODE_AGENT_ENABLED=true and a real-model task); "
            "falling back to balance repair + regeneration"
        )
    spec = execution_spec_from_state(state)
    current_design = execution_design_from_state(state)
    archetype = spec.get("archetype") or current_design.get("archetype") or "topdown_collect"
    balance = _repair_balance(state.get("balance_config") or current_design.get("balance") or {}, archetype, attempts)
    design = _merge_balance_into_design(current_design or _heuristic_design(spec), archetype, balance)
    return {
        "balance_config": balance,
        "game_design": design,
        "generated_assets": [],
        "asset_manifest": {},
        "sprite_demand_manifest": {},
        "asset_batch_specs": {},
        "generated_files": [],
        "project_files": [],
        "build_result": {},
        "validation_result": {},
        "gameplay_qa_result": {},
        # 重生成不能对失因失忆：作者跑一轮 ≈ 百万 token，盲跑只会复刻同样的产物。
        # 把本轮 QA 结论带给下一次 code_generation（作者提示词里必须逐条解决），
        # 软性运行时观察（死导出/动画未播/名册未 spawn）一并带上。
        "gameplay_qa_feedback": list(issues) + _advisory_qa_feedback(qa_result),
        "gameplay_repair_attempts": attempts,
        "last_error": None,
        "_agent": "GameplayRepairAgent",
        "_tokens_delta": agent_tokens,
        "_logs": logs
        + ["applied safer balance: slower hazards, wider spawn interval, lower target, extra life"]
        + _balance_log_lines(archetype, balance)
        + ["queued code regeneration"],
    }


def replan_game_design_node(state: dict) -> dict:
    attempts = state.get("replan_attempts", 0) + 1
    is_3d = state.get("dimension") == "3d"
    extra = {}
    if state.get("use_real"):
        try:
            sys_prompt = prompts.REPLAN_SYSTEM_PROMPT_3D if is_3d else prompts.REPLAN_SYSTEM_PROMPT
            raw, tokens = llm.chat(
                sys_prompt,
                prompts.build_replan_prompt(
                    execution_spec_from_state(state),
                    execution_design_from_state(state),
                    state.get("last_error"),
                ),
                timeout=max(30, int(settings.OPENAI_PLANNING_STREAM_IDLE_TIMEOUT or 180)),
                recover_partial_json=True,
                cache_namespace=prompts.PLANNING_PROMPT_CACHE_NAMESPACE,
                cache_prefix=prompts.PLANNING_SHARED_CACHE_PREFIX,
                # Same per-task cache bucket as the planning chain: the shared
                # global key never serves user content on this gateway.
                cache_task_scoped=True,
            )
            design = _coerce_design(_parse_json(raw), execution_spec_from_state(state))
            extra = {"_tokens_delta": tokens}
        except Exception as exc:
            _real_model_fallback_or_raise("GameDesignAgentReplan", exc, exc)
            current_design = execution_design_from_state(state)
            design = _simplify_design_3d(current_design) if is_3d else _simplify_design(current_design)
    else:
        current_design = execution_design_from_state(state)
        design = _simplify_design_3d(current_design) if is_3d else _simplify_design(current_design)
    out = {
        "game_design": design,
        "generated_assets": [],
        "asset_manifest": {},
        "sprite_demand_manifest": {},
        "asset_batch_specs": {},
        # The replan prompt is a fresh conversation. Do not let a later
        # DesignContractAgent accidentally chain to the superseded design.
        "planning_transcript": None,
        "planning_response_id": None,
        "generated_files": [],
        "project_files": [],
        "build_result": {},
        "validation_result": {},
        "gameplay_qa_result": {},
        "gameplay_qa_feedback": None,  # 设计已重排，旧 QA 结论不再成立
        "repair_attempts": 0,
        "gameplay_repair_attempts": 0,
        "replan_attempts": attempts,
        "last_error": None,
        "_agent": "GameDesignAgentReplan",
        "_logs": [
            f"replan attempt: {attempts}/{MAX_REPLAN}",
            f"reason: {_clip(state.get('last_error'), 180)}",
            (
                "simplified the 3D scope; kept model-authored 3D (no 2D fallback)"
                if is_3d
                else "simplified playable scope and switched to stable template code"
            ),
        ]
        + _design_log_lines(design)
        + ["reset repair counters; queued balance planning"],
        **extra,
    }
    if not is_3d and settings.REAL_MODEL_FALLBACK_ENABLED:
        out["use_template_code"] = True  # 仅 2D 回退稳定模板；3D 保持模型优先
    return out


def next_after_gameplay_repair(state: dict) -> str:
    # patch 路径带着修好的 bundle 回外层门禁复检；重生成路径已清空
    # generated_files，回 code_generation 整包重做。
    if state.get("generated_files") or state.get("project_files"):
        return "project_build"
    # A balance/design repair creates a new contract revision before code is
    # regenerated. Legacy states without a contract retain the old route.
    return "balance_plan" if state.get("design_contract") else "code_generation"


__all__ = [
    '_RUNTIME_QA_PATCHABLE',
    '_RUNTIME_QA_SYMPTOMS',
    '_QUALITY_QA_PATCHABLE',
    '_classify_gameplay_failure',
    '_repair_balance',
    'repair_code_node',
    'revision_repair_node',
    'gameplay_repair_node',
    'replan_game_design_node',
    'next_after_gameplay_repair',
]
