import json
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
                    input_tokens_details=SimpleNamespace(
                        cached_tokens=600,
                        cache_write_tokens=400,
                    ),
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
    assert result.cache_write_tokens == 400
    # stream_tokens=0 起始行 + prompt cache 观测行，各发一次 log_appended
    assert published_events == [(task.id, "log_appended"), (task.id, "log_appended")]

    db = db_session_factory()
    call = db.query(LLMCall).one()
    refreshed_task = db.get(GenerationTask, task.id)
    refreshed_step = db.get(AgentStep, step.id)
    assert call.task_id == task.id
    assert call.step_id == step.id
    assert call.total_tokens == 3000
    assert call.cached_tokens == 600
    assert call.cache_write_tokens == 400
    assert call.cost_usd == Decimal("0.021250")
    assert refreshed_step.tokens == 3000
    assert refreshed_task.tokens_used == 3000
    assert refreshed_task.cost_usd == Decimal("0.021250")
    cache_log = (
        db.query(AgentLog)
        .filter(AgentLog.step_id == step.id, AgentLog.line.like("prompt cache:%"))
        .one()
    )
    assert cache_log.line == "prompt cache: 600/1000 read (60%), 400 written"
    event = json.loads(cache_log.payload_json)
    assert event["type"] == "usage"
    assert event["cached_tokens"] == 600
    assert event["cache_write_tokens"] == 400
    assert event["cache_percent"] == 60
    db.close()


def test_llm_chat_builds_gpt56_explicit_prompt_cache_request(monkeypatch):
    from app.agents import llm
    from app.core.telemetry import bind_context, clear_context

    captured = {}
    progress = []
    response = SimpleNamespace(
        id="resp_cache_write",
        model="gpt-5.6-sol",
        output=[],
        usage=SimpleNamespace(
            input_tokens=2200,
            output_tokens=40,
            total_tokens=2240,
            input_tokens_details=SimpleNamespace(
                cached_tokens=0,
                cache_write_tokens=1772,
            ),
        ),
    )

    class _FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(type="response.output_text.delta", delta='{"ok":true}'),
                SimpleNamespace(type="response.completed", response=response),
            ]

    monkeypatch.setattr(
        llm,
        "_client",
        lambda timeout=None: SimpleNamespace(responses=_FakeResponses()),
    )
    monkeypatch.setattr(
        llm,
        "_record_call",
        lambda _result, retried=False, previous_response_id=None: None,
    )
    monkeypatch.setattr(
        llm,
        "_record_stream_progress",
        lambda line, payload=None: progress.append((line, payload)),
    )
    monkeypatch.setattr(llm.settings, "CODE_AGENT_PROMPT_CACHE_KEY_PREFIX", "cache-test")
    monkeypatch.setattr(llm.settings, "OPENAI_EXPLICIT_PROMPT_CACHE_ENABLED", True)

    cache_prefix = "Stable shared planning contract. " * 400
    system = f"{cache_prefix}\n\nNODE-SPECIFIC RESPONSIBILITY:\nReturn JSON."
    bind_context(task_id="12345678-1234-4abc-9def-1234567890ab")
    try:
        result = llm.chat(
            system,
            "dynamic game state",
            model="gpt-5.6-sol",
            cache_namespace="planning-v1",
            cache_prefix=cache_prefix,
        )
    finally:
        clear_context()

    assert "instructions" not in captured
    assert captured["prompt_cache_key"] == "cache-test:planning-v1:123456781234"
    assert captured["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert captured["input"][0] == {
        "type": "message",
        "role": "developer",
        "content": [
            {
                "type": "input_text",
                "text": cache_prefix,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ],
    }
    assert captured["input"][1]["role"] == "developer"
    assert captured["input"][1]["content"][0]["text"].startswith(
        "NODE-SPECIFIC RESPONSIBILITY:"
    )
    assert captured["input"][2]["role"] == "user"
    assert captured["input"][2]["content"][0]["text"] == "dynamic game state"
    assert result.cache_write_tokens == 1772
    usage_line, usage_payload = next(
        (line, payload) for line, payload in progress if line.startswith("prompt cache:")
    )
    assert usage_line == "prompt cache: 0/2200 read (0%), 1772 written"
    assert usage_payload["cache_write_tokens"] == 1772
    assert usage_payload["prompt_cache_mode"] == "explicit"


def test_sdk_response_ledger_is_idempotent_and_survives_run_level_stops(
    db_session_factory, monkeypatch
):
    from app.agents import llm
    from app.models import AgentStep, GenerationTask, LLMCall
    from app.models.common import StepStatus

    db = db_session_factory()
    user = _user()
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="generate with a bounded team")
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

    monkeypatch.setattr(llm, "SessionLocal", db_session_factory)
    kwargs = {
        "model": "gpt-5.5",
        "prompt_tokens": 80,
        "completion_tokens": 20,
        "cached_tokens": 40,
        "latency_ms": 123,
        "step_id": step_id,
        "run_id": "team-run-1",
        "agent": "RulesAndSimulationCoder",
        "workflow_name": "gameweave-project-rules",
        "provider_response_id": "resp-ledger-1",
        "request_index": 1,
        "retried": True,
    }
    llm.record_response_usage(**kwargs)
    # A reconnect/replay must not double charge or double count.
    llm.record_response_usage(**kwargs)

    db = db_session_factory()
    rows = db.query(LLMCall).all()
    assert len(rows) == 1
    assert rows[0].run_id == "team-run-1"
    assert rows[0].agent == "RulesAndSimulationCoder"
    assert rows[0].provider_response_id == "resp-ledger-1"
    assert rows[0].request_index == 1
    assert rows[0].total_tokens == 100
    assert rows[0].cached_tokens == 40
    assert rows[0].retried is True
    assert db.get(AgentStep, step_id).tokens == 100
    assert db.get(GenerationTask, task_id).tokens_used == 100
    db.close()


