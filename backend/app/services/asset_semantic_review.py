"""Strict, sheet-level semantic review for generated sprite atlases.

The deterministic sprite audit owns geometry and alpha correctness. This
module adds the missing semantic check ("is this actually the requested
object/state?"). The canonical-sheet review never rewrites or reorders an
atlas; the separate pre-grid layout review may only return source regions for
repacking pixels from the original canvas. Callers must run the deterministic
audit again after either path.

Verdict semantics (第十二轮 2026-07-19 复盘后收紧):

- ``fail`` is only valid with at least one CANONICAL failed check.  Free-form
  check names turned the repair loop into a random walk — the reviewer
  invented "missing_required_health_bar" on one pass and "text_present" on the
  next for the same contract.  Unknown-only failures downgrade to
  ``uncertain``.
- ``uncertain`` is soft: it gets one built-in same-image recheck, and callers
  route persistent uncertainty to the background regeneration queue instead of
  the hard gate.
- ``target_semantic_ids`` scopes a review to repaired cells only, with the
  rest of the sheet locked as identity/style ground truth, so previously
  accepted cells can never flip verdict between repair rounds.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Iterable, Mapping

from app.llm import runtime as llm
from app.core.config import settings
from app.services.sprite_pipeline import (
    BatchSpec,
    SpriteDemandManifest,
    strip_ui_overlay_demands,
)

logger = logging.getLogger(__name__)

SEMANTIC_REVIEW_SCHEMA_VERSION = "asset-semantic-review/v2"
LAYOUT_REVIEW_SCHEMA_VERSION = "asset-layout-review/v1"
_ALLOWED_VERDICTS = {"pass", "fail", "uncertain"}

# A cell may fail ONLY for one of these machine-stable reasons.  The repair
# planner keys off these names; anything outside the set is either a synonym
# (normalized below) or an invented standard that must not gate generation.
CANONICAL_FAILED_CHECKS = (
    "wrong_object",
    "wrong_state",
    "duplicate_cell",
    "identity_drift",
    "style_drift",
    "text_present",
    "multiple_objects",
    "empty_cell",
)

_CHECK_SYNONYMS = {
    "semantic_mismatch": "wrong_object",
    "semantic_match": "wrong_object",
    "wrong_animation_state": "wrong_state",
    "wrong_pose": "wrong_state",
    "duplicate_frame": "duplicate_cell",
    "duplicate_idle_pose": "duplicate_cell",
    "duplicate_of_another_requested_cell": "duplicate_cell",
    "character_identity_mismatch": "identity_drift",
    "missing_character_features": "identity_drift",
    "cross_cell_drift": "identity_drift",
    "cross_cell_ui_drift": "style_drift",
    "inconsistent_style": "style_drift",
    "text": "text_present",
    "watermark": "text_present",
    "watermark_present": "text_present",
    "ui_overlay_present": "text_present",
    "multiple_unrelated_objects": "multiple_objects",
    "blank_cell": "empty_cell",
}


def _canonical_check(name: Any) -> str | None:
    """Map a reported check name into the closed rubric, or drop it."""

    value = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not value:
        return None
    if value in CANONICAL_FAILED_CHECKS:
        return value
    if value in _CHECK_SYNONYMS:
        return _CHECK_SYNONYMS[value]
    # "missing_<feature>" demands (health bars, banners, props) are exactly the
    # invented standards the closed rubric exists to reject.
    if value.startswith("missing_"):
        return None
    if "duplicate" in value or "same_as" in value:
        return "duplicate_cell"
    if "watermark" in value or "caption" in value or "label" in value or "text" in value:
        return "text_present"
    if "style" in value:
        return "style_drift"
    if "identity" in value or "drift" in value or "inconsisten" in value:
        return "identity_drift"
    if "animation" in value or "state" in value or "pose" in value:
        return "wrong_state"
    if "empty" in value or "blank" in value:
        return "empty_cell"
    if "multiple" in value or "extra_object" in value or "crowd" in value:
        return "multiple_objects"
    if "wrong" in value or "mismatch" in value or "incorrect" in value:
        return "wrong_object"
    return None


_REVIEW_SYSTEM = """You are a strict sprite-atlas semantic auditor.
Review the supplied spritesheet against the supplied cell contract. The grid
and frame_index are authoritative: never reorder cells, invent a semantic id,
or infer that a wrong object is acceptable because it looks attractive. Judge
each requested cell independently, while using the full sheet to catch
duplicates, identity drift, and inconsistent style.

