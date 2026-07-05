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


def test_begin_step_aborts_when_token_budget_exceeded(client, db_session_factory, monkeypatch):
    from app.agents import tracing
    from app.core.config import settings
    from app.models import AgentStep, GenerationTask

    headers = _auth(client)
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


# ---- 断点续跑：节点快照 → 入口直跳失败节点，成本跨次累计 ----

def _snapshot_json(node="gameplay_qa", **state_overrides):
    import json

    state = {
        "task_kind": "generation",
        "prompt": "a neon breakout game",
        "dimension": "2d",
        "game_spec": {"title": "Snap"},
        "generated_files": [{"path": "game.js", "content": "var x=1;"}],
        "repair_attempts": 1,
        "replan_attempts": 1,
        "gameplay_repair_attempts": 2,
        "last_error": "gameplay QA failed",
    }
    state.update(state_overrides)
    return json.dumps({"node": node, "state": state}, ensure_ascii=False)


def test_begin_step_persists_resume_snapshot(client, db_session_factory, monkeypatch):
    import json

    from app.agents import tracing
    from app.models import GenerationTask

    headers = _auth(client)
    task_id = _make_task(client, headers)
    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    state = {"task_id": task_id, "game_spec": {"title": "S"}, "_logs": ["private"], "_resume_node": "x"}
    tracing.begin_step(task_id, "GameplayQAAgent", "Gameplay QA", node_name="gameplay_qa", state=state)

    db = db_session_factory()
    payload = json.loads(db.get(GenerationTask, task_id).state_json)
    db.close()
    assert payload["node"] == "gameplay_qa"
    assert payload["state"]["game_spec"] == {"title": "S"}
    # 下划线键不入快照，避免续跑套娃
    assert "_logs" not in payload["state"] and "_resume_node" not in payload["state"]


def test_entry_node_router_resume_and_default():
    from app.agents import nodes

    assert nodes.entry_node_router({}) == "safety_intake"
    assert nodes.entry_node_router({"_resume_node": "gameplay_qa"}) == "gameplay_qa"
    # 未知节点名回落全新跑
    assert nodes.entry_node_router({"_resume_node": "nope"}) == "safety_intake"


def test_run_generation_resumes_from_snapshot(client, db_session_factory, monkeypatch):
    """RUNNING 重投递 + 有快照：保留步骤、悬挂步骤翻 failed、tokens 不清零、
    initial 从快照重建并带 _resume_node。"""
    from app.agents.pipeline import run_generation
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.RUNNING
    task.tokens_used = 4321
    task.state_json = _snapshot_json()
    db.add(AgentStep(task_id=task_id, seq=1, agent="A", name="done-1", status=StepStatus.DONE, tokens=0))
    db.add(AgentStep(task_id=task_id, seq=2, agent="B", name="crashed-2", status=StepStatus.RUNNING, tokens=0))
    db.commit()
    db.close()

    seen = {}

    def _capture(initial):
        seen.update(initial)
        return {"status": "failed", "error_message": "still boom"}

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.graph.build_graph", lambda: _StubGraph(_capture))
    run_generation(task_id)

    assert seen["_resume_node"] == "gameplay_qa"
    assert seen["generated_files"] == [{"path": "game.js", "content": "var x=1;"}]
    assert seen["task_id"] == task_id and seen["status"] == "running"

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    steps = {s.name: s.status for s in db.query(AgentStep).filter_by(task_id=task_id)}
    assert steps == {"done-1": StepStatus.DONE, "crashed-2": StepStatus.FAILED}
    assert task.tokens_used == 4321  # 成本跨次累计，不清零
    assert task.status == TaskStatus.FAILED
    assert task.state_json is not None  # 失败保留快照，供下一次 retry 续跑
    db.close()


def test_run_generation_clears_snapshot_on_success(client, db_session_factory, monkeypatch):
    from app.agents.pipeline import run_generation
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.RUNNING
    task.state_json = _snapshot_json(node="publish_artifact")
    db.commit()
    db.close()

    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr(
        "app.agents.graph.build_graph",
        lambda: _StubGraph(lambda initial: {"status": "succeeded", "game_id": "g-1", "version_id": "v-1"}),
    )
    run_generation(task_id)

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.status == TaskStatus.SUCCEEDED
    assert task.state_json is None  # 成功后快照立即释放
    db.close()