def test_unexpected_ledger_integrity_error_is_reported(monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.agents import llm

    class BrokenSession:
        def add(self, _row):
            return None

        def flush(self):
            raise IntegrityError(
                "INSERT INTO llm_calls",
                {},
                RuntimeError("CHECK constraint failed: total_tokens"),
            )

        def rollback(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(llm, "SessionLocal", BrokenSession)
    reported = []
    monkeypatch.setattr(
        llm.logger,
        "exception",
        lambda message, *args, **kwargs: reported.append(message),
    )
    inserted = llm._persist_call(
        llm.LLMResult(
            text="",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            model="gpt-test",
            latency_ms=1,
        ),
        task_id="task-test",
        run_id="run-test",
    )

    assert inserted is False
    assert reported == ["unexpected llm usage ledger integrity failure"]


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
    monkeypatch.setattr(
        llm,
        "_record_call",
        lambda _result, retried=False, previous_response_id=None: None,
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm.settings, "OPENAI_MAX_RETRIES", 2)

    result = llm.chat("system", "user")

    assert result.text == "recovered"
    assert responses.calls == 2


def test_llm_chat_retries_provider_internal_server_error(monkeypatch):
    from app.agents import llm

    completed = SimpleNamespace(
        model="gpt-5.5",
        output=[],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30),
    )
    failed = SimpleNamespace(
        type="error",
        error=SimpleNamespace(code="internal_server_error", message="unexpected EOF"),
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
    monkeypatch.setattr(
        llm,
        "_record_call",
        lambda _result, retried=False, previous_response_id=None: None,
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm.settings, "OPENAI_MAX_RETRIES", 2)

    result = llm.chat("system", "user")

    assert result.text == "recovered"
    assert responses.calls == 2


def test_llm_chat_retries_top_level_response_error_event(monkeypatch):
    from app.agents import llm

    completed = SimpleNamespace(
        model="gpt-5.6-sol",
        output=[],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30),
    )
    failed = SimpleNamespace(
        type="error",
        code="internal_server_error",
        message="stream error: INTERNAL_ERROR received from peer",
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
    monkeypatch.setattr(
        llm,
        "_record_call",
        lambda _result, retried=False, previous_response_id=None: None,
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm.settings, "OPENAI_MAX_RETRIES", 2)

    result = llm.chat("system", "user")

    assert result.text == "recovered"
    assert responses.calls == 2


def test_llm_chat_recovers_complete_json_from_interrupted_attempt(monkeypatch):
    from app.agents import llm

    complete_json = '{"title":"Recovered","genre":"strategy","core_loop":"plan, build, resolve"}'

    class _FakeResponses:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                def interrupted():
                    yield SimpleNamespace(
                        type="response.output_text.delta",
                        delta=complete_json,
                    )
                    raise ConnectionError("peer closed connection")

                return interrupted()
            raise ConnectionError("connection unavailable")

    responses = _FakeResponses()
    recorded = []
    monkeypatch.setattr(llm, "_client", lambda timeout=None: SimpleNamespace(responses=responses))
    monkeypatch.setattr(llm, "_record_stream_progress", lambda _line, payload=None: None)
    monkeypatch.setattr(
        llm,
        "_record_call",
        lambda result, retried=False, previous_response_id=None: recorded.append(
            (result, retried)
        ),
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm.settings, "OPENAI_MAX_RETRIES", 2)
    monkeypatch.setattr(llm.settings, "OPENAI_PARTIAL_STREAM_MIN_CHARS", 2000)

    result = llm.chat("system", "user", recover_partial_json=True)

    assert result.partial is True
    assert json.loads(result.text)["title"] == "Recovered"
    assert responses.calls == 3
    assert recorded == [(result, True)]


def test_llm_chat_logs_stream_failure_details_and_closes_each_attempt(monkeypatch):
    from app.agents import llm

    completed = SimpleNamespace(
        id="resp-ok",
        model="gpt-5.5",
        output=[],
        usage=SimpleNamespace(input_tokens=3, output_tokens=1, total_tokens=4),
    )

    class _FakeStream:
        def __init__(self, events=None, error=None):
            self.events = list(events or [])
            self.error = error
            self.closed = False

        def __iter__(self):
            if self.error is not None:
                raise self.error
            return iter(self.events)

        def close(self):
            self.closed = True

    class _FakeClient:
        def __init__(self, stream):
            self.stream = stream
            self.responses = SimpleNamespace(create=lambda **_kwargs: self.stream)
            self.closed = False

        def close(self):
            self.closed = True

    streams = [
        _FakeStream(error=TimeoutError("local stream read timed out")),
        _FakeStream(
            events=[
                SimpleNamespace(type="response.output_text.delta", delta="OK"),
                SimpleNamespace(type="response.completed", response=completed),
            ]
        ),
    ]
    all_clients = [_FakeClient(stream) for stream in streams]
    pending_clients = list(all_clients)
    progress = []
    monkeypatch.setattr(llm, "_client", lambda timeout=None: pending_clients.pop(0))
    monkeypatch.setattr(
        llm,
        "_record_stream_progress",
        lambda line, payload=None: progress.append((line, payload)),
    )
    monkeypatch.setattr(
        llm,
        "_record_call",
        lambda _result, retried=False, previous_response_id=None: None,
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm.settings, "OPENAI_MAX_RETRIES", 1)

    result = llm.chat("system", "user")

    assert result.text == "OK"
    assert all(stream.closed for stream in streams)
    assert all(client.closed for client in all_clients)
    failure = next(payload for _line, payload in progress if payload and payload.get("type") == "llm_stream_error")
    assert failure["exception_type"] == "TimeoutError"
    assert failure["will_retry"] is True
    assert failure["partial_chars"] == 0


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
