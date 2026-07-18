from __future__ import annotations

import opik
import pytest

from app.agents import opik_integration


class _FakeContext:
    def __init__(self, value=None):
        self.value = value
        self.exit_args = None

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        self.exit_args = args
        return False


def _enable(monkeypatch):
    monkeypatch.setattr(opik_integration.settings, "OPIK_ENABLED", True)
    monkeypatch.setattr(
        opik_integration.settings,
        "OPIK_URL_OVERRIDE",
        "http://localhost:15173/api",
    )
    monkeypatch.setattr(opik_integration.settings, "OPIK_PROJECT_NAME", "test-project")
    monkeypatch.setattr(opik_integration.settings, "OPIK_ENVIRONMENT", "test")


def test_generation_trace_has_searchable_task_identity(monkeypatch):
    _enable(monkeypatch)
    captured = {}
    context = _FakeContext(value={"trace": True})

    def start_trace(**kwargs):
        captured.update(kwargs)
        return context

    monkeypatch.setattr(opik, "start_as_current_trace", start_trace)

    with opik_integration.generation_trace(
        task_id="task-123", dispatch_generation=4
    ) as trace:
        assert trace == {"trace": True}

    assert captured["name"] == "game-generation"
    assert captured["thread_id"] == "task:task-123"
    assert captured["metadata"]["task_id"] == "task-123"
    assert captured["metadata"]["schema_version"] == "gameweave.opik.generation/1.0"
    assert context.exit_args == (None, None, None)


def test_generation_trace_preserves_generation_errors(monkeypatch):
    _enable(monkeypatch)
    context = _FakeContext()
    monkeypatch.setattr(opik, "start_as_current_trace", lambda **_: context)

    with pytest.raises(RuntimeError, match="generation failed"):
        with opik_integration.generation_trace(task_id="task-error"):
            raise RuntimeError("generation failed")

    assert context.exit_args[0] is RuntimeError
    assert str(context.exit_args[1]) == "generation failed"


def test_generation_span_retains_task_metadata(monkeypatch):
    _enable(monkeypatch)
    updates = []
    context = _FakeContext(value={"span": True})
    monkeypatch.setattr(opik, "start_as_current_span", lambda **_: context)
    monkeypatch.setattr(
        opik.opik_context,
        "update_current_span",
        lambda **kwargs: updates.append(kwargs),
    )

    with opik_integration.generation_span(
        node_name="intent_spec",
        task_id="task-456",
        step_id="step-1",
        agent="IntentSpecAgent",
        display_name="Intent Spec",
    ):
        opik_integration.update_generation_span(
            output={"status": "completed"},
            metadata={"failed": False},
            tags=["status:completed"],
        )

    assert updates[0]["metadata"]["task_id"] == "task-456"
    assert updates[0]["metadata"]["step_id"] == "step-1"
    assert updates[-1]["output"] == {"status": "completed"}
    assert updates[-1]["metadata"] == {"failed": False}


def test_generation_trace_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(opik_integration.settings, "OPIK_ENABLED", False)
    with opik_integration.generation_trace(task_id="task-disabled") as trace:
        assert trace is None
