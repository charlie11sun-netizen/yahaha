"""显示比例纪律 + 空间机制可见性门禁的回归测试(像素防线 2026-07-20 取证后新增)。

取证根因:塔用 setDisplaySize(62,62) 归一化后,升级逻辑每帧 setScale(1+level*0.1)
—— setScale 相对原生 256px 素材帧而非归一化尺寸,塔弹回原生分辨率盖满数格;
且塔的 range 数据(145/130/...)从未画过射程圈。两者都是通用失败类:
① scale:conflict → issue 走 quality 最小 patch;② scale:native → 软告警;
③ 规则消费的 range/radius 数值无任何可见 affordance → 软告警(AreaHint/
Graphics 圆环/hint:area 探针三路证据任一豁免)。
"""

from app.agents import repair, validation_nodes
from app.agents.author_prompts import _RESERVED_PATHS
from app.services.phaser_projects import create_modular_phaser_project

_PAD = "// pad\n" * 80


def _vite_state(play_content: str, code_source: str = "author") -> dict:
    project_files = [
        {"path": "package.json", "content": "{}"},
        {"path": "index.html", "content": "<html><main id='game-container'></main></html>"},
        {"path": "src/main.ts", "content": "import Phaser from 'phaser';\nnew Phaser.Game({});"},
        {"path": "src/scenes/PlayScene.ts", "content": play_content},
    ]
    return {
        "dimension": "2d",
        "artifact_format": "phaser-vite/v1",
        "code_source": code_source,
        "game_spec": {"archetype": "topdown_collect"},
        "game_design": {},
        "validation_result": {"valid": True},
        "generated_files": [{"path": "index.html", "content": "<html><canvas></canvas></html>"}],
        "project_files": project_files,
        "asset_manifest": {"assets": []},
    }


def _play_source(extra: str = "") -> str:
    return (
        _PAD
        + "createCursorKeys();\nthis.juice.shake(0.01); // restart\n"
        + "this.tweens.add({});\n"
        + extra
    )


def _run_qa(
    monkeypatch,
    probes: dict,
    *,
    play_extra: str = "",
    code_source: str = "author",
) -> dict:
    from app.services.sandbox_client import SandboxResult

    state = _vite_state(_play_source(play_extra), code_source=code_source)
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
    return validation_nodes._gameplay_qa(state)


_HEALTHY = {
    "probe:ready": 1,
    "scene:start|PlayScene": 1,
    "backdrop:draw|PlayScene": 1,
    "dom:down|pointer": 3,
    "input:down|PlayScene": 5,
    "ui:interactive": 40,
}

_SPATIAL_DATA = (
    "const towers = [{ attackRange: 145, auraRadius: 90 }, { attackRange: 130 }];\n"
    "const splashRadius = 40;\n"
)


# ---------- ① scale:conflict(setDisplaySize 被绝对 setScale 覆盖) ----------

def test_scale_conflict_is_flagged_and_patchable(monkeypatch):
    probes = dict(_HEALTHY, **{"scale:conflict|sheet": 1})
    result = _run_qa(monkeypatch, probes)
    found = [i for i in result["issues"] if i.startswith("sprites lose their normalized display size")]
    assert found, result["issues"]
    assert "sheet" in found[0]
    kind, patchable = repair._classify_gameplay_failure({"issues": found})
    assert kind == "quality"
    assert patchable == found


def test_scale_conflict_warns_for_template_products(monkeypatch):
    probes = dict(_HEALTHY, **{"scale:conflict|sheet": 1})
    result = _run_qa(monkeypatch, probes, code_source="template")
    assert not any("normalized display size" in i for i in result["issues"])
    assert any("normalized display size" in w for w in result["warnings"])


# ---------- ② scale:native(大素材帧近原生比例渲染) ----------

def test_scale_native_warns_but_never_fails(monkeypatch):
    probes = dict(_HEALTHY, **{"scale:native|sheet#12": 1, "scale:native|sheet#3": 1})
    result = _run_qa(monkeypatch, probes)
    assert any(
        w.startswith("sprites render generated art frames at near-native resolution")
        for w in result["warnings"]
    ), result["warnings"]
    assert not any("near-native resolution" in i for i in result["issues"])


