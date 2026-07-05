"""节点级实时追踪：每个节点开始写 running 步骤、结束翻 done，前端可见"正在运行"。

用装饰器包住每个 LangGraph 节点（graph.py），节点内部无需感知 DB。
每次写库用独立短事务，安全（图内节点串行执行）。
"""
import json
import time

from app.agents.state import STEP_META
from app.core.config import settings
from app.core.telemetry import agent_span, bind_context
from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, GenerationTask
from app.models.common import StepStatus, TaskStatus, now_utc


class TaskCancelledError(Exception):
    """用户已取消任务：在下一个节点边界中止整张图（pipeline 捕获后静默收尾）。"""


class TaskBudgetExceededError(Exception):
    """任务 token 硬预算已耗尽：在下一个节点边界中止整张图。"""

_START_HINTS = {
    "Safety Intake": "checking prompt length, uploaded asset ids, and blocked patterns",
    "Intent Spec": "extracting title, genre, theme, controls, and win/loss conditions",
    "Brief Expansion": "expanding the user prompt into a fuller playable game brief",
    "Mechanic Planner": "selecting concrete mechanics, rewards, enemies, and feedback loops",
    "Archetype Router": "selecting a proven playable template family for the prompt",
    "Asset Processing": "loading uploaded references and preparing the asset manifest",
    "Game Design": "planning screen layout, entities, rules, and HUD behavior",
    "Content Plan": "building waves, pickups, hazards, tutorial beats, and puzzle content",
    "Balance Plan": "setting round length, score target, lives, spawn rate, and difficulty thresholds",
    "Code Generation": "rendering HTML, CSS, and game.js for the browser runtime",
    "Build Validation": "checking required files, forbidden APIs, references, and bundle size",
    "Gameplay QA": "checking restart, scoring, timer, input response, and difficulty readability",
    "Gameplay Repair": "retuning balance and regenerating when playtest thresholds fail",
    "Publish Artifact": "uploading files, writing manifest metadata, and saving preview records",
}


def _state_snapshot(node_name: str, state: dict) -> str | None:
    """断点续跑快照：{"node": 当前节点, "state": 公开状态键}。
    下划线前缀键（_logs/_resume_node 等）不入快照；序列化失败不阻断生成。"""
    try:
        public = {k: v for k, v in state.items() if not str(k).startswith("_")}
        return json.dumps({"node": node_name, "state": public}, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return None


def begin_step(task_id: str, agent: str, display: str,
               node_name: str | None = None, state: dict | None = None) -> str | None:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return None
        # 每个节点开始前都会经过这里 —— 取消检查放在这个天然的 DB 往返上，
        # 运行中的任务最多再跑完当前节点就停，不再烧后续的 LLM 调用。
        if task.status == TaskStatus.CANCELLED:
            raise TaskCancelledError(task_id)
        if settings.TASK_TOKEN_BUDGET > 0 and (task.tokens_used or 0) >= settings.TASK_TOKEN_BUDGET:
            raise TaskBudgetExceededError(
                f"token budget exceeded: {task.tokens_used}/{settings.TASK_TOKEN_BUDGET}"
            )
        seq = (task.current_step or 0) + 1
        attempt = (
            db.query(AgentStep)
            .filter(
                AgentStep.task_id == task_id,
                AgentStep.agent == agent,
                AgentStep.name == display,
            )
            .count()
            + 1
        )
        caused_by_step_id = None
        if "Repair" in agent or "Replan" in agent or "Repair" in display or "Replan" in display:
            failed_step = (
                db.query(AgentStep)
                .filter(AgentStep.task_id == task_id, AgentStep.status == StepStatus.FAILED)
                .order_by(AgentStep.seq.desc())
                .first()
            )
            caused_by_step_id = failed_step.id if failed_step else None
        step = AgentStep(
            task_id=task_id,
            seq=seq,
            agent=agent,
            name=display,
            status=StepStatus.RUNNING,
            started_at=now_utc(),
            attempt=attempt,
            caused_by_step_id=caused_by_step_id,
        )
        db.add(step)
        db.flush()
        hint = _START_HINTS.get(display, "running agent node")
        db.add(AgentLog(step_id=step.id, seq=0, line=f"started {display}: {hint}"))
        task.current_step = seq
        task.current_agent = agent
        # 节点开始 = 快照点：存"这个节点的输入"。节点失败/进程崩溃后，续跑即重跑
        # 该节点。借用本函数固有的这次事务，不新增 DB 往返。
        if node_name and state is not None:
            snapshot = _state_snapshot(node_name, state)
            if snapshot:
                task.state_json = snapshot
        db.commit()
        bind_context(task_id=task_id, step_id=step.id, agent=agent, node_name=display)
        return step.id
    finally:
        db.close()


def finish_step(task_id, step_id, logs, tokens=0, repair=None, replan=None, failed=False,
                spec=None, design=None) -> None:
    db = SessionLocal()
    try:
        if step_id:
            step = db.get(AgentStep, step_id)
            if step:
                step.status = StepStatus.FAILED if failed else StepStatus.DONE
                step.tokens = (step.tokens or 0) + int(tokens or 0)
                step.finished_at = now_utc()
                base_seq = len(step.logs or [])
                for i, line in enumerate(logs or []):
                    db.add(AgentLog(step_id=step_id, seq=base_seq + i, line=str(line)))
        task = db.get(GenerationTask, task_id)
        if task:
            task.tokens_used = (task.tokens_used or 0) + int(tokens or 0)
            if repair is not None:
                task.repair_attempts = repair
            if replan is not None:
                task.replan_attempts = replan
            if failed:
                task.failed_stage = step.name if step else task.current_agent
            if spec is not None:  # 实时落库，前端在 game_design 完成后即可看到设计草案
                task.spec_json = json.dumps(spec, ensure_ascii=False)
            if design is not None:
                task.design_json = json.dumps(design, ensure_ascii=False)
        db.commit()
    finally:
        db.close()


def logged(node_name: str):
    """把节点包成：begin(running) → 跑 → finish(done/failed)。"""
    agent, display = STEP_META.get(node_name, (node_name, node_name))

    def deco(fn):
        def wrapper(state: dict):
            task_id = state.get("task_id")
            sid = begin_step(task_id, agent, display, node_name=node_name, state=state)
            if not state.get("use_real"):
                time.sleep(0.45)  # mock 节点太快，停顿让 running 态可见
            with agent_span(
                f"agent.{node_name}",
                {"agent": agent, "task_id": task_id, "step_id": sid},
            ) as span:
                try:
                    result = fn(state)
                except Exception as exc:  # noqa: BLE001
                    span.record_exception(exc)
                    finish_step(task_id, sid, [f"error: {exc}"], failed=True)
                    bind_context(step_id=None, agent=None, node_name=None)
                    raise
                tokens = int(result.get("_tokens_delta", 0) or 0)
                failed = result.get("status") == "failed" or bool(result.get("_step_failed"))
                span.set_attribute("tokens", tokens)
                span.set_attribute("failed", failed)
                span.set_attribute("repair_attempts", result.get("repair_attempts", state.get("repair_attempts", 0)))
                span.set_attribute("replan_attempts", result.get("replan_attempts", state.get("replan_attempts", 0)))
                finish_step(
                    task_id, sid, result.get("_logs"), tokens,
                    repair=result.get("repair_attempts"), replan=result.get("replan_attempts"),
                    failed=failed,
                    spec=result.get("game_spec"), design=result.get("game_design"),
                )
                bind_context(step_id=None, agent=None, node_name=None)
                return result

        return wrapper

    return deco
