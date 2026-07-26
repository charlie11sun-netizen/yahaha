"""胜路模拟回归:WinScript 校验、跨包 parity、解释器确定性、QA warning 级接线。

设计要点:
- 后端 validate_win_script 与沙箱 winscript.parse_script 是同一 schema 的两份
  实现(容器边界不可跨 import),parity 测试钉住两者对齐;
- 解释器必须确定:setup 逐 tick 顺序、cooldown/max_times、缺失 stat 永不满足;
- QA 侧一切裁决都是 warning(repair 路由是前缀匹配,未注册的 issue 文案可能
  升级成整包重做),verdict 与时间线进 metrics.win_simulation。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from app.services.sandbox_client import WinSimulationResult
from app.services.win_script import (
    WIN_SCRIPT_PATH,
    extract_win_script,
    validate_win_script,
)

SAMPLE = {
    "sim_seconds": 120,
    "setup": [
        {"action": "pointer", "x": 100, "y": 200, "label": "opening move"},
        {"action": "wait", "seconds": 1},
    ],
    "rules": [
        {
            "label": "build when affordable",
            "when": {"stat": "gold", "op": "gte", "value": 50},
            "do": {"action": "pointer", "x": 10, "y": 20},
            "cooldown_s": 2,
            "max_times": 3,
        },
        {
            "when": {"always": True},
            "do": {"action": "key", "key": "Space"},
            "cooldown_s": 10,
        },
    ],
}

INVALID_SAMPLES = [
    {},  # needs at least one setup action or rule
    {"setup": [{"action": "teleport", "x": 1, "y": 2}]},  # unknown action
    {"rules": [{"when": {"stat": "gold"}, "do": {"action": "pointer"}}]},  # missing op/value/x/y
    {"setup": [{"action": "key", "key": "F13"}]},  # key outside the whitelist
]

_sandbox_module = None


def _sandbox_winscript():
    global _sandbox_module
    if _sandbox_module is None:
        path = Path(__file__).resolve().parents[3] / "sandbox" / "app" / "winscript.py"
        spec = importlib.util.spec_from_file_location("sandbox_winscript", path)
        module = importlib.util.module_from_spec(spec)
        # 注册进 sys.modules 再执行:dataclass 在 `from __future__ import
        # annotations` 下解析字符串注解要通过 sys.modules 找回定义模块。
        sys.modules["sandbox_winscript"] = module
        spec.loader.exec_module(module)
        _sandbox_module = module
    return _sandbox_module


def test_backend_validator_accepts_sample():
    assert validate_win_script(SAMPLE) == []


def test_backend_validator_rejects_invalid_samples():
    for sample in INVALID_SAMPLES:
        assert validate_win_script(sample), f"expected errors for {sample!r}"


def test_backend_and_sandbox_validators_stay_in_parity():
    ws = _sandbox_winscript()
    _script, errors = ws.parse_script(SAMPLE)
    assert errors == [], f"sandbox parser rejected a backend-valid script: {errors}"
    for sample in INVALID_SAMPLES:
        _script, sandbox_errors = ws.parse_script(sample)
        assert sandbox_errors, f"sandbox parser accepted a backend-invalid script: {sample!r}"


def test_extract_win_script_reads_and_validates_artifact():
    files = [{"path": WIN_SCRIPT_PATH, "content": json.dumps(SAMPLE)}]
    payload, errors = extract_win_script(files)
    assert errors == [] and payload is not None

    assert extract_win_script([{"path": "src/main.ts", "content": "x"}]) == (None, [])

    _payload, bad = extract_win_script([{"path": WIN_SCRIPT_PATH, "content": "{not json"}])
    assert bad and "not valid JSON" in bad[0]


def test_interpreter_setup_fires_in_order_then_rules():
    ws = _sandbox_winscript()
    script, errors = ws.parse_script(SAMPLE)
    assert errors == []
    progress = ws.SimProgress()

    first, source = ws.next_action(script, {}, {}, 0.0, progress)
    assert first["action"] == "pointer" and source == "setup[0]"
    second, _source = ws.next_action(script, {}, {}, 0.5, progress)
    assert second["action"] == "wait"
    # setup 耗尽;gold 未发布 → 规则0永不满足,落到 always 规则。
    third, source3 = ws.next_action(script, {}, {}, 1.0, progress)
    assert third["action"] == "key" and "rule[1]" in source3


def test_interpreter_honors_cooldown_and_max_times():
    ws = _sandbox_winscript()
    script, _ = ws.parse_script(
        {
            "rules": [
                {
                    "when": {"stat": "gold", "op": "gte", "value": 50},
                    "do": {"action": "pointer", "x": 1, "y": 2},
                    "cooldown_s": 2,
                    "max_times": 3,
                }
            ]
        }
    )
    progress = ws.SimProgress()
    stats = {"gold": 100}

    fired_times = []
    for tick in range(40):
        sim_s = tick * 0.5
        action, _src = ws.next_action(script, stats, {}, sim_s, progress)
        if action:
            fired_times.append(sim_s)
    assert fired_times == [0.0, 2.0, 4.0]  # cooldown 2s 间隔,max_times=3 截止


def test_interpreter_missing_stat_never_fires_and_is_reported():
    ws = _sandbox_winscript()
    script, _ = ws.parse_script(
        {
            "rules": [
                {
                    "when": {"stat": "gold", "op": "gte", "value": 1},
                    "do": {"action": "key", "key": "Space"},
                }
            ]
        }
    )
    progress = ws.SimProgress()
    action, _src = ws.next_action(script, {}, {}, 10.0, progress)
    assert action is None
    assert ws.missing_stats(script, {}) == ["gold"]
    assert ws.missing_stats(script, {"gold": 0}) == []


def test_interpreter_terminal_verdict_prefers_won():
    ws = _sandbox_winscript()
    assert ws.terminal_verdict({"game:status|won": 1}) == "won"
    assert ws.terminal_verdict({"game:status|lost": 2}) == "lost"
    assert ws.terminal_verdict({"game:status|won": 1, "game:status|lost": 1}) == "won"
    assert ws.terminal_verdict({}) is None


def _qa_state(script: dict | str | None) -> dict:
    files = [{"path": "index.html", "content": "<html></html>"}]
    if script is not None:
        content = script if isinstance(script, str) else json.dumps(script)
        files = [{"path": WIN_SCRIPT_PATH, "content": content}, *files]
    return {"project_files": files, "generated_files": files, "dimension": "2d"}


def test_win_path_findings_silent_without_artifact():
    from app.agents.gameplay_qa import _win_path_findings

    warnings, metrics = _win_path_findings(_qa_state(None), sandbox_ready=True)
    assert warnings == [] and metrics is None


def test_win_path_findings_flags_invalid_artifact_as_warning():
    from app.agents.gameplay_qa import _win_path_findings

    warnings, metrics = _win_path_findings(_qa_state("{broken"), sandbox_ready=True)
    assert len(warnings) == 1 and warnings[0].startswith("win-path: WinScript.json is present but invalid")
    assert metrics["verdict"] == "invalid"


def test_win_path_findings_lost_verdict_becomes_warning(monkeypatch):
    from app.agents.gameplay_qa import _win_path_findings

    fake = WinSimulationResult(
        verdict="lost",
        ok=False,
        pump_mode="virtual",
        sim_seconds=87.5,
        timeline=[{"t": 80.0, "event": "stats: gold=12"}, {"t": 87.5, "event": "terminal: lost"}],
    )
    monkeypatch.setattr("app.services.sandbox_client.simulate_win", lambda *a, **k: fake)

    warnings, metrics = _win_path_findings(_qa_state(SAMPLE), sandbox_ready=True)
    assert any(item.startswith("win-path simulation could not win") for item in warnings)
    assert metrics["verdict"] == "lost" and metrics["timeline_tail"]


def test_win_path_findings_won_with_missing_stats_warns_only_on_stats(monkeypatch):
    from app.agents.gameplay_qa import _win_path_findings

    fake = WinSimulationResult(
        verdict="won", ok=True, pump_mode="virtual", sim_seconds=42.0, missing_stats=["gold"]
    )
    monkeypatch.setattr("app.services.sandbox_client.simulate_win", lambda *a, **k: fake)

    warnings, metrics = _win_path_findings(_qa_state(SAMPLE), sandbox_ready=True)
    assert metrics["verdict"] == "won"
    assert len(warnings) == 1 and "never published via Probe.stat" in warnings[0]


def test_win_path_findings_skips_when_sandbox_not_ready():
    from app.agents.gameplay_qa import _win_path_findings

    warnings, metrics = _win_path_findings(_qa_state(SAMPLE), sandbox_ready=False)
    assert metrics["verdict"] == "skipped"
    assert any("win-path simulation skipped" in item or "sandbox replay unavailable" in item for item in warnings)


def test_win_path_findings_respects_disable_flag(monkeypatch):
    from app.agents.gameplay_qa import _win_path_findings
    from app.core.config import settings

    monkeypatch.setattr(settings, "WIN_SIMULATION_ENABLED", False)
    warnings, metrics = _win_path_findings(_qa_state(SAMPLE), sandbox_ready=True)
    assert warnings == [] and metrics == {"verdict": "disabled"}
