import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.agents import author_runner
from app.agents.repair_session import RepairSession


class _Session:
    def __init__(self):
        self.turns = []
        self.logs = []
        self.changed = set()

    def _turn(self, state, message, **payload):
        self.turns.append((state, message, payload))

    def _event(self, event_type, **payload):
        return {"type": event_type, **payload}

    def _log(self, message, **payload):
        self.logs.append((message, payload))


class _Result:
    def __init__(self, events, *, error=None, state="resume-state", final_output="DONE"):
        self._events = events
        self._error = error
        self._state = state
        self.final_output = final_output

    async def stream_events(self):
        for event in self._events:
            yield event
        if self._error is not None:
            raise self._error

    def to_state(self):
        return self._state


class _Runner:
    def __init__(self, results):
        self.results = list(results)
        self.inputs = []

    def run_streamed(self, _agent, input_value, **_kwargs):
        self.inputs.append(input_value)
        return self.results.pop(0)


def _raw(
    event_type,
    *,
    sequence=0,
    response_id="resp-1",
    error_code=None,
    delta=None,
    usage=None,
    model="gpt-test",
):
    error = (
        SimpleNamespace(code=error_code, message="failed") if error_code else None
    )
    response = SimpleNamespace(
        id=response_id,
        error=error,
        incomplete_details=None,
        usage=usage,
        model=model,
    )
    data = SimpleNamespace(
        type=event_type,
        response=response,
        sequence_number=sequence,
    )
    if delta is not None:
        data.delta = delta
    return SimpleNamespace(type="raw_response_event", data=data)


def _run(runner, session, *, safe_partial_stream_retry=False):
    return asyncio.run(
        author_runner._run_agent_streamed(
            runner,
            object(),
            "original-input",
            run_kwargs={"max_turns": 5},
            session=session,
            agent_name="GameProjectAuthor",
            activity=author_runner._StreamActivity(),
            execution_run_id="execution-test",
            workflow_name="stream-test",
            model_name="gpt-fallback",
            safe_partial_stream_retry=safe_partial_stream_retry,
        )
    )


