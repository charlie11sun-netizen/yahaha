from conftest import auth_headers, auth_user


def test_create_and_list_task(client):
    h = auth_headers(client, email="t@t.com", display_name="T")
    r = client.post("/tasks", json={"idea": "a platformer", "asset_ids": []}, headers=h)
    assert r.status_code == 200
    tid = r.json()["task_id"]
    items = client.get("/tasks", headers=h).json()["items"]
    assert any(t["id"] == tid for t in items)


def test_list_tasks_paginates(client, db_session_factory):
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers, user_id = auth_user(client, email="task-page@test.com", display_name="TP")
    db = db_session_factory()
    for index in range(3):
        db.add(
            GenerationTask(
                user_id=user_id,
                idea=f"paged task {index}",
                status=TaskStatus.SUCCEEDED,
            )
        )
    db.commit()
    db.close()

    first = client.get("/tasks?limit=2", headers=headers).json()
    assert len(first["items"]) == 2
    assert first["total"] == 3
    assert first["has_more"] is True
    second = client.get("/tasks?limit=2&offset=2", headers=headers).json()
    assert len(second["items"]) == 1
    assert second["has_more"] is False


def test_create_task_dimension_3d(client):
    h = auth_headers(client, email="t@t.com", display_name="T")
    r = client.post("/tasks", json={"idea": "a 3d fps", "asset_ids": [], "dimension": "3d"}, headers=h)
    assert r.status_code == 200
    tid = r.json()["task_id"]
    t = client.get(f"/tasks/{tid}", headers=h).json()
    assert t["dimension"] == "3d"


def test_create_task_dimension_defaults_2d(client):
    h = auth_headers(client, email="t@t.com", display_name="T")
    tid = client.post("/tasks", json={"idea": "a platformer", "asset_ids": []}, headers=h).json()["task_id"]
    t = client.get(f"/tasks/{tid}", headers=h).json()
    assert t["dimension"] == "2d"


def test_task_details_only_emit_summaries_for_steps_that_ran(client, db_session_factory):
    from app.models import AgentStep
    from app.models.common import StepStatus, now_utc

    headers = auth_headers(client, email="step-summary@test.com", display_name="SS")
    task_id = client.post("/tasks", json={"idea": "a strategy game", "asset_ids": []}, headers=headers).json()["task_id"]
    db = db_session_factory()
    finished_at = now_utc()
    db.add_all(
        [
            AgentStep(
                task_id=task_id,
                seq=1,
                agent="IntentSpecAgent",
                name="Intent Spec",
                status=StepStatus.DONE,
                tokens=10,
                attempt=1,
                started_at=finished_at,
                finished_at=finished_at,
            ),
            AgentStep(
                task_id=task_id,
                seq=2,
                agent="GameplayPlanningAgent",
                name="Gameplay Planning",
                status=StepStatus.DONE,
                tokens=20,
                attempt=1,
                started_at=finished_at,
                finished_at=finished_at,
            ),
            AgentStep(
                task_id=task_id,
                seq=3,
                agent="ArchetypeRouterAgent",
                name="Archetype Router",
                status=StepStatus.DONE,
                tokens=0,
                attempt=1,
                started_at=finished_at,
                finished_at=finished_at,
            ),
        ]
    )
    db.commit()
    db.close()

    response = client.get(f"/tasks/{task_id}", headers=headers)
    assert response.status_code == 200
    summaries = {summary["step"]: summary["status"] for summary in response.json()["step_summaries"]}
    assert summaries == {
        "intent_spec": "completed",
        "gameplay_planning": "completed",
        "archetype_router": "completed",
    }


