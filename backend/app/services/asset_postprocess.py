"""Deterministic pixel post-processing for generated assets.

2026-07-26 拆分自 ``game_assets.py``:服务端确定性兜住图像模型靠不住的部分
——精确网格几何、真透明度(品红键控+边缘反混+透明区 RGB 扩散,退路是边界
连通泛洪)、按评审 bbox 的整表重切、背景亮度底线、WebP 重压缩、格级帧审计、
修复单格归一化。``app.services.game_assets`` 回导这些名字,导入路径不变。
"""
from __future__ import annotations

import io
from collections import deque

from app.services.asset_planning import (
    SHEET_CELL,
    SHEET_GRID,
    SHEET_SIZE,
    AssetGenerationRetryRequired,
    SheetCell,
    _cell_demand,
)
from app.services.provider_router import ProviderGenerationError
from app.services.sprite_pipeline import audit_frame
from app.services.tilemaps import TILE_SIZE, TILESET_GRID, TILESET_IMAGE_SIZE


# 背景亮度底线:prompt 只能"劝"图像模型,压不住暗色题材(潜行/夜战)一路画到
# 均值 15/255、93% 像素近黑(2026-07-17 暗影档案实测)。生成后确定性检测 +
# 提亮是硬保证;实测亮度同时写进 manifest,运行时 Backdrop 据此自适应压暗。
_BG_MIN_LUMA = 44
_BG_TARGET_LUMA = 64
# gamma 下限:0.35 时均值 3/255 的近纯黑图也能抬到 ~54,再低会放大噪点。
_BG_MIN_GAMMA = 0.35


def _mean_luma(img) -> float:
    """Average luminance (0-255) of a downscaled copy — cheap and stable."""
    from PIL import Image

    sample = img.convert("L").resize((64, 40), Image.BILINEAR)
    histogram = sample.histogram()
    total = sum(histogram) or 1
    return sum(value * count for value, count in enumerate(histogram)) / total


def _postprocess_background(
    raw: bytes, content_type: str, extension: str
) -> tuple[bytes, str, str, int, int]:
    """Measure a generated background's brightness; lift it when it is too dark.

    Returns (content, content_type, extension, luma_before, luma_after). A lift
    is a gamma curve aimed at _BG_TARGET_LUMA — it raises shadows toward the
    target without clipping highlights, deterministically and cheaply (no
    regeneration round-trip). Bright enough images pass through byte-for-byte.
    """
    import math

    from PIL import Image

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    before = _mean_luma(img)
    if before >= _BG_MIN_LUMA:
        return raw, content_type, extension, int(round(before)), int(round(before))
    gamma = math.log(_BG_TARGET_LUMA / 255.0) / math.log(max(before, 1.0) / 255.0)
    gamma = max(_BG_MIN_GAMMA, min(1.0, gamma))
    curve = [round(((value / 255.0) ** gamma) * 255.0) for value in range(256)]
    img = img.point(curve * 3)
    after = _mean_luma(img)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue(), "image/png", ".png", int(round(before)), int(round(after))


def _is_light_bg(r: int, g: int, b: int) -> bool:
    mx = max(r, g, b)
    return mx >= 172 and mx - min(r, g, b) <= 48


def _magenta_distance(r: int, g: int, b: int) -> int:
    return (255 - r) + g + (255 - b)


