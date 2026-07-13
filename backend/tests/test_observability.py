from decimal import Decimal
from types import SimpleNamespace

import pytest


def _user():
    from app.models import User

    return User(
        email="obs@example.com",
        password_hash="x",
        display_name="Observer",
        avatar_initial="O",
    )


def test_llm_chat_records_usage_and_cost(db_session_factory, monkeypatch):
    import json

    from app.agents import llm
    from app.core.telemetry import bind_context, clear_context
    from app.models import AgentLog, AgentStep, GenerationTask, LLMCall
    from app.models.common import StepStatus

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="make a game")
    db.add(task)
    db.flush()
    step = AgentStep(
        task_id=task.id,
        seq=1,
        agent="GameDesignAgent",
        name="Game Design",
        status=StepStatus.RUNNING,
    )
    db.add(step)
    db.commit()
    db.close()

    class _FakeResponses:
        def create(self, **_kwargs):
            response = SimpleNamespace(
                model="gpt-5.5",
                output=[],
                usage=SimpleNamespace(
                    input_tokens=1000,
                    output_tokens=2000,
                    total_tokens=3000,
                    input_tokens_details=SimpleNamespace(cached_tokens=600),
                ),
            )
            return [
                SimpleNamespace(type="response.output_text.delta", delta=" playable"),
                SimpleNamespace(type="response.output_text.delta", delta=" plan "),
                SimpleNamespace(type="response.completed", response=response),
            ]

    fake_client = SimpleNamespace(responses=_FakeResponses())
    published_events = []
    monkeypatch.setattr(llm, "SessionLocal", db_session_factory)
    monkeypatch.setattr(llm, "_client", lambda timeout=None: fake_client)
    monkeypatch.setattr(
        llm,
        "publish_task_event",
        lambda task_id, event: published_events.append((task_id, event)),
    )

    bind_context(task_id=task.id, step_id=step.id)
    try:
        result = llm.chat("system", "user")
    finally:
        clear_context()

    text, tokens = result
    assert text == "playable plan"
    assert tokens == 3000
    assert result.prompt_tokens == 1000
    assert result.completion_tokens == 2000
    assert result.cached_tokens == 600
    # stream_tokens=0 起始行 + prompt cache 观测行，各发一次 log_appended
    assert published_events == [(task.id, "log_appended"), (task.id, "log_appended")]

    db = db_session_factory()
    call = db.query(LLMCall).one()
    refreshed_task = db.get(GenerationTask, task.id)
    assert call.task_id == task.id
    assert call.step_id == step.id
    assert call.total_tokens == 3000
    assert call.cached_tokens == 600
    assert call.cost_usd == Decimal("0.021250")
    assert refreshed_task.cost_usd == Decimal("0.021250")
    cache_log = (
        db.query(AgentLog)
        .filter(AgentLog.step_id == step.id, AgentLog.line.like("prompt cache:%"))
        .one()
    )
    assert cache_log.line == "prompt cache: 600/1000 read (60%)"
    event = json.loads(cache_log.payload_json)
    assert event["type"] == "usage"
    assert event["cached_tokens"] == 600
    assert event["cache_percent"] == 60
    db.close()


def test_code_agent_detailed_trace_switch_controls_full_payload(
    db_session_factory, monkeypatch
):
    import json

    from app.agents import detailed_trace, llm
    from app.core.telemetry import bind_context, clear_context
    from app.models import AgentStep, AgentTraceEvent, GenerationTask
    from app.models.common import StepStatus

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="trace a code run")
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

    class _FakeResponses:
        def create(self, **_kwargs):
            response = SimpleNamespace(
                model="gpt-trace",
                output=[SimpleNamespace(type="message", content="complete model output")],
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
            )
            return [
                SimpleNamespace(type="response.output_text.delta", delta="complete model output"),
                SimpleNamespace(type="response.completed", response=response),
            ]

    monkeypatch.setattr(llm, "SessionLocal", db_session_factory)
    monkeypatch.setattr(detailed_trace, "SessionLocal", db_session_factory)
    monkeypatch.setattr(
        llm,
        "_client",
        lambda timeout=None: SimpleNamespace(responses=_FakeResponses()),
    )
    monkeypatch.setattr(llm, "publish_task_event", lambda *_args: None)

    full_system = "SYSTEM-DETAIL\n" + ("policy line\n" * 200)
    full_user = "USER-DETAIL\n" + ("game requirement\n" * 200)
    bind_context(
        task_id=task_id,
        step_id=step_id,
        agent="GameCodeAgent",
        node_name="Code Generation",
    )
    try:
        monkeypatch.setattr(
            llm.settings, "CODE_AGENT_DETAILED_LOGGING_ENABLED", False
        )
        llm.chat(full_system, full_user, model="gpt-trace")
        db = db_session_factory()
        assert db.query(AgentTraceEvent).count() == 0
        db.close()

        monkeypatch.setattr(
            llm.settings, "CODE_AGENT_DETAILED_LOGGING_ENABLED", True
        )
        llm.chat(full_system, full_user, model="gpt-trace")
    finally:
        clear_context()

    db = db_session_factory()
    rows = db.query(AgentTraceEvent).order_by(AgentTraceEvent.seq).all()
    assert [row.event_type for row in rows] == [
        "run_start",
        "llm_input",
        "llm_output",
        "run_end",
    ]
    assert len({row.run_id for row in rows}) == 1
    start_payload = json.loads(rows[0].payload_json)
    output_payload = json.loads(rows[2].payload_json)
    assert start_payload["system_prompt"] == full_system
    assert start_payload["user_input"] == full_user
    assert output_payload["text"] == "complete model output"
    assert rows[0].payload_chars == len(rows[0].payload_json)
    db.close()