def test_task_details_accept_author_team_activity_events(client, db_session_factory):
    import json

    from app.models import AgentLog, AgentStep
    from app.models.common import StepStatus, now_utc

    headers = auth_headers(client, email="author-team-event@test.com", display_name="ATE")
    task_id = client.post("/tasks", json={"idea": "a puzzle game", "asset_ids": []}, headers=headers).json()["task_id"]
    db = db_session_factory()
    step = AgentStep(
        task_id=task_id,
        seq=1,
        agent="GameCodeAgent",
        name="Code Generation",
        status=StepStatus.RUNNING,
        tokens=0,
        attempt=1,
        started_at=now_utc(),
    )
    db.add(step)
    db.flush()
    db.add_all(
        [AgentLog(
            step_id=step.id,
            seq=0,
            line="author team started from frozen base abc123",
            payload_json=json.dumps(
                {
                    "type": "author_team",
                    "phase": "start",
                    "base_revision": "abc123",
                }
            ),
        ),
        AgentLog(
            step_id=step.id,
            seq=1,
            line="role budget reached",
            payload_json=json.dumps(
                {
                    "type": "role_budget_exhausted",
                    "agent": "RulesAndSimulationCoder",
                    "operation": "authoring",
                    "reason": "max_turns",
                    "turns_limit": 6,
                    "status": "partial",
                }
            ),
        ),
        AgentLog(
            step_id=step.id,
            seq=2,
            line="repair attempt started",
            payload_json=json.dumps(
                {
                    "type": "repair_attempt_started",
                    "agent": "GameCodeAgentRepair",
                    "operation": "repairing",
                    "repair_kind": "build",
                    "attempt": 1,
                    "max_attempts": 2,
                    "status": "running",
                }
            ),
        )]
    )
    db.commit()
    db.close()

    response = client.get(f"/tasks/{task_id}", headers=headers)
    assert response.status_code == 200
    log = response.json()["logs"][-1]
    assert log["step_id"] == step.id
    assert [entry["cursor"] for entry in log["entries"]] == sorted(
        entry["cursor"] for entry in log["entries"]
    )
    events = [entry["event"] for entry in log["entries"]]
    assert events[0]["type"] == "author_team"
    assert events[0]["phase"] == "start"
    assert events[0]["base_revision"] == "abc123"
    assert events[1]["type"] == "role_budget_exhausted"
    assert events[1]["status"] == "partial"
    assert events[2]["type"] == "repair_attempt_started"
    assert events[2]["attempt"] == 1


def test_create_task_dimension_invalid_rejected(client):
    h = auth_headers(client, email="t@t.com", display_name="T")
    r = client.post("/tasks", json={"idea": "x", "asset_ids": [], "dimension": "4d"}, headers=h)
    assert r.status_code == 422


def test_create_task_rejects_oversized_prompt_before_persisting(client, db_session_factory):
    from app.models import GenerationTask

    h = auth_headers(client, email="t@t.com", display_name="T")
    r = client.post("/tasks", json={"idea": "x" * 2001, "asset_ids": []}, headers=h)
    assert r.status_code == 422

    db = db_session_factory()
    assert db.query(GenerationTask).count() == 0
    db.close()


def test_create_remix_task_from_published_source(client, db_session_factory):
    from app.models import Game, GameVersion, GenerationDispatchOutbox, GenerationTask, User
    from app.models.common import GameSource, GameStatus

    headers = auth_headers(client, email="t@t.com", display_name="T")
    db = db_session_factory()
    owner = User(email="remix-source@example.com", display_name="Source", avatar_initial="S")
    db.add(owner)
    db.flush()
    source = Game(
        author_id=owner.id,
        title="Source Game",
        summary="source summary",
        genre="ARCADE",
        cover="",
        source=GameSource.SEED,
        status=GameStatus.PUBLISHED,
        current_version="v1",
    )
    db.add(source)
    db.flush()
    version = GameVersion(
        game_id=source.id,
        version="v1",
        manifest_key=f"games/{source.id}/v1/manifest.json",
        bundle_key=f"games/{source.id}/v1/index.html",
        source_task_id=None,
    )
    db.add(version)
    db.commit()
    source_id = source.id
    db.close()

    response = client.post(
        "/tasks",
        json={
            "idea": "make it faster and neon",
            "asset_ids": [],
            "task_kind": "remix",
            "source_game_id": source_id,
        },
        headers=headers,
    )
    assert response.status_code == 200
    db = db_session_factory()
    task = db.get(GenerationTask, response.json()["task_id"])
    assert task.task_kind == "remix"
    assert task.base_game_id == source_id
    assert task.base_version == "v1"
    assert task.feedback_text == "make it faster and neon"
    assert "Source Game Remix" in task.spec_json
    event = db.query(GenerationDispatchOutbox).filter_by(task_id=task.id).one()
    assert task.dispatch_generation == event.dispatch_generation == 1
    db.close()