def _unmix_magenta(r: int, g: int, b: int, a: int) -> tuple[int, int, int]:
    """Recover the sprite color from an anti-aliased edge pixel.

    Edge pixels are `a*sprite + (1-a)*magenta`; without unmixing they render as
    a pink fringe around every sprite. Solve back for the sprite color.
    """
    if a <= 0 or a >= 255:
        return r, g, b
    inv = 255 - a
    red = min(255, max(0, (255 * r - 255 * inv) // a))
    blue = min(255, max(0, (255 * b - 255 * inv) // a))
    green = min(255, (255 * g) // a)
    return red, green, blue


def _dilate_rgb_into_transparent(data: list, width: int, height: int, passes: int = 2) -> list:
    """Bleed sprite RGB one ring at a time into fully-transparent neighbors.

    GPU linear filtering samples the RGB of transparent texels next to sprite
    edges; leaving the keyed backdrop color there produces colored halos.
    """
    colored = bytearray(a > 32 for _, _, _, a in data)
    for _ in range(max(0, passes)):
        src = list(data)
        source_mask = bytes(colored)
        for idx, (r, g, b, a) in enumerate(src):
            if a != 0 or colored[idx]:
                continue
            x, y = idx % width, idx // width
            rs = gs = bs = count = 0
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    nidx = ny * width + nx
                    if source_mask[nidx]:
                        nr, ng, nb, _na = src[nidx]
                        rs += nr
                        gs += ng
                        bs += nb
                        count += 1
            if count:
                data[idx] = (rs // count, gs // count, bs // count, 0)
                colored[idx] = 1
    return data


_COMPRESS_MIN_BYTES = 262_144
_COMPRESS_KEEP_RATIO = 0.85


def _compress_image_asset(
    content: bytes, content_type: str, extension: str, *, keep_alpha: bool
) -> tuple[bytes, str, str]:
    """Re-encode large raster assets as WebP.

    Provider PNGs run 1.5-2.7MB each; a bundle of sheets and background
    variants pushed total payloads past 14MB and browser load times past 20s.
    Sprite sheets keep alpha (lossless vs q95, whichever is smaller); plain
    backgrounds go lossy q85. The original is kept when WebP does not win by
    a meaningful margin, so this can never make a bundle worse.
    """
    lowered = (content_type or "").lower()
    if len(content) < _COMPRESS_MIN_BYTES or ("png" not in lowered and "jpeg" not in lowered):
        return content, content_type, extension
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content))
        candidates: list[bytes] = []
        if keep_alpha:
            rgba = img.convert("RGBA")
            for kwargs in (
                {"lossless": True, "method": 4},
                {"quality": 95, "method": 5},
            ):
                out = io.BytesIO()
                rgba.save(out, format="WEBP", **kwargs)
                candidates.append(out.getvalue())
        else:
            out = io.BytesIO()
            img.convert("RGB").save(out, format="WEBP", quality=85, method=5)
            candidates.append(out.getvalue())
        best = min(candidates, key=len)
        if len(best) <= len(content) * _COMPRESS_KEEP_RATIO:
            return best, "image/webp", ".webp"
    except Exception:  # noqa: BLE001 - compression is best-effort
        import logging

        logging.getLogger(__name__).exception(
            "image asset compression failed; keeping original"
        )
    return content, content_type, extension


def _normalize_spritesheet_canvas(raw: bytes, content_type: str):
    """Decode and key a generated sheet without changing its source geometry."""
    if "svg" in (content_type or "").lower():
        raise ValueError("vector placeholder cannot be sliced into a spritesheet")
    from PIL import Image

    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    data = list(img.getdata())
    total = len(data)
    transparent = sum(1 for _, _, _, a in data if a < 16)
    if transparent >= total * 0.05:
        pass  # provider delivered real alpha — keep as-is
    else:
        magenta_hits = sum(1 for r, g, b, _ in data if _magenta_distance(r, g, b) <= 120)
        if magenta_hits >= total * 0.03:
            # Chroma-key the prompted magenta backdrop: hard-key the flat area,
            # feather + unmix the anti-aliased edge band, then bleed sprite RGB
            # into the cleared pixels so linear filtering cannot show pink halos.
            keyed = []
            for r, g, b, a in data:
                dist = _magenta_distance(r, g, b)
                if dist <= 120:
                    keyed.append((r, g, b, 0))
                elif dist <= 200:
                    alpha = min(a, (dist - 120) * 255 // 80)
                    keyed.append((*_unmix_magenta(r, g, b, alpha), alpha))
                else:
                    keyed.append((r, g, b, a))
            img.putdata(_dilate_rgb_into_transparent(keyed, img.width, img.height))
        else:
            # Fallback: the model painted a light/checkerboard backdrop. Clear
            # everything light-and-unsaturated that connects to the sheet border;
            # sprites survive as interior islands behind their dark outlines.
            width, height = img.size
            seen = bytearray(total)
            queue: deque[int] = deque()
            for x in range(width):
                for y in (0, height - 1):
                    idx = y * width + x
                    if not seen[idx] and _is_light_bg(*data[idx][:3]):
                        seen[idx] = 1
                        queue.append(idx)
            for y in range(height):
                for x in (0, width - 1):
                    idx = y * width + x
                    if not seen[idx] and _is_light_bg(*data[idx][:3]):
                        seen[idx] = 1
                        queue.append(idx)
            while queue:
                idx = queue.popleft()
                x, y = idx % width, idx // width
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        nidx = ny * width + nx
                        if not seen[nidx] and _is_light_bg(*data[nidx][:3]):
                            seen[nidx] = 1
                            queue.append(nidx)
            cleared = [
                (r, g, b, 0) if seen[i] else (r, g, b, a)
                for i, (r, g, b, a) in enumerate(data)
            ]
            if sum(1 for flag in seen if flag) < total * 0.02:
                raise ValueError("could not identify a keyable sheet background")
            img.putdata(_dilate_rgb_into_transparent(cleared, img.width, img.height))

    return img


def _postprocess_spritesheet(raw: bytes, content_type: str) -> bytes:
    """Normalize a generated sheet: exact size + real alpha transparency."""
    from PIL import Image

    img = _normalize_spritesheet_canvas(raw, content_type)
    if img.size != (SHEET_SIZE, SHEET_SIZE):
        img = img.resize((SHEET_SIZE, SHEET_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _resegment_spritesheet(
    raw_layout_content: bytes,
    cells: tuple[SheetCell, ...],
    layout_review: dict,
    *,
    hybrid_fill: bool = False,
) -> tuple[bytes, dict]:
    """Repack source bboxes from the original canvas into the canonical atlas.

    This is a geometry-only repair: pixels come from the provider's original
    image and are never replaced with generated placeholders or another frame.
    The LLM supplies semantic-to-source regions; deterministic validation then
    packs each region at its existing visual scale (downscaling only when it
    cannot fit the 256px runtime cell).

    ``hybrid_fill`` 用于映射不完整的画布:有可信 bbox 的格用映射,其余格退回
    自己的网格矩形。整表扔掉部分映射改走固定切割,曾把 14/16 已映射好的格
    连带切坏(2026-07-20 像素防线第二跑:12 格像素审计失败,coverage 0.25)。
    """
    from PIL import Image

    if not layout_review.get("enabled") or (
        not hybrid_fill and not layout_review.get("passed")
    ):
        raise AssetGenerationRetryRequired(
            "Spritesheet layout review did not produce a complete semantic mapping; "
            "generation is paused for manual retry."
        )
    source = Image.open(io.BytesIO(raw_layout_content)).convert("RGBA")
    source_width, source_height = source.size
    cell_by_semantic = {
        _cell_demand(cell).semantic_id: cell
        for cell in cells
        if not cell.name.startswith("bonus_")
    }
    canonical_index = {
        _cell_demand(cell).semantic_id: index
        for index, cell in enumerate(cells)
        if not cell.name.startswith("bonus_")
    }
    expected_ids = set(cell_by_semantic)
    mappings = {
        str(frame.get("semantic_id")): frame
        for frame in (layout_review.get("frames") or [])
        if isinstance(frame, dict) and frame.get("semantic_id")
    }
    if not hybrid_fill and set(mappings) != expected_ids:
        missing = sorted(expected_ids - set(mappings))
        extra = sorted(set(mappings) - expected_ids)
        raise AssetGenerationRetryRequired(
            "Spritesheet layout review mapping does not match the semantic contract "
            f"(missing={missing[:6]}, extra={extra[:6]}). Generation is paused for manual retry."
        )

    atlas = Image.new("RGBA", (SHEET_SIZE, SHEET_SIZE), (0, 0, 0, 0))
    used_frame_indexes: set[int] = set()
    used_source_boxes: list[tuple[float, float, float, float, str]] = []
    packed: list[dict] = []
    hybrid_cell_ids: list[str] = []
    for semantic_id, cell in cell_by_semantic.items():
        mapping = mappings.get(semantic_id) or {}
        hybrid_cell = False
        parsed_bbox: tuple[float, float, float, float] | None = None
        bbox = mapping.get("source_bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                candidate = tuple(float(value) for value in bbox)
            except (TypeError, ValueError):
                candidate = None
            if (
                candidate
                and 0.0 <= candidate[0] < candidate[2] <= 1.0
                and 0.0 <= candidate[1] < candidate[3] <= 1.0
            ):
                parsed_bbox = candidate
        mapping_usable = str(mapping.get("verdict") or "") == "pass" and parsed_bbox is not None
        if not mapping_usable:
            if not hybrid_fill:
                if str(mapping.get("verdict") or "") != "pass":
                    raise AssetGenerationRetryRequired(
                        f"Spritesheet layout mapping for {semantic_id} is not a confident pass; "
                        "generation is paused for manual retry."
                    )
                raise AssetGenerationRetryRequired(
                    f"Spritesheet layout mapping for {semantic_id} has no usable source bbox; "
                    "generation is paused for manual retry."
                )
            hybrid_cell = True
            hybrid_cell_ids.append(semantic_id)
            index = canonical_index[semantic_id]
            grid_col, grid_row = index % SHEET_GRID, index // SHEET_GRID
            parsed_bbox = (
                grid_col / SHEET_GRID,
                grid_row / SHEET_GRID,
                (grid_col + 1) / SHEET_GRID,
                (grid_row + 1) / SHEET_GRID,
            )
        else:
            index = int(mapping.get("target_frame_index", mapping.get("frame_index", -1)))
        x0, y0, x1, y1 = parsed_bbox
        if index < 0 or index >= len(cells) or index in used_frame_indexes:
            raise AssetGenerationRetryRequired(
                f"Spritesheet layout mapping for {semantic_id} reuses an invalid target frame; "
                "generation is paused for manual retry."
            )
        used_frame_indexes.add(index)
        if not hybrid_cell:
            # 网格兜底格是位置性的,不代表语义主张;把它计入重叠检测会与
            # 恰好落在同一区域的可信映射互杀。
            for left, top, right, bottom, prior_id in used_source_boxes:
                overlap = max(0.0, min(x1, right) - max(x0, left)) * max(0.0, min(y1, bottom) - max(y0, top))
                area = min((x1 - x0) * (y1 - y0), (right - left) * (bottom - top))
                if area > 0 and overlap / area > 0.92:
                    raise AssetGenerationRetryRequired(
                        f"Spritesheet layout mappings for {semantic_id} and {prior_id} overlap the same source object; "
                        "generation is paused for manual retry."
                    )
            used_source_boxes.append((x0, y0, x1, y1, semantic_id))

        # Add a small amount of context, then trim only transparent edges. This
        # avoids clipping anti-aliased outlines while keeping unrelated objects
        # out of the target cell.
        px0, py0 = x0 * source_width, y0 * source_height
        px1, py1 = x1 * source_width, y1 * source_height
        pad_x, pad_y = max(1.0, (px1 - px0) * 0.04), max(1.0, (py1 - py0) * 0.04)
        crop_box = (
            max(0, int(px0 - pad_x)),
            max(0, int(py0 - pad_y)),
            min(source_width, int(px1 + pad_x + 0.999)),
            min(source_height, int(py1 + pad_y + 0.999)),
        )
        crop = source.crop(crop_box)
        alpha_bbox = crop.getchannel("A").getbbox()
        if alpha_bbox is None:
            if hybrid_cell:
                # 网格兜底格恰好为空:留透明格交给修复轮重画,而不是暂停。
                packed.append(
                    {
                        "semantic_id": semantic_id,
                        "target_frame_index": index,
                        "source_frame_index": -1,
                        "source_bbox": [round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6)],
                        "source_dimensions": [source_width, source_height],
                        "hybrid_grid_fill": True,
                        "empty_source": True,
                    }
                )
                continue
            raise AssetGenerationRetryRequired(
                f"Spritesheet layout bbox for {semantic_id} contains no visible pixels; "
                "generation is paused for manual retry."
            )
        crop = crop.crop(alpha_bbox)
        demand = _cell_demand(cell)
        max_extent = max(crop.size)
        scale = min(1.0, (SHEET_CELL * 0.94) / max_extent) if max_extent else 1.0
        if scale < 1.0:
            crop = crop.resize(
                (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
                Image.LANCZOS,
            )
        target = Image.new("RGBA", (SHEET_CELL, SHEET_CELL), (0, 0, 0, 0))
        anchor_x, anchor_y = demand.anchor
        dest_x = round(float(anchor_x) * SHEET_CELL - crop.width / 2)
        baseline = min(SHEET_CELL - 2, max(0, round(float(anchor_y) * SHEET_CELL)))
        dest_y = baseline - crop.height
        dest_x = max(0, min(SHEET_CELL - crop.width, dest_x))
        dest_y = max(0, min(SHEET_CELL - crop.height, dest_y))
        target.alpha_composite(crop, (dest_x, dest_y))
        col, row = index % SHEET_GRID, index // SHEET_GRID
        atlas.alpha_composite(target, (col * SHEET_CELL, row * SHEET_CELL))
        entry = {
            "semantic_id": semantic_id,
            "target_frame_index": index,
            "source_frame_index": int(mapping.get("source_frame_index") or -1),
            "source_bbox": [round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6)],
            "source_dimensions": [source_width, source_height],
        }
        if hybrid_cell:
            entry["hybrid_grid_fill"] = True
        packed.append(entry)
    out = io.BytesIO()
    atlas.save(out, format="PNG")
    return out.getvalue(), {
        "schema_version": "asset-layout-repack/v1",
        "resegmented": True,
        "source_dimensions": [source_width, source_height],
        "frames": packed,
        "hybrid_cell_ids": hybrid_cell_ids,
    }


def _audit_sheet_frames(content: bytes, cells: tuple[SheetCell, ...]) -> dict:
    """Run the deterministic cell-level audit used by the asset hard gate."""
    from PIL import Image

    image = Image.open(io.BytesIO(content)).convert("RGBA")
    frame_results: list[dict] = []
    for index, cell in enumerate(cells):
        row, col = divmod(index, SHEET_GRID)
        crop = image.crop(
            (col * SHEET_CELL, row * SHEET_CELL, (col + 1) * SHEET_CELL, (row + 1) * SHEET_CELL)
        )
        result = audit_frame(crop, _cell_demand(cell), expected_size=(SHEET_CELL, SHEET_CELL))
        result["frame_index"] = index
        result["required"] = _cell_demand(cell).required
        frame_results.append(result)
    required = [item for item in frame_results if item.get("required", True)]
    passed_required = [item for item in required if item["passed"]]
    failed = [item for item in required if not item["passed"]]
    return {
        "schema_version": "frame-audit/v1",
        "dimensions": list(image.size),
        "frame_count": len(frame_results),
        "frames": frame_results,
        "failed_frame_ids": [item["semantic_id"] for item in failed],
        "required_asset_coverage": round(len(passed_required) / len(required), 4) if required else 1.0,
        "unused_required_frame": 0,
        "passed": not failed,
    }


def _normalize_repair_cell(raw: bytes, content_type: str) -> bytes:
    """Normalize a provider's single-cell response without substituting art.

    Compatible image gateways sometimes ignore the requested 256px size and
    return a larger square canvas (the Opik failure returned 1254x1254). A
    visible-object crop is a lossless semantic normalization path; exact
    1024px legacy sheets retain their historical first-cell adapter behavior.
    """

    from PIL import Image

    try:
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise ProviderGenerationError(f"repair provider returned an invalid image: {exc}") from exc
    if image.size == (SHEET_SIZE, SHEET_SIZE):
        # Some compatible/local image adapters ignore 256x256. Normalize the
        # returned sheet through the same deterministic path and take its first
        # cell; this is an adapter compatibility path, not a visual fallback.
        normalized = Image.open(io.BytesIO(_postprocess_spritesheet(raw, content_type))).convert("RGBA")
        image = normalized.crop((0, 0, SHEET_CELL, SHEET_CELL))
    elif image.size != (SHEET_CELL, SHEET_CELL):
        normalized = _normalize_spritesheet_canvas(raw, content_type)
        alpha_bbox = normalized.getchannel("A").getbbox()
        if alpha_bbox is None:
            raise ProviderGenerationError(
                f"repair provider returned {image.size[0]}x{image.size[1]} with no visible sprite"
            )
        image = normalized.crop(alpha_bbox)
        max_extent = max(image.size)
        scale = min(1.0, (SHEET_CELL * 0.94) / max_extent) if max_extent else 1.0
        if scale < 1.0:
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.LANCZOS,
            )
        target = Image.new("RGBA", (SHEET_CELL, SHEET_CELL), (0, 0, 0, 0))
        target.alpha_composite(
            image,
            (
                max(0, (SHEET_CELL - image.width) // 2),
                max(0, SHEET_CELL - image.height - 2),
            ),
        )
        image = target
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _postprocess_tileset(raw: bytes, content_type: str) -> bytes:
    """Key the generated tileset like a sheet, then downscale per cell to the
    runtime tile grid. Per-cell resize keeps LANCZOS from bleeding one cell's
    colors across its neighbor's border, which would leave semi-transparent
    seams on adjoining floor tiles."""
    from PIL import Image

    keyed = Image.open(io.BytesIO(_postprocess_spritesheet(raw, content_type))).convert("RGBA")
    cell_px = SHEET_SIZE // TILESET_GRID
    out_img = Image.new("RGBA", (TILESET_IMAGE_SIZE, TILESET_IMAGE_SIZE), (0, 0, 0, 0))
    for index in range(TILESET_GRID * TILESET_GRID):
        col, row = index % TILESET_GRID, index // TILESET_GRID
        cell = keyed.crop((col * cell_px, row * cell_px, (col + 1) * cell_px, (row + 1) * cell_px))
        out_img.paste(cell.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS), (col * TILE_SIZE, row * TILE_SIZE))
    out = io.BytesIO()
    out_img.save(out, format="PNG")
    return out.getvalue()