def test_agents_sdk_hooks_capture_full_llm_and_tool_io(
    db_session_factory, monkeypatch
):
    import asyncio
    import json

    from app.agents import detailed_trace
    from app.core.telemetry import bind_context, clear_context
    from app.models import AgentStep, AgentTraceEvent, GenerationTask
    from app.models.common import StepStatus

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="hook trace")
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

    monkeypatch.setattr(
        detailed_trace.settings, "CODE_AGENT_DETAILED_LOGGING_ENABLED", True
    )
    monkeypatch.setattr(detailed_trace, "SessionLocal", db_session_factory)
    bind_context(task_id=task_id, step_id=step_id, agent="GameCodeAgent")
    try:
        recorder = detailed_trace.create_recorder(
            source="agents_sdk", agent="GameProjectAuthor", model="gpt-trace"
        )
        hooks = detailed_trace.build_run_hooks(recorder)
        context = SimpleNamespace(
            usage=SimpleNamespace(total_tokens=9),
            tool_call_id="call-1",
            tool_name="write_file",
            tool_arguments='{"path":"src/main.ts","content":"FULL SOURCE"}',
        )
        agent = SimpleNamespace(name="GameProjectAuthor")
        tool = SimpleNamespace(
            type="function",
            name="write_file",
            description="write a complete file",
            params_json_schema={"type": "object"},
        )
        response = SimpleNamespace(
            model="gpt-trace",
            output=[{"type": "function_call", "arguments": "FULL SOURCE"}],
        )

        async def exercise_hooks():
            await hooks.on_llm_start(
                context,
                agent,
                "FULL SYSTEM PROMPT",
                [{"role": "user", "content": "FULL USER INPUT"}],
            )
            await hooks.on_llm_end(context, agent, response)
            await hooks.on_tool_start(context, agent, tool)
            await hooks.on_tool_end(context, agent, tool, "FULL TOOL RESULT")

        asyncio.run(exercise_hooks())
    finally:
        clear_context()

    db = db_session_factory()
    rows = db.query(AgentTraceEvent).order_by(AgentTraceEvent.seq).all()
    assert [row.event_type for row in rows] == [
        "llm_input",
        "llm_output",
        "tool_input",
        "tool_output",
    ]
    assert json.loads(rows[0].payload_json)["system_prompt"] == "FULL SYSTEM PROMPT"
    tool_output = json.loads(rows[-1].payload_json)
    assert tool_output["tool_arguments"].endswith('"FULL SOURCE"}')
    assert tool_output["result"] == "FULL TOOL RESULT"
    db.close()


