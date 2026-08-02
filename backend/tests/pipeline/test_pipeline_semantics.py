"""P0 语义回归：真取消、重投递幂等、publish 幂等、记忆捕获幂等。

这些行为共同保证：取消不再烧 LLM / 不留孤儿游戏；acks_late 重投递不会
双跑同一任务（重复 Game、重复 bundle、memory 证据重复计数）。
"""
from conftest import auth_headers

import pytest


def test_contract_gate_failure_resumes_the_contract_compiler():
    from types import SimpleNamespace

    from app.agents.pipeline import _failed_resume_node
    from app.models.common import StepStatus

    steps = [
        SimpleNamespace(
            agent="DesignContractCompilerAgent",
            name="Design Contract",
            status=StepStatus.FAILED,
        ),
        SimpleNamespace(
            agent="ContractGateAgent",
            name="Contract Gate",
            status=StepStatus.FAILED,
        ),
    ]

    assert _failed_resume_node(steps) == "design_contract"


def test_standalone_failure_still_resumes_its_own_node():
    from types import SimpleNamespace

    from app.agents.pipeline import _failed_resume_node
    from app.models.common import StepStatus

    steps = [
        SimpleNamespace(
            agent="GameplayQAAgent",
            name="Gameplay QA",
            status=StepStatus.FAILED,
        )
    ]

    assert _failed_resume_node(steps) == "gameplay_qa"


def _make_task(client, headers):
    return client.post("/tasks", json={"idea": "a neon breakout game"}, headers=headers).json()["task_id"]


class _StubGraph:
    def __init__(self, fn):
        self._fn = fn

    def invoke(self, initial, _config=None):
        return self._fn(initial)

    def get_state_history(self, _config):
        return iter(())

    def update_state(self, config, _values):
        return config


def test_begin_step_aborts_cancelled_task(client, db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.models import AgentStep, GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="p0@t.com", display_name="P0")
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


def test_begin_step_aborts_when_token_budget_exceeded(client, db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.core.config import settings
    from app.models import AgentStep, GenerationTask

    headers = auth_headers(client, email="p0@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.tokens_used = 10
    db.commit()
    db.close()

    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    monkeypatch.setattr(settings, "TASK_TOKEN_BUDGET", 10)
    with pytest.raises(tracing.TaskBudgetExceededError):
        tracing.begin_step(task_id, "PlannerAgent", "Intent Spec")

    db = db_session_factory()
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 0
    db.close()


def test_run_generation_skips_terminal_task(client, db_session_factory, monkeypatch):
    from app.agents.pipeline import run_generation
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="p0@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    db = db_session_factory()
    db.get(GenerationTask, task_id).status = TaskStatus.SUCCEEDED
    db.commit()
    db.close()

    def _explode(**_kwargs):
        raise AssertionError("graph must not run for a terminal task")

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.graph.build_graph", _explode)
    run_generation(task_id)

    db = db_session_factory()
    assert db.get(GenerationTask, task_id).status == TaskStatus.SUCCEEDED
    db.close()


def test_run_generation_skips_stale_dispatch_generation(client, db_session_factory, monkeypatch):
    from app.agents.pipeline import run_generation
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="stale-generation@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    db = db_session_factory()
    current_generation = db.get(GenerationTask, task_id).dispatch_generation
    db.close()

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("stale delivery must not run")),
    )
    run_generation(task_id, expected_dispatch_generation=current_generation - 1)

    db = db_session_factory()
    assert db.get(GenerationTask, task_id).status == TaskStatus.PENDING
    db.close()


def test_run_generation_rerun_clears_stale_steps(client, db_session_factory, monkeypatch):
    """worker 崩溃后的重投递：RUNNING 任务重跑前应清空上一轮的步骤流。"""
    from app.agents.pipeline import run_generation
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = auth_headers(client, email="p0@t.com", display_name="P0")
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
        lambda **_kwargs: _StubGraph(lambda initial: {"status": "failed", "error_message": "boom"}),
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

    headers = auth_headers(client, email="p0@t.com", display_name="P0")
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
    monkeypatch.setattr("app.agents.graph.build_graph", lambda **_kwargs: _StubGraph(_publish_then_cancelled))
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

    auth_headers(client, email="p0@t.com", display_name="P0")
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