def test_remix_private_source_requires_owner(client, db_session_factory):
    from app.models import Game, GameVersion, User
    from app.models.common import GameSource, GameStatus

    headers = auth_headers(client, email="t@t.com", display_name="T")
    db = db_session_factory()
    owner = User(email="private-source@example.com", display_name="Source", avatar_initial="S")
    db.add(owner)
    db.flush()
    source = Game(
        author_id=owner.id,
        title="Private Source",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
    )
    db.add(source)
    db.flush()
    db.add(
        GameVersion(
            game_id=source.id,
            version="v1",
            manifest_key=f"games/{source.id}/v1/manifest.json",
            bundle_key=f"games/{source.id}/v1/index.html",
        )
    )
    db.commit()
    source_id = source.id
    db.close()

    response = client.post(
        "/tasks",
        json={"idea": "remix it", "asset_ids": [], "task_kind": "remix", "source_game_id": source_id},
        headers=headers,
    )
    assert response.status_code == 404


def test_third_active_task_for_same_user_rejected(client):
    h = auth_headers(client, email="t@t.com", display_name="T")
    assert client.post("/tasks", json={"idea": "one", "asset_ids": []}, headers=h).status_code == 200
    assert client.post("/tasks", json={"idea": "two", "asset_ids": []}, headers=h).status_code == 200
    r = client.post("/tasks", json={"idea": "three", "asset_ids": []}, headers=h)
    assert r.status_code == 409
    assert r.json()["detail"] == "TOO_MANY_ACTIVE_TASKS"


def test_create_task_acquires_user_quota_advisory_lock(client, monkeypatch):
    headers, user_id = auth_user(client, email="task-lock@test.com", display_name="TL")
    locks = []
    monkeypatch.setattr(
        "app.services.task_actions._acquire_advisory_xact_lock",
        lambda _db, namespace, identity: locks.append((namespace, identity)),
    )

    response = client.post("/tasks", json={"idea": "locked task", "asset_ids": []}, headers=headers)

    assert response.status_code == 200
    assert locks == [("task_active_user", user_id)]


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


def test_runtime_smoke_degrades_open_when_engine_process_aborts(monkeypatch):
    from app.agents import smoke

    class Completed:
        returncode = -6
        stdout = ""
        stderr = "aborted"

    monkeypatch.setattr(smoke, "_AVAILABLE", True)
    monkeypatch.setattr(smoke.subprocess, "run", lambda *args, **kwargs: Completed())

    ok, detail = smoke.run_smoke("var ok = 1;")

    assert ok is True
    assert "skipped" in detail
    assert "SIGABRT" in detail


def test_delete_active_task_rejected(client):
    h = auth_headers(client, email="t@t.com", display_name="T")
    tid = client.post("/tasks", json={"idea": "x", "asset_ids": []}, headers=h).json()["task_id"]
    # 任务创建后处于 pending（generate 被 mock 不会真正运行），活动任务禁止直接删除
    assert client.delete(f"/tasks/{tid}", headers=h).status_code == 400


def test_delete_terminal_task(client, db_session_factory):
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    h = auth_headers(client, email="t@t.com", display_name="T")
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
    from app.models import GenerationDispatchOutbox, GenerationTask

    headers = auth_headers(client, email="t@t.com", display_name="T")
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
    event = db.query(GenerationDispatchOutbox).filter_by(task_id=revision.id).one()
    assert revision.dispatch_generation == event.dispatch_generation == 1
    db.close()


def test_revision_acquires_quota_and_game_advisory_locks(client, db_session_factory, monkeypatch):
    from app.models import GenerationTask

    headers = auth_headers(client, email="t@t.com", display_name="T")
    source_task_id, game_id, _ = _completed_preview(client, db_session_factory, headers)
    db = db_session_factory()
    user_id = db.get(GenerationTask, source_task_id).user_id
    db.close()
    locks = []
    monkeypatch.setattr(
        "app.services.task_actions._acquire_advisory_xact_lock",
        lambda _db, namespace, identity: locks.append((namespace, identity)),
    )

    response = client.post(
        f"/tasks/{source_task_id}/revise",
        json={"feedback": "make it faster"},
        headers=headers,
    )

    assert response.status_code == 200
    assert locks == [("task_active_user", user_id), ("task_revision_game", game_id)]


