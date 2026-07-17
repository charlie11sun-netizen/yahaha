import base64
import sys
from types import ModuleType

import httpx
import pytest


def _files():
    js = "var x = 1;\n" + ("// padding\n" * 60) + "requestAnimationFrame(function loop(){requestAnimationFrame(loop)});"
    return [
        {"path": "index.html", "content": '<!doctype html><script src="game.js"></script>'},
        {"path": "style.css", "content": "body{margin:0}"},
        {"path": "game.js", "content": js},
    ]


def test_sandbox_client_skips_when_not_required_and_unconfigured(monkeypatch):
    from app.core.config import settings
    from app.services import sandbox_client

    monkeypatch.setattr(settings, "SANDBOX_URL", "")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", False)
    result = sandbox_client.run_bundle(_files())
    assert result.ok is True
    assert result.skipped is True


def test_sandbox_client_fails_closed_when_required_and_unavailable(monkeypatch):
    from app.core.config import settings
    from app.services import sandbox_client

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", True)
    with pytest.raises(sandbox_client.SandboxUnavailableError):
        sandbox_client.run_bundle(_files(), timeout_ms=500)


def test_sandbox_client_reports_http_error_detail(monkeypatch):
    from app.core.config import settings
    from app.services import sandbox_client

    response = httpx.Response(
        413,
        json={"detail": "phaser.min.js exceeds 1000000 bytes"},
        request=httpx.Request("POST", "http://sandbox:8001/run"),
    )

    def fake_post(*_args, **_kwargs):
        response.raise_for_status()

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://sandbox:8001")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", False)
    monkeypatch.setattr(sandbox_client.httpx, "post", fake_post)

    result = sandbox_client.run_bundle(_files(), timeout_ms=500)
    assert result.skipped is True
    assert "413" in result.detail
    assert "phaser.min.js exceeds" in result.detail


