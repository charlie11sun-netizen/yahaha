"""第三批回归：CSP 强制注入、演示后门默认关闭、扩充的违禁 API 黑名单。"""


def test_inject_csp_placed_in_head_and_idempotent():
    from app.services.packaging import inject_csp

    html = "<html><head><title>t</title></head><body></body></html>"
    once = inject_csp(html)
    assert once.count("Content-Security-Policy") == 1
    assert once.index("Content-Security-Policy") < once.index("<title>")
    assert "connect-src 'none'" in once
    assert "script-src 'self' 'unsafe-inline'" in once
    assert inject_csp(once) == once  # 幂等：revision 复用旧 index.html 不会重复注入

    headless = inject_csp("<div>x</div>")
    assert headless.startswith('<meta http-equiv="Content-Security-Policy"')


def test_publish_generated_uploads_csp_hardened_index(client, db_session_factory, monkeypatch):
    from app.models import User
    from app.services import packaging
    from app.storage import s3

    client.post(
        "/auth/register",
        json={"email": "csp@t.com", "password": "secret1", "display_name": "C"},
    )
    db = db_session_factory()
    user_id = db.query(User).first().id
    db.close()

    captured: dict[str, str] = {}

    def _capture(key, body, content_type):
        captured[key] = body if isinstance(body, str) else body.decode("utf-8")
        return key

    monkeypatch.setattr(s3, "put_object", _capture)
    monkeypatch.setattr("app.db.session.SessionLocal", db_session_factory)
    packaging.publish_generated({
        "task_id": "csp-task",
        "user_id": user_id,
        "game_spec": {"title": "CSP Game", "genre": "arcade", "summary": "s", "tags": []},
        "generated_files": [
            {"path": "index.html", "content": "<html><head></head><body></body></html>"},
            {"path": "style.css", "content": "body{}"},
            {"path": "game.js", "content": "var x=1;"},
        ],
        "dimension": "2d",
    })

    index_key = next(k for k in captured if k.endswith("/index.html"))
    assert "Content-Security-Policy" in captured[index_key]
    assert "connect-src 'none'" in captured[index_key]
    # manifest 的 sha256 必须与实际上传（注入后）的内容一致
    import hashlib
    import json

    manifest = json.loads(captured[next(k for k in captured if k.endswith("/manifest.json"))])
    index_entry = next(f for f in manifest["files"] if f["path"] == "index.html")
    assert index_entry["sha256"] == hashlib.sha256(captured[index_key].encode("utf-8")).hexdigest()


def test_demo_fault_injection_off_by_default():
    from app.agents import nodes

    # 普通用户创意里碰巧出现关键词，不得改变引擎行为
    assert nodes._should_inject({"prompt": "a force-repair robot game", "repair_attempts": 0}) is False
    assert nodes._should_inject({"prompt": "force-replan the city", "replan_attempts": 0}) is False


def test_demo_fault_injection_requires_explicit_flag(monkeypatch):
    from app.agents import nodes
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEMO_FAULT_INJECTION", True)
    assert nodes._should_inject({"prompt": "force-repair", "repair_attempts": 0}) is True
    assert nodes._should_inject({"prompt": "force-repair", "repair_attempts": 1}) is False


def test_validation_blocks_network_bypass_apis():
    from app.agents.validation import validate_files

    files = [
        {"path": "index.html", "content": "<script src='game.js'></script>game.js"},
        {"path": "style.css", "content": "body{}"},
        {"path": "game.js", "content": "import('https://x/mod.js'); navigator.sendBeacon('/x'); new EventSource('/y');"},
    ]
    result = validate_files(files)
    labels = " ".join(result["errors"])
    assert "dynamic import()" in labels
    assert "sendBeacon" in labels
    assert "EventSource" in labels
