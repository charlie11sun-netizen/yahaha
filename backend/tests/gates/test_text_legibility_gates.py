"""Genre-neutral runtime and visual gates for essential game text."""

from app.agents import repair, validation_nodes
from app.services.phaser_projects import create_modular_phaser_project


_PAD = "// pad\n" * 80


def _state(code_source: str = "author") -> dict:
    play = _PAD + "createCursorKeys();\nthis.juice.shake(0.01); // restart\nthis.tweens.add({});\n"
    return {
        "dimension": "2d",
        "artifact_format": "phaser-vite/v1",
        "code_source": code_source,
        # A rhythm archetype guards against accidentally making this a
        # tower-defense-only policy.
        "game_spec": {"archetype": "rhythm"},
        "game_design": {},
        "validation_result": {"valid": True},
        "generated_files": [
            {"path": "index.html", "content": "<html><canvas></canvas></html>"}
        ],
        "project_files": [
            {"path": "package.json", "content": "{}"},
            {
                "path": "index.html",
                "content": "<html><main id='game-container'></main></html>",
            },
            {
                "path": "src/main.ts",
                "content": "import Phaser from 'phaser';\nnew Phaser.Game({});",
            },
            {"path": "src/scenes/PlayScene.ts", "content": play},
        ],
        "asset_manifest": {"assets": []},
    }


_HEALTHY = {
    "probe:ready": 1,
    "scene:start|PlayScene": 1,
    "backdrop:draw|PlayScene": 1,
    "dom:down|pointer": 3,
    "input:down|PlayScene": 5,
    "ui:interactive": 20,
}


def _run(monkeypatch, probes: dict, *, code_source: str = "author") -> dict:
    from app.services.sandbox_client import SandboxResult

    monkeypatch.setattr(
        validation_nodes.sandbox_client,
        "run_bundle",
        lambda *args, **kwargs: SandboxResult(
            ok=True,
            frames_observed=30,
            load_ms=500,
            probes=probes,
            probes_start={},
            frames_start=0,
            input_attempted=True,
            inputs_sent=["pointer:canvas-center"],
        ),
    )
    return validation_nodes._gameplay_qa(_state(code_source))


def test_blobbed_glyph_probe_is_hard_and_patchable_for_authored_games(monkeypatch):
    probes = dict(
        _HEALTHY,
        **{
            "text:blob|PlayScene,font=18.0,stroke=3.0,contrast=1.09,text=伤害40 射程120": 1,
        },
    )
    result = _run(monkeypatch, probes)
    found = [
        item
        for item in result["issues"]
        if item.startswith("essential UI text uses outlines that obscure glyphs")
    ]
    assert found, result["issues"]
    assert "dense CJK/Japanese/Korean" in found[0]
    kind, patchable = repair._classify_gameplay_failure({"issues": found})
    assert kind == "quality"
    assert patchable == found


def test_tiny_effective_text_probe_is_hard_and_patchable_across_genres(monkeypatch):
    probes = dict(
        _HEALTHY,
        **{
            "text:tiny|PlayScene,effective=9.8,source=16.0,text=PERFECT WINDOW": 1,
        },
    )
    result = _run(monkeypatch, probes)
    found = [
        item
        for item in result["issues"]
        if item.startswith("essential UI text renders below 12 CSS pixels")
    ]
    assert found, result["issues"]
    kind, patchable = repair._classify_gameplay_failure({"issues": found})
    assert kind == "quality"
    assert patchable == found


def test_text_probes_warn_for_template_products(monkeypatch):
    probes = dict(
        _HEALTHY,
        **{
            "text:blob|PlayScene,font=18.0,stroke=3.0,contrast=1.09,text=价格120": 1,
            "text:tiny|PlayScene,effective=9.8,source=16.0,text=PAUSE": 1,
        },
    )
    result = _run(monkeypatch, probes, code_source="template")
    assert not any(item.startswith("essential UI text") for item in result["issues"])
    assert any(item.startswith("essential UI text uses outlines") for item in result["warnings"])
    assert any(item.startswith("essential UI text renders below") for item in result["warnings"])


def test_healthy_text_probes_do_not_flag(monkeypatch):
    result = _run(monkeypatch, dict(_HEALTHY))
    assert not any(item.startswith("essential UI text") for item in result["issues"])
    assert not any(item.startswith("essential UI text") for item in result["warnings"])


def test_scaffold_probe_contains_live_text_legibility_instrumentation():
    files = {
        str(item["path"]): str(item.get("content") or "")
        for item in create_modular_phaser_project({}, {})
    }
    probe = files["src/systems/Probe.ts"]
    for token in (
        "sampleTextLegibility",
        "text:blob",
        "text:tiny",
        "contrastRatio",
        "denseGlyphs",
        "getBoundingClientRect",
    ):
        assert token in probe, token

