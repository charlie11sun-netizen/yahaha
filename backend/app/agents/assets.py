"""Asset-generation node kept separate from planning and code authoring."""
from __future__ import annotations

from app.agents.design_contract import enforce_execution_boundary
from app.services.game_assets import generate_game_assets


def asset_generation_node(state: dict) -> dict:
    enforce_execution_boundary(state)
    if state.get("generated_assets"):
        return {
            "_agent": "GameAssetGenerationAgent",
            "_logs": [f"reused {len(state.get('generated_assets') or [])} generated asset file(s)"],
        }
    result = generate_game_assets(state)
    current = dict(state.get("asset_manifest") or {})
    if state.get("contract_hash"):
        current["contract_hash"] = state["contract_hash"]
    if state.get("style_bible"):
        current["style_bible"] = dict(state["style_bible"])
    assets = list(current.get("assets") or [])
    assets.extend(result["manifest_entries"])
    current["assets"] = assets
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
        "_agent": "GameAssetGenerationAgent",
        "_logs": logs + [f"generated artifact files: {len(result['artifacts'])}"],
    }


__all__ = ["asset_generation_node"]
