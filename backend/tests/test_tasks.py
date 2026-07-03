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


def test_third_active_task_for_same_user_rejected(client):
    h = _auth(client)
    assert client.post("/tasks", json={"idea": "one", "asset_ids": []}, headers=h).status_code == 200
    assert client.post("/tasks", json={"idea": "two", "asset_ids": []}, headers=h).status_code == 200
    r = client.post("/tasks", json={"idea": "three", "asset_ids": []}, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"] == "TOO_MANY_ACTIVE_TASKS"


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
        "window.parent.postMessage({type:'gameweave:score',points:1},'*');"
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


def _completed_preview(client, db_session_factory, headers):
    from app.models import Game, GameVersion, GenerationTask
    from app.models.common import GameSource, GameStatus, TaskStatus

    task_id = client.post("/tasks", json={"idea": "a responsive arcade game"}, headers=headers).json()["task_id"]
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    game = Game(
        author_id=task.user_id,
        title="Revision Test",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
        prompt=task.idea,
    )
    db.add(game)
    db.flush()
    version = GameVersion(
        game_id=game.id,
        version="v1",
        manifest_key=f"games/{game.id}/v1/manifest.json",
        bundle_key=f"games/{game.id}/v1/index.html",
        source_task_id=task.id,
    )
    db.add(version)
    db.flush()
    task.status = TaskStatus.SUCCEEDED
    task.result_game_id = game.id
    task.version_id = version.id
    task.spec_json = '{"title":"Revision Test","genre":"arcade"}'
    task.design_json = '{"rules":{"win":"score"}}'
    db.commit()
    result = task.id, game.id, version.id
    db.close()
    return result


def test_create_revision_task_preserves_raw_feedback(client, db_session_factory):
    from app.models import GenerationTask

    headers = _auth(client)
    source_task_id, game_id, _ = _completed_preview(client, db_session_factory, headers)
    feedback = "跳跃有点笨重；想更轻快，但不要明显跳得更高。"
    response = client.post(
        f"/tasks/{source_task_id}/revise",
        json={"feedback": feedback},
        headers=headers,
    )
    assert response.status_code == 200
    db = db_session_factory()
    revision = db.get(GenerationTask, response.json()["task_id"])
    assert revision.task_kind == "revision"
    assert revision.feedback_text == feedback
    assert revision.base_game_id == game_id
    assert revision.base_version == "v1"
    assert revision.result_game_id == game_id
    assert revision.spec_json == '{"title":"Revision Test","genre":"arcade"}'
    db.close()


def test_revision_rejects_stale_preview_task(client, db_session_factory):
    headers = _auth(client)
    source_task_id, game_id, _ = _completed_preview(client, db_session_factory, headers)
    from app.models import Game

    db = db_session_factory()
    game = db.get(Game, game_id)
    game.current_version = "v2"
    db.commit()
    db.close()
    response = client.post(
        f"/tasks/{source_task_id}/revise",
        json={"feedback": "make it faster"},
        headers=headers,
    )
    assert response.status_code == 409


def test_incremental_revision_merges_only_returned_files(monkeypatch):
    from app.agents import nodes

    existing = [
        {"path": "index.html", "content": '<link rel="stylesheet" href="style.css"><script src="game.js"></script>'},
        {"path": "style.css", "content": "body{color:white}"},
        {"path": "game.js", "content": "const speed=8;"},
    ]
    monkeypatch.setattr(nodes.llm, "chat", lambda *args, **kwargs: ("```css\nbody{color:cyan}\n```", 12))
    files, tokens, changed, _ = nodes._generate_revision_code({
        "use_real": True,
        "existing_files": existing,
        "source_feedback": "make the text cyan",
        "feedback_brief": "Change only the text color.",
        "game_spec": {},
        "game_design": {},
    })
    by_path = {file["path"]: file["content"] for file in files}
    assert tokens == 12
    assert changed == ["style.css"]
    assert by_path["index.html"] == existing[0]["content"]
    assert by_path["game.js"] == existing[2]["content"]
    assert by_path["style.css"] == "body{color:cyan}"


def test_publish_revision_creates_immutable_next_version(client, db_session_factory, monkeypatch):
    from app.models import Game, GenerationTask
    from app.services import packaging

    headers = _auth(client)
    source_task_id, game_id, _ = _completed_preview(client, db_session_factory, headers)
    db = db_session_factory()
    source = db.get(GenerationTask, source_task_id)
    user_id = source.user_id
    db.close()
    monkeypatch.setattr("app.db.session.SessionLocal", db_session_factory)
    files = [
        {"path": "index.html", "content": '<link rel="stylesheet" href="style.css"><script src="game.js"></script>'},
        {"path": "style.css", "content": "body{color:cyan}"},
        {"path": "game.js", "content": "const speed=11;"},
    ]
    result = packaging.publish_revision({
        "task_id": "revision-task",
        "user_id": user_id,
        "base_game_id": game_id,
        "base_version": "v1",
        "dimension": "2d",
        "generated_files": files,
        "revision_result": {"changed_files": ["style.css", "game.js"]},
    })
    assert result[2] == "v2"
    db = db_session_factory()
    game = db.get(Game, game_id)
    assert game.current_version == "v2"
    assert sorted(version.version for version in game.versions) == ["v1", "v2"]
    db.close()
