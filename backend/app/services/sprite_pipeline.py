"""Semantic sprite demand, batching, audit, and atlas helpers.

The image provider is deliberately kept at the *visual* part of the pipeline.
This module owns the contract around it:

``DesignContract -> runtime consumers -> SpriteDemandManifest -> BatchSpec``

Every generated cell has one semantic state.  The provider may still return a
2x2/2x4/4x4 image, but the returned image is treated as an intermediate batch
and is never the runtime contract.  Runtime code consumes the semantic
manifest, while the atlas coordinates remain an implementation detail.
"""
from __future__ import annotations

import hashlib
import io
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


SPRITE_DEMAND_SCHEMA_VERSION = "sprite-demand/v1"
FRAME_AUDIT_SCHEMA_VERSION = "frame-audit/v1"

# UI 覆盖物(血条/文字横幅/名牌/数值)是运行时 HUD 的职责。设计描述把它们写进
# 精灵格要求后,图像模型会往素材里烙字,随后又被评审的 no-text 规则判死——
# 第十二轮(2026-07-19,三线守望)boss.idle 先因"缺抗性横幅"被要求重画、加字后
# 又因 text_present 挂掉,修复循环因此永不收敛。生成提示词、修复提示词与评审
# 契约三侧共用这一份剥离规则,矛盾标准从源头消失。
_UI_OVERLAY_PATTERN = re.compile(
    r"(health\s*bar|hp\s*bar|mana\s*bar|stamina\s*bar|status\s*bar|progress\s*bar|"
    r"text\s*(banner|label|overlay)|resistance\s*(banner|text)|name\s*(tag|plate|label)|"
    r"floating\s*(text|number)|damage\s*number|caption|watermark|tooltip|hud\b|ui\s*overlay|"
    r"血条|体力条|文字|字样|标注|标签|横幅|名牌|数值|气泡)",
    re.IGNORECASE,
)


def strip_ui_overlay_demands(text: Any) -> str:
    """Drop clauses that demand baked-in UI overlays from a cell description.

    Clause-level: "armored knight with a shield, health bar above head" keeps
    the knight and loses the health bar. Returns "" when nothing survives so
    callers can fall back to the frame name.
    """
    raw = " ".join(str(text or "").split())
    if not raw or not _UI_OVERLAY_PATTERN.search(raw):
        return raw
    parts = re.split(r"(?<=[,;，；。.!?])", raw)
    kept = [part for part in parts if not _UI_OVERLAY_PATTERN.search(part)]
    return "".join(kept).strip(" ,;，；。.!?")


def _slug(value: Any, fallback: str = "sprite") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return (text or fallback)[:64]


def _semantic_id(object_name: Any, state: Any, fallback: str = "sprite") -> str:
    return f"{_slug(object_name, fallback)}.{_slug(state, 'default')}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class SpriteDemand:
    """One requested semantic frame.

    ``frame_id`` is the stable local key used inside a sheet.  It is not used
    by gameplay code directly; ``semantic_id`` is the public identity.
    """

    semantic_id: str
    frame_id: str
    object_name: str
    state: str
    consumer_refs: tuple[str, ...] = ()
    required: bool = True
    animated: bool = False
    batch_group: str = ""
    expected_object_count: int = 1
    variant_strategy: str = "generated"
    anchor: tuple[float, float] = (0.5, 1.0)
    style_group: str = "default"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_id": self.semantic_id,
            "frame_id": self.frame_id,
            "object_name": self.object_name,
            "state": self.state,
            "consumer_refs": list(self.consumer_refs),
            "required": self.required,
            "animated": self.animated,
            "batch_group": self.batch_group or self.object_name,
            "expected_object_count": self.expected_object_count,
            "variant_strategy": self.variant_strategy,
            "anchor": list(self.anchor),
            "style_group": self.style_group,
            "metadata": _jsonable(dict(self.metadata)),
        }


