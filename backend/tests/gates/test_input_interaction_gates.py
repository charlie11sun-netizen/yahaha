"""交互探针门禁的回归测试(像素市长 2026-07-17 三类"按钮点不动"取证后新增)。

覆盖:①注入指针到达页面但场景零处理 → issue;②安静尾窗内 interactive 注册持续
增长(UI 每帧重建)→ issue;③addKey 解析不出 keycode 的死键注册 → issue;
④canvas 0×0 → warning;三类 issue 均走 quality 最小 patch 分类;正例(正常计数)
不误报;脚手架含 InputRouter/新探针钩子/内联关键尺寸样式。
"""

from app.agents import repair, validation_nodes
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
    probes_start: dict | None = None,
    frames_start: int = 0,
    frames_observed: int = 30,
    inputs_sent: list[str] | None = None,
    code_source: str = "author",
) -> dict:
    from app.services.sandbox_client import SandboxResult

    state = _vite_state(_play_source(), code_source=code_source)
    monkeypatch.setattr(
        validation_nodes.sandbox_client,
        "run_bundle",
        lambda *args, **kwargs: SandboxResult(
            ok=True,
            frames_observed=frames_observed,
            load_ms=500,
            probes=probes,
            probes_start=probes_start or {},
            frames_start=frames_start,
            input_attempted=True,
            inputs_sent=inputs_sent or [],
        ),
    )
    return validation_nodes._gameplay_qa(state)


_HEALTHY = {
    "probe:ready": 1,
    "scene:start|PlayScene": 1,
    "backdrop:draw|PlayScene": 1,
    "dom:down|pointer": 3,
    "dom:down|key": 10,
    "input:down|PlayScene": 5,
    "ui:interactive": 40,
}


def test_dead_pointer_pipeline_is_flagged_and_patchable(monkeypatch):
    probes = dict(_HEALTHY)
    probes.pop("input:down|PlayScene")
    result = _run_qa(monkeypatch, probes, inputs_sent=["pointer:canvas-center", "keyboard:Space"])
    found = [i for i in result["issues"] if i.startswith("browser input probe: injected pointer presses")]
    assert found, result["issues"]
    kind, patchable = repair._classify_gameplay_failure({"issues": found})
    assert kind == "quality"
    assert patchable == found


def test_processed_pointers_pass_the_input_gate(monkeypatch):
    result = _run_qa(monkeypatch, dict(_HEALTHY), inputs_sent=["pointer:canvas-center"])
    assert not any("browser input probe" in i for i in result["issues"]), result["issues"]


def test_pointer_gate_requires_injected_pointer_evidence(monkeypatch):
    # 沙箱没能注入指针(inputs_sent 无 pointer:)时不评判,防止把注入失败当游戏缺陷。
    probes = dict(_HEALTHY)
    probes.pop("input:down|PlayScene")
    result = _run_qa(monkeypatch, probes, inputs_sent=["keyboard:Space"])
    assert not any("browser input probe" in i for i in result["issues"]), result["issues"]


def test_per_frame_ui_rebuild_is_flagged_and_patchable(monkeypatch):
    probes = dict(_HEALTHY, **{"ui:interactive": 540})
    result = _run_qa(
        monkeypatch,
        probes,
        probes_start=dict(_HEALTHY, **{"ui:interactive": 300}),
        frames_start=100,
        frames_observed=200,
        inputs_sent=["pointer:canvas-center"],
    )
    found = [i for i in result["issues"] if i.startswith("gameplay UI is rebuilt every frame")]
    assert found, result["issues"]
    kind, patchable = repair._classify_gameplay_failure({"issues": found})
    assert kind == "quality"
    assert patchable == found


def test_one_time_scene_build_burst_does_not_trip_churn(monkeypatch):
    # 建场高峰发生在尾窗采样之前:尾窗内只新增 8 个注册,远低于阈值。
    probes = dict(_HEALTHY, **{"ui:interactive": 408})
    result = _run_qa(
        monkeypatch,
        probes,
        probes_start=dict(_HEALTHY, **{"ui:interactive": 400}),
        frames_start=100,
        frames_observed=200,
        inputs_sent=["pointer:canvas-center"],
    )
    assert not any("rebuilt every frame" in i for i in result["issues"]), result["issues"]


def test_churn_gate_skips_legacy_sandbox_without_tail_sample(monkeypatch):
    # 旧 sandbox/旧 Probe 没有 probes_start:门禁必须整体短路。
    result = _run_qa(
        monkeypatch,
        dict(_HEALTHY, **{"ui:interactive": 9000}),
        probes_start=None,
        frames_start=0,
        frames_observed=200,
    )
    assert not any("rebuilt every frame" in i for i in result["issues"]), result["issues"]


def test_invalid_key_registration_is_flagged_and_patchable(monkeypatch):
    probes = dict(_HEALTHY, **{"key:invalid": 3})
    result = _run_qa(monkeypatch, probes)
    found = [i for i in result["issues"] if i.startswith("keyboard keys registered with invalid key codes")]
    assert found, result["issues"]
    kind, patchable = repair._classify_gameplay_failure({"issues": found})
    assert kind == "quality"
    assert patchable == found


def test_interaction_gates_warn_instead_of_fail_for_template_products(monkeypatch):
    probes = dict(_HEALTHY, **{"key:invalid": 2})
    probes.pop("input:down|PlayScene")
    result = _run_qa(
        monkeypatch, probes, inputs_sent=["pointer:canvas-center"], code_source="template"
    )
    assert not any("browser input probe" in i for i in result["issues"])
    assert not any("invalid key codes" in i for i in result["issues"])
    assert any("browser input probe" in w for w in result["warnings"])
    assert any("invalid key codes" in w for w in result["warnings"])


def test_zero_size_canvas_warns(monkeypatch):
    probes = dict(_HEALTHY, **{"canvas:zerosize": 1})
    result = _run_qa(monkeypatch, probes)
    assert any(w.startswith("game canvas measured 0x0") for w in result["warnings"]), result["warnings"]
    assert not any("canvas measured 0x0" in i for i in result["issues"])


# ---------- 脚手架内容 ----------

def _scaffold() -> dict[str, str]:
    return {
        str(f["path"]): str(f.get("content") or "")
        for f in create_modular_phaser_project({}, {})
    }


def test_scaffold_ships_input_router_and_probe_hooks():
    files = _scaffold()
    router = files["src/systems/InputRouter.ts"]
    assert "worldPointer" in router and "shield" in router
    assert "over.length > 0" in router  # currentlyOver guard,世界输入不穿透 UI
    probe = files["src/systems/Probe.ts"]
    for token in (
        "processDownEvents",
        "setInteractive",
        "addKey",
        "dom:down",
        "input:down",
        "ui:interactive",
        "__GW_INTERACTIVE_TARGETS__",
        "key:invalid",
        "key:registered",
        "action(id:",
        "outcome(id:",
        "canvas:zerosize",
    ):
        assert token in probe, token


def test_scaffold_index_html_inlines_critical_sizing():
    files = _scaffold()
    index_html = files["index.html"]
    style_at = index_html.find("#game-container { width: 100%; height: 100%")
    script_at = index_html.find("<script")
    assert style_at != -1, "inline critical sizing missing"
    assert script_at == -1 or style_at < script_at


def test_input_router_reserved_from_authors():
    from app.agents.author_prompts import _RESERVED_PATHS

    assert "src/systems/InputRouter.ts" in _RESERVED_PATHS
    assert "src/systems/InputRouter.ts" in validation_nodes._STOCK_KIT_FILES
