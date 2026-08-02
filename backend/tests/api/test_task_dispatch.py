from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import auth_headers

from app.models import GenerationDispatchOutbox, GenerationTask
from app.models.common import TaskStatus, now_utc
from app.services.task_dispatch import (
    dispatch_generation_event,
    dispatch_pending_generation_events,
    stage_generation_dispatch,
)


class _RecordingQueue:
    def __init__(self):
        self.calls = []

    def apply_async(self, **kwargs):
        self.calls.append(kwargs)


class _FailingQueue:
    def delay(self, *_args, **_kwargs):
        raise ConnectionError("broker unavailable")


class _RecordingDispatcher:
    def __init__(self, *, fail: bool = False):
        self.messages = []
        self.fail = fail

    def dispatch(self, message):
        self.messages.append(message)
        if self.fail:
            raise ConnectionError("broker unavailable")


def test_create_commits_outbox_and_publishes_generation(
    client, db_session_factory, monkeypatch
):
    from app.api.routers import tasks as tasks_router

    queue = _RecordingQueue()
    monkeypatch.setattr(tasks_router, "generate_game", queue)
    headers = auth_headers(
        client, email="dispatch-create@example.com", display_name="Dispatch"
    )

    response = client.post(
        "/tasks", json={"idea": "reliable dispatch"}, headers=headers
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    event = db.query(GenerationDispatchOutbox).filter_by(task_id=task_id).one()
    assert task.status == TaskStatus.PENDING
    assert task.dispatch_generation == 1
    assert event.dispatch_generation == 1
    assert event.attempts == 1 and event.published_at is not None
    assert queue.calls == [
        {
            "args": [task_id],
            "task_id": event.id,
            "headers": {"request_id": event.request_id, "dispatch_generation": 1},
        }
    ]
    db.close()


def test_broker_failure_keeps_pending_task_and_retryable_event(
    client, db_session_factory, monkeypatch
):
    from app.api.routers import tasks as tasks_router

    monkeypatch.setattr(tasks_router, "generate_game", _FailingQueue())
    headers = auth_headers(
        client, email="dispatch-fail@example.com", display_name="Dispatch"
    )

    response = client.post(
        "/tasks", json={"idea": "survive broker failure"}, headers=headers
    )

    assert response.status_code == 200
    db = db_session_factory()
    task = db.get(GenerationTask, response.json()["task_id"])
    event = db.query(GenerationDispatchOutbox).filter_by(task_id=task.id).one()
    assert task.status == TaskStatus.PENDING and task.dispatch_generation == 1
    assert event.published_at is None and event.attempts == 1
    assert "broker unavailable" in event.last_error
    assert event.available_at > event.last_attempt_at
    db.close()


def test_task_and_outbox_roll_back_together_before_publish(
    client,
    db_session_factory,
    monkeypatch,
):
    from app.models import User
    from app.schemas import TaskCreateIn
    from app.services import task_actions

    auth_headers(client, email="dispatch-rollback@example.com", display_name="Dispatch")
    db = db_session_factory()
    user = db.query(User).filter_by(email="dispatch-rollback@example.com").one()
    queue = _RecordingQueue()
    monkeypatch.setattr(
        db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed"))
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        task_actions.create_task(
            db, TaskCreateIn(idea="atomic write"), user, queue=queue
        )
    db.rollback()
    db.close()

    check = db_session_factory()
    assert check.query(GenerationTask).filter_by(idea="atomic write").count() == 0
    assert check.query(GenerationDispatchOutbox).count() == 0
    assert queue.calls == []
    check.close()


def test_retry_advances_generation_and_keeps_each_dispatch(client, db_session_factory):
    headers = auth_headers(
        client, email="dispatch-retry@example.com", display_name="Dispatch"
    )
    task_id = client.post("/tasks", json={"idea": "retry me"}, headers=headers).json()[
        "task_id"
    ]
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.FAILED
    db.commit()
    db.close()

    response = client.post(f"/tasks/{task_id}/retry", headers=headers)

    assert response.status_code == 200
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    generations = [
        event.dispatch_generation
        for event in db.query(GenerationDispatchOutbox)
        .filter_by(task_id=task_id)
        .order_by(GenerationDispatchOutbox.dispatch_generation)
    ]
    assert task.dispatch_generation == 2
    assert generations == [1, 2]
    db.close()


def test_stale_concurrent_retry_is_revalidated_instead_of_hitting_unique_constraint(
    client,
    db_session_factory,
):
    from app.models import User
    from app.services import task_actions
    from app.services.errors import ServiceError

    headers = auth_headers(
        client, email="dispatch-race@example.com", display_name="Dispatch"
    )
    task_id = client.post(
        "/tasks", json={"idea": "retry race"}, headers=headers
    ).json()["task_id"]
    setup = db_session_factory()
    setup.get(GenerationTask, task_id).status = TaskStatus.FAILED
    setup.commit()
    setup.close()

    first = db_session_factory()
    second = db_session_factory()
    user = first.query(User).filter_by(email="dispatch-race@example.com").one()
    first.get(GenerationTask, task_id)
    stale = second.get(GenerationTask, task_id)
    assert (
        stale.status == TaskStatus.FAILED
    )  # keep a strong reference to stale identity-map state
    queue = SimpleNamespace(delay=lambda *_args, **_kwargs: None)

    task_actions.retry_task(first, task_id, user, queue=queue)
    with pytest.raises(ServiceError, match="Only failed tasks can be retried"):
        task_actions.retry_task(second, task_id, user, queue=queue)

    second.rollback()
    first.close()
    second.close()

    check = db_session_factory()
    assert check.get(GenerationTask, task_id).dispatch_generation == 2
    assert check.query(GenerationDispatchOutbox).filter_by(task_id=task_id).count() == 2
    check.close()


def test_scanner_retries_due_event_and_does_not_republish(db_session_factory):
    from app.models import User

    db = db_session_factory()
    user = User(
        email="scanner@example.com",
        password_hash=None,
        display_name="Scanner",
        avatar_initial="S",
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="scan me", status=TaskStatus.PENDING)
    db.add(task)
    event = stage_generation_dispatch(db, task, request_id="request-1")
    db.commit()

    failing = _RecordingDispatcher(fail=True)
    assert dispatch_generation_event(db, event.id, failing) is False
    db.refresh(event)
    assert event.attempts == 1 and event.published_at is None

    event.available_at = now_utc() - timedelta(seconds=1)
    db.commit()
    succeeding = _RecordingDispatcher()
    assert dispatch_pending_generation_events(db, succeeding) == 1
    assert len(succeeding.messages) == 1
    db.refresh(event)
    assert event.attempts == 2 and event.published_at is not None

    assert dispatch_generation_event(db, event.id, succeeding) is False
    assert len(succeeding.messages) == 1

    # If Redis accepted but later lost the message, an active task is reopened
    # after the visibility/hard-timeout safety window.
    event.published_at = now_utc() - timedelta(seconds=120)
    event.available_at = now_utc() - timedelta(seconds=1)
    db.commit()
    event_id = event.id
    db.close()
    db = db_session_factory()
    event = db.get(GenerationDispatchOutbox, event_id)
    assert (
        dispatch_pending_generation_events(
            db,
            succeeding,
            republish_after_seconds=60,
        )
        == 1
    )
    assert len(succeeding.messages) == 2
    db.refresh(event)
    assert event.attempts == 3
    db.close()


def test_worker_retries_when_execution_lock_is_busy(monkeypatch):
    from app.tasks import generate as generate_module

    class LockBusy(Exception):
        pass

    @contextmanager
    def _busy_lock(_task_id):
        yield False

    monkeypatch.setattr(generate_module, "_dispatch_is_current", lambda *_args: True)
    monkeypatch.setattr(generate_module, "generation_execution_lock", _busy_lock)
    monkeypatch.setattr(
        generate_module.generate_game,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(LockBusy()),
    )
    monkeypatch.setattr(
        generate_module,
        "run_generation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    try:
        generate_module.generate_game.run("task-1", 1)
    except LockBusy:
        pass
    else:
        raise AssertionError("lock contention must request a Celery retry")


def test_worker_retries_when_checkpoint_storage_is_unavailable(monkeypatch):
    from app.core.checkpointing import CheckpointStorageError
    from app.tasks import generate as generate_module

    class RetryRequested(Exception):
        pass

    @contextmanager
    def _acquired_lock(_task_id):
        yield True

    monkeypatch.setattr(generate_module, "_dispatch_is_current", lambda *_args: True)
    monkeypatch.setattr(generate_module, "generation_execution_lock", _acquired_lock)
    monkeypatch.setattr(
        generate_module,
        "run_generation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CheckpointStorageError("checkpoint database unavailable")
        ),
    )
    monkeypatch.setattr(
        generate_module.generate_game,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(RetryRequested()),
    )

    with pytest.raises(RetryRequested):
        generate_module.generate_game.run("task-1", 1)


def test_worker_reads_generation_header_and_defaults_legacy_messages_to_zero():
    from app.tasks.generate import _message_dispatch_generation

    assert (
        _message_dispatch_generation(
            SimpleNamespace(
                request=SimpleNamespace(headers={"dispatch_generation": 3})
            ),
            None,
        )
        == 3
    )
    assert (
        _message_dispatch_generation(
            SimpleNamespace(request=SimpleNamespace(headers={})), None
        )
        == 0
    )
    assert (
        _message_dispatch_generation(
            SimpleNamespace(request=SimpleNamespace(headers={})), 4
        )
        == 4
    )


def test_outbox_scanner_uses_dedicated_celery_queue():
    from app.tasks.generate import generate_game, generate_game_legacy
    from app.tasks.celery_app import celery

    assert generate_game.name == "generate_game_v2"
    assert generate_game_legacy.name == "generate_game"
    assert celery.conf.task_routes["generate_game_v2"]["queue"] == "generation-v2"
    assert (
        celery.conf.task_routes["dispatch_generation_outbox"]["queue"]
        == "generation-outbox"
    )


def test_worker_rechecks_generation_after_lock(monkeypatch):
    from app.tasks import generate as generate_module

    checks = iter([True, False])
    calls = []

    @contextmanager
    def _acquired_lock(_task_id):
        yield True

    monkeypatch.setattr(
        generate_module, "_dispatch_is_current", lambda *_args: next(checks)
    )
    monkeypatch.setattr(generate_module, "generation_execution_lock", _acquired_lock)
    monkeypatch.setattr(
        generate_module,
        "run_generation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    generate_module.generate_game.run("task-1", 1)

    assert calls == []


def test_postgres_execution_lock_unlocks_after_body_error(monkeypatch):
    from app.tasks import generate as generate_module

    class _Result:
        def scalar_one(self):
            return True

    class _Connection:
        def __init__(self):
            self.calls = []
            self.invalidated = False
            self.closed = False
            self.commits = 0

        def execute(self, statement, params):
            self.calls.append((str(statement), params))
            return _Result()

        def invalidate(self):
            self.invalidated = True

        def commit(self):
            self.commits += 1

        def close(self):
            self.closed = True

    connection = _Connection()
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        connect=lambda: connection,
    )
    monkeypatch.setattr(generate_module, "engine", fake_engine)

    with pytest.raises(RuntimeError, match="body failed"):
        with generate_module.generation_execution_lock("task-1") as acquired:
            assert acquired is True
            raise RuntimeError("body failed")

    assert "pg_try_advisory_lock" in connection.calls[0][0]
    assert "pg_advisory_unlock" in connection.calls[1][0]
    assert connection.calls[0][1]["lock_key"] == connection.calls[1][1]["lock_key"]
    assert connection.commits == 2
    assert connection.invalidated is False
    assert connection.closed is True