def test_streamed_run_retries_terminal_failure_before_output(monkeypatch):
    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(author_runner.settings, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    first = _Result(
        [
            _raw("response.created"),
            _raw("response.failed", sequence=1, error_code="server_error"),
        ],
        error=RuntimeError("response failed"),
    )
    second = _Result(
        [
            _raw("response.created", response_id="resp-2"),
            _raw("response.completed", sequence=1, response_id="resp-2"),
        ],
        final_output="DONE after retry",
    )
    runner = _Runner([first, second])
    session = _Session()
    ledger = []
    monkeypatch.setattr(
        author_runner.llm,
        "record_response_usage",
        lambda **kwargs: ledger.append(kwargs),
    )

    result = _run(runner, session)

    assert result.final_output == "DONE after retry"
    assert runner.inputs == ["original-input", "resume-state"]
    assert session.turns[0][0] == "retrying"
    assert session.turns[0][2]["stream_event"] == "response.failed"
    assert session.turns[0][2]["error_code"] == "server_error"
    assert len(ledger) == 1
    assert ledger[0]["provider_response_id"] == "resp-2"
    assert ledger[0]["retried"] is True


def test_streamed_retry_uses_real_session_without_event_type_collision(monkeypatch):
    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(author_runner.settings, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    runner = _Runner(
        [
            _Result(
                [_raw("response.failed", error_code="server_error")],
                error=RuntimeError("response failed"),
            ),
            _Result([_raw("response.completed", response_id="resp-2")]),
        ]
    )
    session = RepairSession.from_files([])

    result = _run(runner, session)

    assert result.final_output == "DONE"
    assert any("retrying model turn" in line for line in session.log_lines)


def test_streamed_run_retries_transport_error_without_events(monkeypatch):
    class APITimeoutError(RuntimeError):
        pass

    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(author_runner.settings, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    runner = _Runner(
        [
            _Result([], error=APITimeoutError("request timed out")),
            _Result([_raw("response.completed", response_id="resp-2")]),
        ]
    )
    session = _Session()

    _run(runner, session)

    assert runner.inputs == ["original-input", "resume-state"]
    assert "APITimeoutError" in session.turns[0][1]


def test_streamed_run_retries_after_agent_event_idle_timeout(monkeypatch):
    class _SlowResult(_Result):
        async def stream_events(self):
            await asyncio.sleep(0.2)
            yield _raw("response.completed")

    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(author_runner.settings, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(author_runner.settings, "CODE_AGENT_STREAM_IDLE_TIMEOUT", 0.01)
    runner = _Runner(
        [
            _SlowResult([]),
            _Result([_raw("response.completed", response_id="resp-2")]),
        ]
    )
    session = _Session()

    result = _run(runner, session, safe_partial_stream_retry=True)

    assert result.final_output == "DONE"
    assert runner.inputs == ["original-input", "resume-state"]
    assert "TimeoutError" in session.turns[0][1]


def test_streamed_run_does_not_retry_after_partial_model_output(monkeypatch):
    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 2)
    monkeypatch.setattr(author_runner.settings, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    runner = _Runner(
        [
            _Result(
                [
                    _raw("response.created"),
                    _raw("response.output_text.delta", sequence=1, delta="partial"),
                    _raw("response.failed", sequence=2, error_code="server_error"),
                ],
                error=RuntimeError("response failed after partial output"),
            )
        ]
    )

    with pytest.raises(RuntimeError, match="partial output"):
        _run(runner, _Session())

    assert runner.inputs == ["original-input"]


def test_streamed_run_restarts_safe_read_only_turn_after_partial_transport_eof(
    monkeypatch,
):
    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(author_runner.settings, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    runner = _Runner(
        [
            _Result(
                [
                    _raw("response.created"),
                    _raw("response.output_text.delta", sequence=1, delta='{"partial":'),
                ],
                error=RuntimeError(
                    "peer closed connection without sending complete message body "
                    "(incomplete chunked read)"
                ),
            ),
            _Result(
                [_raw("response.completed", response_id="resp-2")],
                final_output='{"complete":true}',
            ),
        ]
    )
    session = _Session()

    result = _run(runner, session, safe_partial_stream_retry=True)

    assert result.final_output == '{"complete":true}'
    assert runner.inputs == ["original-input", "original-input"]
    assert "discardable partial output" in session.turns[0][1]


def test_streamed_run_does_not_restart_partial_turn_after_workspace_write(
    monkeypatch,
):
    class _WritingResult(_Result):
        async def stream_events(self):
            yield _raw("response.created")
            self.session.changed.add("src/systems/Rules.ts")
            yield _raw("response.output_text.delta", sequence=1, delta="partial")
            raise RuntimeError("unexpected EOF")

    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 1)
    monkeypatch.setattr(author_runner.settings, "OPENAI_RETRY_BACKOFF_SECONDS", 0)
    session = _Session()
    first = _WritingResult([])
    first.session = session
    runner = _Runner([first])

    with pytest.raises(RuntimeError, match="unexpected EOF"):
        _run(runner, session, safe_partial_stream_retry=True)

    assert runner.inputs == ["original-input"]


def test_streamed_run_emits_cumulative_usage_progress(monkeypatch):
    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 0)
    first_usage = SimpleNamespace(
        input_tokens=80,
        output_tokens=20,
        total_tokens=100,
        input_tokens_details=SimpleNamespace(
            cached_tokens=40,
            cache_write_tokens=30,
        ),
    )
    second_usage = SimpleNamespace(
        input_tokens=150,
        output_tokens=50,
        total_tokens=200,
        input_tokens_details=SimpleNamespace(
            cached_tokens=100,
            cache_write_tokens=20,
        ),
    )
    runner = _Runner(
        [
            _Result(
                [
                    _raw("response.created", response_id="resp-1"),
                    _raw("response.completed", response_id="resp-1", usage=first_usage),
                    _raw("response.created", response_id="resp-2"),
                    _raw("response.completed", response_id="resp-2", usage=second_usage),
                ]
            )
        ]
    )
    session = _Session()
    ledger = []
    monkeypatch.setattr(
        author_runner.llm,
        "record_response_usage",
        lambda **kwargs: ledger.append(kwargs),
    )

    _run(runner, session)

    progress = [item for item in session.logs if item[1].get("event", {}).get("type") == "usage_progress"]
    assert [item[0] for item in progress] == ["stream_tokens=100", "stream_tokens=300"]
    assert progress[-1][1]["event"] == {
        "type": "usage_progress",
        "agent": "GameProjectAuthor",
        "input_tokens": 230,
        "output_tokens": 70,
        "total_tokens": 300,
        "cached_tokens": 140,
        "cache_write_tokens": 50,
        "status": "running",
    }
    assert [row["provider_response_id"] for row in ledger] == ["resp-1", "resp-2"]
    assert [row["request_index"] for row in ledger] == [1, 2]
    assert [row["prompt_tokens"] for row in ledger] == [80, 150]
    assert [row["completion_tokens"] for row in ledger] == [20, 50]
    assert [row["cache_write_tokens"] for row in ledger] == [30, 20]
    assert [row["retried"] for row in ledger] == [False, False]
    assert {row["run_id"] for row in ledger} == {"execution-test"}
    assert {row["agent"] for row in ledger} == {"GameProjectAuthor"}
    assert {row["workflow_name"] for row in ledger} == {"stream-test"}
    assert all(row["latency_ms"] >= 0 for row in ledger)


def test_streamed_usage_survives_max_turns_and_completed_event_replay(monkeypatch):
    from agents.exceptions import MaxTurnsExceeded

    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 0)
    usage = SimpleNamespace(
        input_tokens=120,
        output_tokens=30,
        total_tokens=150,
        input_tokens_details=SimpleNamespace(
            cached_tokens=60,
            cache_write_tokens=40,
        ),
    )
    completed = _raw("response.completed", response_id="resp-replayed", usage=usage)
    runner = _Runner(
        [
            _Result(
                [
                    _raw("response.created", response_id="resp-replayed"),
                    completed,
                    completed,
                ],
                error=MaxTurnsExceeded("max turns exceeded"),
            )
        ]
    )
    session = _Session()
    activity = author_runner._StreamActivity()
    ledger = []
    monkeypatch.setattr(
        author_runner.llm,
        "record_response_usage",
        lambda **kwargs: ledger.append(kwargs),
    )

    with pytest.raises(MaxTurnsExceeded, match="max turns"):
        asyncio.run(
            author_runner._run_agent_streamed(
                runner,
                object(),
                "original-input",
                run_kwargs={"max_turns": 5},
                session=session,
                agent_name="GameProjectAuthor",
                activity=activity,
                execution_run_id="execution-test",
                workflow_name="stream-test",
                model_name="gpt-fallback",
            )
        )

    state = activity.snapshot()
    assert state["response_count"] == 1
    assert state["input_tokens"] == 120
    assert state["output_tokens"] == 30
    assert state["total_tokens"] == 150
    assert state["cached_tokens"] == 60
    assert state["cache_write_tokens"] == 40
    assert len(ledger) == 1
    assert ledger[0]["provider_response_id"] == "resp-replayed"
    assert ledger[0]["request_index"] == 1
    assert ledger[0]["cache_write_tokens"] == 40
    progress = [
        item
        for item in session.logs
        if item[1].get("event", {}).get("type") == "usage_progress"
    ]
    assert len(progress) == 1
    assert progress[0][1]["event"]["cache_write_tokens"] == 40


def test_fallback_response_ledger_forwards_cache_write_tokens(monkeypatch):
    usage = SimpleNamespace(
        requests=1,
        input_tokens=90,
        output_tokens=10,
        total_tokens=100,
        input_tokens_details=SimpleNamespace(
            cached_tokens=20,
            cache_write_tokens=50,
        ),
    )
    result = SimpleNamespace(
        context_wrapper=SimpleNamespace(usage=usage),
        last_response_id="resp-fallback",
    )
    ledger = []
    monkeypatch.setattr(
        author_runner.llm,
        "record_response_usage",
        lambda **kwargs: ledger.append(kwargs),
    )

    total = author_runner._record_fallback_response(
        result,
        model_name="gpt-fallback",
        latency_ms=25,
        execution_run_id="execution-test",
        agent_name="GameProjectAuthor",
        workflow_name="stream-test",
        step_id="step-test",
        retried=True,
    )

    assert total == 100
    assert len(ledger) == 1
    assert ledger[0]["cache_write_tokens"] == 50
    assert ledger[0]["retried"] is True


def test_streamed_run_stops_at_deadline_before_start(monkeypatch):
    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 0)
    runner = _Runner([_Result([])])

    with pytest.raises(author_runner._AgentDeadlineExceeded, match="deadline"):
        asyncio.run(
            author_runner._run_agent_streamed(
                runner,
                object(),
                "original-input",
                run_kwargs={"max_turns": 5},
                session=_Session(),
                agent_name="GameProjectAuthor",
                activity=author_runner._StreamActivity(),
                deadline_at=0,
            )
        )

    assert runner.inputs == []


def test_streamed_run_stops_at_deadline_while_waiting_for_event(monkeypatch):
    class _SlowResult(_Result):
        async def stream_events(self):
            await asyncio.sleep(0.05)
            yield _raw("response.completed")

    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 0)
    monkeypatch.setattr(author_runner.settings, "CODE_AGENT_STREAM_IDLE_TIMEOUT", 60)
    runner = _Runner([_SlowResult([])])

    with pytest.raises(author_runner._AgentDeadlineExceeded, match="deadline"):
        asyncio.run(
            author_runner._run_agent_streamed(
                runner,
                object(),
                "original-input",
                run_kwargs={"max_turns": 5},
                session=_Session(),
                agent_name="GameProjectAuthor",
                activity=author_runner._StreamActivity(),
                deadline_at=time.monotonic() + 0.05,
            )
        )

    assert runner.inputs == ["original-input"]


