import io
import json
from types import SimpleNamespace

from PIL import Image, ImageDraw

from app.core.config import settings
from app.services import asset_semantic_review
from app.services.game_assets import SHEET_CELL, SHEET_SIZE, SheetCell, _resegment_spritesheet
from app.services.sprite_pipeline import BatchSpec, SpriteDemand, SpriteDemandManifest


def _fixture() -> tuple[bytes, SpriteDemandManifest, BatchSpec]:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    for index in range(4):
        col, row = index % 2, index // 2
        ImageDraw.Draw(image).rectangle(
            [col * 256 + 80, row * 256 + 60, col * 256 + 184, row * 256 + 232],
            fill=(40, 40, 40, 255),
        )
    out = io.BytesIO()
    image.save(out, format="PNG")
    demands = tuple(
        SpriteDemand(
            semantic_id=f"tower.{state}",
            frame_id=f"tower_{state}",
            object_name="tower",
            state=state,
            consumer_refs=("test",),
            style_group="test",
        )
        for state in ("idle", "attack", "hurt", "dead")
    )
    return (
        out.getvalue(),
        SpriteDemandManifest(demands),
        BatchSpec("sheet", "sheet", tuple(item.semantic_id for item in demands), 2, 2, style_group="test"),
    )


def test_full_sheet_review_returns_failed_semantic_ids(monkeypatch):
    content, manifest, batch = _fixture()
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE", 0.85)

    def fake_chat(system, prompt, **kwargs):
        contract = json.loads(prompt.split("Cell contract (semantic_id and frame_index are immutable):\n", 1)[1])
        cells = [
            {
                "semantic_id": item["semantic_id"],
                "frame_index": item["frame_index"],
                "verdict": "pass",
                "observed_category": "tower",
                "confidence": 0.96,
            }
            for item in contract
        ]
        cells[1].update(
            verdict="fail",
            observed_category="wolf",
            confidence=0.98,
            failed_checks=["semantic_mismatch"],
        )
        return SimpleNamespace(text=json.dumps({"sheet_verdict": "fail", "cells": cells}))

    monkeypatch.setattr(asset_semantic_review.llm, "chat", fake_chat)
    result = asset_semantic_review.review_spritesheet(content, manifest, batch)

    assert result["passed"] is False
    assert result["failed_frame_ids"] == ["tower.attack"]
    assert result["uncertain_frame_ids"] == []
    failed_frame = next(f for f in result["frames"] if f["semantic_id"] == "tower.attack")
    # 自由检查名归一进封闭 rubric,原始名保留在 reported_checks 供排障
    assert failed_frame["failed_checks"] == ["wrong_object"]
    assert failed_frame["reported_checks"] == ["semantic_mismatch"]


def test_low_confidence_is_uncertain_and_never_passes(monkeypatch):
    content, manifest, batch = _fixture()
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE", 0.85)
    calls = {"n": 0}

    def fake_chat(system, prompt, **kwargs):
        calls["n"] += 1
        contract = json.loads(prompt.split("Cell contract (semantic_id and frame_index are immutable):\n", 1)[1])
        return SimpleNamespace(
            text=json.dumps(
                {
                    "sheet_verdict": "pass",
                    "cells": [
                        {
                            "semantic_id": item["semantic_id"],
                            "frame_index": item["frame_index"],
                            "verdict": "pass",
                            "confidence": 0.84,
                        }
                        for item in contract
                    ],
                }
            )
        )

    monkeypatch.setattr(asset_semantic_review.llm, "chat", fake_chat)
    result = asset_semantic_review.review_spritesheet(content, manifest, batch)

    assert calls["n"] == 2, "uncertain 必须触发一次同图复核"
    assert result["recheck_used"] is True
    assert result["passed"] is False
    assert result["failed_frame_ids"] == []
    assert set(result["uncertain_frame_ids"]) == {
        "tower.idle",
        "tower.attack",
        "tower.hurt",
        "tower.dead",
    }


def test_invented_standard_fail_downgrades_and_recheck_resolves(monkeypatch):
    """第十二轮回归:评审自创 missing_required_health_bar 类标准不得判死格子。"""

    content, manifest, batch = _fixture()
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE", 0.85)
    calls = {"n": 0}

    def fake_chat(system, prompt, **kwargs):
        calls["n"] += 1
        contract = json.loads(prompt.split("Cell contract (semantic_id and frame_index are immutable):\n", 1)[1])
        if calls["n"] == 1:
            cells = []
            for item in contract:
                cell = {
                    "semantic_id": item["semantic_id"],
                    "frame_index": item["frame_index"],
                    "verdict": "pass",
                    "confidence": 0.95,
                }
                if item["semantic_id"] == "tower.idle":
                    cell.update(
                        verdict="fail",
                        confidence=0.97,
                        failed_checks=["missing_required_health_bar"],
                    )
                cells.append(cell)
            return SimpleNamespace(text=json.dumps({"sheet_verdict": "fail", "cells": cells}))
        assert [item["semantic_id"] for item in contract] == ["tower.idle"], "复核只审可疑格"
        return SimpleNamespace(
            text=json.dumps(
                {
                    "sheet_verdict": "pass",
                    "cells": [
                        {
                            "semantic_id": "tower.idle",
                            "frame_index": contract[0]["frame_index"],
                            "verdict": "pass",
                            "confidence": 0.96,
                        }
                    ],
                }
            )
        )

    monkeypatch.setattr(asset_semantic_review.llm, "chat", fake_chat)
    result = asset_semantic_review.review_spritesheet(content, manifest, batch)

    assert calls["n"] == 2
    assert result["passed"] is True
    assert result["failed_frame_ids"] == []
    assert result["uncertain_frame_ids"] == []


