"""Per-key asset reuse gate for re-entered asset stages.

2026-07-26 拆分自 ``game_assets.py``:素材阶段被 balance 修复/replan/revision
重入时,prompt 未变的图不回炉——整批重画会把已成功的图重新压上不稳定的图像
端点(2026-07-20 三路守卫:revision 重画 5 张全部素材,sheet 连吃 502 团灭
任务)。``stale_planned_keys`` 逐 key 用 manifest 的 ``prompt_hash`` 对照本轮
计划;``_append_carried_asset`` 把未变素材(工件+清单条目+trace)搬进新一轮。
``app.services.game_assets`` 回导这些名字,导入路径不变。
"""
from __future__ import annotations

import hashlib
import json

from app.core.config import settings
from app.generation.design_contract import (
    contract_to_design_payload,
    contract_to_spec_payload,
)
from app.observability.decision_trace import asset_trace_record, prompt_hash
from app.services.artifacts import artifact_bytes
from app.services.asset_planning import PlannedAsset, _tileset_prompt, plan_game_assets
from app.services.tilemaps import TILEMAP_ARCHETYPES


def _execution_spec_design(state: dict) -> tuple[dict, dict]:
    contract = state.get("design_contract")
    if contract:
        spec = state.get("spec_execution_view") or contract_to_spec_payload(contract)
        design = state.get("design_execution_view") or contract_to_design_payload(contract)
        return spec, design
    return state.get("game_spec") or {}, state.get("game_design") or {}


def _tilemap_wanted_for(state: dict, spec: dict) -> bool:
    return (
        settings.TILEMAP_GENERATION_ENABLED
        and state.get("dimension") != "3d"
        and str(spec.get("archetype") or "") in TILEMAP_ARCHETYPES
    )


def _generated_manifest_entries(state: dict) -> list[dict]:
    entries = (state.get("asset_manifest") or {}).get("assets") or []
    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("source") or "") != "uploaded"
    ]


def _artifacts_by_path(state: dict) -> dict[str, dict]:
    by_path: dict[str, dict] = {}
    for artifact in state.get("generated_assets") or []:
        if isinstance(artifact, dict) and artifact.get("path"):
            by_path[str(artifact["path"])] = artifact
    return by_path


def _entry_artifact(entry: dict, artifacts: dict[str, dict]) -> dict | None:
    path = str(entry.get("path") or "")
    if not path:
        return None
    return artifacts.get(f"public/{path}") or artifacts.get(path)


def _entry_reusable(entry: dict, expected_prompt: str, artifacts: dict[str, dict]) -> bool:
    if str(entry.get("prompt_hash") or "") != prompt_hash(expected_prompt):
        return False
    if _entry_artifact(entry, artifacts) is None:
        return False
    if str(entry.get("kind")) == "spritesheet":
        audit = entry.get("frame_audit") or {}
        if not (audit.get("passed") or audit.get("released_with_warnings")):
            return False
        if not entry.get("semantic_frames"):
            return False
    return True


_TILEMAP_FAMILY_PREFIXES = ("tileset", "tilemap")


def _tilemap_family_entries(entries: list[dict]) -> list[dict]:
    return [
        entry
        for entry in entries
        if str(entry.get("key") or "").startswith(_TILEMAP_FAMILY_PREFIXES)
    ]


def stale_planned_keys(state: dict) -> list[str] | None:
    """Per-key reuse verdict for a re-entered asset stage.

    素材阶段可能被 balance 修复/replan/revision 重入。逐 key 用 manifest 里的
    ``prompt_hash`` 对照本轮计划的 prompt:没变的图直接复用,变了的才重画——
    整批重画会把已成功的图重新压上不稳定的图像端点(2026-07-20 三路守卫:
    revision 重画 5 张全部素材,sheet 连吃 502 团灭任务)。

    Returns ``None`` when per-key validation is impossible (no generated
    entries, a legacy manifest without hashes, or asset generation disabled)
    — callers keep their historical behavior; ``[]`` when every planned key
    is reusable; otherwise the list of keys that must be regenerated.
    """
    if not settings.ASSET_GENERATION_ENABLED:
        return None
    entries = _generated_manifest_entries(state)
    if not entries or any(not entry.get("prompt_hash") for entry in entries):
        return None
    artifacts = _artifacts_by_path(state)
    by_key = {str(entry.get("key") or ""): entry for entry in entries}
    stale: list[str] = []
    for item in plan_game_assets(state):
        entry = by_key.get(item.key)
        if entry is None or not _entry_reusable(entry, item.prompt, artifacts):
            stale.append(item.key)
    spec, design = _execution_spec_design(state)
    if _tilemap_wanted_for(state, spec):
        tileset_entry = by_key.get("tileset")
        family = _tilemap_family_entries(entries)
        family_ok = (
            tileset_entry is not None
            and _entry_reusable(tileset_entry, _tileset_prompt(spec, design), artifacts)
            and all(_entry_artifact(entry, artifacts) is not None for entry in family)
        )
        if not family_ok:
            stale.append("tileset")
    return stale


def _append_carried_asset(
    item: PlannedAsset,
    entry: dict,
    artifacts_by_path: dict[str, dict],
    artifacts: list[dict],
    manifest_entries: list[dict],
    asset_trace: list[dict],
    logs: list[str],
    state: dict,
) -> None:
    artifact = _entry_artifact(entry, artifacts_by_path)
    artifacts.append(dict(artifact or {}))
    manifest_entries.append(json.loads(json.dumps(entry)))
    try:
        content = artifact_bytes(artifact)
    except Exception:  # noqa: BLE001 —— trace hashing is best-effort for reuse
        content = b""
    trace = asset_trace_record(
        task_id=state.get("task_id"),
        key=item.key,
        prompt=item.prompt,
        modality=item.modality,
        provider=str(entry.get("provider") or "reused"),
        model=str(entry.get("model") or "reused"),
        content=content,
        requested_states=list(entry.get("requested_states") or []),
        postprocess_checks={"generated": False, "reused": True},
        frame_count=int(entry.get("frame_count") or 0),
        coverage_result={
            "status": "pending",
            "reason": "consumer analysis runs after code generation",
        },
        contract_hash=state.get("contract_hash"),
    )
    trace["output_artifact_id"] = f"output:{entry.get('path')}:{hashlib.sha256(content).hexdigest()[:24]}"
    asset_trace.append(trace)
    logs.append(
        f"{item.key}: reused previously generated {entry.get('kind') or item.modality} (prompt unchanged)"
    )
