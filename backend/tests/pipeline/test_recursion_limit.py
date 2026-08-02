"""P0 回归:图步数上限必须随 run config 下发,触顶落 RECURSION_LIMIT 专属失因。

2026-07-26 架构评审①:幸福路径 ~19 superstep,修复/重规划预算满载理论 ~57,
langgraph 默认 25 会截断合法运行;触顶若走 UNKNOWN 则失因不可辨。
"""
from conftest import auth_headers

from langgraph.errors import GraphRecursionError


def _make_task(client, headers):
    return client.post("/tasks", json={"idea": "a neon breakout game"}, headers=headers).json()["task_id"]


class _RecordingGraph:
    """Stub graph that captures the run config, then raises like a runaway loop."""

    def __init__(self):
        self.configs = []

    def invoke(self, _initial, config=None):
        self.configs.append(config)
        raise GraphRecursionError("Recursion limit of 80 reached without hitting a stop condition")

    def get_state_history(self, _config):
        return iter(())

    def update_state(self, config, _values):
        return config


def test_recursion_limit_flows_into_config_and_maps_to_dedicated_error(
    client, db_session_factory, monkeypatch
):
    from app.agents.pipeline import run_generation
    from app.core.config import settings
    from app.core.errors import TaskErrorCode
    from app.models import GenerationTask
    from app.models.common import TaskStatus

    headers = auth_headers(client, email="rl@t.com", display_name="RL")
    task_id = _make_task(client, headers)

    graph = _RecordingGraph()
    monkeypatch.setattr("app.agents.pipeline.SessionLocal", db_session_factory)
    monkeypatch.setattr("app.agents.graph.build_graph", lambda **_kwargs: graph)
    run_generation(task_id)

    assert graph.configs and graph.configs[0]["recursion_limit"] == settings.GRAPH_RECURSION_LIMIT

    db = db_session_factory()
    task = db.get(GenerationTask, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.error_code == TaskErrorCode.RECURSION_LIMIT.value
    assert "Recursion limit" in (task.error or "")
    db.close()


def test_recursion_limit_keeps_headroom_over_saturated_repair_budget():
    # 上限若调到理论修复步数(~57)以下,合法长修复会被杀成 RECURSION_LIMIT 失败。
    from app.core.config import settings

    assert settings.GRAPH_RECURSION_LIMIT >= 70
