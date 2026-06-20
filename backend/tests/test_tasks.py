def _auth(client):
    token = client.post(
        "/auth/register",
        json={"email": "t@t.com", "password": "secret1", "display_name": "T"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_and_list_task(client):
    h = _auth(client)
    r = client.post("/tasks", json={"idea": "a platformer", "asset_ids": []}, headers=h)
    assert r.status_code == 200
    tid = r.json()["task_id"]
    items = client.get("/tasks", headers=h).json()["items"]
    assert any(t["id"] == tid for t in items)


def test_create_task_dimension_3d(client):
    h = _auth(client)
    r = client.post("/tasks", json={"idea": "a 3d fps", "asset_ids": [], "dimension": "3d"}, headers=h)
    assert r.status_code == 200
    tid = r.json()["task_id"]
    t = client.get(f"/tasks/{tid}", headers=h).json()
    assert t["dimension"] == "3d"


def test_create_task_dimension_defaults_2d(client):
    h = _auth(client)
    tid = client.post("/tasks", json={"idea": "a platformer", "asset_ids": []}, headers=h).json()["task_id"]
    t = client.get(f"/tasks/{tid}", headers=h).json()
    assert t["dimension"] == "2d"


def test_create_task_dimension_invalid_rejected(client):
    h = _auth(client)
    r = client.post("/tasks", json={"idea": "x", "asset_ids": [], "dimension": "4d"}, headers=h)
    assert r.status_code == 422


def test_three_engine_vendored_and_injected():
    """3D 引擎已 vendored，且 3D bundle 会注入 three.min.js（2D 不注入）。"""
    from app.agents import nodes
    from app.services import packaging

    assert (packaging._three_engine_bytes() or b"").startswith(b"/**")  # Three.js license banner
    files_3d = nodes._assemble_bundle({"game.js": "x" * 500}, "T", dimension="3d")
    idx_3d = next(f["content"] for f in files_3d if f["path"] == "index.html")
    assert "three.min.js" in idx_3d
    files_2d = nodes._assemble_bundle({"game.js": "x" * 500}, "T", dimension="2d")
    idx_2d = next(f["content"] for f in files_2d if f["path"] == "index.html")
    assert "three.min.js" not in idx_2d


def test_runtime_smoke_catches_use_before_init():
    import pytest

    from app.agents import smoke

    if not smoke.available():
        pytest.skip("py_mini_racer not installed")
    # 正常：先声明再用
    ok_good, _ = smoke.run_smoke("var WAVES=[1,2,3]; function start(){return WAVES.length;} start();")
    # 崩溃：start() 在 var WAVES 赋值前执行 -> 读 undefined.length（就是这次的真实 bug 形态）
    ok_bad, detail = smoke.run_smoke("start(); function start(){return WAVES.length;} var WAVES=[1,2,3];")
    assert ok_good is True
    assert ok_bad is False and "length" in detail.lower()


def test_runtime_smoke_allows_three_and_dom():
    import pytest

    from app.agents import smoke

    if not smoke.available():
        pytest.skip("py_mini_racer not installed")
    js = (
        "var r=new THREE.WebGLRenderer({antialias:true}); r.setSize(innerWidth,innerHeight);"
        "document.body.appendChild(r.domElement);"
        "var s=new THREE.Scene(); var c=new THREE.PerspectiveCamera(70,1,0.1,100); c.position.set(0,1,0);"
        "var arr=[]; s.children.forEach(function(x){arr.push(x)});"  # iterating a stub must not throw
        "requestAnimationFrame(function(){}); addEventListener('click',function(){});"
        "window.parent.postMessage({type:'playforge:score',points:1},'*');"
    )
    ok, detail = smoke.run_smoke(js)
    assert ok is True, detail


def test_delete_active_task_rejected(client):
    h = _auth(client)
    tid = client.post("/tasks", json={"idea": "x", "asset_ids": []}, headers=h).json()["task_id"]
    # 任务创建后处于 pending（generate 被 mock 不会真正运行），活动任务禁止直接删除
    assert client.delete(f"/tasks/{tid}", headers=h).status_code == 400


def test_delete_terminal_task(client, db_session_factory):
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    h = _auth(client)
    tid = client.post("/tasks", json={"idea": "x", "asset_ids": []}, headers=h).json()["task_id"]
    db = db_session_factory()
    task = db.get(GenerationTask, tid)
    task.status = TaskStatus.FAILED
    db.commit()
    db.close()
    assert client.delete(f"/tasks/{tid}", headers=h).status_code == 200
