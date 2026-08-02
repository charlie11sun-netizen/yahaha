"""Game-specific asset planning and generation orchestration.

Visual assets are planned as semantic frame demands, then consolidated into
homogeneous sprite SHEET batches (strict 4x4 grids of 256px cells for legacy
Phaser compatibility) plus a small set of scene BACKGROUND variants and, for
tile-friendly archetypes, an environment tileset rendered in the same style.
The provider owns visual content; the program owns cell slicing, audits,
packing, and the semantic runtime manifest. Unused grid slots are transparent
non-assets and never enter the formal demand manifest.

Every actor is planned as a FRAME GROUP: the player gets an idle/move/action
core plus design-driven skill poses (up to 5 abilities), hurt/jump/death/
victory poses; enemies get attack and movement frames (bosses additionally a
special-skill frame); items get an activated frame.
Core cells (one per designed entity) are budgeted first, then remaining
capacity upgrades actors into animation frames by priority. A group's frames
never straddle pages — Phaser animations require all frames on one texture.
Rosters overflow onto "sheet-2", "sheet-3"… (capped at
settings.ASSET_SHEET_MAX_PAGES); pages are generated CONCURRENTLY
(settings.ASSET_GENERATION_CONCURRENCY, default 2 parallel image calls).

Image models reached through OpenAI-compatible gateways often ignore the
transparent-background parameter and paint a fake checkerboard instead, and may
return off-size canvases. `_postprocess_spritesheet` therefore normalizes each
sheet server-side: resize to the exact grid, then recover real transparency by
chroma-keying the solid magenta backdrop we prompt for (falling back to a
border-connected flood fill for light/checkerboard backdrops).
"""
from __future__ import annotations

import contextvars
import io
import json
import logging
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from app.core.config import settings
from app.generation.design_contract import (
    contract_to_design_payload,
    contract_to_spec_payload,
    derive_sprite_demand_manifest,
)
from app.observability import opik_integration
from app.observability.decision_trace import asset_trace_record
from app.services.artifacts import artifact_bytes, binary_artifact
from app.services.asset_semantic_review import (
    AssetSemanticReviewError,
    review_spritesheet,
    review_spritesheet_layout,
)
from app.services.provider_router import (
    MediaRequest,
    ProviderConfigurationError,
    ProviderGenerationError,
    ProviderRouter,
    ProviderStreamProtocolError,
)
from app.services.tilemaps import (
    TILESET_GRID,
    TILESET_IMAGE_SIZE,
    generate_tilemap_artifacts,
)
from app.services.sprite_pipeline import (
    BatchSpec,
    SpriteDemand,
    SpriteDemandManifest,
    build_cell_regeneration_specs,
    build_sprite_demand_manifest,
    strip_ui_overlay_demands,
)

# ── 拆分兼容面(2026-07-26)──────────────────────────────────────────────
# 规划(asset_planning)、像素后处理(asset_postprocess)、复用门禁
# (asset_reuse)已按职责拆入独立模块;这里显式回导,既是编排的真实依赖,也
# 保持既有调用方/测试从本模块导入(含下划线名)的契约不变。monkeypatch 打在
# 本模块上的 _audit_sheet_frames / review_spritesheet(_layout) /
# _transparent_param_unsupported 仍然生效:它们的全部调用方都留在本模块,按
# 模块全局名解析。
from app.services.asset_planning import (  # noqa: F401 —— 兼容回导
    SHEET_CELL,
    SHEET_GRID,
    SHEET_SIZE,
    AssetGenerationRetryRequired,
    PlannedAsset,
    SheetCell,
    _cell_demand,
    _clip_text,
    _layout_brief,
    _sheet_manifest_extra,
    _tileset_prompt,
    design_obstacles,
    plan_game_assets,
)
from app.services.asset_postprocess import (  # noqa: F401 —— 兼容回导
    _BG_MIN_LUMA,
    _audit_sheet_frames,
    _compress_image_asset,
    _normalize_repair_cell,
    _normalize_spritesheet_canvas,
    _postprocess_background,
    _postprocess_spritesheet,
    _postprocess_tileset,
    _resegment_spritesheet,
)
from app.services.asset_reuse import (  # noqa: F401 —— 兼容回导
    _append_carried_asset,
    _artifacts_by_path,
    _entry_artifact,
    _generated_manifest_entries,
    _tilemap_family_entries,
    _tilemap_wanted_for,
    stale_planned_keys,
)

logger = logging.getLogger(__name__)


def _merge_semantic_review_into_audit(audit: dict, semantic_review: dict) -> dict:
    """Fold semantic verdicts into the frame audit.

    fail → hard frame failure (feeds the repair loop and the release gate).
    uncertain → soft defect: recorded in ``soft_frame_ids`` for the background
    regeneration queue, never a hard failure. 第十二轮(2026-07-19)教训:
    uncertain 当硬失败 + 低置信度降 uncertain 的组合让 16 格全过的概率结构性
    偏低,把重试从兜底变成了标准流程。
    """

    review_by_id = {
        str(item.get("semantic_id")): item
        for item in (semantic_review.get("frames") or [])
        if isinstance(item, dict) and item.get("semantic_id")
    }
    soft_frame_ids: list[str] = []
    for frame in audit.get("frames") or []:
        if not frame.get("required", True):
            continue
        review = review_by_id.get(str(frame.get("semantic_id")))
        if review is None:
            continue
        frame["semantic_review"] = review
        verdict = str(review.get("verdict") or "uncertain")
        frame["checks"]["semantic_match"] = verdict == "pass"
        if verdict == "pass" and "single_expected_object" in (frame.get("failed_checks") or []):
            # 语义评审能区分"一个主体+挥砍特效/粒子"与"两个主体",像素连通域
            # 计数不能——后者的误报曾把 7 个健康格推进修复循环(2026-07-19
            # 像素防线)。语义 pass 时该项以 VLM 为准;尺寸/越界/透明底等几何
            # 检查仍由确定性审计一票否决。
            frame["failed_checks"] = [
                check for check in frame["failed_checks"] if check != "single_expected_object"
            ]
            frame["checks"]["single_expected_object"] = True
            frame["checks"]["single_expected_object_overridden"] = True
            if not frame["failed_checks"]:
                frame["passed"] = True
        if verdict == "fail":
            frame["failed_checks"] = list(
                dict.fromkeys(
                    [
                        *list(review.get("failed_checks") or []),
                        "semantic_match",
                        *list(frame.get("failed_checks") or []),
                    ]
                )
            )
            frame["passed"] = False
        elif verdict == "uncertain":
            frame["soft_checks"] = list(
                dict.fromkeys(list(review.get("failed_checks") or []) or ["semantic_uncertain"])
            )
            if frame.get("passed"):
                soft_frame_ids.append(str(frame.get("semantic_id")))
    required = [
        frame
        for frame in (audit.get("frames") or [])
        if frame.get("required", True)
    ]
    passed_required = [frame for frame in required if frame.get("passed")]
    audit["failed_frame_ids"] = [
        str(frame.get("semantic_id")) for frame in required if not frame.get("passed")
    ]
    audit["soft_frame_ids"] = soft_frame_ids
    audit["required_asset_coverage"] = round(
        len(passed_required) / len(required), 4
    ) if required else 1.0
    audit["passed"] = not audit["failed_frame_ids"]
    return audit