def test_revision_rejects_existing_active_revision(client, db_session_factory):
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="t@t.com", display_name="T")
    source_task_id, game_id, _ = _completed_preview(client, db_session_factory, headers)
    db = db_session_factory()
    source = db.get(GenerationTask, source_task_id)
    db.add(
        GenerationTask(
            user_id=source.user_id,
            idea=source.idea,
            task_kind="revision",
            base_game_id=game_id,
            result_game_id=game_id,
            feedback_text="already running",
            status=TaskStatus.PENDING,
        )
    )
    db.commit()
    db.close()

    response = client.post(
        f"/tasks/{source_task_id}/revise",
        json={"feedback": "make it faster"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "A revision is already running for this preview"


def test_revision_rejects_stale_preview_task(client, db_session_factory):
    headers = auth_headers(client, email="t@t.com", display_name="T")
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

    headers = auth_headers(client, email="t@t.com", display_name="T")
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


def test_publish_remix_creates_new_game_with_source_pointer(client, db_session_factory, monkeypatch):
    from app.models import Game, GameVersion, User
    from app.models.common import GameSource, GameStatus
    from app.services import packaging

    db = db_session_factory()
    user = User(email="remixer@example.com", display_name="Remixer", avatar_initial="R")
    owner = User(email="original@example.com", display_name="Original", avatar_initial="O")
    db.add_all([user, owner])
    db.flush()
    source = Game(
        author_id=owner.id,
        title="Original Game",
        summary="source",
        genre="ARCADE",
        cover="linear-gradient(135deg,#000,#fff)",
        source=GameSource.SEED,
        status=GameStatus.PUBLISHED,
        current_version="v1",
    )
    db.add(source)
    db.flush()
    db.add(
        GameVersion(
            game_id=source.id,
            version="v1",
            manifest_key=f"games/{source.id}/v1/manifest.json",
            bundle_key=f"games/{source.id}/v1/index.html",
        )
    )
    db.commit()
    source_id = source.id
    user_id = user.id
    db.close()

    monkeypatch.setattr("app.db.session.SessionLocal", db_session_factory)
    files = [
        {"path": "index.html", "content": '<link rel="stylesheet" href="style.css"><script src="game.js"></script>'},
        {"path": "style.css", "content": "body{color:white}"},
        {"path": "game.js", "content": "requestAnimationFrame(()=>{});"},
    ]
    game_id, version_id, _ = packaging.publish_remix({
        "task_id": "remix-task",
        "user_id": user_id,
        "base_game_id": source_id,
        "base_version": "v1",
        "source_feedback": "make it neon",
        "game_spec": {"title": "Neon Remix", "genre": "arcade", "tags": ["neon"]},
        "dimension": "2d",
        "generated_files": files,
        "revision_result": {"changed_files": ["game.js"]},
    })

    db = db_session_factory()
    remix = db.get(Game, game_id)
    assert remix.id != source_id
    assert remix.remixed_from_game_id == source_id
    assert remix.remixed_from_version == "v1"
    assert remix.current_version == "v1"
    assert db.get(GameVersion, version_id).game_id == game_id
    db.close()


def test_generated_assets_endpoint_returns_checkpoint_images_and_enforces_owner(client, monkeypatch):
    from conftest import auth_headers

    from app.services.artifacts import binary_artifact
    from app.services import task_generated_assets

    headers = auth_headers(client, email="generated-assets@example.com", display_name="Assets")
    task_id = client.post("/tasks", json={"idea": "show generated art"}, headers=headers).json()["task_id"]
    image = binary_artifact("public/assets/sheet.png", b"png-bytes", "image/png")
    audio = binary_artifact("public/assets/bgm.wav", b"wav-bytes", "audio/wav")
    monkeypatch.setattr(
        task_generated_assets,
        "_checkpoint_values",
        lambda _task_id: {
            "generated_assets": [image, audio],
            "asset_manifest": {
                "assets": [
                    {
                        "key": "sheet",
                        "kind": "spritesheet",
                        "path": "assets/sheet.png",
                    }
                ]
            },
        },
    )

    response = client.get(f"/tasks/{task_id}/generated-assets", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "key": "sheet",
                "name": "Sheet",
                "kind": "spritesheet",
                "content_type": "image/png",
                "bytes": 9,
                "data_url": "data:image/png;base64,cG5nLWJ5dGVz",
            }
        ]
    }

    other_headers = auth_headers(client, email="generated-assets-other@example.com", display_name="Other")
    forbidden = client.get(f"/tasks/{task_id}/generated-assets", headers=other_headers)
    assert forbidden.status_code == 403
