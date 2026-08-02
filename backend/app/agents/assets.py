"""Asset-generation node kept separate from planning and code authoring."""
from __future__ import annotations

from app.agents.design_contract import enforce_execution_boundary
from app.core.config import settings
from app.services.game_assets import (
    AssetGenerationRetryRequired,
    generate_game_assets,
    stale_planned_keys,
)


def _manifest_gate(state: dict) -> dict:
    existing = state.get("asset_generation_gate")
    if (
        isinstance(existing, dict)
        and existing
        and existing.get("status") not in {"passed", "disabled"}
    ):
        return dict(existing)
    for entry in (state.get("asset_manifest") or {}).get("assets") or []:
        if not isinstance(entry, dict) or str(entry.get("kind")) != "spritesheet":
            continue
        audit = entry.get("frame_audit") or {}
        # 带伤放行(released_with_warnings)是合法终态:coverage 达标、失败格已
        # 排进 regeneration_plan。复用门禁若仍按 coverage<1.0 拦截,等于把主
        # 流程的放行决定在续跑时推翻(第十二轮 2026-07-19)。
        released = bool(audit.get("released_with_warnings"))
        try:
            coverage = float(audit.get("required_asset_coverage") or 0.0)
        except (TypeError, ValueError):
            coverage = 0.0
        if audit and audit.get("passed") is False and not released:
            return {
                "status": "manual_recovery_required",
                "reason": "required spritesheet frame audit is not passed",
                "asset": entry.get("key"),
            }
        if audit and released and coverage < float(settings.ASSET_RELEASE_COVERAGE_FLOOR):
            return {
                "status": "manual_recovery_required",
                "reason": "released spritesheet is below the coverage floor",
                "asset": entry.get("key"),
            }
        review = entry.get("semantic_review") or {}
        if (
            review
            and review.get("enabled")
            and review.get("failed_frame_ids")
            and audit.get("passed") is not True
            and not released
        ):
            return {
                "status": "manual_recovery_required",
                "reason": "required spritesheet semantic review is not passed",
                "asset": entry.get("key"),
            }
        if settings.ASSET_SEMANTIC_REVIEW_ENABLED:
            layout_review = entry.get("layout_review") or {}
            layout_repack = entry.get("layout_repack") or {}
            layout_ok = bool(layout_review.get("enabled") and layout_review.get("passed"))
            # layout 评审映射不全/不可用时主流程已退回混合重切或固定网格,
            # 逐格语义评审仍然把关——这是合法路径,不是缺口。
            fixed_grid_fallback = layout_repack.get("fallback") == "fixed_grid"
            hybrid_resegmented = bool(layout_repack.get("resegmented"))
            if not layout_ok and not fixed_grid_fallback and not hybrid_resegmented:
                return {
                    "status": "manual_recovery_required",
                    "reason": "required spritesheet source layout review is not passed",
                    "asset": entry.get("key"),
                }
    return {"status": "passed", "reason": "validated asset manifest"}


def asset_generation_node(state: dict) -> dict:
    enforce_execution_boundary(state)
    stale = None
    if state.get("generated_assets"):
        gate = _manifest_gate(state)
        if gate and gate.get("status") not in {"passed", "disabled"}:
            raise AssetGenerationRetryRequired(
                "Asset generation gate is not passed; generation is paused for manual recovery."
            )
        # 逐 key 校验复用:清单条目带 prompt_hash 时,只有全部计划 key 都未变
        # 才整体复用;有变化的走 generate_game_assets 做增量重生成(未变的 key
        # 在里面原样搬运)。无哈希的旧清单保持整体复用的历史行为(stale=None)。
        stale = stale_planned_keys(state)
        if not stale:
            return {
                "_agent": "GameAssetGenerationAgent",
                "_logs": [
                    f"reused {len(state.get('generated_assets') or [])} generated asset file(s)"
                    + ("" if stale is None else " (per-key prompt validation passed)")
                ],
                "asset_generation_gate": gate or {"status": "passed", "reason": "reused validated assets"},
            }
    result = generate_game_assets(state)
    current = dict(state.get("asset_manifest") or {})
    if state.get("contract_hash"):
        current["contract_hash"] = state["contract_hash"]
    if state.get("style_bible"):
        current["style_bible"] = dict(state["style_bible"])
    # result 的 manifest_entries 是本轮完整的生成条目集(复用+新生成);旧的
    # 生成条目若继续 extend 会在增量重生成时产生重复,这里整体替换,只保留
    # 用户上传条目。
    uploaded = [
        entry
        for entry in (current.get("assets") or [])
        if isinstance(entry, dict) and str(entry.get("source") or "") == "uploaded"
    ]
    current["assets"] = uploaded + list(result["manifest_entries"])
    current["asset_trace"] = list(current.get("asset_trace") or []) + list(result.get("asset_trace") or [])
    if result.get("sprite_demand_manifest"):
        current["sprite_demand_manifest"] = result["sprite_demand_manifest"]
    if state.get("asset_batch_specs"):
        current["asset_batch_specs"] = dict(state["asset_batch_specs"])
    logs = result["logs"] or ["generated assets: disabled or no eligible requests"]
    return {
        "asset_manifest": current,
        "generated_assets": result["artifacts"],
        "asset_trace": result.get("asset_trace") or [],
        "sprite_demand_manifest": result.get("sprite_demand_manifest") or {},
        "asset_request_count": result.get("asset_request_count", len(result.get("manifest_entries") or [])),
        "asset_generation_gate": result.get("asset_generation_gate") or {"status": "passed"},
        "_agent": "GameAssetGenerationAgent",
        "_logs": logs + [f"generated artifact files: {len(result['artifacts'])}"],
    }


__all__ = ["asset_generation_node"]