def _regeneration_plan_audit(frame_audit: dict) -> dict:
    """Audit view for the background regeneration queue.

    带伤放行的失败格和 uncertain 软缺陷格都要排进 regeneration_plan;软缺陷
    格在硬门禁里算通过,但作为补射对象时不能拿自己当参照,故在这个视图里
    翻成失败。
    """

    soft_ids = {str(value) for value in (frame_audit.get("soft_frame_ids") or [])}
    if not soft_ids:
        return frame_audit
    frames = []
    for frame in frame_audit.get("frames") or []:
        if str(frame.get("semantic_id")) in soft_ids:
            frame = {
                **frame,
                "passed": False,
                "failed_checks": list(frame.get("soft_checks") or ["semantic_uncertain"]),
            }
        frames.append(frame)
    return {
        **frame_audit,
        "frames": frames,
        "failed_frame_ids": [
            *[str(value) for value in (frame_audit.get("failed_frame_ids") or [])],
            *sorted(soft_ids),
        ],
    }


def _sheet_regen_prompt(item: PlannedAsset, audit: dict, review: dict) -> str:
    """Full-sheet correction prompt carrying the failed-cell feedback.

    2026-07-20 用户定调:修复不做单格重画——成本按失败格数倍增(第二跑一轮
    烧了 8 次图像调用)。整表重掷每轮固定 1 次图像调用,与旧表逐格择优合成;
    同表重画天然保持角色身份一致,替代文字身份锚定。UI 覆盖物提示照旧剥离。
    """

    review_by_id = {
        str(frame.get("semantic_id")): frame
        for frame in (review.get("frames") or [])
        if isinstance(frame, dict) and frame.get("semantic_id")
    }
    frames_by_id = {
        str(frame.get("semantic_id")): frame
        for frame in (audit.get("frames") or [])
        if isinstance(frame, dict) and frame.get("semantic_id")
    }
    issues: list[str] = []
    for semantic_id in [str(value) for value in (audit.get("failed_frame_ids") or [])][:8]:
        checks = ", ".join(
            str(check) for check in (frames_by_id.get(semantic_id, {}).get("failed_checks") or [])[:3]
        )
        hint = strip_ui_overlay_demands(
            (review_by_id.get(semantic_id) or {}).get("repair_prompt") or ""
        )
        entry = f"{semantic_id}: {checks or 'wrong content'}"
        if hint:
            entry += f" — {_clip_text(hint, 70)}"
        issues.append(entry)
    return " ".join(
        [
            item.prompt,
            "CORRECTION PASS: the previous canvas failed review for these cells:",
            "; ".join(issues) + ".",
            "Redraw the FULL sheet with the same layout and art style.",
            "Every listed cell must clearly show its required object/state,",
            "adjacent animation frames must be visibly different poses,",
            "and every frame of one actor must keep the same character identity.",
        ]
    )


def _slice_sheet_canvas(
    raw_content: bytes,
    content_type: str,
    item: PlannedAsset,
    review_manifest: SpriteDemandManifest,
    source_batch: BatchSpec,
    logs: list[str],
) -> tuple[bytes, dict, dict]:
    """Normalize one provider canvas and slice it into the canonical atlas.

    初始画布与修复轮的整表重掷共用这条路径:布局评审→(混合)重切;评审不可
    用或映射不全时逐级退回网格切割,绝不在切割环节暂停任务。
    """

    layout_review: dict = {
        "schema_version": "asset-layout-review/v1",
        "enabled": False,
        "status": "disabled",
        "passed": True,
        "frames": [],
        "failed_frame_ids": [],
        "uncertain_frame_ids": [],
    }
    layout_repack: dict = {"resegmented": False}
    if not settings.ASSET_SEMANTIC_REVIEW_ENABLED:
        return _postprocess_spritesheet(raw_content, content_type), layout_review, layout_repack
    # Preserve the provider's original geometry for semantic discovery. The
    # old path resized first, making a wrong source grid impossible to
    # recover deterministically.
    source_image = _normalize_spritesheet_canvas(raw_content, content_type)
    source_out = io.BytesIO()
    source_image.save(source_out, format="PNG")
    source_layout_content = source_out.getvalue()
    review_error: Exception | None = None
    for layout_attempt in range(
        1, max(1, min(4, int(settings.ASSET_SEMANTIC_REVIEW_MAX_RETRIES) + 1)) + 1
    ):
        try:
            layout_review = review_spritesheet_layout(
                source_layout_content,
                review_manifest,
                source_batch,
                attempt=layout_attempt,
            )
            review_error = None
            break
        except AssetSemanticReviewError as exc:
            review_error = exc
            logs.append(
                f"{item.key}: layout review attempt {layout_attempt} failed; retrying audit"
            )
    if review_error is not None:
        logs.append(
            f"{item.key}: layout review unavailable ({_clip_text(review_error, 140)}); "
            "falling back to fixed-grid slicing"
        )
        return (
            _postprocess_spritesheet(raw_content, content_type),
            {
                "enabled": True,
                "passed": False,
                "status": "unavailable",
                "error": _clip_text(review_error, 200),
            },
            {"resegmented": False, "fallback": "fixed_grid"},
        )
    canonical_index_by_semantic = {
        _cell_demand(cell).semantic_id: index
        for index, cell in enumerate(item.sheet_cells)
        if not cell.name.startswith("bonus_")
    }
    for layout_frame in layout_review.get("frames") or []:
        semantic_id = str(layout_frame.get("semantic_id") or "")
        if semantic_id in canonical_index_by_semantic:
            # The review prompt uses a compact semantic list; translate it to
            # the real atlas index in case a page contains unused bonus slots.
            layout_frame["target_frame_index"] = canonical_index_by_semantic[semantic_id]
            layout_frame["frame_index"] = canonical_index_by_semantic[semantic_id]
    if not layout_review.get("passed"):
        # 部分映射照用:扔掉 pass 格的 bbox 整表固定切割,曾把 14/16 已映射
        # 好的格连带切坏(2026-07-20 第二跑,coverage 0.25)。
        unmapped = list(
            layout_review.get("failed_frame_ids")
            or layout_review.get("uncertain_frame_ids")
            or []
        )
        try:
            content, layout_repack = _resegment_spritesheet(
                source_layout_content,
                item.sheet_cells,
                layout_review,
                hybrid_fill=True,
            )
        except AssetGenerationRetryRequired as exc:
            logs.append(
                f"{item.key}: hybrid re-segmentation unavailable ({_clip_text(exc, 140)}); "
                "falling back to fixed-grid slicing"
            )
            return (
                _postprocess_spritesheet(raw_content, content_type),
                layout_review,
                {"resegmented": False, "fallback": "fixed_grid"},
            )
        hybrid_ids = list(layout_repack.get("hybrid_cell_ids") or [])
        logs.append(
            f"{item.key}: layout mapping incomplete "
            f"({', '.join(str(value) for value in unmapped[:6]) or 'unknown'}); "
            f"hybrid re-segmentation kept "
            f"{len(layout_repack.get('frames') or []) - len(hybrid_ids)} mapped region(s), "
            f"{len(hybrid_ids)} grid-filled cell(s)"
        )
        return content, layout_review, layout_repack
    try:
        content, layout_repack = _resegment_spritesheet(
            source_layout_content,
            item.sheet_cells,
            layout_review,
        )
    except AssetGenerationRetryRequired as exc:
        logs.append(
            f"{item.key}: re-segmentation unavailable ({_clip_text(exc, 140)}); "
            "falling back to fixed-grid slicing"
        )
        return (
            _postprocess_spritesheet(raw_content, content_type),
            layout_review,
            {"resegmented": False, "fallback": "fixed_grid"},
        )
    logs.append(
        f"{item.key}: semantic layout review re-segmented "
        f"{len(layout_repack.get('frames') or [])} source regions before grid packing"
    )
    return content, layout_review, layout_repack


