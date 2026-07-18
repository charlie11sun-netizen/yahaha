import io

from PIL import Image, ImageDraw

from app.services.sprite_pipeline import (
    BatchSpec,
    SpriteDemandManifest,
    apply_programmatic_variant,
    audit_frame,
    build_batch_specs,
    build_cell_regeneration_specs,
    build_sprite_demand_manifest,
    pack_atlas,
)
from app.services.game_assets import plan_game_assets


def test_demand_manifest_keeps_building_levels_as_semantic_states():
    manifest = build_sprite_demand_manifest(
        {
            "entities": [
                {"name": "residential.level_1", "role": "structure", "visual": "bungalow"},
                {"name": "residential.level_2", "role": "structure", "visual": "townhouse"},
                {"name": "residential.level_3", "role": "structure", "visual": "apartment"},
            ]
        }
    )
    ids = {item.semantic_id for item in manifest.demands}
    assert {"residential.level_1", "residential.level_2", "residential.level_3"} <= ids
    batches = build_batch_specs(manifest)
    residential = [batch for batch in batches if batch.group == "residential"]
    assert len(residential) == 1
    assert residential[0].semantic_ids == (
        "residential.level_1",
        "residential.level_2",
        "residential.level_3",
    )


def test_frame_audit_flags_multiple_subjects_in_one_cell():
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 80, 88, 192), fill=(20, 120, 220, 255))
    draw.rectangle((164, 80, 228, 192), fill=(220, 80, 40, 255))
    demand = next(
        item
        for item in build_sprite_demand_manifest({"entities": [{"name": "residential", "role": "structure"}]}).demands
        if item.semantic_id == "residential.default"
    )
    result = audit_frame(image, demand)
    assert result["detected_object_count"] == 2
    assert "single_expected_object" in result["failed_checks"]
    assert not result["passed"]


def test_regeneration_plan_retries_only_failed_cell_with_same_batch_and_style():
    batch = BatchSpec(
        batch_id="city-buildings",
        group="residential",
        semantic_ids=("residential.level_1", "residential.level_2"),
        rows=1,
        columns=2,
        style_group="city-night",
    )
    audit = {
        "failed_frame_ids": ["residential.level_2"],
        "frames": [
            {"semantic_id": "residential.level_1", "passed": True},
            {
                "semantic_id": "residential.level_2",
                "passed": False,
                "failed_checks": ["single_expected_object"],
            },
        ],
    }
    retries = build_cell_regeneration_specs(
        audit,
        batch,
        style_bible={"theme": "neon city"},
        contract_hash="sha256:contract",
    )
    assert [item.semantic_id for item in retries] == ["residential.level_2"]
    retry = retries[0].to_dict()
    assert retry["source_batch"] == batch.to_dict()
    assert retry["reference_semantic_ids"] == ["residential.level_1"]
    assert retry["replacement"]["semantic_ids"] == ["residential.level_2"]
    assert retry["contract_hash"] == "sha256:contract"


def test_pack_atlas_and_programmatic_variant_produce_runtime_safe_mapping():
    base = Image.new("RGBA", (32, 32), (20, 40, 80, 255))
    atlas, mapping = pack_atlas({"residential.level_3": base}, cell_width=32, cell_height=32, columns=1)
    assert Image.open(io.BytesIO(atlas)).size == (32, 32)
    assert mapping["residential.level_3"]["frame_id"] == "f_000"
    variant = Image.open(io.BytesIO(apply_programmatic_variant(base, "selected")))
    assert variant.mode == "RGBA" and variant.size == base.size
    manifest = SpriteDemandManifest.from_dict(
        {"demands": [{"semantic_id": "residential.level_3", "frame_id": "f_000", "object_name": "residential", "state": "level_3"}]}
    )
    assert manifest.by_semantic_id["residential.level_3"].frame_id == "f_000"


def test_plan_can_prune_generation_to_explicit_runtime_consumers():
    plans = plan_game_assets(
        {
            "game_spec": {"title": "City"},
            "game_design": {
                "entities": [
                    {"name": "residential_level_1", "role": "structure"},
                    {"name": "residential_level_2", "role": "structure"},
                    {"name": "residential_level_3", "role": "structure"},
                ]
            },
            "runtime_consumers": {"residential.level_3": ["src/world/Buildings.ts"]},
        }
    )
    frames = [cell.semantic_id for item in plans if item.sheet_cells for cell in item.sheet_cells if cell.semantic_id]
    assert frames == ["residential.level_3"]
