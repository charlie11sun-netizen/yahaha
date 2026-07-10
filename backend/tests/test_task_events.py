from conftest import auth_headers


def _make_task(client, headers):
    response = client.post(
        "/tasks",
        json={"idea": "an SSE task"},
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()["task_id"]


def test_terminal_task_event_stream_sends_snapshot_and_closes(
    client, db_session_factory, monkeypatch
):
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="sse-terminal@x.com", display_name="SSE")
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.FAILED
    task.error = "stopped"
    db.commit()
    db.close()

    monkeypatch.setattr("app.api.routers.tasks.SessionLocal", db_session_factory)
    response = client.get(f"/tasks/{task_id}/events", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert "event: task" in response.text
    assert '"status":"failed"' in response.text


def test_task_event_stream_pushes_redis_invalidated_state(
    client, db_session_factory, monkeypatch
):
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="sse-live@x.com", display_name="SSE")
    task_id = _make_task(client, headers)
    monkeypatch.setattr("app.api.routers.tasks.SessionLocal", db_session_factory)

    async def fake_events(_task_id):
        db = db_session_factory()
        task = db.get(GenerationTask, task_id)
        task.status = TaskStatus.SUCCEEDED
        db.commit()
        db.close()
        yield "updated"

    monkeypatch.setattr("app.api.routers.tasks.subscribe_task_events", fake_events)
    response = client.get(f"/tasks/{task_id}/events", headers=headers)

    assert response.status_code == 200
    assert response.text.count("event: task") == 2
    assert '"status":"pending"' in response.text
    assert '"status":"succeeded"' in response.text


def test_task_event_stream_enforces_ownership(client, db_session_factory, monkeypatch):
    owner = auth_headers(client, email="sse-owner@x.com", display_name="Owner")
    task_id = _make_task(client, owner)
    other = auth_headers(client, email="sse-other@x.com", display_name="Other")
    monkeypatch.setattr("app.api.routers.tasks.SessionLocal", db_session_factory)

    response = client.get(f"/tasks/{task_id}/events", headers=other)

    assert response.status_code == 403


def test_tracing_publishes_step_and_log_invalidations(
    client, db_session_factory, monkeypatch
):
    from app.agents import tracing

    headers = auth_headers(client, email="sse-tracing@x.com", display_name="SSE")
    task_id = _make_task(client, headers)
    published = []
    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.tracing.publish_task_event",
        lambda current_task_id, kind="updated": published.append((current_task_id, kind)),
    )

    step_id = tracing.begin_step(task_id, "PlannerAgent", "Intent Spec")
    assert tracing.record_step_log("working", step_id=step_id) is True
    tracing.finish_step(task_id, step_id, ["done"])

    assert published == [
        (task_id, "step_started"),
        (task_id, "log_appended"),
        (task_id, "step_finished"),
    ]