def _semantic_review_with_retry(
    content: bytes,
    review_manifest: SpriteDemandManifest,
    source_batch: BatchSpec,
    logs: list[str],
    key: str,
    *,
    target_semantic_ids: tuple[str, ...] | None = None,
    accepted_context: dict[str, str] | None = None,
) -> dict:
    """Run the semantic review with bounded transport retries."""

    attempts = max(1, min(4, int(settings.ASSET_SEMANTIC_REVIEW_MAX_RETRIES) + 1))
    review_error: Exception | None = None
    for review_attempt in range(1, attempts + 1):
        try:
            return review_spritesheet(
                content,
                review_manifest,
                source_batch,
                attempt=review_attempt,
                target_semantic_ids=target_semantic_ids,
                accepted_context=accepted_context,
            )
        except AssetSemanticReviewError as exc:
            review_error = exc
            logs.append(f"{key}: semantic review attempt {review_attempt} failed; retrying audit")
    assert review_error is not None
    raise review_error


def _merge_scoped_review(previous: dict, scoped: dict, required_ids: set[str]) -> dict:
    """Merge a scoped re-review into the running full-sheet review state.

    Only the re-reviewed cells change verdict; every other cell keeps its
    locked result, so a repair round can never un-pass an untouched frame.
    """

    frames_by_id = {
        str(frame.get("semantic_id")): dict(frame)
        for frame in (previous.get("frames") or [])
        if frame.get("semantic_id")
    }
    for frame in scoped.get("frames") or []:
        semantic_id = str(frame.get("semantic_id") or "")
        if semantic_id:
            frames_by_id[semantic_id] = dict(frame)
    order = list(
        dict.fromkeys(
            [
                *(str(f.get("semantic_id")) for f in (previous.get("frames") or []) if f.get("semantic_id")),
                *(str(f.get("semantic_id")) for f in (scoped.get("frames") or []) if f.get("semantic_id")),
            ]
        )
    )
    frames = [frames_by_id[semantic_id] for semantic_id in order]
    failed = [
        semantic_id
        for semantic_id in order
        if semantic_id in required_ids and frames_by_id[semantic_id].get("verdict") == "fail"
    ]
    uncertain = [
        semantic_id
        for semantic_id in order
        if semantic_id in required_ids and frames_by_id[semantic_id].get("verdict") == "uncertain"
    ]
    passed = not failed and not uncertain
    return {
        **previous,
        "frames": frames,
        "failed_frame_ids": failed,
        "uncertain_frame_ids": uncertain,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "sheet_verdict": "pass" if passed else "fail",
        "recheck_used": bool(previous.get("recheck_used") or scoped.get("recheck_used")),
        "scoped": False,
        "target_semantic_ids": None,
    }


def _finalize_sheet_release(
    item: PlannedAsset,
    content: bytes,
    audit: dict,
    review: dict,
    logs: list[str],
) -> tuple[bytes, dict, dict]:
    """Release with warnings above the coverage floor; pause only below it.

    带伤放行:失败格仍有可用的画(几何/透明度过了确定性审计),语义缺陷记入
    regeneration_plan 由后台补射。烧完修复预算再暂停整个任务是最差结局——
    既花了三倍的钱又零产物(第十二轮 40 分钟后用户手动取消)。
    """

    failed_ids = [str(value) for value in (audit.get("failed_frame_ids") or [])]
    if not failed_ids:
        return content, audit, review
    coverage = float(audit.get("required_asset_coverage") or 0.0)
    floor = max(0.0, min(1.0, float(settings.ASSET_RELEASE_COVERAGE_FLOOR)))
    if coverage >= floor:
        audit["released_with_warnings"] = True
        audit["release_coverage_floor"] = floor
        logs.append(
            f"{item.key}: released with {len(failed_ids)} imperfect required frame(s) "
            f"({', '.join(failed_ids[:8])}); coverage {coverage:.2f} >= floor {floor:.2f}; "
            "queued for background regeneration"
        )
        return content, audit, review
    raise AssetGenerationRetryRequired(
        f"Spritesheet '{item.key}' required frame coverage {coverage:.2f} is below the "
        f"release floor {floor:.2f}; failed: {', '.join(failed_ids[:12])}. "
        "Generation is paused; waiting for manual retry."
    )


