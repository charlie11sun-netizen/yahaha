import logging


def test_stream_progress_uses_shared_agent_log_append_contract(db_session_factory):
    from app.agents import llm_accounting
    from app.models import AgentLog, AgentStep, GenerationTask, User
    from app.models.common import StepStatus

    db = db_session_factory()
    user = User(
        email="agent-log@example.com",
        password_hash="x",
        display_name="Agent Log",
        avatar_initial="A",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="append logs")
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
    db.commit()
    task_id, step_id = task.id, step.id
    db.close()

    published = []
    context = {"task_id": task_id, "step_id": step_id}
    publish = lambda event_task_id, event_name: published.append((event_task_id, event_name))

    llm_accounting.record_stream_progress(
        "stream_tokens=4",
        {"type": "usage", "tokens": 4},
        session_factory=db_session_factory,
        context=context,
        publish_task_event=publish,
        logger=logging.getLogger("test-agent-log-append"),
        sleep=lambda _delay: None,
    )
    llm_accounting.record_stream_progress(
        "stream_tokens=8",
        None,
        session_factory=db_session_factory,
        context=context,
        publish_task_event=publish,
        logger=logging.getLogger("test-agent-log-append"),
        sleep=lambda _delay: None,
    )

    db = db_session_factory()
    logs = db.query(AgentLog).filter(AgentLog.step_id == step_id).order_by(AgentLog.seq).all()
    assert [log.seq for log in logs] == [0, 1]
    assert [log.level for log in logs] == ["info", "info"]
    assert logs[0].payload_json == '{"type": "usage", "tokens": 4}'
    assert logs[1].payload_json is None
    assert published == [(task_id, "log_appended"), (task_id, "log_appended")]
    db.close()


def test_finish_step_deduplicates_live_rows_by_occurrence(db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.models import AgentLog, AgentStep, GenerationTask, User
    from app.models.common import StepStatus

    db = db_session_factory()
    user = User(
        email="finish-log@example.com",
        password_hash="x",
        display_name="Finish Log",
        avatar_initial="F",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="finish repeated logs")
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
    db.add(AgentLog(step_id=step.id, seq=0, line="same line"))
    db.commit()
    task_id, step_id = task.id, step.id
    db.close()

    monkeypatch.setattr(tracing, "SessionLocal", db_session_factory)
    monkeypatch.setattr(tracing, "publish_task_event", lambda *_args: None)
    tracing.finish_step(task_id, step_id, ["same line", "same line"])

    db = db_session_factory()
    logs = db.query(AgentLog).filter(AgentLog.step_id == step_id).order_by(AgentLog.seq).all()
    assert [log.line for log in logs] == ["same line", "same line"]
    db.close()
