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
    logs = result["logs"] or ["generated assets: disabled or no eligible requests"]
    return {
        "asset_manifest": current,
        "generated_assets": result["artifacts"],
        "_agent": "GameAssetGenerationAgent",
        "_logs": logs + [f"generated artifact files: {len(result['artifacts'])}"],
    }


__all__ = ["asset_generation_node"]