# ---- LangGraph 原生检查点：崩溃恢复、失败 replay、从头重跑 ----

def _native_retry_graph(checkpointer, calls):
    """A tiny durable graph with the same failed-node name as production."""
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class RetryState(TypedDict, total=False):
        task_id: str
        status: str
        repair_attempts: int
        replan_attempts: int
        gameplay_repair_attempts: int
        last_error: str | None
        error_code: str | None
        error_message: str | None
        game_id: str
        version_id: str

    def gameplay_qa(state):
        calls.append(dict(state))
        if len(calls) == 1:
            return {
                "status": "failed",
                "repair_attempts": 2,
                "replan_attempts": 1,
                "gameplay_repair_attempts": 2,
                "last_error": "gameplay QA failed",
                "error_message": "gameplay QA failed",
            }
        return {"status": "succeeded", "game_id": "g-native", "version_id": "v-native"}

    builder = StateGraph(RetryState)
    builder.add_node("gameplay_qa", gameplay_qa)
    builder.add_node("failed", lambda _state: {})
    builder.add_edge(START, "gameplay_qa")
    builder.add_conditional_edges(
        "gameplay_qa",
        lambda state: "failed" if state.get("status") == "failed" else "done",
        {"failed": "failed", "done": END},
    )
    builder.add_edge("failed", END)
    return builder.compile(checkpointer=checkpointer)


def _seed_native_failure(task_id, calls):
    from app.core.checkpointing import checkpoint_config, open_checkpointer

    with open_checkpointer() as saver:
        graph = _native_retry_graph(saver, calls)
        final = graph.invoke(
            {
                "task_id": task_id,
                "status": "running",
                "repair_attempts": 0,
                "replan_attempts": 0,
                "gameplay_repair_attempts": 0,
            },
            checkpoint_config(task_id),
        )
    assert final["status"] == "failed"


def test_worker_redelivery_resumes_native_checkpoint(client, db_session_factory, monkeypatch):
    """A worker crash replays the interrupted node and keeps prior cost/steps."""
    from app.agents.pipeline import run_generation
    from app.core.checkpointing import checkpoint_config, checkpoint_exists, open_checkpointer
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = auth_headers(client, email="checkpoint-crash@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    calls = []
    should_crash = {"value": True}

    def build_crashing_graph(checkpointer):
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph

        class CrashState(TypedDict, total=False):
            task_id: str
            status: str
            repair_attempts: int
            replan_attempts: int
            gameplay_repair_attempts: int
            game_id: str
            version_id: str

        def gameplay_qa(state):
            calls.append(dict(state))
            if should_crash["value"]:
                should_crash["value"] = False
                raise RuntimeError("worker crashed")
            return {"status": "succeeded", "game_id": "g-crash", "version_id": "v-crash"}

        builder = StateGraph(CrashState)
        builder.add_node("gameplay_qa", gameplay_qa)
        builder.add_edge(START, "gameplay_qa")
        builder.add_edge("gameplay_qa", END)
        return builder.compile(checkpointer=checkpointer)

    with open_checkpointer() as saver:
        graph = build_crashing_graph(saver)
        with pytest.raises(RuntimeError, match="worker crashed"):
            graph.invoke(
                {
                    "task_id": task_id,
                    "status": "running",
                    "repair_attempts": 1,
                    "replan_attempts": 1,
                    "gameplay_repair_attempts": 1,
                },
                checkpoint_config(task_id),
            )

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.RUNNING
    task.tokens_used = 4321
    db.add(
        AgentStep(
            task_id=task_id,
            seq=1,
            agent="GameplayQAAgent",
            name="Gameplay QA",
            status=StepStatus.RUNNING,
            tokens=0,
        )
    )
    db.commit()
    db.close()

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda *, checkpointer=None: build_crashing_graph(checkpointer),
    )
    run_generation(task_id)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    steps = db.query(AgentStep).filter_by(task_id=task_id).all()
    assert task.status == TaskStatus.SUCCEEDED
    assert task.tokens_used == 4321
    assert len(steps) == 1 and steps[0].status == StepStatus.FAILED
    assert calls[-1]["gameplay_repair_attempts"] == 1
    assert checkpoint_exists(task_id) is False
    db.close()


