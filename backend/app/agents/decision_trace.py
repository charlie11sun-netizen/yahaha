"""Structured provenance helpers for agent decision-chain traces.

The normal task log is intentionally human-readable.  This module provides a
small, JSON-safe contract used by both the SQL trace tables and Opik so a trace
can answer *why* a decision was made, not only which node called which node.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from app.core.config import settings
from app.services.artifacts import artifact_sha256, artifact_text

DECISION_TRACE_SCHEMA_VERSION = "gameweave.agent-decision/1.0"
ASSET_TRACE_SCHEMA_VERSION = "gameweave.asset-generation/1.0"


def json_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:  # noqa: BLE001
        return json.dumps(str(value), ensure_ascii=False)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()


def artifact_id(value: Any, *, namespace: str = "artifact") -> str | None:
    """Return a stable, non-sensitive id for an in-memory artifact/file."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return str(value)
    explicit = value.get("artifact_id") or value.get("asset_id") or value.get("id")
    if explicit:
        return str(explicit)
    path = str(value.get("path") or "")
    try:
        digest = artifact_sha256(value)
    except Exception:  # noqa: BLE001
        digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"{namespace}:{path}:{digest[:24]}" if path else f"{namespace}:{digest[:24]}"


def artifact_ids(values: Any, *, namespace: str = "artifact") -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes, dict)):
        values = [values]
    result: list[str] = []
    for value in values if isinstance(values, Iterable) else [values]:
        item = artifact_id(value, namespace=namespace)
        if item and item not in result:
            result.append(item)
    return result


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


def _output_files(result: dict[str, Any]) -> list[dict]:
    files: list[dict] = []
    for key in ("generated_assets", "generated_files", "project_files", "artifacts"):
        value = result.get(key)
        if isinstance(value, list):
            files.extend(item for item in value if isinstance(item, dict))
    return files


def annotate_asset_consumption(manifest: dict | None, output_files: list[dict]) -> list[dict]:
    """Add deterministic consumer references and coverage to asset entries."""
    if not isinstance(manifest, dict):
        return []
    texts = [(str(item.get("path") or ""), artifact_text(item) or "") for item in output_files]
    annotations: list[dict] = []
    consumed_semantic_ids: set[str] = set()
    demand_manifest = manifest.get("sprite_demand_manifest")
    demand_by_id = {
        str(item.get("semantic_id")): item
        for item in (demand_manifest.get("demands") or [])
        if isinstance(item, dict) and item.get("semantic_id")
    } if isinstance(demand_manifest, dict) else {}
    for entry in manifest.get("assets") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "")
        path = str(entry.get("path") or "")
        frame_names = list((entry.get("frames") or {}).keys()) if isinstance(entry.get("frames"), dict) else []
        semantic_frames = entry.get("semantic_frames") or entry.get("semanticFrames") or {}
        semantic_ids = list(semantic_frames.keys()) if isinstance(semantic_frames, dict) else []
        refs = [
            output_path
            for output_path, text in texts
            if text and any(token and token in text for token in (key, path, *frame_names, *semantic_ids))
        ]
        frame_consumers = {
            semantic_id: [
                output_path
                for output_path, text in texts
                if text
                and any(
                    token and token in text
                    for token in (
                        semantic_id,
                        str(value.get("frame") or "") if isinstance(value, dict) else "",
                        str(value.get("legacy_frame") or "") if isinstance(value, dict) else "",
                    )
                )
            ]
            for semantic_id, value in (semantic_frames.items() if isinstance(semantic_frames, dict) else [])
        }
        required_semantic_ids = [
            semantic_id
            for semantic_id in semantic_ids
            if bool((demand_by_id.get(semantic_id) or {}).get("required", True))
        ]
        covered_required = [semantic_id for semantic_id in required_semantic_ids if frame_consumers.get(semantic_id)]
        consumed_semantic_ids.update(covered_required)
        entry["consumer_refs"] = refs
        if frame_consumers:
            entry["frame_consumers"] = frame_consumers
            entry["unused_required_frame"] = len(required_semantic_ids) - len(covered_required)
        entry["coverage_result"] = {
            "status": "covered" if refs else "uncovered",
            "consumer_count": len(refs),
            "checked_output_files": len(texts),
            "required_asset_coverage": round(len(covered_required) / len(required_semantic_ids), 4)
            if required_semantic_ids
            else (1.0 if not semantic_ids else 0.0),
        }
        annotations.append(
            {
                "asset_id": entry.get("asset_id"),
                "consumer_refs": refs,
                "coverage_result": entry["coverage_result"],
                "runtime_consumed": bool(refs),
                "unused_required_frame": entry.get("unused_required_frame", 0),
            }
        )
    if isinstance(demand_manifest, dict):
        required = [item for item in demand_manifest.get("demands") or [] if isinstance(item, dict) and item.get("required", True)]
        runtime_manifest = demand_manifest.get("runtime_manifest") or {}
        covered = [
            item
            for item in required
            if item.get("semantic_id") in runtime_manifest
            and item.get("semantic_id") in consumed_semantic_ids
        ]
        metrics = dict(demand_manifest.get("metrics") or {})
        metrics["required_asset_coverage"] = round(len(covered) / len(required), 4) if required else 1.0
        metrics["unused_required_frame"] = max(0, len(required) - len(covered))
        demand_manifest["metrics"] = metrics
    return annotations


