"""节点级实时追踪：每个节点开始写 running 步骤、结束翻 done，前端可见"正在运行"。

用装饰器包住每个 LangGraph 节点（graph.py），节点内部无需感知 DB。
每次写库用独立短事务，安全（图内节点串行执行）。
"""
import json
import time

from app.agents.state import STEP_META
from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, GenerationTask
from app.models.common import StepStatus, now_utc

_START_HINTS = {
    "Safety Intake": "checking prompt length, uploaded asset ids, and blocked patterns",
    "Intent Spec": "extracting title, genre, theme, controls, and win/loss conditions",
    "Asset Processing": "loading uploaded references and preparing the asset manifest",
    "Game Design": "planning screen layout, entities, rules, and HUD behavior",
    "Code Generation": "rendering HTML, CSS, and game.js for the browser runtime",
    "Build Validation": "checking required files, forbidden APIs, references, and bundle size",
    "Publish Artifact": "uploading files, writing manifest metadata, and saving preview records",
}


def begin_step(task_id: str, agent: str, display: str) -> str | None:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return None
        seq = (task.current_step or 0) + 1
        step = AgentStep(task_id=task_id, seq=seq, agent=agent, name=display,
                         status=StepStatus.RUNNING, started_at=now_utc())
        db.add(step)
        db.flush()
        hint = _START_HINTS.get(display, "running agent node")
        db.add(AgentLog(step_id=step.id, seq=0, line=f"started {display}: {hint}"))
        task.current_step = seq
        task.current_agent = agent
        db.commit()
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
            sid = begin_step(task_id, agent, display)
            if not state.get("use_real"):
                time.sleep(0.45)  # mock 节点太快，停顿让 running 态可见
            try:
                result = fn(state)
            except Exception as exc:  # noqa: BLE001
                finish_step(task_id, sid, [f"error: {exc}"], failed=True)
                raise
            finish_step(
                task_id, sid, result.get("_logs"), result.get("_tokens_delta", 0),
                repair=result.get("repair_attempts"), replan=result.get("replan_attempts"),
                failed=result.get("status") == "failed",
                spec=result.get("game_spec"), design=result.get("game_design"),
            )
            return result

        return wrapper

    return deco