@dataclass(frozen=True)
class BatchSpec:
    """A homogeneous provider request and deterministic cell layout."""

    batch_id: str
    group: str
    semantic_ids: tuple[str, ...]
    rows: int
    columns: int
    cell_width: int = 256
    cell_height: int = 256
    padding: int = 0
    style_group: str = "default"

    @property
    def width(self) -> int:
        return self.columns * self.cell_width + max(0, self.columns - 1) * self.padding

    @property
    def height(self) -> int:
        return self.rows * self.cell_height + max(0, self.rows - 1) * self.padding

    def frame_index(self, semantic_id: str) -> int:
        try:
            return self.semantic_ids.index(semantic_id)
        except ValueError as exc:
            raise KeyError(semantic_id) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "group": self.group,
            "semantic_ids": list(self.semantic_ids),
            "rows": self.rows,
            "columns": self.columns,
            "cell_width": self.cell_width,
            "cell_height": self.cell_height,
            "padding": self.padding,
            "style_group": self.style_group,
        }


@dataclass(frozen=True)
class CellRegenerationSpec:
    """A retry for exactly one failed semantic cell.

    The original batch is retained as immutable evidence; references are only
    successful peers from that same batch, so a repair cannot silently drift
    to another visual family or contract revision.
    """

    semantic_id: str
    source_batch: BatchSpec
    reference_semantic_ids: tuple[str, ...] = ()
    failed_checks: tuple[str, ...] = ()
    style_bible: Mapping[str, Any] = field(default_factory=dict)
    contract_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_id": self.semantic_id,
            "source_batch": self.source_batch.to_dict(),
            "reference_semantic_ids": list(self.reference_semantic_ids),
            "failed_checks": list(self.failed_checks),
            "style_bible": _jsonable(dict(self.style_bible)),
            "contract_hash": self.contract_hash,
            "replacement": {
                "semantic_ids": [self.semantic_id],
                "rows": 1,
                "columns": 1,
                "cell_width": self.source_batch.cell_width,
                "cell_height": self.source_batch.cell_height,
                "style_group": self.source_batch.style_group,
            },
        }