def test_worker_redelivery_finalizes_completed_checkpoint_without_rerun(
    client, db_session_factory, monkeypatch
):
    from app.agents.pipeline import run_generation
    from app.core.checkpointing import checkpoint_config, checkpoint_exists, open_checkpointer
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="checkpoint-complete@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    calls = [{"preseed": True}]
    with open_checkpointer() as saver:
        final = _native_retry_graph(saver, calls).invoke(
            {
                "task_id": task_id,
                "status": "running",
                "repair_attempts": 0,
                "replan_attempts": 0,
                "gameplay_repair_attempts": 0,
            },
            checkpoint_config(task_id),
        )
    assert final["status"] == "succeeded"
    call_count = len(calls)

    db = db_session_factory()
    db.get(GenerationTask, task_id).status = TaskStatus.RUNNING
    db.commit()
    db.close()

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda *, checkpointer=None: _native_retry_graph(checkpointer, calls),
    )
    run_generation(task_id)

    db = db_session_factory()
    assert db.get(GenerationTask, task_id).status == TaskStatus.SUCCEEDED
    assert len(calls) == call_count
    assert checkpoint_exists(task_id) is False
    db.close()


def test_retry_endpoint_replays_failed_node_and_resets_budgets(
    client, db_session_factory, monkeypatch
):
    from app.agents.pipeline import run_generation
    from app.core.checkpointing import checkpoint_exists
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = auth_headers(client, email="checkpoint-retry@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    calls = []
    _seed_native_failure(task_id, calls)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.FAILED
    task.error = "gameplay QA failed"
    task.tokens_used = 999
    db.add(
        AgentStep(
            task_id=task_id,
            seq=1,
            agent="GameplayQAAgent",
            name="Gameplay QA",
            status=StepStatus.FAILED,
            tokens=0,
        )
    )
    db.commit()
    db.close()

    response = client.post(f"/tasks/{task_id}/retry", headers=headers)
    assert response.status_code == 200
    assert response.json()["mode"] == "resume"

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda *, checkpointer=None: _native_retry_graph(checkpointer, calls),
    )
    run_generation(task_id)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.status == TaskStatus.SUCCEEDED
    assert task.tokens_used == 999
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 1
    assert calls[-1]["repair_attempts"] == 0
    assert calls[-1]["replan_attempts"] == 0
    assert calls[-1]["gameplay_repair_attempts"] == 0
    assert calls[-1]["last_error"] is None
    assert checkpoint_exists(task_id) is False
    db.close()