def _repair_failed_sheet_frames(
    content: bytes,
    item: PlannedAsset,
    frame_audit: dict,
    semantic_review: dict,
    source_batch: BatchSpec,
    review_manifest: SpriteDemandManifest,
    state: dict,
    router: ProviderRouter,
    logs: list[str],
) -> tuple[bytes, dict, dict]:
    """Regenerate the WHOLE sheet once per round and keep the best of each cell.

    2026-07-20 用户定调:不做单格重画——成本按失败格数倍增(第二跑一轮烧了
    8 次图像调用)。每轮固定 1 次图像调用:整表重掷(带失败反馈提示词)→
    与旧表逐格择优合成(已 pass 格锁定不动,失败格换入新表中通过审计的版本)
    → 换入格做一次跨表局部复审,身份漂移的换入格回退。失败集不严格收缩或
    预算耗尽即止损,由带伤放行判定收尾。
    """

    max_attempts = max(1, min(4, int(settings.ASSET_FRAME_AUDIT_MAX_RETRIES) + 1))
    image_budget = max(1, int(settings.ASSET_REPAIR_MAX_IMAGE_CALLS))
    images_used = 0
    current_content = content
    current_audit = frame_audit
    current_review = semantic_review
    required_ids = {demand.semantic_id for demand in review_manifest.required}
    known_ids = {
        _cell_demand(cell).semantic_id
        for cell in item.sheet_cells
        if not cell.name.startswith("bonus_")
    }
    from PIL import Image

    def _cell_box(semantic_id: str) -> tuple[int, int, int, int]:
        index = source_batch.frame_index(semantic_id)
        col, row = index % SHEET_GRID, index // SHEET_GRID
        return (
            col * SHEET_CELL,
            row * SHEET_CELL,
            (col + 1) * SHEET_CELL,
            (row + 1) * SHEET_CELL,
        )

    review_enabled = bool(settings.ASSET_SEMANTIC_REVIEW_ENABLED and current_review.get("enabled"))
    for attempt in range(1, max_attempts + 1):
        failed_ids = [
            str(value)
            for value in (current_audit.get("failed_frame_ids") or [])
            if str(value) in known_ids
        ]
        if not failed_ids:
            break
        if images_used >= image_budget:
            logs.append(
                f"{item.key}: repair image budget exhausted ({image_budget}); stopping repair"
            )
            break
        try:
            media = _generate_with_retry(
                router,
                MediaRequest(
                    modality="image",
                    prompt=_sheet_regen_prompt(item, current_audit, current_review),
                    size=f"{SHEET_SIZE}x{SHEET_SIZE}",
                    extra={"background": "transparent", "quality": "medium"},
                ),
                logs,
                f"{item.key}:regen{attempt}",
            )
        except Exception as exc:  # noqa: BLE001 —— 重掷失败留给放行判定兜底
            logs.append(
                f"{item.key}: sheet regeneration failed ({_clip_text(exc, 140)}); stopping repair"
            )
            break
        images_used += 1
        try:
            candidate_content, _candidate_layout, _candidate_repack = _slice_sheet_canvas(
                media.content,
                media.content_type,
                item,
                review_manifest,
                source_batch,
                logs,
            )
        except Exception as exc:  # noqa: BLE001 —— 候选画布不可用不值得暂停
            logs.append(
                f"{item.key}: regenerated canvas unusable ({_clip_text(exc, 140)}); stopping repair"
            )
            break
        candidate_audit = _audit_sheet_frames(candidate_content, item.sheet_cells)
        candidate_review: dict = {"enabled": False, "frames": []}
        if review_enabled:
            try:
                candidate_review = _semantic_review_with_retry(
                    candidate_content,
                    review_manifest,
                    source_batch,
                    logs,
                    f"{item.key}:regen{attempt}",
                )
            except AssetSemanticReviewError as exc:
                logs.append(
                    f"{item.key}: candidate review unavailable ({_clip_text(exc, 140)}); "
                    "stopping repair"
                )
                break
            candidate_audit = _merge_semantic_review_into_audit(candidate_audit, candidate_review)
        candidate_failed = {
            str(value) for value in (candidate_audit.get("failed_frame_ids") or [])
        }
        swap_ids = [semantic_id for semantic_id in failed_ids if semantic_id not in candidate_failed]
        if not swap_ids:
            logs.append(
                f"{item.key}: regenerated sheet improved no failed cell; stopping repair"
            )
            break
        composed = Image.open(io.BytesIO(current_content)).convert("RGBA")
        pristine = composed.copy()
        candidate_sheet = Image.open(io.BytesIO(candidate_content)).convert("RGBA")
        for semantic_id in swap_ids:
            box = _cell_box(semantic_id)
            composed.paste(candidate_sheet.crop(box), box[:2])
        kept_swaps = list(swap_ids)
        if review_enabled:
            composed_out = io.BytesIO()
            composed.save(composed_out, format="PNG")
            accepted_context = {
                str(frame.get("semantic_id")): str(frame.get("observed_category") or "")
                for frame in (current_review.get("frames") or [])
                if str(frame.get("verdict")) == "pass"
                and str(frame.get("semantic_id")) not in set(swap_ids)
            }
            try:
                scoped = _semantic_review_with_retry(
                    composed_out.getvalue(),
                    review_manifest,
                    source_batch,
                    logs,
                    item.key,
                    target_semantic_ids=tuple(swap_ids),
                    accepted_context=accepted_context,
                )
            except AssetSemanticReviewError as exc:
                # 跨表校验不可用:保守放弃全部换入,保持旧表,交给放行判定。
                logs.append(
                    f"{item.key}: cross-sheet verification unavailable ({_clip_text(exc, 140)}); "
                    "keeping the original sheet"
                )
                break
            scoped_by_id = {
                str(frame.get("semantic_id")): frame
                for frame in (scoped.get("frames") or [])
                if frame.get("semantic_id")
            }
            revert_ids = [
                semantic_id
                for semantic_id in swap_ids
                if str((scoped_by_id.get(semantic_id) or {}).get("verdict")) == "fail"
            ]
            for semantic_id in revert_ids:
                box = _cell_box(semantic_id)
                composed.paste(pristine.crop(box), box[:2])
                logs.append(
                    f"{item.key}: swapped cell {semantic_id} reverted after cross-sheet check"
                )
            kept_swaps = [
                semantic_id for semantic_id in swap_ids if semantic_id not in revert_ids
            ]
            if kept_swaps:
                kept_frames = [
                    scoped_by_id[semantic_id]
                    for semantic_id in kept_swaps
                    if semantic_id in scoped_by_id
                ]
                current_review = _merge_scoped_review(
                    current_review,
                    {"frames": kept_frames, "recheck_used": scoped.get("recheck_used")},
                    required_ids,
                )
        if not kept_swaps:
            logs.append(
                f"{item.key}: no swapped cell survived verification; stopping repair"
            )
            break
        out = io.BytesIO()
        composed.save(out, format="PNG")
        current_content = out.getvalue()
        current_audit = _audit_sheet_frames(current_content, item.sheet_cells)
        if current_review.get("enabled"):
            current_audit = _merge_semantic_review_into_audit(current_audit, current_review)
        new_failed = [str(value) for value in (current_audit.get("failed_frame_ids") or [])]
        logs.append(
            f"{item.key}: repair round {attempt} (full-sheet regen) -> "
            f"{len(new_failed)} failed required frame(s)"
        )
        if len(new_failed) >= len(failed_ids):
            logs.append(f"{item.key}: failure set did not shrink; stopping repair")
            break
    return _finalize_sheet_release(item, current_content, current_audit, current_review, logs)


def _screen_size(design: dict) -> tuple[int, int]:
    """Design screen size with the scaffold's own clamps (defaults 1152x768)."""
    screen = design.get("screen") if isinstance(design.get("screen"), dict) else {}

    def _num(value, default: int, lo: int, hi: int) -> int:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            parsed = default
        return max(lo, min(hi, parsed))

    return _num(screen.get("width"), 1152, 640, 1600), _num(screen.get("height"), 768, 480, 1000)


