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
    assert response.text.count("event: task\n") == 1
    assert response.text.count("event: task_delta\n") == 1
    assert '"status":"pending"' in response.text
    assert '"status":"succeeded"' in response.text


def test_task_event_stream_resumes_from_durable_log_cursor(
    client, db_session_factory, monkeypatch
):
    from app.models import AgentLog, AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus, now_utc

    headers = auth_headers(client, email="sse-resume@x.com", display_name="SSE")
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.FAILED
    step = AgentStep(
        task_id=task_id,
        seq=1,
        agent="GameCodeAgent",
        name="Code Generation",
        status=StepStatus.FAILED,
        started_at=now_utc(),
        finished_at=now_utc(),
    )
    db.add(step)
    db.flush()
    first = AgentLog(step_id=step.id, seq=0, line="first")
    second = AgentLog(step_id=step.id, seq=1, line="second")
    db.add_all([first, second])
    db.commit()
    first_cursor, second_cursor = first.id, second.id
    db.close()

    monkeypatch.setattr("app.api.routers.tasks.SessionLocal", db_session_factory)

    def fail_full_snapshot(*_args):
        raise AssertionError("resume must not build a full snapshot")

    monkeypatch.setattr(
        "app.api.routers.tasks._event_snapshot",
        fail_full_snapshot,
    )
    response = client.get(
        f"/tasks/{task_id}/events",
        headers={**headers, "Last-Event-ID": str(first_cursor)},
    )

    assert response.status_code == 200
    assert "event: task_delta\n" in response.text
    assert "event: task\n" not in response.text
    assert f"id: {second_cursor}\n" in response.text
    assert '"line":"second"' in response.text
    assert '"line":"first"' not in response.text


def test_snapshot_cursor_never_advances_past_serialized_logs(
    client, db_session_factory, monkeypatch
):
    from app.api.routers import tasks as task_router
    from app.models import GenerationTask

    headers = auth_headers(client, email="sse-snapshot-cursor@x.com", display_name="SSE")
    task_id = _make_task(client, headers)
    db = db_session_factory()
    user_id = db.get(GenerationTask, task_id).user_id
    db.close()

    payload = {
        "id": task_id,
        "status": "running",
        "logs": [
            {"entries": [{"cursor": 4}, {"cursor": 9}]},
            {"entries": [{"cursor": 7}, {"cursor": None}]},
        ],
    }
    monkeypatch.setattr(task_router, "SessionLocal", db_session_factory)
    monkeypatch.setattr(task_router, "task_out", lambda _task: payload)

    state, snapshot, cursor = task_router._event_snapshot(task_id, user_id)

    assert state == "ok"
    assert snapshot is payload
    assert cursor == 9


def test_task_delta_patches_finished_step_without_requiring_a_new_log(
    client, db_session_factory, monkeypatch
):
    from app.api.routers import tasks as task_router
    from app.models import AgentLog, AgentStep, GenerationTask
    from app.models.common import StepStatus, now_utc

    headers = auth_headers(client, email="sse-step-patch@x.com", display_name="SSE")
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    step = AgentStep(
        task_id=task_id,
        seq=1,
        agent="GameCodeAgent",
        name="Code Generation",
        status=StepStatus.RUNNING,
        started_at=now_utc(),
    )
    db.add(step)
    db.flush()
    log = AgentLog(step_id=step.id, seq=0, line="started")
    db.add(log)
    db.commit()
    cursor = log.id
    user_id = task.user_id
    step.status = StepStatus.DONE
    step.finished_at = now_utc()
    db.commit()
    db.close()

    monkeypatch.setattr(task_router, "SessionLocal", db_session_factory)
    state, delta, next_cursor = task_router._event_delta(task_id, user_id, cursor)

    assert state == "ok"
    assert next_cursor == cursor
    assert delta["logs"] == []
    assert delta["steps"] == [
        {
            "step_id": step.id,
            "agent_name": "GameCodeAgent",
            "step": "Code Generation",
            "status": "completed",
            "duration": delta["steps"][0]["duration"],
        }
    ]
    assert delta["steps"][0]["duration"] is not None


def test_sqlite_agent_log_cursor_is_not_reused_after_delete(db_session_factory):
    from app.models import AgentLog, AgentStep, GenerationTask, User
    from app.models.common import StepStatus

    db = db_session_factory()
    user = User(
        email="cursor-sequence@x.com",
        display_name="Cursor",
        avatar_initial="C",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="cursor sequence")
    db.add(task)
    db.flush()
    step = AgentStep(
        task_id=task.id,
        seq=1,
        agent="GameCodeAgent",
        name="Code Generation",
        status=StepStatus.RUNNING,
    )
    db.add(step)
    db.flush()
    first = AgentLog(step_id=step.id, seq=0, line="first")
    db.add(first)
    db.commit()
    first_id = first.id
    db.delete(first)
    db.commit()
    second = AgentLog(step_id=step.id, seq=0, line="second")
    db.add(second)
    db.commit()

    assert second.id > first_id
    db.close()


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


def test_repair_step_emits_explicit_attempt_event_and_log_seq_uses_max(
    client, db_session_factory, monkeypatch
):
    import json

    from app.agents import tracing
    from app.models import AgentLog

    headers = auth_headers(client, email="repair-event@x.com", display_name="Repair")
    task_id = _make_task(client, headers)
    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.tracing.publish_task_event", lambda *_args: None)

    step_id = tracing.begin_step(task_id, "GameCodeAgentRepair", "Repair Code")
    db = db_session_factory()
    logs = db.query(AgentLog).filter(AgentLog.step_id == step_id).order_by(AgentLog.seq).all()
    event = json.loads(logs[1].payload_json)
    assert event == {
        "type": "repair_attempt_started",
        "agent": "GameCodeAgentRepair",
        "operation": "repairing",
        "repair_kind": "build",
        "attempt": 1,
        "max_attempts": 4,
        "caused_by_step_id": None,
        "status": "running",
    }
    db.add(AgentLog(step_id=step_id, seq=10, line="legacy gap"))
    db.commit()
    db.close()

    assert tracing.record_step_log("after gap", step_id=step_id)
    db = db_session_factory()
    appended = (
        db.query(AgentLog)
        .filter(AgentLog.step_id == step_id, AgentLog.line == "after gap")
        .one()
    )
    assert appended.seq == 11
    db.close()


def test_finish_step_reconciles_llm_ledger_without_double_charging(
    client, db_session_factory, monkeypatch
):
    from app.agents import tracing
    from app.models import AgentStep, GenerationTask, LLMCall

    headers = auth_headers(client, email="token-reconcile@x.com", display_name="Tokens")
    task_id = _make_task(client, headers)
    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.tracing.publish_task_event", lambda *_args: None)

    step_id = tracing.begin_step(task_id, "GameCodeAgent", "Code Generation")
    db = db_session_factory()
    step = db.get(AgentStep, step_id)
    task = db.get(GenerationTask, task_id)
    db.add(
        LLMCall(
            task_id=task_id,
            step_id=step_id,
            model="gpt-test",
            prompt_tokens=80,
            completion_tokens=20,
            total_tokens=100,
        )
    )
    # Persisted usage recording has already applied these atomic counters.
    step.tokens = 100
    task.tokens_used = 100
    db.commit()
    db.close()

    tracing.finish_step(task_id, step_id, ["done"], tokens=100)

    db = db_session_factory()
    assert db.get(AgentStep, step_id).tokens == 100
    assert db.get(GenerationTask, task_id).tokens_used == 100
    db.close()
