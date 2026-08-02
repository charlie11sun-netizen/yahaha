"""Build validation and gameplay QA nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *
from app.agents.design_contract import enforce_execution_boundary

# ── 拆分兼容面(2026-07-26)──────────────────────────────────────────────
# 静态门禁在 validation_gates,QA 编排在 gameplay_qa;这里显式回导全部既有名
# 字,测试的 `validation_nodes._gameplay_qa` / `validation_nodes._STOCK_KIT_FILES`
# 等访问路径不变。smoke/sandbox_client/visual_review 仍经 nodes_common 星导出
# 挂在本模块上;测试对 `validation_nodes.sandbox_client` 的补丁改的是模块对象
# 本身,实际调用方(gameplay_qa)看到的是同一个对象。
from app.agents.validation_gates import (
    _CAPABILITY_DECLARATION_FILES,
    _MENU_SCENE_KEYS,
    _NON_GAMEPLAY_FILES,
    _STOCK_KIT_FILES,
    _dead_runtime_exports,
    _entry_reachable_paths,
    _js_braced_body,
    _js_method,
    _js_update_top_level_code,
    _literal_gameplay_font_sizes,
    _orphan_author_modules,
    _phaser_destroyed_body_issues,
    _phaser_player_overlap_issues,
    _phaser_removed_api_issues,
    _primary_play_source,
    _resolve_relative_import,
    _resolved_entity_lifecycle_issues,
    _runtime_debug_ui_issues,
    _runtime_interaction_probe_issues,
    _sandbox_files_for_qa,
    _spatial_interaction_fidelity_issues,
    _topdown_generated_avatar_rotation_issues,
    _topdown_uncontrolled_facing_issues,
    _usage_positions,
)
from app.agents.gameplay_qa import (
    _gameplay_qa,
    _gameplay_qa_log_lines,
)


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
    # Exhausting an implementation/presentation patch budget is not evidence
    # that the player's design is wrong. Only a failure classified as a
    # design/feasibility problem may cross the design-contract boundary.
    from app.agents.repair import _classify_gameplay_failure

    failure_kind, _ = _classify_gameplay_failure(state.get("gameplay_qa_result") or {})
    if failure_kind == "design" and state.get("replan_attempts", 0) < MAX_REPLAN:
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