def test_healthy_scale_probes_do_not_flag(monkeypatch):
    result = _run_qa(monkeypatch, dict(_HEALTHY))
    assert not any("display size" in i for i in result["issues"]), result["issues"]
    assert not any("near-native resolution" in w for w in result["warnings"])


# ---------- ③ 空间机制可见性(range/radius 数据无 affordance) ----------

def test_invisible_spatial_extents_warn(monkeypatch):
    result = _run_qa(monkeypatch, dict(_HEALTHY), play_extra=_SPATIAL_DATA)
    found = [w for w in result["warnings"] if w.startswith("gameplay rules consult spatial extents")]
    assert found, result["warnings"]
    assert "attackrange" in found[0]


def test_area_hint_usage_suppresses_spatial_warning(monkeypatch):
    extra = _SPATIAL_DATA + 'AreaHint.circle(this, "sel", x, y, tower.attackRange);\n'
    result = _run_qa(monkeypatch, dict(_HEALTHY), play_extra=extra)
    assert not any("spatial extents" in w for w in result["warnings"]), result["warnings"]


def test_raw_ring_drawing_suppresses_spatial_warning(monkeypatch):
    extra = _SPATIAL_DATA + "gfx.strokeCircle(x, y, tower.attackRange);\n"
    result = _run_qa(monkeypatch, dict(_HEALTHY), play_extra=extra)
    assert not any("spatial extents" in w for w in result["warnings"]), result["warnings"]


def test_runtime_hint_probe_suppresses_spatial_warning(monkeypatch):
    probes = dict(_HEALTHY, **{"hint:area|circle": 2})
    result = _run_qa(monkeypatch, probes, play_extra=_SPATIAL_DATA)
    assert not any("spatial extents" in w for w in result["warnings"]), result["warnings"]


def test_presentation_noise_tokens_are_not_spatial_mechanics(monkeypatch):
    extra = (
        "const cornerRadius = 8;\nconst shadowBlurRadius = 12;\n"
        "const cameraRange = 300;\nconst spawnRadius = 50;\n"
    )
    result = _run_qa(monkeypatch, dict(_HEALTHY), play_extra=extra)
    assert not any("spatial extents" in w for w in result["warnings"]), result["warnings"]


def test_scale_and_spatial_warnings_reach_repair_briefs():
    warnings = [
        "sprites render generated art frames at near-native resolution (scale≈1 ...)",
        "gameplay rules consult spatial extents (attackrange) that are never shown ...",
    ]
    assert repair._advisory_qa_feedback({"warnings": warnings}) == warnings


# ---------- 脚手架内容 ----------

def _scaffold() -> dict[str, str]:
    return {
        str(f["path"]): str(f.get("content") or "")
        for f in create_modular_phaser_project({}, {})
    }


def test_scaffold_ships_area_hint_system():
    files = _scaffold()
    hint = files["src/systems/AreaHint.ts"]
    for token in ("circle(", "rect(", "hide(", "clear(", "hint:area", "gameConfig.palette.accent"):
        assert token in hint, token


def test_scaffold_probe_ships_scale_instrumentation():
    probe = _scaffold()["src/systems/Probe.ts"]
    for token in (
        "scale:conflict",
        "scale:native",
        "setDisplaySize",
        "gwScenery",
        "intendedSizes",
    ):
        assert token in probe, token


def test_backdrop_tags_scenery_for_scale_probe():
    files = _scaffold()
    assert 'setData("gwScenery", true)' in files["src/systems/Backdrop.ts"]


def test_juice_pulse_scales_relative_to_current_scale():
    juice = _scaffold()["src/systems/Juice.ts"]
    assert "scaleX: baseX * factor" in juice
    assert "scaleY: baseY * factor" in juice


def test_area_hint_reserved_from_authors():
    assert "src/systems/AreaHint.ts" in _RESERVED_PATHS
    assert "src/systems/AreaHint.ts" in validation_nodes._STOCK_KIT_FILES