@dataclass(frozen=True)
class SpriteDemandManifest:
    """Serializable demand contract consumed by generation and runtime QA."""

    demands: tuple[SpriteDemand, ...] = ()
    style_bible: Mapping[str, Any] = field(default_factory=dict)
    runtime_consumers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    schema_version: str = SPRITE_DEMAND_SCHEMA_VERSION

    @property
    def by_semantic_id(self) -> dict[str, SpriteDemand]:
        return {item.semantic_id: item for item in self.demands}

    @property
    def required(self) -> tuple[SpriteDemand, ...]:
        return tuple(item for item in self.demands if item.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "style_bible": _jsonable(dict(self.style_bible)),
            "runtime_consumers": {key: list(value) for key, value in self.runtime_consumers.items()},
            "demands": [item.to_dict() for item in self.demands],
            "metrics": {
                "required_frame_count": len(self.required),
                "frame_count": len(self.demands),
                "unused_required_frame": 0,
            },
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "SpriteDemandManifest":
        raw = raw or {}
        demands: list[SpriteDemand] = []
        for item in raw.get("demands") or []:
            if not isinstance(item, Mapping):
                continue
            anchor = item.get("anchor") or (0.5, 1.0)
            try:
                anchor_tuple = (float(anchor[0]), float(anchor[1]))
            except (TypeError, ValueError, IndexError):
                anchor_tuple = (0.5, 1.0)
            demands.append(
                SpriteDemand(
                    semantic_id=str(item.get("semantic_id") or ""),
                    frame_id=str(item.get("frame_id") or item.get("semantic_id") or ""),
                    object_name=str(item.get("object_name") or "sprite"),
                    state=str(item.get("state") or "default"),
                    consumer_refs=tuple(str(ref) for ref in (item.get("consumer_refs") or [])),
                    required=bool(item.get("required", True)),
                    animated=bool(item.get("animated", False)),
                    batch_group=str(item.get("batch_group") or item.get("object_name") or "sprite"),
                    expected_object_count=max(1, int(item.get("expected_object_count") or 1)),
                    variant_strategy=str(item.get("variant_strategy") or "generated"),
                    anchor=anchor_tuple,
                    style_group=str(item.get("style_group") or "default"),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        consumers = {
            str(key): tuple(str(ref) for ref in (value or []))
            for key, value in (raw.get("runtime_consumers") or {}).items()
            if isinstance(value, (list, tuple, set))
        }
        return cls(
            tuple(item for item in demands if item.semantic_id),
            dict(raw.get("style_bible") or {}),
            consumers,
            str(raw.get("schema_version") or SPRITE_DEMAND_SCHEMA_VERSION),
        )


def _consumer_map(runtime_consumers: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = defaultdict(list)
    if isinstance(runtime_consumers, Mapping):
        for key, refs in runtime_consumers.items():
            if isinstance(refs, str):
                refs = [refs]
            if isinstance(refs, Iterable):
                result[str(key)].extend(str(ref) for ref in refs if str(ref))
    elif isinstance(runtime_consumers, Sequence):
        for item in runtime_consumers:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("semantic_id") or item.get("id") or "")
            ref = str(item.get("consumer") or item.get("consumer_ref") or item.get("path") or "")
            if key and ref:
                result[key].append(ref)
    return {key: tuple(dict.fromkeys(refs)) for key, refs in result.items()}


def _states(raw: Mapping[str, Any], default: Sequence[str]) -> list[str]:
    value = raw.get("states") or raw.get("animation_states") or raw.get("semantic_states")
    if isinstance(value, Mapping):
        value = list(value.keys())
    if isinstance(value, str):
        value = [value]
    states = [str(item).strip() for item in (value or default) if str(item).strip()]
    return list(dict.fromkeys(states)) or list(default)


def build_sprite_demand_manifest(
    design: Mapping[str, Any] | None,
    runtime_consumers: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    include_optional_states: bool = True,
) -> SpriteDemandManifest:
    """Derive semantic demands from a design contract.

    Names are normalized only for IDs; the original object description remains
    in metadata.  Explicit runtime consumers win.  Core design states are
    required by default, while extra states can be marked optional by the
    design (`required: false`) or by omitting their consumer in strict mode.
    """

    design = design or {}
    consumers = _consumer_map(runtime_consumers or design.get("runtime_consumers"))
    demands: list[SpriteDemand] = []
    seen: set[str] = set()

    def add(
        object_name: Any,
        state: str,
        *,
        raw: Mapping[str, Any] | None = None,
        default_required: bool = True,
        animated: bool = False,
        batch_group: str | None = None,
        variant_strategy: str = "generated",
        expected_object_count: int = 1,
    ) -> None:
        raw = raw or {}
        semantic = str(raw.get("semantic_id") or _semantic_id(object_name, state))
        if semantic in seen:
            return
        seen.add(semantic)
        refs = tuple(consumers.get(semantic, ()))
        # A design-level consumer declaration is useful before codegen; it is
        # replaced by exact file references once runtime annotation runs.
        inferred_ref = f"design:{_slug(object_name)}" if default_required else ""
        if not refs and inferred_ref:
            refs = (inferred_ref,)
        required = bool(raw.get("required", default_required))
        if consumers and semantic not in consumers and not bool(raw.get("required")):
            required = False
        frame_id = _slug(raw.get("frame_id") or semantic.replace(".", "_"))
        demands.append(
            SpriteDemand(
                semantic_id=semantic,
                frame_id=frame_id,
                object_name=str(object_name),
                state=str(state),
                consumer_refs=refs,
                required=required,
                animated=animated,
                batch_group=str(batch_group or _slug(object_name)),
                expected_object_count=expected_object_count,
                variant_strategy=str(raw.get("variant_strategy") or variant_strategy),
                anchor=tuple(raw.get("anchor") or (0.5, 1.0)),
                style_group=str(raw.get("style_group") or "default"),
                metadata={"visual": raw.get("visual"), "role": raw.get("role")},
            )
        )

    player = design.get("player") if isinstance(design.get("player"), Mapping) else {}
    player_states = _states(player, ("idle", "move_a", "move_b", "action"))
    if include_optional_states:
        for state in ("hurt", "jump", "death", "victory"):
            if state not in player_states and (state in player.get("states", {}) if isinstance(player.get("states"), Mapping) else True):
                player_states.append(state)
    for state in player_states:
        add("player", state, raw=player, animated=state.startswith("move"), batch_group="player")

    entities = [item for item in (design.get("entities") or []) if isinstance(item, Mapping)]
    boss = design.get("boss")
    if isinstance(boss, Mapping) and boss.get("name") and not any(str(e.get("name")) == str(boss.get("name")) for e in entities):
        entities.append({**boss, "role": "boss"})
    for entity in entities:
        name = entity.get("id") or entity.get("name") or "entity"
        raw_name = str(name)
        level_match = re.match(r"^(.+?)[._-]level[_-]?(\d+)$", raw_name, re.IGNORECASE)
        level_object = level_match.group(1) if level_match else name
        level_state = f"level_{level_match.group(2)}" if level_match else None
        role = str(entity.get("role") or entity.get("type") or "other").lower()
        if role.startswith(("enemy", "boss", "hazard")):
            defaults = ("idle", "attack") + (("special",) if role.startswith("boss") else ())
            states = _states(entity, defaults)
        elif role.startswith(("item", "pickup", "powerup")):
            states = _states(entity, ("idle", "activated"))
        else:
            states = _states(entity, ("default",))
        if level_state:
            states = [level_state]
        for state in states:
            add(level_object, state, raw=entity, default_required=True, animated=state not in {"idle", "default"}, batch_group=_slug(level_object))

    for collection_name in ("powerups", "reward_items", "items"):
        for item in design.get(collection_name) or []:
            if isinstance(item, Mapping) and item.get("name"):
                add(item.get("name"), "idle", raw=item, batch_group=_slug(item.get("name")))
                add(item.get("name"), "activated", raw=item, animated=True, batch_group=_slug(item.get("name")))

    # Effects are cheap and generally better made as programmatic variants.
    for effect in ("projectile", "explosion", "flash"):
        add(f"effect_{effect}", "default", default_required=False, variant_strategy="programmatic", batch_group="effects")

    style = {
        "theme": design.get("theme") or design.get("visual_style"),
        "visual_style": design.get("visual_style"),
        "palette": design.get("palette") or {},
    }
    return SpriteDemandManifest(tuple(demands), style, consumers)


def build_batch_specs(
    manifest: SpriteDemandManifest | Mapping[str, Any],
    *,
    max_cells: int = 16,
    cell_width: int = 256,
    cell_height: int = 256,
    columns: int | None = None,
    include_optional: bool = False,
) -> list[BatchSpec]:
    """Group only same-object/style demands into deterministic batches."""

    manifest = manifest if isinstance(manifest, SpriteDemandManifest) else SpriteDemandManifest.from_dict(manifest)
    max_cells = max(1, int(max_cells))
    grouped: dict[tuple[str, str], list[SpriteDemand]] = defaultdict(list)
    for demand in manifest.demands:
        if not include_optional and not demand.required:
            continue
        if demand.variant_strategy == "programmatic":
            continue
        grouped[(demand.batch_group or demand.object_name, demand.style_group)].append(demand)
    batches: list[BatchSpec] = []
    for (group, style_group), items in grouped.items():
        for offset in range(0, len(items), max_cells):
            chunk = items[offset : offset + max_cells]
            if columns is None:
                # Prefer provider-friendly 2x2 / 2x4 / 4x4 batches.  Empty
                # slots are transparent padding, not additional demands.
                cols = 2 if len(chunk) <= 4 else 4
            else:
                cols = max(1, min(int(columns), len(chunk)))
            rows = 2 if len(chunk) <= 4 else (2 if len(chunk) <= 8 else 4)
            rows = max(rows, (len(chunk) + cols - 1) // cols)
            batches.append(
                BatchSpec(
                    batch_id=f"batch_{len(batches) + 1:03d}",
                    group=group,
                    semantic_ids=tuple(item.semantic_id for item in chunk),
                    rows=rows,
                    columns=cols,
                    cell_width=int(cell_width),
                    cell_height=int(cell_height),
                    style_group=style_group,
                )
            )
    return batches


def _rgba_image(value: Any):
    from PIL import Image

    if isinstance(value, Image.Image):
        return value.convert("RGBA")
    if isinstance(value, (bytes, bytearray)):
        return Image.open(io.BytesIO(value)).convert("RGBA")
    raise TypeError("expected a PIL image or image bytes")


def _component_pixel_sizes(mask: list[bool], width: int, height: int, threshold: int) -> list[int]:
    """Sizes of connected alpha components with at least ``threshold`` pixels."""

    seen = bytearray(width * height)
    sizes: list[int] = []
    for index, active in enumerate(mask):
        if not active or seen[index]:
            continue
        queue = deque([index])
        seen[index] = 1
        pixels = 0
        while queue:
            current = queue.popleft()
            pixels += 1
            x, y = current % width, current // width
            for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                nx, ny = neighbour
                if 0 <= nx < width and 0 <= ny < height:
                    ni = ny * width + nx
                    if mask[ni] and not seen[ni]:
                        seen[ni] = 1
                        queue.append(ni)
        if pixels >= threshold:
            sizes.append(pixels)
    return sizes


def audit_frame(
    image: Any,
    demand: SpriteDemand | Mapping[str, Any],
    *,
    expected_size: tuple[int, int] = (256, 256),
    reference_style: str | None = None,
    semantic_match: bool | None = None,
) -> dict[str, Any]:
    """Audit one cell and return machine-readable evidence.

    Object count is intentionally conservative: tiny disconnected pixels are
    ignored, while two sizeable silhouettes fail the `expected_object_count=1`
    rule that catches the classic "three buildings in one cell" error.
    """

    demand = demand if isinstance(demand, SpriteDemand) else SpriteDemandManifest.from_dict({"demands": [demand]}).demands[0]
    img = _rgba_image(image)
    width, height = img.size
    pixels = list(img.getdata())
    alpha = [a >= 16 for _, _, _, a in pixels]
    visible_pixels = [(r, g, b) for (r, g, b, a) in pixels if a >= 16]
    if visible_pixels:
        mean_rgb = tuple(int(sum(pixel[channel] for pixel in visible_pixels) / len(visible_pixels)) for channel in range(3))
    else:
        mean_rgb = (0, 0, 0)
    style_signature = hashlib.sha1(bytes(mean_rgb)).hexdigest()[:12]
    threshold = max(8, int(width * height * 0.0002))
    # 主体计数只认与最大剪影"大小可比"(≥15%)的组件:动作帧的挥砍弧光、
    # 粒子、飞溅碎屑是主体的装饰而非第二个物体——把它们计成物体曾让 7 个
    # 健康格进修复循环烧光预算(2026-07-19 像素防线取证:player.action 被数出
    # 24 个"物体"而锚点误差仅 0.008)。两栋楼挤一格的经典错误仍会被抓:
    # 第二栋楼与第一栋大小可比。
    component_sizes = _component_pixel_sizes(alpha, width, height, threshold)
    largest_component = max(component_sizes) if component_sizes else 0
    major_floor = max(threshold, int(largest_component * 0.15))
    object_count = sum(1 for size in component_sizes if size >= major_floor)
    visible = [index for index, active in enumerate(alpha) if active]
    if visible:
        xs = [index % width for index in visible]
        ys = [index // width for index in visible]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        anchor = ((bbox[0] + bbox[2]) / 2 / width, bbox[3] / height)
    else:
        bbox = None
        anchor = None
    touches_boundary = bool(visible) and any(
        x == 0 or y == 0 or x == width - 1 or y == height - 1
        for x, y in ((index % width, index // width) for index in visible)
    )
    anchor_error = None
    if anchor is not None:
        anchor_error = round(((anchor[0] - demand.anchor[0]) ** 2 + (anchor[1] - demand.anchor[1]) ** 2) ** 0.5, 4)
    checks = {
        "size": [width, height] == [int(expected_size[0]), int(expected_size[1])],
        "transparent_background": any(a < 16 for _, _, _, a in pixels),
        "cell_boundary": not touches_boundary,
        "single_expected_object": object_count == demand.expected_object_count,
        "semantic_match": semantic_match is not False,
        "anchor_stable": anchor_error is None or anchor_error <= 0.22,
        "runtime_consumer": bool(demand.consumer_refs) if demand.required else True,
        "style_consistent": reference_style is None or reference_style == demand.style_group,
    }
    passed = all(checks.values())
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "schema_version": FRAME_AUDIT_SCHEMA_VERSION,
        "semantic_id": demand.semantic_id,
        "frame_id": demand.frame_id,
        "passed": passed,
        "checks": checks,
        "failed_checks": failed,
        "expected_object_count": demand.expected_object_count,
        "detected_object_count": object_count,
        "bbox": list(bbox) if bbox else None,
        "anchor": list(anchor) if anchor else None,
        "anchor_error": anchor_error,
        "style_signature": style_signature,
    }


def audit_batch(
    raw: Any,
    batch: BatchSpec,
    manifest: SpriteDemandManifest | Mapping[str, Any],
    *,
    fail_required_only: bool = False,
) -> dict[str, Any]:
    """Slice and audit every cell in a generated batch."""

    manifest = manifest if isinstance(manifest, SpriteDemandManifest) else SpriteDemandManifest.from_dict(manifest)
    by_id = manifest.by_semantic_id
    image = _rgba_image(raw)
    expected = (batch.width, batch.height)
    dimensions_valid = image.size == expected
    frames: list[dict[str, Any]] = []
    for index, semantic_id in enumerate(batch.semantic_ids):
        demand = by_id.get(semantic_id)
        if demand is None:
            continue
        col, row = index % batch.columns, index // batch.columns
        x = col * (batch.cell_width + batch.padding)
        y = row * (batch.cell_height + batch.padding)
        cell = image.crop((x, y, x + batch.cell_width, y + batch.cell_height))
        result = audit_frame(cell, demand, expected_size=(batch.cell_width, batch.cell_height))
        result["frame_index"] = index
        result["batch_id"] = batch.batch_id
        if not dimensions_valid:
            result["passed"] = False
            result["failed_checks"] = list(dict.fromkeys(["batch_dimensions", *result["failed_checks"]]))
            result["checks"]["batch_dimensions"] = False
        frames.append(result)
    # Compare anchors within each homogeneous batch.  Per-frame expected
    # anchors catch gross offsets; this cross-frame check catches a wobbling
    # baseline that makes an animation look like it jumps.
    anchors_by_group: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for result in frames:
        anchor = result.get("anchor")
        demand = by_id.get(result["semantic_id"])
        if anchor and demand:
            anchors_by_group[demand.batch_group].append((float(anchor[0]), float(anchor[1])))
    anchor_stability: dict[str, bool] = {}
    for group, anchors in anchors_by_group.items():
        if len(anchors) < 2:
            anchor_stability[group] = True
            continue
        max_delta = max(
            ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
            for left in anchors
            for right in anchors
        )
        anchor_stability[group] = max_delta <= 0.18
    style_consistency: dict[str, bool] = {}
    for group in set(by_id[item["semantic_id"]].batch_group for item in frames if item["semantic_id"] in by_id):
        signatures = [item.get("style_signature") for item in frames if by_id[item["semantic_id"]].batch_group == group]
        # The signature is a diagnostic hint, not a pixel-equality gate.  A
        # batch remains consistent when at least one visual signature repeats.
        style_consistency[group] = len(signatures) < 2 or len(set(signatures)) < len(signatures)
    for result in frames:
        demand = by_id.get(result["semantic_id"])
        if demand and not anchor_stability.get(demand.batch_group, True):
            result["checks"]["anchor_group_stable"] = False
            result["failed_checks"] = list(dict.fromkeys(["anchor_group_stable", *result["failed_checks"]]))
            result["passed"] = False
    failed = [item for item in frames if not item["passed"] and (not fail_required_only or by_id[item["semantic_id"]].required)]
    required = [item for item in frames if by_id[item["semantic_id"]].required]
    covered = [item for item in required if item["passed"]]
    return {
        "schema_version": FRAME_AUDIT_SCHEMA_VERSION,
        "batch_id": batch.batch_id,
        "dimensions_valid": dimensions_valid,
        "frames": frames,
        "failed_frame_ids": [item["semantic_id"] for item in failed],
        "anchor_stability": anchor_stability,
        "style_consistency": style_consistency,
        "required_asset_coverage": round(len(covered) / len(required), 4) if required else 1.0,
        "unused_required_frame": 0,
        "passed": not failed,
    }


def build_cell_regeneration_specs(
    audit: Mapping[str, Any],
    batch: BatchSpec,
    *,
    style_bible: Mapping[str, Any] | None = None,
    contract_hash: str | None = None,
) -> list[CellRegenerationSpec]:
    """Plan retries for failed cells only, reusing batch/style references."""

    failed_ids = {
        str(item)
        for item in (audit.get("failed_frame_ids") or [])
        if str(item) in batch.semantic_ids
    }
    passed_ids = tuple(
        str(frame.get("semantic_id"))
        for frame in (audit.get("frames") or [])
        if frame.get("passed") and str(frame.get("semantic_id")) in batch.semantic_ids
    )
    failures_by_id = {
        str(frame.get("semantic_id")): tuple(str(item) for item in (frame.get("failed_checks") or []))
        for frame in (audit.get("frames") or [])
    }
    return [
        CellRegenerationSpec(
            semantic_id=semantic_id,
            source_batch=batch,
            reference_semantic_ids=passed_ids,
            failed_checks=failures_by_id.get(semantic_id, ()),
            style_bible=dict(style_bible or {}),
            contract_hash=contract_hash,
        )
        for semantic_id in batch.semantic_ids
        if semantic_id in failed_ids
    ]


def pack_atlas(
    frames: Mapping[str, Any] | Sequence[tuple[str, Any]],
    *,
    cell_width: int = 256,
    cell_height: int = 256,
    columns: int = 4,
    padding: int = 0,
) -> tuple[bytes, dict[str, dict[str, Any]]]:
    """Pack individually validated frames into a PNG atlas and map IDs."""

    from PIL import Image

    items = list(frames.items()) if isinstance(frames, Mapping) else list(frames)
    columns = max(1, int(columns))
    rows = (len(items) + columns - 1) // columns
    width = columns * cell_width + max(0, columns - 1) * padding
    height = max(1, rows * cell_height + max(0, rows - 1) * padding)
    atlas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mapping: dict[str, dict[str, Any]] = {}
    for index, (semantic_id, value) in enumerate(items):
        cell = _rgba_image(value).resize((cell_width, cell_height))
        col, row = index % columns, index // columns
        x, y = col * (cell_width + padding), row * (cell_height + padding)
        atlas.alpha_composite(cell, (x, y))
        mapping[str(semantic_id)] = {
            "frame_id": f"f_{index:03d}",
            "frame_index": index,
            "x": x,
            "y": y,
            "width": cell_width,
            "height": cell_height,
            "anchor": [0.5, 1.0],
        }
    output = io.BytesIO()
    atlas.save(output, format="PNG")
    return output.getvalue(), mapping


def apply_programmatic_variant(image: Any, variant: str, *, color: tuple[int, int, int, int] = (255, 80, 80, 120)) -> bytes:
    """Create cheap state variants without another model call."""

    from PIL import Image, ImageEnhance, ImageOps

    base = _rgba_image(image)
    variant = str(variant or "").lower()
    if variant in {"selected", "highlight"}:
        overlay = Image.new("RGBA", base.size, color)
        base = Image.alpha_composite(base, overlay)
    elif variant in {"hurt", "damaged", "red_flash"}:
        red = Image.new("RGBA", base.size, color)
        base = Image.alpha_composite(base, red)
    elif variant in {"shadow", "silhouette"}:
        alpha = base.getchannel("A")
        base = Image.new("RGBA", base.size, (0, 0, 0, 0))
        base.putalpha(alpha.point(lambda value: int(value * 0.55)))
    elif variant in {"desaturate", "disabled"}:
        base = ImageEnhance.Color(base).enhance(0.2)
    elif variant == "outline":
        alpha = base.getchannel("A")
        outline = ImageOps.expand(alpha, border=2, fill=160).crop((2, 2, alpha.width + 2, alpha.height + 2))
        base.putalpha(outline)
    output = io.BytesIO()
    base.save(output, format="PNG")
    return output.getvalue()


def semantic_manifest_for_sheet(
    sheet_key: str,
    batch: BatchSpec,
    manifest: SpriteDemandManifest | Mapping[str, Any],
    *,
    frame_names: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the runtime semantic-ID -> sheet/frame mapping."""

    manifest = manifest if isinstance(manifest, SpriteDemandManifest) else SpriteDemandManifest.from_dict(manifest)
    names = list(frame_names or [])
    result: dict[str, dict[str, Any]] = {}
    for index, semantic_id in enumerate(batch.semantic_ids):
        demand = manifest.by_semantic_id.get(semantic_id)
        if not demand:
            continue
        frame_id = names[index] if index < len(names) else demand.frame_id
        result[semantic_id] = {
            "sheet": sheet_key,
            "frame": f"f_{index:03d}",
            "frame_id": f"f_{index:03d}",
            "legacy_frame": frame_id,
            "frame_index": index,
            "anchor": list(demand.anchor),
            "required": demand.required,
            "consumer_refs": list(demand.consumer_refs),
        }
    return result


__all__ = [
    "SPRITE_DEMAND_SCHEMA_VERSION",
    "FRAME_AUDIT_SCHEMA_VERSION",
    "SpriteDemand",
    "SpriteDemandManifest",
    "BatchSpec",
    "CellRegenerationSpec",
    "build_sprite_demand_manifest",
    "build_batch_specs",
    "audit_frame",
    "audit_batch",
    "build_cell_regeneration_specs",
    "pack_atlas",
    "apply_programmatic_variant",
    "semantic_manifest_for_sheet",
]