def test_scoped_review_judges_only_target_cells(monkeypatch):
    content, manifest, batch = _fixture()
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE", 0.85)
    seen: dict = {}

    def fake_chat(system, prompt, **kwargs):
        contract = json.loads(prompt.split("Cell contract (semantic_id and frame_index are immutable):\n", 1)[1])
        seen["contract_ids"] = [item["semantic_id"] for item in contract]
        seen["locked_note"] = "already accepted and locked" in prompt
        seen["reference"] = "Accepted reference cells" in prompt
        return SimpleNamespace(
            text=json.dumps(
                {
                    "sheet_verdict": "fail",
                    "cells": [
                        {
                            "semantic_id": "tower.attack",
                            "frame_index": contract[0]["frame_index"],
                            "verdict": "fail",
                            "confidence": 0.97,
                            "failed_checks": ["duplicate_cell"],
                        }
                    ],
                }
            )
        )

    monkeypatch.setattr(asset_semantic_review.llm, "chat", fake_chat)
    result = asset_semantic_review.review_spritesheet(
        content,
        manifest,
        batch,
        target_semantic_ids=["tower.attack"],
        accepted_context={"tower.idle": "grey stone tower"},
    )

    assert seen["contract_ids"] == ["tower.attack"]
    assert seen["locked_note"] and seen["reference"]
    assert [frame["semantic_id"] for frame in result["frames"]] == ["tower.attack"]
    assert result["failed_frame_ids"] == ["tower.attack"]
    assert result["scoped"] is True


def test_layout_review_returns_source_bboxes_for_resegmentation(monkeypatch):
    content, manifest, batch = _fixture()
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE", 0.85)

    def fake_chat(system, prompt, **kwargs):
        assert "ORIGINAL spritesheet before fixed-grid slicing" in prompt
        assert "source_bbox" in system
        contract = json.loads(prompt.split("Target semantic contract (target_frame_index is only the destination):\n", 1)[1])
        # Deliberately move the source regions away from their destination grid
        # cells; the caller must use these bboxes rather than frame_index.
        cells = [
            {
                "semantic_id": item["semantic_id"],
                "target_frame_index": item["target_frame_index"],
                "source_frame_index": (item["target_frame_index"] + 1) % 4,
                "source_bbox": [0.48, 0.02, 0.98, 0.48] if item["target_frame_index"] == 0 else [0.02, 0.02, 0.48, 0.48],
                "verdict": "pass",
                "confidence": 0.96,
            }
            for item in contract
        ]
        return SimpleNamespace(text=json.dumps({"sheet_verdict": "resegment", "cells": cells}))

    monkeypatch.setattr(asset_semantic_review.llm, "chat", fake_chat)
    result = asset_semantic_review.review_spritesheet_layout(content, manifest, batch)

    assert result["passed"] is True
    assert result["mapping_complete"] is True
    assert result["frames"][0]["target_frame_index"] == 0
    assert result["frames"][0]["source_frame_index"] == 1
    assert result["frames"][0]["source_bbox"] == [0.48, 0.02, 0.98, 0.48]


def test_resegment_uses_source_bbox_instead_of_source_grid():
    source = Image.new("RGBA", (512, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rectangle([12, 48, 116, 220], fill=(40, 80, 220, 255))
    draw.rectangle([268, 28, 384, 216], fill=(220, 70, 40, 255))
    out = io.BytesIO()
    source.save(out, format="PNG")
    cells = (
        SheetCell("red_idle", "red", semantic_id="red.idle"),
        SheetCell("blue_idle", "blue", semantic_id="blue.idle"),
    )
    layout_review = {
        "enabled": True,
        "passed": True,
        "frames": [
            {
                "semantic_id": "red.idle",
                "target_frame_index": 0,
                "source_frame_index": 1,
                "source_bbox": [0.5, 0.05, 0.8, 0.9],
                "verdict": "pass",
            },
            {
                "semantic_id": "blue.idle",
                "target_frame_index": 1,
                "source_frame_index": 0,
                "source_bbox": [0.0, 0.1, 0.25, 0.9],
                "verdict": "pass",
            },
        ],
    }
    packed, metadata = _resegment_spritesheet(out.getvalue(), cells, layout_review)
    result = Image.open(io.BytesIO(packed)).convert("RGBA")

    assert result.size == (SHEET_SIZE, SHEET_SIZE)
    assert metadata["resegmented"] is True
    # Red was on the right in the source, but the semantic mapping puts it in
    # target frame 0; blue is correspondingly placed in frame 1.
    assert result.getpixel((SHEET_CELL // 2, 190))[0] > 150
    assert result.getpixel((SHEET_CELL + SHEET_CELL // 2, 190))[2] > 150
