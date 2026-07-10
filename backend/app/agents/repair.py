"""Repair and replan nodes for the GameWeave LangGraph pipeline."""
from app.agents.codegen import _generate_code, _generate_revision_code
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


def _nodes_facade_attr(name: str, fallback):
    import sys

    facade = sys.modules.get("app.agents.nodes")
    return getattr(facade, name, fallback) if facade is not None else fallback


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


def _classify_gameplay_failure(qa_result: dict) -> tuple[str, list[str]]:
    """"runtime"：全部 issue 都是运行时报错或其伴随症状（崩溃后零帧/超时），且至少
    一条报错——这是局部代码 bug（如 Phaser API 误用），适合最小 patch。其余（太难/
    无输入/无循环等玩法指标）返回 "design"，走 balance 调参 + 整包重生成。"""
    issues = [str(item) for item in (qa_result or {}).get("issues") or []]
    patchable = [item for item in issues if item.startswith(_RUNTIME_QA_PATCHABLE)]
    symptoms = [item for item in issues if item.startswith(_RUNTIME_QA_SYMPTOMS)]
    if patchable and len(patchable) + len(symptoms) == len(issues):
        return "runtime", patchable
    return "design", patchable


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
    if code_agent.enabled(state):
        outcome = code_agent.run_repair(
            state.get("generated_files") or [],
            error=str(state.get("last_error") or "build validation failed"),
            dimension=str(state.get("dimension") or "2d"),
        )
        if outcome is not None:
            agent_tokens = outcome.tokens
            logs += [f"repair mode: agent tool loop ({outcome.turns} model turn(s))"] + outcome.logs
            if outcome.checks_ok:
                return {
                    "generated_files": outcome.files,
                    "repair_attempts": attempts,
                    "_agent": "GameCodeAgentRepair",
                    "_tokens_delta": agent_tokens,
                    "_logs": logs
                    + _file_log_lines(outcome.files)
                    + ["agent self-checks passed", "queued validation retry"],
                }
            logs.append(
                f"agent loop did not converge ({_clip(outcome.note, 120)}); falling back to full regeneration"
            )
        else:
            logs.append("agent loop unavailable; falling back to full regeneration")
    generate_code = _nodes_facade_attr("_generate_code", _generate_code)
    files, tokens, mode, regen_agent_logs = generate_code({**state, "repair_attempts": attempts}, repair_error=state.get("last_error"))
    return {
        "generated_files": files,
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
            state.get("generated_files") or state.get("existing_files") or [],
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
                    "generated_files": outcome.files,
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
    return {
        "generated_files": files,
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
    # 运行时报错（页面崩溃/console error/Phaser API 误用）是局部 bug：优先内层
    # 工具循环 agent 做最小 patch，保住已生成的玩法，避免整包重生把好的部分改坏。
    # patch 成功回 build_validation 外层门禁复检（agent 自测不作数），再进
    # gameplay_qa；玩法指标问题或 agent 不可用/不收敛，仍走 balance 调参 + 重生成。
    agent_tokens = 0
    failure_kind, runtime_issues = _classify_gameplay_failure(qa_result)
    if failure_kind == "runtime" and code_agent.enabled(state):
        outcome = code_agent.run_repair(
            state.get("generated_files") or [],
            error="; ".join(runtime_issues),
            dimension=str(state.get("dimension") or "2d"),
            failure_label="Browser gameplay QA",
            task_note=(
                "This bundle already passes static build validation and the V8 smoke test; the error(s) above "
                "came from a real headless-browser run. run_checks may therefore report ALL CHECKS PASSED before "
                "you change anything — that alone does NOT mean the bug is fixed. Locate the root cause of the "
                "reported browser error (usually a wrong engine/API call in game.js), apply the smallest fix, "
                "then re-verify with run_checks. Do not redesign gameplay, difficulty or balance."
            ),
        )
        if outcome is not None:
            agent_tokens = outcome.tokens
            logs += [f"repair mode: agent tool loop ({outcome.turns} model turn(s))"] + outcome.logs
            # 浏览器 bug 在 run_checks 里本就不复现，空编辑等于没修，必须有实际改动
            if outcome.checks_ok and outcome.changed:
                return {
                    "generated_files": outcome.files,
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
            logs.append(
                f"agent loop did not converge ({_clip(outcome.note, 120)}); falling back to balance repair + regeneration"
            )
        else:
            logs.append("agent loop unavailable; falling back to balance repair + regeneration")
    elif failure_kind == "runtime":
        logs.append(
            "code agent disabled (needs CODE_AGENT_ENABLED=true and a real-model task); "
            "falling back to balance repair + regeneration"
        )
    spec = state.get("game_spec") or {}
    archetype = spec.get("archetype") or (state.get("game_design") or {}).get("archetype") or "topdown_collect"
    balance = _repair_balance(state.get("balance_config") or (state.get("game_design") or {}).get("balance") or {}, archetype, attempts)
    design = _merge_balance_into_design(state.get("game_design") or _heuristic_design(spec), archetype, balance)
    return {
        "balance_config": balance,
        "game_design": design,
        "generated_files": [],
        "validation_result": {},
        "gameplay_qa_result": {},
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
            raw, tokens = llm.chat(sys_prompt, prompts.build_replan_prompt(state.get("game_spec"), state.get("game_design"), state.get("last_error")))
            design = _coerce_design(_parse_json(raw), state.get("game_spec"))
            extra = {"_tokens_delta": tokens}
        except Exception as exc:
            _real_model_fallback_or_raise("GameDesignAgentReplan", exc, exc)
            design = _simplify_design_3d(state.get("game_design")) if is_3d else _simplify_design(state.get("game_design"))
    else:
        design = _simplify_design_3d(state.get("game_design")) if is_3d else _simplify_design(state.get("game_design"))
    out = {
        "game_design": design,
        "generated_files": [],
        "validation_result": {},
        "gameplay_qa_result": {},
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
    return "build_validation" if state.get("generated_files") else "code_generation"


__all__ = [
    '_RUNTIME_QA_PATCHABLE',
    '_RUNTIME_QA_SYMPTOMS',
    '_classify_gameplay_failure',
    '_repair_balance',
    'repair_code_node',
    'revision_repair_node',
    'gameplay_repair_node',
    'replan_game_design_node',
    'next_after_gameplay_repair',
]
