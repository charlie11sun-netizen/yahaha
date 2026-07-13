import asyncio
from types import SimpleNamespace

import pytest

from app.agents import author_runner


class _Session:
    def __init__(self):
        self.turns = []
        self.logs = []

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


def _raw(event_type, *, sequence=0, response_id="resp-1", error_code=None, delta=None):
    error = (
        SimpleNamespace(code=error_code, message="failed") if error_code else None
    )
    response = SimpleNamespace(id=response_id, error=error, incomplete_details=None)
    data = SimpleNamespace(
        type=event_type,
        response=response,
        sequence_number=sequence,
    )
    if delta is not None:
        data.delta = delta
    return SimpleNamespace(type="raw_response_event", data=data)


def _run(runner, session):
    return asyncio.run(
        author_runner._run_agent_streamed(
            runner,
            object(),
            "original-input",
            run_kwargs={"max_turns": 5},
            session=session,
            agent_name="GameProjectAuthor",
            activity=author_runner._StreamActivity(),
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

    result = _run(runner, session)

    assert result.final_output == "DONE after retry"
    assert runner.inputs == ["original-input", "resume-state"]
    assert session.turns[0][0] == "retrying"
    assert session.turns[0][2]["event_type"] == "response.failed"
    assert session.turns[0][2]["error_code"] == "server_error"


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