def test_image_failure_waits_for_manual_retry_and_resumes_asset_node(
    client, db_session_factory, monkeypatch
):
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    from app.agents.pipeline import run_generation
    from app.agents.tracing import logged
    from app.core.checkpointing import checkpoint_exists
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus
    from app.services.game_assets import AssetGenerationRetryRequired

    headers = auth_headers(client, email="asset-manual-retry@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    calls = []

    class AssetState(TypedDict, total=False):
        task_id: str
        use_real: bool
        status: str
        game_id: str
        version_id: str

    def build_asset_graph(checkpointer):
        def asset_generation(state):
            calls.append(dict(state))
            if len(calls) == 1:
                raise AssetGenerationRetryRequired(
                    "Image asset 'sheet' failed after the automatic retry. "
                    "Generation is paused; retry the failed step manually."
                )
            return {"status": "succeeded", "game_id": "g-asset", "version_id": "v-asset"}

        builder = StateGraph(AssetState)
        builder.add_node("asset_generation", logged("asset_generation")(asset_generation))
        builder.add_edge(START, "asset_generation")
        builder.add_edge("asset_generation", END)
        return builder.compile(checkpointer=checkpointer)

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda *, checkpointer=None: build_asset_graph(checkpointer),
    )

    run_generation(task_id)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.error_code == "ASSET_GENERATION_FAILED"
    assert "retry the failed step manually" in task.error
    steps = db.query(AgentStep).filter_by(task_id=task_id).all()
    assert len(steps) == 1 and steps[0].status == StepStatus.FAILED
    assert checkpoint_exists(task_id) is True
    db.close()

    response = client.post(f"/tasks/{task_id}/retry", headers=headers)
    assert response.status_code == 200
    assert response.json()["mode"] == "resume"

    run_generation(task_id)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.status == TaskStatus.SUCCEEDED
    assert len(calls) == 2
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 2
    assert checkpoint_exists(task_id) is False
    db.close()


def test_author_team_failure_stops_before_integration_and_keeps_checkpoint(
    client, db_session_factory, monkeypatch
):
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    from app.agents.pipeline import run_generation
    from app.agents.tracing import logged
    from app.core.checkpointing import checkpoint_exists
    from app.core.errors import AuthorTeamRetryRequired
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = auth_headers(
        client,
        email="author-team-manual-retry@t.com",
        display_name="P0",
    )
    task_id = _make_task(client, headers)

    class AuthorState(TypedDict, total=False):
        task_id: str
        use_real: bool
        status: str

    def build_author_graph(checkpointer):
        def code_generation(_state):
            raise AuthorTeamRetryRequired(
                "Author team implementation incomplete; integration was not started. "
                "Generation is paused; retry the failed step manually."
            )

        builder = StateGraph(AuthorState)
        builder.add_node("code_generation", logged("code_generation")(code_generation))
        builder.add_edge(START, "code_generation")
        builder.add_edge("code_generation", END)
        return builder.compile(checkpointer=checkpointer)

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.opik_integration.settings.OPIK_ENABLED",
        False,
    )
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda *, checkpointer=None: build_author_graph(checkpointer),
    )

    run_generation(task_id)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.error_code == "MODEL_INVALID_OUTPUT"
    assert "integration was not started" in task.error
    steps = db.query(AgentStep).filter_by(task_id=task_id).all()
    assert len(steps) == 1 and steps[0].status == StepStatus.FAILED
    assert checkpoint_exists(task_id) is True
    db.close()


def test_retry_endpoint_from_scratch_deletes_native_thread(client, db_session_factory):
    from app.core.checkpointing import checkpoint_exists
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = auth_headers(client, email="checkpoint-restart@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    _seed_native_failure(task_id, [])

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.FAILED
    task.tokens_used = 999
    db.add(AgentStep(task_id=task_id, seq=1, agent="A", name="stale", status=StepStatus.DONE, tokens=0))
    db.commit()
    db.close()

    response = client.post(f"/tasks/{task_id}/retry?from_scratch=true", headers=headers)
    assert response.status_code == 200
    assert response.json()["mode"] == "restart"

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.tokens_used == 0
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 0
    assert checkpoint_exists(task_id) is False
    db.close()


def test_cancel_deletes_native_checkpoint_thread(client):
    from app.core.checkpointing import checkpoint_exists

    headers = auth_headers(client, email="checkpoint-cancel@t.com", display_name="P0")
    task_id = _make_task(client, headers)
    _seed_native_failure(task_id, [])

    response = client.post(f"/tasks/{task_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert checkpoint_exists(task_id) is False


def test_capture_success_memories_idempotent(client, db_session_factory):
    from app.models import Game, GenerationTask, MemoryItem
    from app.models.common import GameSource, GameStatus, TaskStatus
    from app.services.memory import capture_success_memories

    headers = auth_headers(client, email="p0@t.com", display_name="P0")
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
