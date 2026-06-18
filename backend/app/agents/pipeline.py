"""生成任务执行入口：跑固定 LangGraph 工作流，把每个节点流式落库成 agent_steps / agent_logs。

mock（默认离线）与 real（USE_REAL_MODEL=true + GPT-5.5）走同一张图，区别只在 intent_spec /
game_design / replan 节点内部是调模型还是用启发式。
"""
import json
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, GenerationTask, User
from app.models.common import StepStatus, TaskStatus, now_utc


def run_generation(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return
        _ = db.get(User, task.user_id)

        task.status = TaskStatus.RUNNING
        task.started_at = now_utc()
        task.current_step = 0
        task.tokens_used = 0
        task.error = None
        task.error_code = None
        task.repair_attempts = 0
        task.replan_attempts = 0
        db.commit()

        from app.agents.graph import build_graph
        from app.agents.state import STEP_META

        use_real = settings.USE_REAL_MODEL and bool(settings.OPENAI_API_KEY.strip())
        graph = build_graph()
        initial = {
            "task_id": task.id,
            "user_id": task.user_id,
            "use_real": use_real,
            "status": "running",
            "prompt": task.idea,
            "asset_ids": [a.id for a in task.assets],
            "repair_attempts": 0,
            "replan_attempts": 0,
        }

        step_seq = 0
        total_tokens = 0
        final: dict = {}
        for event in graph.stream(initial, stream_mode="updates"):
            for node_name, update in event.items():
                if not isinstance(update, dict):
                    continue
                final.update({k: v for k, v in update.items() if not k.startswith("_")})
                if node_name in ("failed", "done"):
                    continue  # 终态处理节点不作为展示步骤

                agent_default, display = STEP_META.get(node_name, (node_name, node_name))
                agent = update.get("_agent", agent_default)
                step_seq += 1
                step = AgentStep(
                    task_id=task.id, seq=step_seq, agent=agent, name=display,
                    status=StepStatus.DONE, started_at=now_utc(), finished_at=now_utc(),
                )
                db.add(step)
                task.current_step = step_seq
                task.current_agent = agent
                db.commit()

                for i, line in enumerate(update.get("_logs", [])):
                    db.add(AgentLog(step_id=step.id, seq=i, line=str(line)))
                total_tokens += int(update.get("_tokens_delta", 0) or 0)
                task.tokens_used = total_tokens
                if "repair_attempts" in update:
                    task.repair_attempts = update["repair_attempts"]
                if "replan_attempts" in update:
                    task.replan_attempts = update["replan_attempts"]
                db.commit()
                if not use_real:
                    time.sleep(0.4)  # mock 路径无模型延迟，稍作停顿让步骤可见地流式出现

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
    except Exception as exc:  # noqa: BLE001 — 失败即落库，前端可读
        db.rollback()
        t = db.get(GenerationTask, task_id)
        if t:
            t.status = TaskStatus.FAILED
            t.error = str(exc)[:500]
            t.finished_at = now_utc()
            db.commit()
    finally:
        db.close()
