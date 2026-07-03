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
