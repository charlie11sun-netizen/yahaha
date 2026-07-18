import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def test_agents_sdk_hooks_offload_writes_and_store_history_deltas(monkeypatch):
    from app.agents import detailed_trace

    recorder = detailed_trace.TraceRecorder(
        task_id="task-test",
        step_id="step-test",
        source="agents_sdk",
        agent="GameProjectAuthor",
        model="gpt-test",
    )
    calls = []

    def capture_record(event_type, payload, *, agent=None, model=None):
        calls.append((event_type, payload, threading.get_ident()))
        return True

    monkeypatch.setattr(recorder, "record", capture_record)
    hooks = detailed_trace.build_run_hooks(recorder)
    context = SimpleNamespace(usage=SimpleNamespace(total_tokens=0))
    agent = SimpleNamespace(name="GameProjectAuthor")
    first_item = {"role": "user", "content": "first"}

    async def exercise_hooks():
        loop_thread = threading.get_ident()
        await hooks.on_llm_start(context, agent, "SYSTEM", [first_item])
        await hooks.on_llm_start(
            context,
            agent,
            "SYSTEM",
            [
                first_item,
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "second"},
            ],
        )
        await hooks.on_agent_end(context, agent, "done")
        return loop_thread

    loop_thread = asyncio.run(exercise_hooks())

    assert [call[0] for call in calls] == ["llm_input", "llm_input", "agent_end"]
    first_payload = calls[0][1]
    second_payload = calls[1][1]
    assert first_payload["history_mode"] == "snapshot"
    assert first_payload["input_items"] == [first_item]
    assert second_payload["history_mode"] == "delta"
    assert second_payload["input_items_from_index"] == 1
    assert second_payload["input_items_total"] == 3
    assert second_payload["input_items"] == [
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    assert second_payload["system_prompt"] is None
    assert second_payload["system_prompt_reused"] is True
    assert all(call[2] != loop_thread for call in calls)


def test_trace_payload_warns_and_is_capped(monkeypatch):
    from app.agents import detailed_trace

    added = []
    warnings = []

    class _FakeSession:
        def add(self, row):
            added.append(row)

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(detailed_trace, "SessionLocal", _FakeSession)
    monkeypatch.setattr(
        detailed_trace.logger,
        "warning",
        lambda message, *args: warnings.append(message % args),
    )
    monkeypatch.setattr(detailed_trace.settings, "CODE_AGENT_TRACE_PAYLOAD_WARN_CHARS", 100)
    monkeypatch.setattr(detailed_trace.settings, "CODE_AGENT_TRACE_MAX_PAYLOAD_CHARS", 300)
    recorder = detailed_trace.TraceRecorder(
        task_id="task-test",
        step_id="step-test",
        source="agents_sdk",
        agent="GameProjectAuthor",
        model="gpt-test",
    )

    assert recorder.record("tool_output", {"result": "x" * 2_000}) is True

    assert len(added) == 1
    row = added[0]
    payload = json.loads(row.payload_json)
    assert row.payload_chars == len(row.payload_json) <= 300
    assert payload["_trace_payload_truncated"] is True
    assert payload["original_chars"] > 2_000
    assert payload["stored_limit_chars"] == 300
    assert "event_type=tool_output" in warnings[0]
    assert "truncated=True" in warnings[0]


def test_agent_trace_retention_task_deletes_only_expired_rows(
    db_session_factory, monkeypatch
):
    from app.models import AgentStep, AgentTraceEvent, GenerationTask, User
    from app.tasks import traces

    now = datetime(2026, 7, 18, tzinfo=timezone.utc)
    db = db_session_factory()
    user = User(
        email="trace-retention@example.com",
        password_hash="x",
        display_name="Trace Retention",
        avatar_initial="T",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="retain bounded traces")
    db.add(task)
    db.flush()
    step = AgentStep(task_id=task.id, seq=1, agent="GameCodeAgent", name="Code")
    db.add(step)
    db.flush()
    for seq, created_at in enumerate(
        (now - timedelta(days=8), now - timedelta(days=1)),
        start=1,
    ):
        db.add(
            AgentTraceEvent(
                task_id=task.id,
                step_id=step.id,
                run_id="run-retention",
                seq=seq,
                source="agents_sdk",
                event_type="llm_input",
                agent="GameProjectAuthor",
                model="gpt-test",
                payload_json="{}",
                payload_chars=2,
                created_at=created_at,
            )
        )
    db.commit()
    db.close()

    monkeypatch.setattr(traces, "SessionLocal", db_session_factory)
    monkeypatch.setattr(traces, "now_utc", lambda: now)
    monkeypatch.setattr(traces.settings, "CODE_AGENT_TRACE_RETENTION_DAYS", 7)

    assert traces.purge_expired_agent_traces.run() == 1

    db = db_session_factory()
    rows = db.query(AgentTraceEvent).all()
    assert len(rows) == 1
    assert rows[0].created_at.replace(tzinfo=timezone.utc) == now - timedelta(days=1)
    db.close()


def test_agent_trace_retention_is_registered_with_celery_beat():
    from app.tasks.celery_app import celery

    assert "app.tasks.traces" in celery.conf.include
    assert celery.conf.beat_schedule["purge-expired-agent-traces-daily"] == {
        "task": "purge_expired_agent_traces",
        "schedule": 24 * 60 * 60,
    }
