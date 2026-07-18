"""Asset-generation node kept separate from planning and code authoring."""
from __future__ import annotations

from app.services.game_assets import generate_game_assets


def asset_generation_node(state: dict) -> dict:
    if state.get("generated_assets"):
        return {
            "_agent": "GameAssetGenerationAgent",
            "_logs": [f"reused {len(state.get('generated_assets') or [])} generated asset file(s)"],
        }
    result = generate_game_assets(state)
    current = dict(state.get("asset_manifest") or {})
    assets = list(current.get("assets") or [])
    assets.extend(result["manifest_entries"])
    current["assets"] = assets
    current["asset_trace"] = list(current.get("asset_trace") or []) + list(result.get("asset_trace") or [])
    if result.get("sprite_demand_manifest"):
        current["sprite_demand_manifest"] = result["sprite_demand_manifest"]
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