def _record_image_call(
    key: str,
    model: str | None,
    latency_ms: float,
    status: str,
    error: Exception | None = None,
) -> None:
    """Ledger one image-provider call into ``llm_calls`` (fail-open).

    第十二轮(2026-07-19)盲区:修复轮 17 次图像调用在 llm_calls/Opik 双双不可
    见,10-12 分钟的空窗只能靠 docker 日志反推。tokens 记 0,延迟真实。
    """

    try:
        from app.llm import accounting as llm_accounting
        from app.core.telemetry import get_context
        from app.db.session import SessionLocal

        llm_accounting.persist_call(
            llm_accounting.LLMResult(
                text="",
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=str(model or settings.ASSET_IMAGE_MODEL or "image"),
                latency_ms=max(0, int(latency_ms)),
            ),
            session_factory=SessionLocal,
            context=get_context(),
            logger=logger,
            agent="AssetImageProvider",
            workflow_name="Generate Game Assets",
            status=status,
            error_code=type(error).__name__ if error is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - accounting must never stop generation
        logger.debug("image call ledger skipped for %s: %s", key, exc)


_TRANSPARENT_REJECT_MARKER = "transparent background is not supported"
# 进程级记忆:订阅制网关(如 sub2api 的 chatgpt 后端图像通道)对
# background=transparent 直接 400 而非忽略;首次被拒后全进程剥离该参数。
_transparent_param_unsupported = False


def _wants_transparent_background(request: MediaRequest) -> bool:
    return (
        request.modality == "image"
        and str((request.extra or {}).get("background", "")).strip().lower() == "transparent"
    )


def _without_background_extra(request: MediaRequest) -> MediaRequest:
    extra = {k: v for k, v in (request.extra or {}).items() if k != "background"}
    return replace(request, extra=extra or None)


def _native_transparency_enabled() -> bool:
    mode = str(settings.ASSET_IMAGE_NATIVE_TRANSPARENCY or "auto").strip().lower()
    if mode == "never":
        return False
    return not _transparent_param_unsupported


def _generate_with_retry(router: ProviderRouter, request: MediaRequest, logs: list[str], key: str):
    """Retry ordinary generation errors before requiring manual retry.

    Configuration failures do not heal. An invalid/empty final streaming event
    is also not retried because the provider may already have generated and
    billed the image; repeating it can duplicate both output and cost.
    background=transparent is optional polish: prompts already demand a magenta
    backdrop and `_postprocess_spritesheet`/`_postprocess_tileset` chroma-key it,
    so a provider that rejects the parameter gets a retry without it. Two extra
    escapes before pausing the pipeline (both generic, 2026-07-20 三路守卫):
    a LAST-RESORT retry without the transparent parameter — some gateways route
    requests carrying it to a broken upstream and fail with 5xx instead of a
    parameter error — and, when ASSET_<MODALITY>_FALLBACK_* is configured, a
    failover pass against the fallback provider.
    """
    global _transparent_param_unsupported
    retries = max(0, min(4, int(settings.ASSET_PROVIDER_MAX_RETRIES)))
    if _wants_transparent_background(request) and not _native_transparency_enabled():
        request = _without_background_extra(request)
        logs.append(
            f"{key}: background=transparent omitted (provider rejects it; "
            f"magenta chroma-key recovers transparency)"
        )
    fallback_config = None
    # getattr:测试常以桩替换模块级 ProviderRouter 符号,桩不必实现兜底解析。
    fallback_resolver = getattr(ProviderRouter, "resolve_fallback", None)
    if callable(fallback_resolver):
        try:
            fallback_config = fallback_resolver(request.modality)
        except ProviderConfigurationError as exc:
            logs.append(f"{key}: fallback provider misconfigured; ignoring it ({_clip_text(exc, 120)})")
    phases: list[tuple] = [(None, retries + 1)]
    if fallback_config is not None:
        phases.append((fallback_config, min(2, retries + 1)))
    last_error: ProviderGenerationError | None = None
    for phase_index, (config, attempts) in enumerate(phases):
        phase_request = request
        wants_transparent = _wants_transparent_background(phase_request)
        if phase_index:
            logs.append(
                f"{key}: primary provider exhausted its retries; failing over to "
                f"{config.provider} at {config.base_url}"
            )
        stripped_last_resort = False
        attempt = 0
        while attempt < attempts:
            attempt += 1
            started = time.perf_counter()
            with opik_integration.media_generation_span(
                key=key,
                model=str(config.model if config is not None else settings.ASSET_IMAGE_MODEL or "") or None,
                prompt_chars=len(phase_request.prompt or ""),
                metadata={
                    "attempt": attempt,
                    "modality": phase_request.modality,
                    "provider_phase": "fallback" if phase_index else "primary",
                },
            ):
                try:
                    media = (
                        router.generate(phase_request, config=config)
                        if config is not None
                        else router.generate(phase_request)
                    )
                except ProviderStreamProtocolError as exc:
                    _record_image_call(
                        key, None, (time.perf_counter() - started) * 1000, "error", exc
                    )
                    raise
                except ProviderGenerationError as exc:
                    _record_image_call(
                        key, None, (time.perf_counter() - started) * 1000, "error", exc
                    )
                    last_error = exc
                    if wants_transparent and _TRANSPARENT_REJECT_MARKER in str(exc).lower():
                        if config is None:
                            _transparent_param_unsupported = True
                        phase_request = _without_background_extra(phase_request)
                        wants_transparent = False
                        # 参数被拒不是生成失败,剥参后的请求保留完整重试预算。
                        attempt -= 1
                        logs.append(
                            f"{key}: provider rejected background=transparent; retrying "
                            f"without it (magenta chroma-key recovers transparency)"
                        )
                        continue
                    if attempt >= attempts:
                        if wants_transparent and not stripped_last_resort:
                            # 最后一搏:剥掉可选的 transparent 参数再试一次。部分网关按
                            # 参数把请求路由到坏上游,报 5xx 而非参数错误(accel 实测:
                            # 带 transparent 的 sheet 必挂,不带该参数的背景全过)。
                            stripped_last_resort = True
                            phase_request = _without_background_extra(phase_request)
                            wants_transparent = False
                            attempts += 1
                            logs.append(
                                f"{key}: attempt {attempt} failed ({_clip_text(exc, 140)}); "
                                "last-resort retry without background=transparent "
                                "(magenta chroma-key recovers transparency)"
                            )
                            continue
                        break
                    logs.append(
                        f"{key}: attempt {attempt} failed ({_clip_text(exc, 140)}); "
                        f"retrying attempt {attempt + 1}/{attempts}"
                    )
                    continue
                _record_image_call(
                    key, media.model, (time.perf_counter() - started) * 1000, "completed"
                )
                return media
    if last_error is not None:
        raise last_error
    raise AssertionError("asset generation retry loop exited unexpectedly")


def _produce_media(router: ProviderRouter, item: PlannedAsset) -> tuple:
    """Worker: generate one planned asset off-thread → (media, error, local logs).

    异常作为返回值带回,由主循环按计划顺序统一定夺——错误语义与日志顺序
    因此保持串行版的确定性,与线程完成的先后无关。
    """
    logs: list[str] = []
    started = time.perf_counter()
    try:
        media = _generate_with_retry(
            router,
            MediaRequest(
                modality=item.modality,  # type: ignore[arg-type]
                prompt=item.prompt,
                size=item.size,
                duration_seconds=item.duration_seconds,
                extra=item.extra,
            ),
            logs,
            item.key,
        )
    except Exception as exc:  # noqa: BLE001 —— 跨线程传回,主循环分类处理
        return None, exc, logs
    return media, None, logs, {"latency_ms": int((time.perf_counter() - started) * 1000)}


def generate_game_assets(state: dict, router: ProviderRouter | None = None) -> dict:
    router = router or ProviderRouter()
    artifacts: list[dict] = []
    manifest_entries: list[dict] = []
    asset_trace: list[dict] = []
    logs: list[str] = []

    contract = state.get("design_contract")
    if contract:
        spec = state.get("spec_execution_view") or contract_to_spec_payload(contract)
        design = state.get("design_execution_view") or contract_to_design_payload(contract)
        sprite_demand_manifest = SpriteDemandManifest.from_dict(
            state.get("sprite_demand_manifest") or derive_sprite_demand_manifest(contract)
        )
    else:
        # Compatibility for direct callers and historical revisions.  New
        # generation tasks always arrive here after Contract Gate.
        spec = state.get("game_spec") or {}
        design = state.get("game_design") or {}
        sprite_demand_manifest = build_sprite_demand_manifest(
            design,
            state.get("runtime_consumers") or design.get("runtime_consumers"),
        )
    tilemap_wanted = _tilemap_wanted_for(state, spec)

    planned = plan_game_assets(state) if settings.ASSET_GENERATION_ENABLED else []
    # 重入的素材阶段(balance 修复/replan/revision)逐 key 复核复用:prompt 没变
    # 的图不再回炉。整批重画会把已成功的图重新压上不稳定的图像端点。
    stale_keys = stale_planned_keys(state)
    carried_by_key: dict[str, dict] = {}
    carried_tilemap_entries: list[dict] = []
    prev_artifacts = _artifacts_by_path(state)
    to_generate = planned
    tileset_generation_wanted = tilemap_wanted
    if stale_keys is not None:
        stale_set = set(stale_keys)
        prev_by_key = {str(entry.get("key") or ""): entry for entry in _generated_manifest_entries(state)}
        to_generate = [item for item in planned if item.key in stale_set]
        carried_by_key = {
            item.key: prev_by_key[item.key] for item in planned if item.key not in stale_set
        }
        if tilemap_wanted and "tileset" not in stale_set:
            tileset_generation_wanted = False
            carried_tilemap_entries = _tilemap_family_entries(list(prev_by_key.values()))
        if carried_by_key or carried_tilemap_entries:
            logs.append(
                f"asset reuse: {len(carried_by_key) + len(carried_tilemap_entries)} unchanged asset(s) "
                f"reused, {len(to_generate)} to regenerate"
            )
    results: list[tuple] = []
    tileset_result: tuple | None = None
    if to_generate or (tileset_generation_wanted and settings.ASSET_GENERATION_ENABLED):
        # 图像调用并行化:图集页数扩容后串行墙钟时间不可接受(单页实测 ~72s,
        # 3 页图集+背景串行近 5 分钟)。httpx 按请求建连,ProviderRouter 无共享
        # 可变状态,线程安全。并发保守取 2,避免踩网关限流。失败语义:所有
        # 在飞请求跑完后按计划顺序结算,首个失败的图像资产仍旧暂停整条流水线。
        workers = max(1, int(settings.ASSET_GENERATION_CONCURRENCY))
        logs.append(f"dispatching {len(to_generate)} asset request(s), concurrency {workers}")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # 每个任务独立 copy_context(Context 不可并发 enter):图像调用的
            # Opik span 与 llm_calls 记账靠线程内的 telemetry/trace 上下文。
            futures = [
                pool.submit(contextvars.copy_context().run, _produce_media, router, item)
                for item in to_generate
            ]
            tileset_future = None
            if tileset_generation_wanted and settings.ASSET_GENERATION_ENABLED:
                tileset_future = pool.submit(
                    contextvars.copy_context().run,
                    _produce_media,
                    router,
                    PlannedAsset(
                        "tileset",
                        "image",
                        _tileset_prompt(spec, design),
                        size=f"{SHEET_SIZE}x{SHEET_SIZE}",
                        extra={"background": "transparent", "quality": "medium"},
                    ),
                )
            results = [future.result() for future in futures]
            if tileset_future is not None:
                tileset_result = tileset_future.result()
    results_by_key = {item.key: result for item, result in zip(to_generate, results)}

    for item in planned:
        carried_entry = carried_by_key.get(item.key)
        if carried_entry is not None:
            _append_carried_asset(
                item, carried_entry, prev_artifacts, artifacts, manifest_entries, asset_trace, logs, state
            )
            continue
        result_tuple = results_by_key.get(item.key) or (
            None,
            ProviderConfigurationError(f"no generation result for '{item.key}'"),
            [],
        )
        media, error, item_logs = result_tuple[:3]
        request_meta = (
            result_tuple[3]
            if len(result_tuple) > 3 and isinstance(result_tuple[3], dict)
            else {}
        )
        logs.extend(item_logs)
        if error is not None:
            if not isinstance(error, (ProviderConfigurationError, ProviderGenerationError)):
                raise error
            if item.modality == "image":
                if isinstance(error, ProviderConfigurationError):
                    detail = "could not start because the image provider is not configured correctly"
                else:
                    detail = (
                        f"failed after {max(0, int(settings.ASSET_PROVIDER_MAX_RETRIES))} "
                        "automatic retries"
                    )
                raise AssetGenerationRetryRequired(
                    f"Image asset '{item.key}' {detail}: {_clip_text(error, 220)}. "
                    "Generation is paused; waiting for manual retry."
                ) from error
            if not settings.ASSET_GENERATION_FAIL_OPEN:
                raise error
            logs.append(f"{item.key}: {error}; skipped")
            continue
        content = media.content
        content_type = media.content_type
        extension = media.extension
        kind = item.modality
        entry_extra: dict = {}
        postprocess_checks: dict[str, object] = {
            "generated": True,
            "normalized": False,
            "compression": "not_run",
        }
        requested_states = list((item.extra or {}).get("requested_states") or [])
        if not requested_states:
            requested_states = [cell.name for cell in item.sheet_cells] or ["default"]
        requested_semantic_ids = [
            _cell_demand(cell).semantic_id
            for cell in item.sheet_cells
            if _cell_demand(cell).semantic_id
        ]
        returned_dimensions: tuple[int, int] | None = None
        if item.modality == "image":
            try:
                from PIL import Image

                with Image.open(io.BytesIO(content)) as image:
                    returned_dimensions = (int(image.width), int(image.height))
                postprocess_checks["returned_dimensions_valid"] = True
            except Exception as exc:  # noqa: BLE001
                postprocess_checks["returned_dimensions_valid"] = False
                postprocess_checks["dimension_error"] = _clip_text(exc, 120)
        if item.sheet_cells and item.modality == "image":
            try:
                entry_extra = _sheet_manifest_extra(item.sheet_cells, item.sheet_groups)
                if state.get("contract_hash"):
                    entry_extra["contract_hash"] = state["contract_hash"]
                source_batch = BatchSpec(
                    batch_id=item.key,
                    group=item.key,
                    semantic_ids=tuple(
                        _cell_demand(cell).semantic_id
                        for cell in item.sheet_cells
                        if not cell.name.startswith("bonus_")
                    ),
                    rows=SHEET_GRID,
                    columns=SHEET_GRID,
                    cell_width=SHEET_CELL,
                    cell_height=SHEET_CELL,
                    style_group=str(
                        (state.get("style_bible") or {}).get("theme") or "default"
                    ),
                )
                review_manifest = SpriteDemandManifest(
                    tuple(_cell_demand(cell) for cell in item.sheet_cells if not cell.name.startswith("bonus_")),
                    dict(state.get("style_bible") or {}),
                )
                content, layout_review, layout_repack = _slice_sheet_canvas(
                    media.content,
                    media.content_type,
                    item,
                    review_manifest,
                    source_batch,
                    logs,
                )
                if layout_review.get("enabled"):
                    entry_extra["layout_review"] = layout_review
                if layout_repack.get("resegmented") or layout_repack.get("fallback"):
                    entry_extra["layout_repack"] = layout_repack
                content_type, extension = "image/png", ".png"
                kind = "spritesheet"
                frame_audit = _audit_sheet_frames(content, item.sheet_cells)
                entry_extra["frame_audit"] = frame_audit
                semantic_review = _semantic_review_with_retry(
                    content,
                    review_manifest,
                    source_batch,
                    logs,
                    item.key,
                )
                if semantic_review.get("enabled"):
                    frame_audit = _merge_semantic_review_into_audit(frame_audit, semantic_review)
                if frame_audit.get("failed_frame_ids"):
                    content, frame_audit, semantic_review = _repair_failed_sheet_frames(
                        content,
                        item,
                        frame_audit,
                        semantic_review,
                        source_batch,
                        review_manifest,
                        state,
                        router,
                        logs,
                    )
                if not frame_audit.get("passed") and not frame_audit.get("released_with_warnings"):
                    raise AssetGenerationRetryRequired(
                        f"Spritesheet '{item.key}' failed required frame audit: "
                        f"{', '.join(str(value) for value in frame_audit.get('failed_frame_ids') or [])}. "
                        "Generation is paused; waiting for manual retry."
                    )
                entry_extra["frame_audit"] = frame_audit
                entry_extra["semantic_review"] = semantic_review
                if layout_review.get("enabled"):
                    entry_extra["layout_review"] = layout_review
                    entry_extra["layout_repack"] = layout_repack
                entry_extra["regeneration_plan"] = [
                    retry.to_dict()
                    for retry in build_cell_regeneration_specs(
                        _regeneration_plan_audit(frame_audit),
                        source_batch,
                        style_bible=state.get("style_bible") or {},
                        contract_hash=state.get("contract_hash"),
                    )
                ]
                # Keep sheet-local semantic lookups self-contained.  A later
                # atlas packer may move the frame; the top-level semantic map
                # is updated from this record, never from a hard-coded index.
                for frame in entry_extra.get("semantic_frames", {}).values():
                    frame["sheet"] = item.key
                postprocess_checks.update(
                    {
                        "normalized": True,
                        "spritesheet_grid": f"{SHEET_GRID}x{SHEET_GRID}",
                        "frame_audit": {
                            "passed": frame_audit["passed"],
                            "failed_frame_ids": frame_audit["failed_frame_ids"],
                            "soft_frame_ids": list(frame_audit.get("soft_frame_ids") or []),
                            "required_asset_coverage": frame_audit["required_asset_coverage"],
                            "released_with_warnings": bool(
                                frame_audit.get("released_with_warnings")
                            ),
                        },
                        "semantic_review": {
                            "enabled": bool(semantic_review.get("enabled")),
                            "passed": bool(semantic_review.get("passed")),
                            "failed_frame_ids": list(semantic_review.get("failed_frame_ids") or []),
                            "uncertain_frame_ids": list(semantic_review.get("uncertain_frame_ids") or []),
                            "recheck_used": bool(semantic_review.get("recheck_used")),
                        },
                        "layout_review": {
                            "enabled": bool(layout_review.get("enabled")),
                            "passed": bool(layout_review.get("passed")),
                            "resegmented": bool(layout_repack.get("resegmented")),
                            "source_dimensions": list(layout_repack.get("source_dimensions") or []),
                            "failed_frame_ids": list(layout_review.get("failed_frame_ids") or []),
                            "uncertain_frame_ids": list(layout_review.get("uncertain_frame_ids") or []),
                        },
                    }
                )
                logs.append(
                    f"{item.key}: normalized to {SHEET_SIZE}px spritesheet "
                    f"({SHEET_GRID}x{SHEET_GRID} grid, {len(item.sheet_cells)} named frames, "
                    f"{len(item.sheet_groups)} animated actor(s))"
                )
            except AssetGenerationRetryRequired:
                # 失败路径不返回 result,logs 列表会整体丢失——第十二轮取证时
                # 12 分钟的修复轨迹在 worker 日志里完全不可见。暂停前落盘尾部。
                logger.warning(
                    "%s paused before release; stage log tail:\n%s",
                    item.key,
                    "\n".join(logs[-30:]),
                )
                raise
            except AssetSemanticReviewError as exc:
                raise AssetGenerationRetryRequired(
                    f"Image asset '{item.key}' could not complete required semantic review: "
                    f"{_clip_text(exc, 220)}. Generation is paused; waiting for manual retry."
                ) from exc
            except Exception as exc:  # noqa: BLE001 —— invalid generated image requires manual retry
                raise AssetGenerationRetryRequired(
                    f"Image asset '{item.key}' was generated but could not be normalized as a spritesheet: "
                    f"{_clip_text(exc, 220)}. Generation is paused; waiting for manual retry."
                ) from exc
        elif item.modality == "image" and item.key.startswith("background"):
            try:
                content, content_type, extension, luma_before, luma = _postprocess_background(
                    content, content_type, extension
                )
            except Exception as exc:  # noqa: BLE001 —— 亮度检测失败不值得停线,按原图继续
                logs.append(f"{item.key}: brightness check skipped ({_clip_text(exc, 120)})")
            else:
                entry_extra = {"luma": luma}
                postprocess_checks["background_luma"] = {"before": luma_before, "after": luma}
                if luma != luma_before:
                    logs.append(
                        f"{item.key}: lifted too-dark background (avg luma {luma_before} -> {luma} / 255)"
                    )
        if kind in {"image", "spritesheet"}:
            original_bytes = len(content)
            content, content_type, extension = _compress_image_asset(
                content, content_type, extension, keep_alpha=(kind == "spritesheet")
            )
            if extension == ".webp" and original_bytes != len(content):
                logs.append(
                    f"{item.key}: recompressed to WebP "
                    f"({original_bytes // 1024}KB -> {len(content) // 1024}KB)"
                )
                postprocess_checks["compression"] = "webp"
            else:
                postprocess_checks["compression"] = extension.lstrip(".") or "none"
        runtime_path = f"assets/{item.key}{extension}"
        artifacts.append(binary_artifact(f"public/{runtime_path}", content, content_type))
        trace = asset_trace_record(
            task_id=state.get("task_id"),
            key=item.key,
            prompt=item.prompt,
            modality=item.modality,
            provider=media.provider,
            model=media.model,
            content=content,
            requested_states=requested_states,
            returned_dimensions=returned_dimensions,
            postprocess_checks=postprocess_checks,
            frame_count=len(item.sheet_cells),
            coverage_result={
                "status": "pending",
                "reason": "consumer analysis runs after code generation",
            },
            contract_hash=state.get("contract_hash"),
        )
        trace["output_artifact_id"] = (
            f"output:{runtime_path}:{hashlib.sha256(content).hexdigest()[:24]}"
        )
        trace["requested_semantic_ids"] = requested_semantic_ids
        trace["latency_ms"] = int(request_meta.get("latency_ms") or 0)
        asset_trace.append(trace)
        entry_extra.update(
            {
                "asset_id": trace["asset_id"],
                "prompt_hash": trace["prompt_hash"],
                "requested_states": trace["requested_states"],
                "requested_semantic_ids": requested_semantic_ids,
                "returned_dimensions": trace["returned_dimensions"],
                "postprocess_checks": trace["postprocess_checks"],
                "frame_count": trace["frame_count"],
                "consumer_refs": [],
                "coverage_result": trace["coverage_result"],
                "latency_ms": int(request_meta.get("latency_ms") or 0),
            }
        )
        manifest_entries.append(
            {
                "key": item.key,
                "kind": kind,
                "path": runtime_path,
                "content_type": content_type,
                "provider": media.provider,
                "model": media.model,
                **entry_extra,
            }
        )
        logs.append(f"{item.key}: generated {item.modality} via {media.provider}/{media.model}")

    if tilemap_wanted and carried_tilemap_entries:
        # tileset prompt 未变且工件齐全:整族(tileset+tilemap)原样复用,
        # 程序化 tilemap 由同一 seed 决定,与被复用的 tileset 保持一致。
        for entry in carried_tilemap_entries:
            artifact = _entry_artifact(entry, prev_artifacts)
            artifacts.append(dict(artifact or {}))
            manifest_entries.append(json.loads(json.dumps(entry)))
        logs.append(
            f"tilemap: reused {len(carried_tilemap_entries)} unchanged tileset/tilemap asset(s)"
        )
    elif tilemap_wanted:
        archetype = str(spec.get("archetype") or "")
        tileset_png: bytes | None = None
        tileset_provider, tileset_model = "procedural", "palette"
        if tileset_result is not None:
            # tileset 与图集/背景走同一画风管线(并行批里一起生成);它是氛围
            # 装饰,失败不值得暂停整条流水线 —— 任何异常都回退调色板程序化 tileset。
            media, error, tileset_logs = tileset_result[:3]
            logs.extend(tileset_logs)
            if error is not None:
                if not isinstance(error, (ProviderConfigurationError, ProviderGenerationError)):
                    raise error
                if isinstance(error, ProviderConfigurationError):
                    detail = "could not start because the image provider is not configured correctly"
                else:
                    detail = (
                        f"failed after {max(0, int(settings.ASSET_PROVIDER_MAX_RETRIES))} "
                        "automatic retries"
                    )
                raise AssetGenerationRetryRequired(
                    f"Image asset 'tileset' {detail}: {_clip_text(error, 220)}. "
                    "Generation is paused; waiting for manual retry."
                ) from error
            else:
                try:
                    tileset_png = _postprocess_tileset(media.content, media.content_type)
                    tileset_provider, tileset_model = media.provider, media.model
                    logs.append(
                        f"tileset: generated via {media.provider}/{media.model}, "
                        f"normalized to {TILESET_IMAGE_SIZE}px tile grid"
                    )
                    trace = asset_trace_record(
                        task_id=state.get("task_id"),
                        key="tileset",
                        prompt=_tileset_prompt(spec, design),
                        modality="image",
                        provider=media.provider,
                        model=media.model,
                        content=tileset_png,
                        requested_states=["tileset"],
                        returned_dimensions=(TILESET_IMAGE_SIZE, TILESET_IMAGE_SIZE),
                        postprocess_checks={
                            "generated": True,
                            "normalized": True,
                            "tile_grid": TILESET_GRID,
                        },
                        frame_count=TILESET_GRID * TILESET_GRID,
                        coverage_result={
                            "status": "pending",
                            "reason": "consumer analysis runs after code generation",
                        },
                        contract_hash=state.get("contract_hash"),
                    )
                    trace["output_artifact_id"] = (
                        f"output:assets/tileset.png:{hashlib.sha256(tileset_png).hexdigest()[:24]}"
                    )
                    asset_trace.append(trace)
                except Exception as exc:  # noqa: BLE001 —— invalid generated image requires manual retry
                    raise AssetGenerationRetryRequired(
                        "Image asset 'tileset' was generated but could not be normalized: "
                        f"{_clip_text(exc, 220)}. Generation is paused; waiting for manual retry."
                    ) from exc
        screen_width, screen_height = _screen_size(design)
        seed = str(
            state.get("task_id")
            or state.get("contract_hash")
            or state.get("prompt")
            or archetype
        )
        tilemap = generate_tilemap_artifacts(
            archetype,
            seed,
            screen_width=screen_width,
            screen_height=screen_height,
            palette=design.get("palette") if isinstance(design.get("palette"), dict) else None,
            tileset_png=tileset_png,
            tileset_provider=tileset_provider,
            tileset_model=tileset_model,
        )
        if tilemap:
            tile_artifacts, tile_entries = tilemap
            for entry, artifact in zip(tile_entries, tile_artifacts):
                if not isinstance(entry, dict):
                    continue
                existing = next(
                    (item for item in asset_trace if item.get("key") == entry.get("key")),
                    None,
                )
                if existing is None:
                    raw = artifact_bytes(artifact)
                    trace = asset_trace_record(
                        task_id=state.get("task_id"),
                        key=str(entry.get("key") or "tilemap"),
                        prompt="deterministic tilemap generated from the selected archetype",
                        modality=str(entry.get("kind") or "asset"),
                        provider=entry.get("provider") or "procedural",
                        model=entry.get("model") or "tilemap-v2",
                        content=raw,
                        requested_states=["world"],
                        postprocess_checks={"generated": True, "normalized": True},
                        coverage_result={"status": "pending", "reason": "consumer analysis runs after code generation"},
                        contract_hash=state.get("contract_hash"),
                    )
                    trace["output_artifact_id"] = (
                        f"output:{entry.get('path')}:{hashlib.sha256(raw).hexdigest()[:24]}"
                    )
                    asset_trace.append(trace)
                    existing = trace
                entry.update(
                    {
                        "asset_id": existing.get("asset_id"),
                        "prompt_hash": existing.get("prompt_hash"),
                        "requested_states": existing.get("requested_states"),
                        "returned_dimensions": existing.get("returned_dimensions"),
                        "postprocess_checks": existing.get("postprocess_checks"),
                        "frame_count": existing.get("frame_count", 0),
                        "consumer_refs": existing.get("consumer_refs", []),
                        "coverage_result": existing.get("coverage_result"),
                    }
                )
            artifacts.extend(tile_artifacts)
            manifest_entries.extend(tile_entries)
            logs.append(f"tilemap: generated deterministic Tiled JSON for {archetype}")

    semantic_runtime_map: dict[str, dict] = {}
    for entry in manifest_entries:
        if str(entry.get("kind")) != "spritesheet":
            continue
        for semantic_id, frame in (entry.get("semantic_frames") or {}).items():
            if semantic_id and semantic_id not in semantic_runtime_map:
                semantic_runtime_map[semantic_id] = {
                    **frame,
                    "sheet": str(frame.get("sheet") or entry.get("key") or ""),
                }
    # The planner still emits legacy frame keys for old Phaser projects.  Make
    # every actual cell visible in the formal semantic demand manifest too;
    # this prevents an alias such as `grunt_b` from becoming an invisible,
    # untracked asset when the runtime contract is evaluated.
    known_demands = {item.semantic_id for item in sprite_demand_manifest.demands}
    cell_demands: list[SpriteDemand] = list(sprite_demand_manifest.demands)
    for entry in manifest_entries:
        if str(entry.get("kind")) != "spritesheet":
            continue
        for semantic_id, frame in (entry.get("semantic_frames") or {}).items():
            if semantic_id in known_demands:
                continue
            frame_id = str((frame or {}).get("frame_id") or (frame or {}).get("frame") or semantic_id)
            cell_demands.append(
                SpriteDemand(
                    semantic_id=str(semantic_id),
                    frame_id=frame_id,
                    object_name=str(semantic_id).rsplit(".", 1)[0],
                    state=str(semantic_id).rsplit(".", 1)[-1],
                    consumer_refs=(f"design:{str(semantic_id).split('.', 1)[0]}",),
                    required=bool((frame or {}).get("required", True)),
                    anchor=tuple((frame or {}).get("anchor") or (0.5, 1.0)),
                )
            )
            known_demands.add(str(semantic_id))
    sprite_demand_manifest = SpriteDemandManifest(
        tuple(cell_demands),
        sprite_demand_manifest.style_bible,
        sprite_demand_manifest.runtime_consumers,
        sprite_demand_manifest.schema_version,
    )
    sprite_demand_payload = sprite_demand_manifest.to_dict()
    if state.get("contract_hash"):
        sprite_demand_payload["contract_hash"] = state["contract_hash"]
    sprite_demand_payload["runtime_manifest"] = semantic_runtime_map
    sprite_demand_payload["metrics"]["required_asset_coverage"] = (
        1.0
        if not sprite_demand_manifest.required
        else round(
            sum(1 for item in sprite_demand_manifest.required if item.semantic_id in semantic_runtime_map)
            / len(sprite_demand_manifest.required),
            4,
        )
    )
    sprite_demand_payload["metrics"]["unused_required_frame"] = sum(
        1 for item in sprite_demand_manifest.required if item.semantic_id not in semantic_runtime_map
    )
    return {
        "artifacts": artifacts,
        "manifest_entries": manifest_entries,
        "logs": logs,
        "asset_trace": asset_trace,
        "asset_generation_gate": {
            "status": "passed",
            "required_frame_audit": "passed",
            "semantic_review": "enabled" if settings.ASSET_SEMANTIC_REVIEW_ENABLED else "disabled",
        },
        "sprite_demand_manifest": sprite_demand_payload,
        "asset_request_count": len(to_generate)
        + (1 if tileset_generation_wanted and settings.ASSET_GENERATION_ENABLED else 0),
    }