def build_decision(
    state: dict[str, Any] | None,
    result: dict[str, Any] | None,
    *,
    agent: str,
    display_name: str,
    latency_ms: int = 0,
) -> dict[str, Any]:
    state = state or {}
    result = result or {}
    inputs = artifact_ids(
        result.get("input_artifacts")
        or result.get("input_artifact_ids")
        or result.get("input_artifact_id")
        or state.get("input_artifacts")
        or state.get("asset_ids")
        or state.get("uploaded_assets")
        or state.get("existing_files")
    )
    outputs = artifact_ids(
        result.get("output_artifacts")
        or result.get("output_artifact_ids")
        or result.get("output_artifact_id")
        or _output_files(result),
        namespace="output",
    )
    manifest = result.get("asset_manifest") or state.get("asset_manifest")
    assets = result.get("asset_trace") or state.get("asset_trace") or []
    qa = (
        result.get("qa_result")
        or result.get("gameplay_qa_result")
        or result.get("validation_result")
        or state.get("gameplay_qa_result")
        or state.get("validation_result")
    )
    rejected = (
        result.get("rejected_plans")
        or result.get("rejected_plan")
        or result.get("alternatives_rejected")
        or state.get("rejected_plans")
        or []
    )
    adopted = (
        result.get("adopted_plan")
        or result.get("chosen_plan")
        or result.get("selected_plan")
        or result.get("decision")
        or result.get("archetype_result")
        or result.get("game_spec")
        or result.get("game_design")
        or result.get("asset_manifest")
        or result.get("validation_result")
        or result.get("build_result")
        or state.get("adopted_plan")
        or state.get("archetype_result")
    )
    repair_reason = (
        result.get("repair_reason")
        or result.get("gameplay_qa_feedback")
        or result.get("last_error")
        or result.get("error_message")
        or state.get("repair_reason")
        or state.get("last_error")
    )
    impact = (
        result.get("impact_scope")
        or result.get("affected_modules")
        or result.get("_affected_modules")
        or state.get("impact_scope")
        or [display_name]
    )
    runtime_consumed = result.get("runtime_consumed")
    if runtime_consumed is None and isinstance(manifest, dict):
        annotations = annotate_asset_consumption(manifest, _output_files(result))
        if annotations:
            runtime_consumed = all(item["runtime_consumed"] for item in annotations)
            by_id = {item.get("asset_id"): item for item in annotations if item.get("asset_id")}
            for asset in assets:
                if isinstance(asset, dict) and asset.get("asset_id") in by_id:
                    asset.update(by_id[asset["asset_id"]])
    request_count = result.get("asset_request_count")
    if request_count is None:
        request_count = (
            len(assets) or len(manifest.get("assets") or [])
            if isinstance(manifest, dict)
            else len(assets)
        )
    model = result.get("model") or state.get("model") or settings.CODE_AGENT_MODEL or settings.MODEL_NAME
    provider = result.get("provider") or state.get("provider") or "openai"
    decision = {
        "schema_version": DECISION_TRACE_SCHEMA_VERSION,
        "contract_version": result.get("contract_version") or state.get("contract_version") or "agent-step/v1",
        "prompt_version": result.get("prompt_version") or state.get("prompt_version") or "prompt/v1",
        "agent": agent,
        "display_name": display_name,
        "model": model,
        "provider": provider,
        "input_artifact_ids": inputs,
        "output_artifact_ids": outputs,
        "adopted_plan": adopted,
        "rejected_plans": rejected,
        "asset_request_count": int(request_count or 0),
        "qa_result": qa,
        "repair_reason": repair_reason,
        "impact_scope": impact,
        "latency_ms": int(latency_ms or 0),
        "cost_usd": result.get("cost_usd"),
        "runtime_consumed": runtime_consumed,
        "asset_trace": assets,
    }
    return decision


def asset_trace_record(
    *,
    task_id: str | None,
    key: str,
    prompt: str,
    modality: str,
    provider: str | None,
    model: str | None,
    content: bytes | None,
    requested_states: list[str] | tuple[str, ...] | None = None,
    returned_dimensions: tuple[int, int] | None = None,
    postprocess_checks: dict[str, Any] | None = None,
    frame_count: int = 0,
    consumer_refs: list[str] | None = None,
    coverage_result: Any = None,
) -> dict[str, Any]:
    digest = hashlib.sha256(content or b"").hexdigest()
    return {
        "schema_version": ASSET_TRACE_SCHEMA_VERSION,
        "asset_id": f"generated:{task_id or 'task'}:{key}:{digest[:24]}",
        "key": key,
        "modality": modality,
        "prompt_hash": prompt_hash(prompt),
        "requested_states": list(requested_states or []),
        "returned_dimensions": (
            {"width": int(returned_dimensions[0]), "height": int(returned_dimensions[1])}
            if returned_dimensions
            else None
        ),
        "postprocess_checks": postprocess_checks or {},
        "frame_count": int(frame_count or 0),
        "consumer_refs": list(consumer_refs or []),
        "coverage_result": coverage_result,
        "provider": provider,
        "model": model,
        "output_artifact_id": f"output:assets/{key}:{digest[:24]}",
    }


__all__ = [
    "ASSET_TRACE_SCHEMA_VERSION",
    "DECISION_TRACE_SCHEMA_VERSION",
    "annotate_asset_consumption",
    "artifact_id",
    "artifact_ids",
    "asset_trace_record",
    "build_decision",
    "json_text",
    "prompt_hash",
]