A cell FAILS only for one of these canonical reasons; failed_checks must use
these exact names:
- wrong_object: the cell shows a different object than requested
- wrong_state: right object, but the wrong animation state or pose
- duplicate_cell: near-duplicate of another requested cell that must differ
- identity_drift: the character's face/hair/outfit/colors do not match the
  same character elsewhere in the sheet
- style_drift: rendering style inconsistent with the rest of the sheet
- text_present: any baked-in text, digits, caption, watermark, or UI overlay
- multiple_objects: more subjects than expected_object_count
- empty_cell: nothing recognizable is drawn

HUD/UI overlays (health bars, resistance banners, name labels, status text,
damage numbers) are rendered by the game engine at runtime, never inside
sprite artwork. If a cell description asks for such an overlay, IGNORE that
part of the description: its absence is NEVER a failure, and its presence IS a
text_present failure.

Return only JSON with this shape:
{
  "sheet_verdict": "pass" | "fail" | "uncertain",
  "cells": [
    {
      "semantic_id": "...",
      "frame_index": 0,
      "verdict": "pass" | "fail" | "uncertain",
      "observed_category": "short description",
      "confidence": 0.0,
      "failed_checks": ["wrong_object"],
      "repair_prompt": "short instruction for regenerating only this cell"
    }
  ]
}

Use pass only when the expected object and state are clearly visible. Use
uncertain when the image is ambiguous, cropped, or too small to identify —
never use fail for a reason outside the canonical list. Do not return image
bytes or replacement artwork."""


_LAYOUT_REVIEW_SYSTEM = """You are a strict sprite-sheet layout and semantic auditor.
The supplied image is the ORIGINAL provider canvas, before any fixed grid
resize or slicing. The provider may have drawn the requested sprites in the
wrong cells, with uneven spacing, or without a reliable grid. Locate each
requested semantic object/state anywhere in the full image and return the
source region that should be repacked into its target frame.

Do not regenerate, redraw, or invent artwork. Do not use the target frame
index as evidence that an object is there. Each requested semantic_id must be
returned at most once. source_bbox is normalized to the complete image as
[x0, y0, x1, y1] with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1. It should
enclose the complete visible sprite, with only a small amount of surrounding
background. Use source_frame_index only when a regular source grid is clearly
present; source_bbox remains mandatory.

Return only JSON with this shape:
{
  "sheet_verdict": "pass" | "resegment" | "fail" | "uncertain",
  "cells": [
    {
      "semantic_id": "...",
      "target_frame_index": 0,
      "source_frame_index": 0,
      "source_bbox": [0.0, 0.0, 0.25, 0.25],
      "verdict": "pass" | "fail" | "uncertain",
      "observed_category": "short description",
      "confidence": 0.0,
      "failed_checks": ["layout_mismatch"],
      "repair_prompt": "short instruction if the object is missing or wrong"
    }
  ]
}

Use pass only when the requested object/state is clearly identifiable and the
source_bbox is a usable one-to-one crop. Use uncertain for ambiguity, a crop
that contains multiple requested objects, or a missing bbox. A wrong object,
duplicate, text/watermark, or missing requested state is a failure."""


class AssetSemanticReviewError(RuntimeError):
    """The required semantic review could not produce a trustworthy verdict."""


def _clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _coerce_frame_index(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if any(item < 0.0 or item > 1.0 for item in values):
        return None
    x0, y0, x1, y1 = values
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    return [round(item, 6) for item in values]


def _review_metadata(demand_metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Sanitize contract metadata so it cannot demand baked-in UI overlays."""

    metadata = dict(demand_metadata)
    for key in ("description", "meta"):
        if metadata.get(key):
            metadata[key] = strip_ui_overlay_demands(metadata[key])
    return metadata


