"""生成任务执行入口。

跑固定 LangGraph 工作流；每个节点由 tracing.logged 包装，开始/结束实时写
agent_steps / agent_logs（前端可见"正在运行"的那一步）。本函数只负责起止状态收尾。
mock（默认离线）与 real（USE_REAL_MODEL=true + GPT-5.5）走同一张图。
"""
import json

from app.core.config import settings
from app.core.errors import TaskErrorCode
from app.core.telemetry import bind_context, clear_context
from app.db.session import SessionLocal
from app.models import GenerationTask
from app.models.common import StepStatus, TaskStatus, now_utc


def _load_resume_snapshot(raw: str | None) -> tuple[str, dict] | None:
    """state_json → (node, state)。缺失/损坏一律 None，回落全新跑，不比旧路径差。"""
    try:
        payload = json.loads(raw or "")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    node, state = payload.get("node"), payload.get("state")
    if isinstance(node, str) and node and isinstance(state, dict) and state:
        return node, state
    return None


def _json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _load_revision_files(game_id: str, version: str) -> list[dict]:
    from app.storage import s3

    files = []
    for path in ("index.html", "style.css", "game.js"):
        raw = s3.get_object(f"games/{game_id}/{version}/{path}")
        if raw is None:
            raise RuntimeError(f"revision base file is missing: {path}")
        files.append({"path": path, "content": raw.decode("utf-8")})
    return files


def _uses_existing_bundle(task_kind: str) -> bool:
    return task_kind in {"revision", "remix"}


def _cleanup_cancelled_artifacts(db, task, final: dict | None) -> None:
    """取消恰好落在 publish 节点执行中时，图内已经建出 Game + bundle，
    而收尾不会回填 result_game_id —— 删掉这个游离的 preview 游戏和它的对象存储产物。
    revision 任务的 game_id 是用户已有的游戏，绝不能删，只保留新版本原样。
    """
    if not final or not final.get("game_id"):
        return
    if (task.task_kind or "generation") == "revision":
        return
    from app.models import Game
    from app.storage import s3

    game = db.get(Game, final["game_id"])
    if game and game.id != task.result_game_id:
        db.delete(game)
        db.commit()
        try:
            s3.delete_prefix(f"games/{final['game_id']}/")
        except Exception:  # noqa: BLE001  尽力清理，OSS 失败不影响取消语义
            pass


