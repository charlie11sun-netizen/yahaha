"""生成任务执行入口。

跑固定 LangGraph 工作流；每个节点由 tracing.logged 包装，开始/结束实时写
agent_steps / agent_logs（前端可见"正在运行"的那一步）。本函数只负责起止状态收尾。
mock（默认离线）与 real（USE_REAL_MODEL=true + GPT-5.5）走同一张图。
"""
import json

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import GenerationTask
from app.models.common import TaskStatus, now_utc


def run_generation(task_id: str) -> None:
    # 1) 置 running + 读取入参
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return
        if task.status == TaskStatus.CANCELLED:
            return
        task.status = TaskStatus.RUNNING
        task.started_at = now_utc()
        task.current_step = 0
        task.current_agent = None
        task.tokens_used = 0
        task.error = None
        task.error_code = None
        task.repair_attempts = 0
        task.replan_attempts = 0
        idea = task.idea
        user_id = task.user_id
        asset_ids = [a.id for a in task.assets]
        db.commit()
    finally:
        db.close()

    # 2) 跑图（节点内部实时落库）
    final: dict | None = None
    err = ""
    try:
        from app.agents.graph import build_graph

        use_real = settings.USE_REAL_MODEL and bool(settings.OPENAI_API_KEY.strip())
        graph = build_graph()
        final = graph.invoke({
            "task_id": task_id, "user_id": user_id, "use_real": use_real, "status": "running",
            "prompt": idea, "asset_ids": asset_ids, "repair_attempts": 0, "replan_attempts": 0,
        })
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:500]

    # 3) 收尾
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return
        if task.status == TaskStatus.CANCELLED:
            return
        if final is None:
            task.status = TaskStatus.FAILED
            task.error = err or "generation crashed"
        else:
            if final.get("game_spec"):
                task.spec_json = json.dumps(final["game_spec"], ensure_ascii=False)
            if final.get("game_design"):
                task.design_json = json.dumps(final["game_design"], ensure_ascii=False)
            if final.get("status") == "succeeded" and final.get("game_id"):
                task.result_game_id = final["game_id"]
                task.version_id = final.get("version_id")
                task.status = TaskStatus.SUCCEEDED
            else:
                task.status = TaskStatus.FAILED
                task.error = final.get("error_message") or final.get("last_error") or "generation failed"
                task.error_code = final.get("error_code")
        task.finished_at = now_utc()
        db.commit()
    finally:
        db.close()