def _review_context(manifest: SpriteDemandManifest, batch: BatchSpec) -> list[dict[str, Any]]:
    by_id = manifest.by_semantic_id
    cells: list[dict[str, Any]] = []
    for index, semantic_id in enumerate(batch.semantic_ids):
        demand = by_id.get(semantic_id)
        if demand is None:
            continue
        cells.append(
            {
                "semantic_id": demand.semantic_id,
                "frame_index": index,
                "grid": {
                    "row": index // batch.columns,
                    "column": index % batch.columns,
                },
                "expected": {
                    "object_name": demand.object_name,
                    "state": demand.state,
                    "expected_object_count": demand.expected_object_count,
                    "anchor": list(demand.anchor),
                    "style_group": demand.style_group,
                    "required": demand.required,
                    "metadata": _review_metadata(demand.metadata),
                },
            }
        )
    return cells


def _normalize_verdict(raw: Any, expected: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raw = {}
    semantic_id = str(raw.get("semantic_id") or expected.get("semantic_id") or "")
    verdict = str(raw.get("verdict") or "uncertain").strip().lower()
    if verdict not in _ALLOWED_VERDICTS:
        verdict = "uncertain"
    confidence = _clamp_confidence(raw.get("confidence"))
    if verdict == "pass" and confidence < float(settings.ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE):
        verdict = "uncertain"
    reported_checks = [str(item)[:120] for item in (raw.get("failed_checks") or [])[:8]]
    failed_checks: list[str] = []
    for item in reported_checks:
        mapped = _canonical_check(item)
        if mapped and mapped not in failed_checks:
            failed_checks.append(mapped)
    if verdict == "fail" and not failed_checks:
        # The reviewer could not express the failure inside the closed rubric
        # (e.g. a "missing_required_health_bar" style invented standard).  Such
        # a verdict must not gate generation; the recheck pass gets one chance
        # to reclassify it.
        verdict = "uncertain"
    if verdict != "pass" and not failed_checks:
        failed_checks = ["semantic_uncertain"]
    return {
        "semantic_id": semantic_id,
        "frame_index": _coerce_frame_index(
            raw.get("frame_index") if raw.get("frame_index") is not None else expected.get("frame_index", -1)
        ),
        "verdict": verdict,
        "observed_category": str(raw.get("observed_category") or "unknown")[:240],
        "confidence": confidence,
        "failed_checks": failed_checks,
        "reported_checks": reported_checks,
        "repair_prompt": str(raw.get("repair_prompt") or "")[:600],
    }


def _accepted_reference_lines(accepted_context: Mapping[str, Any] | None) -> str:
    if not accepted_context:
        return ""
    entries = [
        {"semantic_id": str(key), "observed": str(value)[:120]}
        for key, value in list(accepted_context.items())[:24]
        if str(value or "").strip()
    ]
    if not entries:
        return ""
    return (
        "Accepted reference cells (identity and style ground truth):\n"
        + json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    )


def _review_pass(
    content: bytes,
    batch: BatchSpec,
    expected_cells: list[dict[str, Any]],
    *,
    scoped: bool,
    accepted_context: Mapping[str, Any] | None,
    recheck: bool,
) -> dict[str, dict[str, Any]]:
    """One VLM pass over ``expected_cells``; returns verdicts keyed by id."""

    expected_by_id = {str(item["semantic_id"]): item for item in expected_cells}
    scope_lines = ""
    if scoped:
        scope_lines = (
            "Judge ONLY the cells listed in the contract below. Every other cell "
            "in the image is already accepted and locked: use locked cells as "
            "identity and style ground truth, report duplicate_cell if a judged "
            "cell duplicates a locked cell that must differ, and never report "
            "locked cells themselves.\n"
        )
    if recheck:
        scope_lines += (
            "This is a one-time verification recheck of previously uncertain "
            "cells. Decide pass or fail wherever the artwork allows it.\n"
        )
    prompt = (
        "Audit this complete spritesheet. The image is a strict "
        f"{batch.columns}x{batch.rows} grid of {batch.cell_width}x{batch.cell_height} cells.\n"
        + scope_lines
        + _accepted_reference_lines(accepted_context)
        + "Cell contract (semantic_id and frame_index are immutable):\n"
        + json.dumps(expected_cells, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        result = llm.chat(
            _REVIEW_SYSTEM,
            prompt,
            model=settings.ASSET_SEMANTIC_REVIEW_MODEL or None,
            timeout=settings.ASSET_SEMANTIC_REVIEW_TIMEOUT_SECONDS,
            response_format={"type": "json_object"},
            images_b64=[base64.b64encode(content).decode("ascii")],
        )
        payload = json.loads(result.text)
    except Exception as exc:  # noqa: BLE001 - this is a hard asset gate
        raise AssetSemanticReviewError(
            f"{batch.batch_id}: semantic review unavailable: {str(exc)[:220]}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AssetSemanticReviewError(f"{batch.batch_id}: semantic review returned a non-object payload")

    returned: dict[str, dict[str, Any]] = {}
    for raw in payload.get("cells") or []:
        raw_mapping = raw if isinstance(raw, Mapping) else {}
        item = _normalize_verdict(
            raw_mapping,
            expected_by_id.get(str(raw_mapping.get("semantic_id") or ""), {}),
        )
        if item["semantic_id"] in expected_by_id and item["semantic_id"] not in returned:
            returned[item["semantic_id"]] = item
    return returned


def review_spritesheet(
    content: bytes,
    manifest: SpriteDemandManifest | Mapping[str, Any],
    batch: BatchSpec,
    *,
    attempt: int = 1,
    target_semantic_ids: Iterable[str] | None = None,
    accepted_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Review a sheet (or a locked-sheet subset) with normalized verdicts.

    Review transport/parsing failures are hard failures.  There is no
    fail-open path here: a required frame cannot enter code generation without
    an auditable semantic result.  Uncertain verdicts get one built-in recheck
    on the same image; persistent uncertainty stays soft for the caller.
    """

    if not settings.ASSET_SEMANTIC_REVIEW_ENABLED:
        return {
            "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
            "enabled": False,
            "status": "disabled",
            "passed": True,
            "attempt": attempt,
            "frames": [],
            "failed_frame_ids": [],
            "uncertain_frame_ids": [],
        }

    manifest = manifest if isinstance(manifest, SpriteDemandManifest) else SpriteDemandManifest.from_dict(manifest)
    all_cells = _review_context(manifest, batch)
    targets = (
        {str(item) for item in target_semantic_ids}
        if target_semantic_ids is not None
        else None
    )
    expected_cells = (
        [item for item in all_cells if item["semantic_id"] in targets]
        if targets is not None
        else all_cells
    )
    expected_by_id = {str(item["semantic_id"]): item for item in expected_cells}
    if not expected_cells:
        raise AssetSemanticReviewError(f"{batch.batch_id}: semantic review has no expected cells")

    scoped = targets is not None
    returned = _review_pass(
        content,
        batch,
        expected_cells,
        scoped=scoped,
        accepted_context=accepted_context,
        recheck=False,
    )

    frames: list[dict[str, Any]] = []
    for expected in expected_cells:
        semantic_id = str(expected["semantic_id"])
        item = returned.get(semantic_id)
        if item is None:
            item = _normalize_verdict(
                {
                    "semantic_id": semantic_id,
                    "frame_index": expected["frame_index"],
                    "verdict": "uncertain",
                    "failed_checks": ["missing_review"],
                },
                expected,
            )
        frames.append(item)

    required_ids = {
        demand.semantic_id for demand in manifest.required if demand.semantic_id in expected_by_id
    }

    # One built-in recheck: uncertainty must survive two independent looks at
    # the same pixels before the caller treats it as a soft defect.
    recheck_used = False
    uncertain_ids = [
        frame["semantic_id"]
        for frame in frames
        if frame["semantic_id"] in required_ids and frame["verdict"] == "uncertain"
    ]
    if uncertain_ids:
        recheck_cells = [item for item in expected_cells if item["semantic_id"] in set(uncertain_ids)]
        try:
            rechecked = _review_pass(
                content,
                batch,
                recheck_cells,
                scoped=True,
                accepted_context=accepted_context,
                recheck=True,
            )
            recheck_used = True
            frames = [rechecked.get(frame["semantic_id"], frame) for frame in frames]
        except AssetSemanticReviewError as exc:
            logger.warning("%s: uncertain recheck unavailable: %s", batch.batch_id, exc)

    failed_frame_ids = [
        frame["semantic_id"]
        for frame in frames
        if frame["semantic_id"] in required_ids and frame["verdict"] == "fail"
    ]
    uncertain_frame_ids = [
        frame["semantic_id"]
        for frame in frames
        if frame["semantic_id"] in required_ids and frame["verdict"] == "uncertain"
    ]
    passed = not failed_frame_ids and not uncertain_frame_ids
    return {
        "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
        "enabled": True,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "sheet_verdict": "pass" if passed else "fail",
        "attempt": attempt,
        "model": settings.ASSET_SEMANTIC_REVIEW_MODEL or settings.MODEL_NAME,
        "min_confidence": float(settings.ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE),
        "scoped": scoped,
        "target_semantic_ids": sorted(targets) if targets is not None else None,
        "recheck_used": recheck_used,
        "frames": frames,
        "failed_frame_ids": failed_frame_ids,
        "uncertain_frame_ids": uncertain_frame_ids,
    }


def review_spritesheet_layout(
    content: bytes,
    manifest: SpriteDemandManifest | Mapping[str, Any],
    batch: BatchSpec,
    *,
    attempt: int = 1,
) -> dict[str, Any]:
    """Locate semantic sprites in the original canvas before fixed-grid slicing."""

    if not settings.ASSET_SEMANTIC_REVIEW_ENABLED:
        return {
            "schema_version": LAYOUT_REVIEW_SCHEMA_VERSION,
            "enabled": False,
            "status": "disabled",
            "passed": True,
            "attempt": attempt,
            "frames": [],
            "failed_frame_ids": [],
            "uncertain_frame_ids": [],
        }

    manifest = manifest if isinstance(manifest, SpriteDemandManifest) else SpriteDemandManifest.from_dict(manifest)
    expected_cells = _review_context(manifest, batch)
    expected_by_id = {str(item["semantic_id"]): item for item in expected_cells}
    if not expected_cells:
        raise AssetSemanticReviewError(f"{batch.batch_id}: layout review has no expected cells")
    prompt = (
        "Audit this complete ORIGINAL spritesheet before fixed-grid slicing. "
        "The target atlas is a canonical "
        f"{batch.columns}x{batch.rows} grid of {batch.cell_width}x{batch.cell_height} cells, "
        "but the source image's objects may be misplaced. Return a source_bbox "
        "for every requested semantic id.\n"
        "Target semantic contract (target_frame_index is only the destination):\n"
        + json.dumps(
            [
                {
                    **item,
                    "target_frame_index": item["frame_index"],
                    "frame_index": None,
                }
                for item in expected_cells
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    try:
        result = llm.chat(
            _LAYOUT_REVIEW_SYSTEM,
            prompt,
            model=settings.ASSET_SEMANTIC_REVIEW_MODEL or None,
            timeout=settings.ASSET_SEMANTIC_REVIEW_TIMEOUT_SECONDS,
            response_format={"type": "json_object"},
            images_b64=[base64.b64encode(content).decode("ascii")],
        )
        payload = json.loads(result.text)
    except Exception as exc:  # noqa: BLE001 - this is a hard asset gate
        raise AssetSemanticReviewError(
            f"{batch.batch_id}: layout review unavailable: {str(exc)[:220]}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AssetSemanticReviewError(f"{batch.batch_id}: layout review returned a non-object payload")

    returned: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    for raw in payload.get("cells") or []:
        raw_mapping = raw if isinstance(raw, Mapping) else {}
        semantic_id = str(raw_mapping.get("semantic_id") or "")
        if semantic_id not in expected_by_id:
            continue
        if semantic_id in returned:
            duplicate_ids.append(semantic_id)
            continue
        verdict = str(raw_mapping.get("verdict") or "uncertain").strip().lower()
        if verdict not in _ALLOWED_VERDICTS:
            verdict = "uncertain"
        confidence = _clamp_confidence(raw_mapping.get("confidence"))
        if verdict == "pass" and confidence < float(settings.ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE):
            verdict = "uncertain"
        source_bbox = _normalize_bbox(raw_mapping.get("source_bbox"))
        failed_checks = [str(item)[:120] for item in (raw_mapping.get("failed_checks") or [])[:8]]
        if verdict == "pass" and source_bbox is None:
            verdict = "uncertain"
            failed_checks = list(dict.fromkeys(["missing_source_bbox", *failed_checks]))
        if verdict != "pass" and not failed_checks:
            failed_checks = ["layout_mismatch" if verdict == "fail" else "layout_uncertain"]
        expected = expected_by_id[semantic_id]
        returned[semantic_id] = {
            "semantic_id": semantic_id,
            "frame_index": int(expected["frame_index"]),
            "target_frame_index": int(expected["frame_index"]),
            "source_frame_index": _coerce_frame_index(raw_mapping.get("source_frame_index"), -1),
            "source_bbox": source_bbox,
            "verdict": verdict,
            "observed_category": str(raw_mapping.get("observed_category") or "unknown")[:240],
            "confidence": confidence,
            "failed_checks": failed_checks,
            "repair_prompt": str(raw_mapping.get("repair_prompt") or "")[:600],
        }

    frames: list[dict[str, Any]] = []
    for expected in expected_cells:
        semantic_id = str(expected["semantic_id"])
        item = returned.get(semantic_id)
        if item is None:
            item = {
                "semantic_id": semantic_id,
                "frame_index": int(expected["frame_index"]),
                "target_frame_index": int(expected["frame_index"]),
                "source_frame_index": -1,
                "source_bbox": None,
                "verdict": "uncertain",
                "observed_category": "unknown",
                "confidence": 0.0,
                "failed_checks": ["missing_layout_mapping"],
                "repair_prompt": "locate the requested sprite in the original sheet",
            }
        frames.append(item)

    required_ids = {demand.semantic_id for demand in manifest.required if demand.semantic_id in expected_by_id}
    failed_frame_ids = [
        frame["semantic_id"]
        for frame in frames
        if frame["semantic_id"] in required_ids and frame["verdict"] == "fail"
    ]
    uncertain_frame_ids = [
        frame["semantic_id"]
        for frame in frames
        if frame["semantic_id"] in required_ids and frame["verdict"] != "pass"
    ]
    mapping_complete = all(
        frame["verdict"] == "pass" and frame.get("source_bbox") for frame in frames
    )
    passed = not duplicate_ids and mapping_complete
    return {
        "schema_version": LAYOUT_REVIEW_SCHEMA_VERSION,
        "enabled": True,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "sheet_verdict": str(payload.get("sheet_verdict") or ("pass" if passed else "resegment")),
        "attempt": attempt,
        "model": settings.ASSET_SEMANTIC_REVIEW_MODEL or settings.MODEL_NAME,
        "min_confidence": float(settings.ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE),
        "frames": frames,
        "failed_frame_ids": failed_frame_ids,
        "uncertain_frame_ids": uncertain_frame_ids,
        "duplicate_mapping_ids": duplicate_ids,
        "mapping_complete": mapping_complete,
    }


__all__ = [
    "AssetSemanticReviewError",
    "CANONICAL_FAILED_CHECKS",
    "LAYOUT_REVIEW_SCHEMA_VERSION",
    "SEMANTIC_REVIEW_SCHEMA_VERSION",
    "review_spritesheet",
    "review_spritesheet_layout",
]