def test_retry_endpoint_resumes_and_resets_budgets(client, db_session_factory):
    import json

    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.FAILED
    task.error = "gameplay QA failed"
    task.tokens_used = 999
    task.state_json = _snapshot_json()
    db.add(AgentStep(task_id=task_id, seq=1, agent="A", name="kept", status=StepStatus.DONE, tokens=0))
    db.commit()
    db.close()

    resp = client.post(f"/tasks/{task_id}/retry", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "resume"

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    payload = json.loads(task.state_json)
    assert task.status == TaskStatus.PENDING and task.error is None
    assert task.tokens_used == 999  # 续跑不清 tokens
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 1  # 步骤保留
    # 修复预算重置，否则会在耗尽处立刻再失败；失败痕迹清除
    assert payload["state"]["repair_attempts"] == 0
    assert payload["state"]["gameplay_repair_attempts"] == 0
    assert payload["state"]["replan_attempts"] == 0
    assert "last_error" not in payload["state"]
    db.close()


def test_retry_endpoint_from_scratch_keeps_old_semantics(client, db_session_factory):
    from app.models import AgentStep, GenerationTask
    from app.models.common import StepStatus, TaskStatus

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    task.status = TaskStatus.FAILED
    task.tokens_used = 999
    task.state_json = _snapshot_json()
    db.add(AgentStep(task_id=task_id, seq=1, agent="A", name="stale", status=StepStatus.DONE, tokens=0))
    db.commit()
    db.close()

    resp = client.post(f"/tasks/{task_id}/retry?from_scratch=true", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "restart"

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.tokens_used == 0
    assert task.state_json is None
    assert db.query(AgentStep).filter_by(task_id=task_id).count() == 0
    db.close()


def test_graph_resume_entry_jumps_to_failed_node(client, db_session_factory, monkeypatch):
    """真图冒烟：mock 流水线从 gameplay_qa 断点进入，不重跑前面的节点，
    且能一路走到发布成功。"""
    from app.agents.graph import build_graph
    from app.models import AgentStep, User

    headers = _auth(client)
    task_id = _make_task(client, headers)
    db = db_session_factory()
    user_id = db.query(User).first().id
    db.close()
    monkeypatch.setattr("app.agents.tracing.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.db.session.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.tracing.time.sleep", lambda s: None)

    game_js = (
        "var score=0;var onkeydown=function(){};function restart(){score=0;}\n"
        "setInterval(function(){score+=1;},100);\n"
        + "// gameplay filler so the bundle clears the minimum runnable-size heuristic\n" * 8
    )
    files = [
        {"path": "index.html", "content": "<html><canvas></canvas><script src=\"game.js\"></script></html>"},
        {"path": "style.css", "content": "canvas{display:block}"},
        {"path": "game.js", "content": game_js},
    ]
    final = build_graph().invoke({
        "task_id": task_id,
        "user_id": user_id,
        "use_real": False,
        "status": "running",
        "task_kind": "generation",
        "dimension": "2d",
        "_resume_node": "gameplay_qa",
        "game_spec": {"title": "Resume Smoke", "genre": "arcade", "summary": "s", "tags": []},
        "game_design": {"archetype": "topdown_collect"},
        "generated_files": files,
        "validation_result": {"valid": True, "errors": []},
        "repair_attempts": 0,
        "replan_attempts": 0,
        "gameplay_repair_attempts": 0,
    })

    assert final.get("status") == "succeeded"
    db = db_session_factory()
    ran = [s.name for s in db.query(AgentStep).filter_by(task_id=task_id).order_by(AgentStep.seq)]
    db.close()
    # 断点之前的节点（Safety Intake / Code Generation 等）一个都不该重跑
    assert "Safety Intake" not in ran and "Code Generation" not in ran
    assert ran[0] == "Gameplay QA"


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