def run_generation(task_id: str, expected_dispatch_generation: int | None = None) -> None:
    bind_context(task_id=task_id)
    # 1) 置 running + 读取入参
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            clear_context()
            return
        if (
            expected_dispatch_generation is not None
            and task.dispatch_generation != expected_dispatch_generation
        ):
            clear_context()
            return
        if task.status == TaskStatus.CANCELLED:
            clear_context()
            return
        # acks_late + broker 重投递：终态任务的旧消息直接丢弃，不得重跑
        # （否则会重复建 Game/bundle，并让 memory 证据重复计数）。
        if task.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED):
            clear_context()
            return
        # 断点续跑：state_json 有合法快照（显式 retry 保留、或 worker 崩溃时留下）
        # 就从快照节点继续；否则维持旧语义从头跑。
        resume = _load_resume_snapshot(task.state_json)
        if task.status == TaskStatus.RUNNING:
            if resume is None:
                # worker 崩溃后的重投递且无快照：上一轮的步骤流已经作废，清掉
                # 再从头跑，避免同一任务出现两套同名步骤。
                for step in list(task.steps):
                    db.delete(step)
            else:
                # 有快照：保留已完成步骤（tokens/成本跨次累计），把崩溃时悬挂的
                # running 步骤翻成 failed，续跑会为重跑节点新开一条 attempt+1 步骤。
                for step in task.steps:
                    if step.status == StepStatus.RUNNING:
                        step.status = StepStatus.FAILED
                        step.finished_at = now_utc()
        task.status = TaskStatus.RUNNING
        if resume is None:
            task.started_at = now_utc()
            task.current_step = 0
            task.current_agent = None
            task.tokens_used = 0
            task.cost_usd = None
            task.repair_attempts = 0
            task.replan_attempts = 0
        else:
            task.started_at = task.started_at or now_utc()
        task.error = None
        task.error_code = None
        task.failed_stage = None
        idea = task.idea
        task_kind = task.task_kind or "generation"
        feedback_text = task.feedback_text or ""
        base_game_id = task.base_game_id
        base_version = task.base_version
        spec = _json_object(task.spec_json)
        design = _json_object(task.design_json)
        user_id = task.user_id
        dimension = task.dimension or "2d"
        asset_ids = [a.id for a in task.assets]
        db.commit()
        bind_context(task_id=task_id, user_id=user_id)
    finally:
        db.close()

    # 2) 跑图（节点内部实时落库）
    final: dict | None = None
    err = ""
    error_code = TaskErrorCode.UNKNOWN.value
    try:
        from app.agents.graph import build_graph
        from app.agents.tracing import TaskBudgetExceededError, TaskCancelledError

        use_real = settings.USE_REAL_MODEL and bool(settings.OPENAI_API_KEY.strip())
        graph = build_graph()
        if resume is not None:
            # 断点续跑：快照即失败节点的输入状态，入口路由据 _resume_node 直跳。
            # 基础设施键（task_id/use_real 等）以当前部署为准覆盖快照。
            resume_node, snap_state = resume
            initial = {
                **snap_state,
                "task_id": task_id, "user_id": user_id, "use_real": use_real,
                "status": "running",
                "_resume_node": resume_node,
            }
        else:
            initial = {
                "task_id": task_id, "user_id": user_id, "use_real": use_real, "status": "running",
                "task_kind": task_kind,
                "prompt": feedback_text if _uses_existing_bundle(task_kind) else idea,
                "asset_ids": asset_ids, "dimension": dimension,
                "repair_attempts": 0, "replan_attempts": 0,
                "gameplay_repair_attempts": 0,
            }
            if _uses_existing_bundle(task_kind):
                if not base_game_id or not base_version or not feedback_text:
                    raise RuntimeError(f"{task_kind} task is missing its base version or feedback")
                initial.update({
                    "source_feedback": feedback_text,
                    "base_game_id": base_game_id,
                    "base_version": base_version,
                    "existing_files": _load_revision_files(base_game_id, base_version),
                    "game_spec": spec,
                    "game_design": design,
                })
        final = graph.invoke(initial)
    except TaskCancelledError:
        # 用户取消：begin_step 在节点边界抛出。不算失败，收尾只做孤儿清理。
        final = None
    except TaskBudgetExceededError as exc:
        err = str(exc)[:500]
        error_code = TaskErrorCode.BUDGET_EXCEEDED.value
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:500]

    # 3) 收尾
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return
        if task.status == TaskStatus.CANCELLED:
            _cleanup_cancelled_artifacts(db, task, final)
            task.error_code = TaskErrorCode.CANCELLED.value
            task.state_json = None  # 取消不可重试，快照无用
            db.commit()
            return
        if final is None:
            task.status = TaskStatus.FAILED
            task.error = err or "generation crashed"
            task.error_code = error_code
            task.failed_stage = task.failed_stage or task.current_agent
        else:
            if final.get("game_spec"):
                task.spec_json = json.dumps(final["game_spec"], ensure_ascii=False)
            if final.get("game_design"):
                task.design_json = json.dumps(final["game_design"], ensure_ascii=False)
            if final.get("feedback_brief"):
                task.feedback_brief = str(final["feedback_brief"])
            if final.get("status") == "succeeded" and final.get("game_id"):
                task.result_game_id = final["game_id"]
                task.version_id = final.get("version_id")
                task.status = TaskStatus.SUCCEEDED
                task.state_json = None  # 成功后快照即垃圾（可达 MB 级），立即释放
            else:
                task.status = TaskStatus.FAILED
                task.error = final.get("error_message") or final.get("last_error") or "generation failed"
                task.error_code = final.get("error_code") or TaskErrorCode.UNKNOWN.value
                task.failed_stage = task.failed_stage or task.current_agent
        task.finished_at = now_utc()
        db.commit()
    finally:
        db.close()
        clear_context()