def test_streamed_run_stops_promptly_when_task_is_cancelled(monkeypatch):
    class _SlowResult(_Result):
        async def stream_events(self):
            await asyncio.sleep(10)
            yield _raw("response.completed")

    monkeypatch.setattr(author_runner.settings, "OPENAI_MAX_RETRIES", 0)
    monkeypatch.setattr(author_runner, "_TASK_CANCEL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(author_runner.tracing, "current_task_id", lambda: "task-cancel")
    cancellation_checks = iter([False, True])
    monkeypatch.setattr(
        author_runner.tracing,
        "task_is_cancelled",
        lambda task_id=None: next(cancellation_checks, True),
    )
    runner = _Runner([_SlowResult([])])

    with pytest.raises(author_runner.tracing.TaskCancelledError):
        asyncio.run(
            author_runner._run_agent_streamed(
                runner,
                object(),
                "original-input",
                run_kwargs={"max_turns": 5},
                session=_Session(),
                agent_name="GameProjectAuthor",
                activity=author_runner._StreamActivity(),
            )
        )

    assert runner.inputs == ["original-input"]


def test_terminal_completion_not_ready_continues_until_change_and_checks_pass():
    from agents.tool_context import ToolContext

    session = author_runner.RepairSession.from_files(
        [{"path": "game.js", "content": "const ready = false;"}]
    )
    tool, behavior = author_runner._terminal_completion_components(
        session,
        require_checks=True,
    )
    context = ToolContext(
        None,
        tool_name=tool.name,
        tool_call_id="call-1",
        tool_arguments="{}",
    )

    async def invoke():
        return await tool.on_invoke_tool(
            context,
            json.dumps({"summary": "DONE: implemented gameplay"}),
        )

    unchanged = asyncio.run(invoke())
    unchanged_result = behavior(
        None,
        [SimpleNamespace(tool=tool, output=unchanged)],
    )
    assert unchanged.startswith("NOT_READY:")
    assert unchanged_result.is_final_output is False

    session.changed.add("game.js")
    unchecked = asyncio.run(invoke())
    unchecked_result = behavior(
        None,
        [SimpleNamespace(tool=tool, output=unchecked)],
    )
    assert unchecked == "NOT_READY: run_checks must pass before completion"
    assert unchecked_result.is_final_output is False

    session.checks_ok = True
    ready = asyncio.run(invoke())
    ready_result = behavior(None, [SimpleNamespace(tool=tool, output=ready)])
    assert ready_result.is_final_output is True
    assert ready_result.final_output == "DONE: implemented gameplay"