def test_sandbox_client_adds_http_timeout_headroom(monkeypatch):
    from app.core.config import settings
    from app.services import sandbox_client

    captured: dict[str, object] = {}

    def fake_post(*_args, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return httpx.Response(
            200,
            json={
                "ok": True,
                "page_errors": [],
                "console_errors": [],
                "console_warnings": [],
                "requests_aborted": [],
                "frames_observed": 2,
                "intervals_observed": 0,
                "load_ms": 300,
                "timed_out": False,
                "input_attempted": True,
                "inputs_sent": ["pointer:canvas-center", "keyboard:Enter"],
                "start_attempts": ["pointer:canvas-center", "keyboard:Enter"],
                "visual_probe": "page-screenshot-png-byte-diff",
                "visual_before_sha256": "before",
                "visual_after_sha256": "after",
                "visual_changed": True,
                "visual_change_ratio": 0.25,
            },
            request=httpx.Request("POST", "http://sandbox:8001/run"),
        )

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://sandbox:8001")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", True)
    monkeypatch.setattr(settings, "SANDBOX_HTTP_TIMEOUT_OVERHEAD_MS", 7000)
    monkeypatch.setattr(sandbox_client.httpx, "post", fake_post)

    result = sandbox_client.run_bundle(_files(), timeout_ms=1500)

    assert result.ok is True
    assert captured["timeout"] == 8.5
    assert result.input_attempted is True
    assert result.inputs_sent == ["pointer:canvas-center", "keyboard:Enter"]
    assert result.start_attempts == ["pointer:canvas-center", "keyboard:Enter"]
    assert result.visual_changed is True
    assert result.visual_change_ratio == 0.25
    assert result.visual_probe == "page-screenshot-png-byte-diff"


def test_sandbox_client_keeps_observation_fields_optional(monkeypatch):
    from app.core.config import settings
    from app.services import sandbox_client

    def fake_post(*_args, **_kwargs):
        return httpx.Response(
            200,
            json={"ok": True, "frames_observed": 1, "load_ms": 10},
            request=httpx.Request("POST", "http://sandbox:8001/run"),
        )

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://sandbox:8001")
    monkeypatch.setattr(sandbox_client.httpx, "post", fake_post)

    result = sandbox_client.run_bundle(_files())

    assert result.ok is True
    assert result.inputs_sent == []
    assert result.visual_changed is None
    assert result.visual_change_ratio is None


def test_gameplay_qa_marks_required_sandbox_unavailable(monkeypatch):
    from app.agents import nodes
    from app.core.config import settings

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", True)
    js = (
        "var player=0;"
        "window.onkeydown=function(e){player+=1};"
        "function restart(){player=0};"
        "function loop(){player+=1;requestAnimationFrame(loop)};"
        "requestAnimationFrame(loop);"
        + ("// padding\n" * 80)
    )
    result = nodes.gameplay_qa_node(
        {
            "dimension": "2d",
            "generated_files": [
                {"path": "index.html", "content": '<!doctype html><script src="game.js"></script>'},
                {"path": "style.css", "content": "body{background:#000}"},
                {"path": "game.js", "content": js},
            ],
            "validation_result": {"valid": True},
        }
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "SANDBOX_UNAVAILABLE"


def test_3d_sandbox_payload_includes_vendored_three():
    from app.agents import nodes

    files = nodes._assemble_bundle({"game.js": "const scene = new THREE.Scene();" + ("//x\n" * 120)}, "T", "3d")
    assert {file["path"] for file in files} == {"index.html", "style.css", "game.js"}
    payload = nodes._sandbox_files_for_qa(files, "3d")
    by_path = {file["path"]: file["content"] for file in payload}
    assert "three.min.js" in by_path
    assert len(by_path["three.min.js"].encode("utf-8")) > 500_000


def test_sandbox_default_limits_accept_vendored_phaser(monkeypatch):
    from app.services import packaging

    fake_playwright = ModuleType("playwright")
    fake_async_api = ModuleType("playwright.async_api")
    fake_async_api.Browser = object
    fake_async_api.Error = Exception
    fake_async_api.Page = object
    fake_async_api.async_playwright = lambda: None
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    monkeypatch.delitem(sys.modules, "sandbox.app.main", raising=False)
    from sandbox.app import main as sandbox_main

    engine = packaging.phaser_engine_bytes()
    assert engine
    assert len(engine) > 1_000_000
    assert len(engine) <= sandbox_main.settings.max_file_bytes

    decoded = sandbox_main._decode_files(
        [
            sandbox_main.BundleFile(
                path="phaser.min.js",
                content_b64=base64.b64encode(engine).decode("ascii"),
            )
        ]
    )
    assert decoded["phaser.min.js"] == engine


def test_sandbox_defaults_match_relaxed_vite_limits(monkeypatch):
    monkeypatch.delenv("SANDBOX_RUNNER_MAX_FILE_BYTES", raising=False)
    monkeypatch.delenv("SANDBOX_RUNNER_MAX_TOTAL_BYTES", raising=False)
    fake_playwright = ModuleType("playwright")
    fake_async_api = ModuleType("playwright.async_api")
    fake_async_api.Browser = object
    fake_async_api.Error = Exception
    fake_async_api.Page = object
    fake_async_api.async_playwright = lambda: None
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)
    monkeypatch.delitem(sys.modules, "sandbox.app.main", raising=False)

    from app.services.vite_projects import MAX_PROJECT_BYTES, MAX_PROJECT_FILE_BYTES
    from sandbox.app import main as sandbox_main

    assert sandbox_main.settings.max_file_bytes == MAX_PROJECT_FILE_BYTES
    assert sandbox_main.settings.max_total_bytes == MAX_PROJECT_BYTES

    unchanged = sandbox_main._visual_metrics(b"same", b"same")
    changed = sandbox_main._visual_metrics(b"same", b"some")
    assert unchanged["visual_changed"] is False
    assert unchanged["visual_change_ratio"] == 0.0
    assert changed["visual_changed"] is True
    assert changed["visual_change_ratio"] > 0

    legacy = sandbox_main.RunResponse(
        ok=True,
        page_errors=[],
        console_errors=[],
        frames_observed=1,
        load_ms=10,
    )
    assert legacy.inputs_sent == []
    assert legacy.visual_changed is None


def test_setinterval_loop_is_valid_sandbox_activity(monkeypatch):
    from app.agents import nodes
    from app.services.sandbox_client import SandboxResult

    js = (
        "var player=0;"
        "window.onkeydown=function(e){player+=1};"
        "function restart(){player=0};"
        "setInterval(function(){player+=1}, 16);"
        + ("// padding\n" * 80)
    )
    monkeypatch.setattr(
        nodes.sandbox_client,
        "run_bundle",
        lambda *args, **kwargs: SandboxResult(ok=True, frames_observed=0, intervals_observed=3, load_ms=120),
    )
    result = nodes.gameplay_qa_node(
        {
            "dimension": "2d",
            "generated_files": [
                {"path": "index.html", "content": '<!doctype html><script src="game.js"></script>'},
                {"path": "style.css", "content": "body{background:#000}"},
                {"path": "game.js", "content": js},
            ],
            "validation_result": {"valid": True},
        }
    )
    assert result["gameplay_qa_result"]["passed"] is True


def test_sandbox_client_parses_runtime_probes(monkeypatch):
    from app.core.config import settings
    from app.services import sandbox_client

    def fake_post(*_args, **_kwargs):
        return httpx.Response(
            200,
            json={
                "ok": True,
                "page_errors": [],
                "console_errors": [],
                "frames_observed": 12,
                "intervals_observed": 0,
                "load_ms": 800,
                "probes": {
                    "probe:ready": 1,
                    "scene:start|PlayScene": "2",
                    "anims:play|player-run": 40,
                    "bogus": "not-a-number",
                    12345: 3,
                },
            },
            request=httpx.Request("POST", "http://sandbox:8001/run"),
        )

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://sandbox:8001")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", False)
    monkeypatch.setattr(sandbox_client.httpx, "post", fake_post)

    result = sandbox_client.run_bundle(_files(), timeout_ms=500)
    assert result.probes["probe:ready"] == 1
    assert result.probes["scene:start|PlayScene"] == 2
    assert result.probes["anims:play|player-run"] == 40
    assert result.probes["12345"] == 3
    assert "bogus" not in result.probes


def test_sandbox_client_probes_default_empty(monkeypatch):
    from app.core.config import settings
    from app.services import sandbox_client

    def fake_post(*_args, **_kwargs):
        return httpx.Response(
            200,
            json={"ok": True, "page_errors": [], "console_errors": [], "frames_observed": 3, "load_ms": 100},
            request=httpx.Request("POST", "http://sandbox:8001/run"),
        )

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://sandbox:8001")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", False)
    monkeypatch.setattr(sandbox_client.httpx, "post", fake_post)

    result = sandbox_client.run_bundle(_files(), timeout_ms=500)
    assert result.probes == {}
