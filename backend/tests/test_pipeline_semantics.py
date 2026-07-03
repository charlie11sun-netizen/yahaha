"""P0 语义回归：真取消、重投递幂等、publish 幂等、记忆捕获幂等。

这些行为共同保证：取消不再烧 LLM / 不留孤儿游戏；acks_late 重投递不会
双跑同一任务（重复 Game、重复 bundle、memory 证据重复计数）。
"""
import pytest


def _auth(client):
    token = client.post(
        "/auth/register",
        json={"email": "p0@t.com", "password": "secret1", "display_name": "P0"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _make_task(client, headers):
    return client.post("/tasks", json={"idea": "a neon breakout game"}, headers=headers).json()["task_id"]


class _StubGraph:
    def __init__(self, fn):
        self._fn = fn

    def invoke(self, initial):
        return self._fn(initial)


def test_begin_step_aborts_cancelled_task(client, db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.models import AgentStep, GenerationTask
    from app.models.common import TaskStatus

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    db.get(GenerationTask, task_id).status = TaskStatus.CANCELLED
    db.commit()
    db.close()

    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    with pytest.raises(tracing.TaskCancelledError):
        tracing.begin_step(task_id, "PlannerAgent", "Intent Spec")

    db = db_session_factory()
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 0
    db.close()


def test_run_generation_skips_terminal_task(client, db_session_factory, monkeypatch):
    from app.agents.pipeline import run_generation
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    db.get(GenerationTask, task_id).status = TaskStatus.SUCCEEDED
    db.commit()
    db.close()

    def _explode():
        raise AssertionError("graph must not run for a terminal task")

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.graph.build_graph", _explode)
    run_generation(task_id)

    db = db_session_factory()
    assert db.get(GenerationTask, task_id).status == TaskStatus.SUCCEEDED
    db.close()


def test_run_generation_rerun_clears_stale_steps(client, db_session_factory, monkeypatch):
    """worker 崩溃后的重投递：RUNNING 任务重跑前应清空上一轮的步骤流。"""
    from app.agents.pipeline import run_generation
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.RUNNING
    db.add(AgentStep(task_id=task_id, seq=1, agent="A", name="stale-1", status=StepStatus.RUNNING, tokens=0))
    db.add(AgentStep(task_id=task_id, seq=2, agent="B", name="stale-2", status=StepStatus.DONE, tokens=0))
    db.commit()
    db.close()

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda: _StubGraph(lambda initial: {"status": "failed", "error_message": "boom"}),
    )
    run_generation(task_id)

    db = db_session_factory()
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 0
    assert db.get(GenerationTask, task_id).status == TaskStatus.FAILED
    db.close()


def test_cancel_mid_publish_cleans_orphan_game(client, db_session_factory, monkeypatch):
    """取消恰好落在 publish 节点执行中：图已建出 Game，但收尾必须把孤儿清掉。"""
    from app.agents.pipeline import run_generation
    from app.models import Game, GenerationTask
    from app.models.common import GameSource, GameStatus, TaskStatus
    from app.storage import s3

    headers = _auth(client)
    task_id = _make_task(client, headers)
    created = {}

    def _publish_then_cancelled(initial):
        db = db_session_factory()
        task = db.get(GenerationTask, task_id)
        game = Game(
            author_id=task.user_id, title="Orphan", summary="", genre="ARCADE", cover="x",
            source=GameSource.CREATE, status=GameStatus.PREVIEW, current_version="v1",
            plays_count=0, likes_count=0,
        )
        db.add(game)
        db.flush()
        created["game_id"] = game.id
        task.status = TaskStatus.CANCELLED  # 用户在 publish 执行期间点了取消
        db.commit()
        db.close()
        return {"status": "succeeded", "game_id": created["game_id"], "version_id": "v-x"}

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.graph.build_graph", lambda: _StubGraph(_publish_then_cancelled))
    monkeypatch.setattr(s3, "delete_prefix", lambda prefix: None)
    run_generation(task_id)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.status == TaskStatus.CANCELLED
    assert task.result_game_id is None
    assert db.get(Game, created["game_id"]) is None
    db.close()


def test_publish_generated_idempotent_by_source_task(client, db_session_factory, monkeypatch):
    from app.models import Game, User
    from app.services import packaging

    _auth(client)
    db = db_session_factory()
    user_id = db.query(User).first().id
    db.close()

    monkeypatch.setattr("app.db.session.SessionLocal", db_session_factory)
    state = {
        "task_id": "task-dup",
        "user_id": user_id,
        "game_spec": {"title": "Dup Guard", "genre": "arcade", "summary": "s", "tags": []},
        "generated_files": [
            {"path": "index.html", "content": "<html></html>"},
            {"path": "style.css", "content": "body{}"},
            {"path": "game.js", "content": "var x=1;"},
        ],
        "dimension": "2d",
    }
    first = packaging.publish_generated(state)
    second = packaging.publish_generated(state)

    assert first == second
    db = db_session_factory()
    assert db.query(Game).filter_by(title="Dup Guard").count() == 1
    db.close()


def test_capture_success_memories_idempotent(client, db_session_factory):
    from app.models import Game, GenerationTask, MemoryItem
    from app.models.common import GameSource, GameStatus, TaskStatus
    from app.services.memory import capture_success_memories

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    game = Game(
        author_id=task.user_id, title="Mem Game", summary="", genre="ARCADE", cover="x",
        source=GameSource.CREATE, status=GameStatus.PREVIEW, current_version="v1",
        plays_count=0, likes_count=0,
    )
    db.add(game)
    db.flush()
    task.task_kind = "revision"
    task.base_game_id = game.id
    task.base_version = "v1"
    task.feedback_text = "子弹速度再快一点"
    task.status = TaskStatus.SUCCEEDED
    db.commit()

    first = capture_success_memories(db, task_id=task_id, state={"task_kind": "revision"})
    db.commit()
    second = capture_success_memories(db, task_id=task_id, state={"task_kind": "revision"})
    db.commit()

    assert len(first) == 1
    assert second == []
    assert db.query(MemoryItem).filter_by(source_task_id=task_id).count() == 1
    db.close()