def test_tracing_tracks_attempts_tokens_and_failure_chain(db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.core.telemetry import clear_context
    from app.models import AgentStep, GenerationTask

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="make a game")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    monkeypatch.setattr(tracing, "SessionLocal", db_session_factory)

    failed_step_id = tracing.begin_step(task_id, "BuildValidateAgent", "Build Validation")
    tracing.finish_step(
        task_id,
        failed_step_id,
        ["validation failed"],
        tokens=123,
        failed=True,
    )
    repair_step_id = tracing.begin_step(task_id, "GameCodeAgentRepair", "Repair Code")
    second_repair_step_id = tracing.begin_step(task_id, "GameCodeAgentRepair", "Repair Code")

    db = db_session_factory()
    failed_step = db.get(AgentStep, failed_step_id)
    repair_step = db.get(AgentStep, repair_step_id)
    second_repair_step = db.get(AgentStep, second_repair_step_id)
    refreshed_task = db.get(GenerationTask, task_id)

    assert failed_step.tokens == 123
    assert refreshed_task.tokens_used == 123
    assert refreshed_task.failed_stage == "Build Validation"
    assert repair_step.attempt == 1
    assert repair_step.caused_by_step_id == failed_step_id
    assert second_repair_step.attempt == 2
    assert second_repair_step.caused_by_step_id == failed_step_id
    db.close()
    clear_context()


def test_llm_chat_retries_streamed_server_error(monkeypatch):
    from app.agents import llm

    completed = SimpleNamespace(
        model="gpt-5.5",
        output=[],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30),
    )
    failed = SimpleNamespace(
        type="response.failed",
        response=SimpleNamespace(
            error=SimpleNamespace(
                code="server_error",
                message="An error occurred while processing your request. You can retry your request.",
            )
        ),
    )

    class _FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return [failed]
            return [
                SimpleNamespace(type="response.output_text.delta", delta="recovered"),
                SimpleNamespace(type="response.completed", response=completed),
            ]

    responses = _FakeResponses()
    monkeypatch.setattr(llm, "_client", lambda timeout=None: SimpleNamespace(responses=responses))
    monkeypatch.setattr(llm, "_record_stream_progress", lambda _line, payload=None: None)
    monkeypatch.setattr(llm, "_record_call", lambda _result, retried=False: None)
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm.settings, "OPENAI_MAX_RETRIES", 2)

    result = llm.chat("system", "user")

    assert result.text == "recovered"
    assert responses.calls == 2


def test_llm_chat_does_not_retry_streamed_invalid_prompt(monkeypatch):
    from app.agents import llm

    failed = SimpleNamespace(
        type="response.failed",
        response=SimpleNamespace(
            error=SimpleNamespace(code="invalid_prompt", message="Prompt is invalid")
        ),
    )

    class _FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            return [failed]

    responses = _FakeResponses()
    monkeypatch.setattr(llm, "_client", lambda timeout=None: SimpleNamespace(responses=responses))
    monkeypatch.setattr(llm, "_record_stream_progress", lambda _line, payload=None: None)
    monkeypatch.setattr(llm.settings, "OPENAI_MAX_RETRIES", 2)

    with pytest.raises(llm.LLMResponseError, match="Prompt is invalid"):
        llm.chat("system", "user")

    assert responses.calls == 1


def test_tracing_records_live_step_logs_without_finish_duplicates(db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.core.telemetry import clear_context
    from app.models import AgentLog, GenerationTask
    from app.services.serialize import task_out

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="make a game")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    monkeypatch.setattr(tracing, "SessionLocal", db_session_factory)

    step_id = tracing.begin_step(task_id, "GameCodeAgent", "Code Generation")
    payload = {
        "type": "file_change",
        "tool": "write_file",
        "action": "modified",
        "path": "game.js",
        "added": 12,
        "deleted": 3,
    }
    assert tracing.record_step_log("agent wrote game.js (+12 -3, 1200B)", step_id=step_id, payload=payload)

    db = db_session_factory()
    live_logs = db.query(AgentLog).filter(AgentLog.step_id == step_id).order_by(AgentLog.seq).all()
    live_lines = [log.line for log in live_logs]
    assert "agent wrote game.js (+12 -3, 1200B)" in live_lines
    payload_log = next(log for log in live_logs if log.line.startswith("agent wrote game.js"))
    assert payload_log.payload_json
    dto = task_out(db.get(GenerationTask, task_id))
    entries = dto["logs"][-1]["entries"]
    assert entries[-1]["event"]["type"] == "file_change"
    assert entries[-1]["event"]["path"] == "game.js"
    db.close()

    tracing.finish_step(task_id, step_id, ["agent wrote game.js (+12 -3, 1200B)", "generated files: game.js (1 file(s))"])

    db = db_session_factory()
    final_lines = [log.line for log in db.query(AgentLog).filter(AgentLog.step_id == step_id).order_by(AgentLog.seq)]
    assert final_lines.count("agent wrote game.js (+12 -3, 1200B)") == 1
    assert final_lines[-1] == "generated files: game.js (1 file(s))"
    db.close()
    clear_context()
