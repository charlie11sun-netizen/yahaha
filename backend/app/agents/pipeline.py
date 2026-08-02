"""生成任务执行入口。

跑固定 LangGraph 工作流；每个节点由 tracing.logged 包装，开始/结束实时写
agent_steps / agent_logs（前端可见"正在运行"的那一步）。本函数只负责起止状态收尾。
mock（默认离线）与 real（USE_REAL_MODEL=true + gpt-5.6-sol）走同一张图。
"""
import json
import logging

from langgraph.errors import GraphRecursionError
from psycopg import Error as PsycopgError
from psycopg_pool import PoolTimeout

from app.agents import llm_accounting, opik_integration
from app.agents.decision_trace import (
    AGENT_STEP_CONTRACT_VERSION,
    DECISION_TRACE_SCHEMA_VERSION,
)
from app.agents.state import STEP_META
from app.agents.tracing import TaskBudgetExceededError, TaskCancelledError
from app.core.checkpointing import CheckpointStorageError, checkpoint_config, open_checkpointer
from app.core.config import settings
from app.core.errors import (
    AgentStreamRetryRequired,
    AuthorTeamRetryRequired,
    TaskErrorCode,
)
from app.core.telemetry import bind_context, clear_context
from app.db.session import SessionLocal
from app.models import Game, GameVersion, GenerationTask
from app.models.common import StepStatus, TaskStatus, now_utc
from app.services.game_assets import AssetGenerationRetryRequired
from app.services.task_events import publish_task_event

logger = logging.getLogger(__name__)


def _node_for_step(step) -> str | None:
    if step is None:
        return None
    for node_name, (agent, display) in STEP_META.items():
        if step.agent == agent and step.name == display:
            return node_name
    return None


def _failed_resume_node(steps) -> str | None:
    """Choose the checkpoint node that can actually repair the last failure.

    ``design_contract`` records a failed step by returning ``contract_error``;
    the graph then visits ``contract_gate``, which records a second failure and
    terminates.  Resuming the newest failed step would replay the gate against
    the same stale error forever.  In that paired-failure case the compiler is
    the true repair boundary and must be replayed first.
    """

    failed_nodes = [
        node
        for step in steps
        if step.status == StepStatus.FAILED and (node := _node_for_step(step))
    ]
    if not failed_nodes:
        return None
    if failed_nodes[-1] == "contract_gate" and "design_contract" in failed_nodes:
        return "design_contract"
    return failed_nodes[-1]


def _checkpoint_plan(graph, task_id: str, failed_node: str | None) -> tuple[dict | None, dict | None]:
    """Return (resume_config, completed_final) for a durable task thread.

    An exception or worker crash leaves the latest checkpoint pointing at the
    node that must run. A graph-level failure reaches END normally, so replay
    uses the historical checkpoint immediately before the recorded failed step.
    """

    history = list(graph.get_state_history(checkpoint_config(task_id)))
    if not history:
        return None, None

    latest = history[0]
    if not latest.next and latest.values.get("status") == "succeeded":
        return None, dict(latest.values)
    if latest.next and tuple(latest.next) != ("failed",):
        return latest.config, None

    if failed_node:
        for snapshot in history:
            if tuple(snapshot.next) == (failed_node,):
                return snapshot.config, None

    # Defensive fallback for a legacy/partially recorded step stream: choose
    # the newest real workflow node, never the terminal failure handler.
    for snapshot in history:
        if snapshot.next and tuple(snapshot.next) != ("failed",):
            return snapshot.config, None
    return None, None


def _delete_checkpoint_best_effort(checkpointer, task_id: str) -> None:
    try:
        checkpointer.delete_thread(task_id)
    except Exception:  # noqa: BLE001 - terminal task state must still commit
        logger.exception("failed to delete terminal LangGraph checkpoint thread", extra={"generation_task_id": task_id})


def _json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _load_revision_files(game_id: str, version: str) -> list[dict]:
    from app.storage import s3
    from app.services.artifacts import artifact_from_bytes

    source_prefix = f"game-sources/{game_id}/{version}"
    source_manifest = s3.get_object(f"{source_prefix}/manifest.json")
    if source_manifest:
        try:
            manifest = json.loads(source_manifest.decode("utf-8"))
            files = []
            for item in manifest.get("files") or []:
                path = str(item.get("path") or "")
                raw = s3.get_object(f"{source_prefix}/{path}")
                if raw is None:
                    raise RuntimeError(f"revision source file is missing: {path}")
                content_type = str(item.get("content_type") or "application/octet-stream")
                files.append(artifact_from_bytes(path, raw, content_type))
            if files:
                return files
        except (ValueError, UnicodeDecodeError):
            pass

    runtime_prefix = f"games/{game_id}/{version}"
    runtime_manifest = s3.get_object(f"{runtime_prefix}/manifest.json")
    if runtime_manifest:
        try:
            manifest = json.loads(runtime_manifest.decode("utf-8"))
            files = []
            for item in manifest.get("files") or []:
                path = str(item.get("path") or "")
                if path in {"three.min.js", "phaser.min.js"}:
                    continue
                raw = s3.get_object(f"{runtime_prefix}/{path}")
                if raw is None:
                    raise RuntimeError(f"revision base file is missing: {path}")
                content_type = str(item.get("content_type") or "application/octet-stream")
                files.append(artifact_from_bytes(path, raw, content_type))
            if files:
                return files
        except (ValueError, UnicodeDecodeError):
            pass

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
            s3.delete_prefix(f"game-sources/{final['game_id']}/")
        except Exception:  # noqa: BLE001  尽力清理，OSS 失败不影响取消语义
            pass


def _run_generation(task_id: str, expected_dispatch_generation: int | None = None) -> None:
    bind_context(task_id=task_id)
    # 1) Read immutable inputs and determine whether a prior run may resume.
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
        was_running = task.status == TaskStatus.RUNNING
        resume_requested = was_running or bool(task.steps)
        failed_node = _failed_resume_node(task.steps)
        idea = task.idea
        task_kind = task.task_kind or "generation"
        feedback_text = task.feedback_text or ""
        base_game_id = task.base_game_id
        base_version = task.base_version
        spec = _json_object(task.spec_json)
        design = _json_object(task.design_json)
        saved_contract = _json_object(getattr(task, "contract_json", None))
        saved_contract_meta = (
            dict(saved_contract.get("meta") or {})
            if isinstance(saved_contract.get("meta"), dict)
            else {}
        )
        user_id = task.user_id
        dimension = task.dimension or "2d"
        asset_ids = [a.id for a in task.assets]
        bind_context(task_id=task_id, user_id=user_id)
    finally:
        db.close()

    trace_game_id = base_game_id if task_kind == "revision" else None
    opik_integration.update_generation_trace(
        input={
            "task_id": task_id,
            "task_kind": task_kind,
            "prompt": feedback_text if _uses_existing_bundle(task_kind) else idea,
            "asset_ids": asset_ids,
            "dimension": dimension,
        },
        metadata={
            "task_id": task_id,
            "task_kind": task_kind,
            "dimension": dimension,
            "base_game_id": base_game_id,
            "base_version": base_version,
            "game_id": trace_game_id,
            "model": settings.MODEL_NAME,
            "decision_schema_version": DECISION_TRACE_SCHEMA_VERSION,
            "trace_contract_version": AGENT_STEP_CONTRACT_VERSION,
            "contract_hash": getattr(task, "contract_hash", None),
            "contract_revision": getattr(task, "contract_revision", None),
            "design_contract_hash": getattr(task, "contract_hash", None),
            "design_contract_revision": getattr(task, "contract_revision", None),
            "design_contract_schema_version": saved_contract_meta.get("schema_version"),
            "opik_trace_id": getattr(task, "opik_trace_id", None),
        },
        tags=[
            "gameweave",
            "game-generation",
            f"task-kind:{task_kind}",
            f"dimension:{dimension}",
        ],
        thread_id=f"game:{trace_game_id}" if trace_game_id else None,
    )

    # 2) Resolve and run the durable graph. The saver remains open for the run.
    final: dict | None = None
    err = ""
    error_code = TaskErrorCode.UNKNOWN.value
    with open_checkpointer() as checkpointer:
        try:
            from app.agents.graph import build_graph
            use_real = settings.USE_REAL_MODEL and bool(settings.OPENAI_API_KEY.strip())
            graph = build_graph(checkpointer=checkpointer)
            resume_config, completed_final = (
                _checkpoint_plan(graph, task_id, failed_node)
                if resume_requested
                else (None, None)
            )
            is_resume = resume_config is not None or completed_final is not None
            if resume_requested and not is_resume:
                # No usable native checkpoint exists (for example, a task from
                # before this migration). Fall back to the established restart.
                checkpointer.delete_thread(task_id)

            db = SessionLocal()
            try:
                task = db.get(GenerationTask, task_id)
                if not task or task.status == TaskStatus.CANCELLED:
                    _delete_checkpoint_best_effort(checkpointer, task_id)
                    clear_context()
                    return
                if is_resume:
                    for step in task.steps:
                        if step.status == StepStatus.RUNNING:
                            step.status = StepStatus.FAILED
                            step.finished_at = now_utc()
                    task.started_at = task.started_at or now_utc()
                else:
                    for step in list(task.steps):
                        db.delete(step)
                    task.started_at = now_utc()
                    task.current_step = 0
                    task.current_agent = None
                    task.tokens_used = 0
                    task.cost_usd = None
                    task.repair_attempts = 0
                    task.replan_attempts = 0
                task.status = TaskStatus.RUNNING
                task.error = None
                task.error_code = None
                task.failed_stage = None
                db.commit()
                publish_task_event(task_id, "running")
            finally:
                db.close()

            if completed_final is not None:
                final = completed_final
            elif resume_config is not None:
                if not was_running:
                    # Explicit Retry replenishes graph-level repair budgets. The
                    # update creates a native fork while preserving the next node.
                    resume_config = graph.update_state(
                        resume_config,
                        {
                            "status": "running",
                            "repair_attempts": 0,
                            "replan_attempts": 0,
                            "gameplay_repair_attempts": 0,
                            "gameplay_qa_feedback": None,
                            "last_error": None,
                            "error_code": None,
                            "error_message": None,
                        },
                    )
                final = graph.invoke(
                    None,
                    {**resume_config, "recursion_limit": settings.GRAPH_RECURSION_LIMIT},
                )
            else:
                initial = {
                    "task_id": task_id,
                    "user_id": user_id,
                    "use_real": use_real,
                    "status": "running",
                    "task_kind": task_kind,
                    "prompt": feedback_text if _uses_existing_bundle(task_kind) else idea,
                    "asset_ids": asset_ids,
                    "dimension": dimension,
                    "contract_version": AGENT_STEP_CONTRACT_VERSION,
                    "trace_contract_version": AGENT_STEP_CONTRACT_VERSION,
                    "prompt_version": "generation-prompts/v1",
                    "model": settings.MODEL_NAME,
                    "provider": "openai",
                    "repair_attempts": 0,
                    "replan_attempts": 0,
                    "gameplay_repair_attempts": 0,
                    "gameplay_qa_feedback": None,
                }
                if _uses_existing_bundle(task_kind):
                    if not base_game_id or not base_version or not feedback_text:
                        raise RuntimeError(f"{task_kind} task is missing its base version or feedback")
                    existing_files = _load_revision_files(base_game_id, base_version)
                    from app.services.vite_projects import VITE_PROJECT_FORMAT, is_vite_project

                    vite_source = is_vite_project(existing_files)
                    initial.update(
                        {
                            "source_feedback": feedback_text,
                            "base_game_id": base_game_id,
                            "base_version": base_version,
                            "existing_files": existing_files,
                            "project_files": existing_files if vite_source else [],
                            "artifact_format": VITE_PROJECT_FORMAT if vite_source else "legacy-bundle/v1",
                            "game_spec": spec,
                            "game_design": design,
                            "design_contract": saved_contract,
                            "contract_hash": getattr(task, "contract_hash", None),
                            "contract_revision": getattr(task, "contract_revision", None),
                        }
                    )
                final = graph.invoke(
                    initial,
                    {**checkpoint_config(task_id), "recursion_limit": settings.GRAPH_RECURSION_LIMIT},
                )
        except (PsycopgError, PoolTimeout) as exc:
            # A durable saver outage is infrastructure failure, not a failed
            # generation. Let the Celery delivery retry without changing task state.
            raise CheckpointStorageError("LangGraph checkpoint storage is unavailable") from exc
        except TaskCancelledError:
            # User cancellation is observed at the next node boundary.
            final = None
        except AssetGenerationRetryRequired as exc:
            err = str(exc)[:500]
            error_code = TaskErrorCode.ASSET_GENERATION_FAILED.value
        except AgentStreamRetryRequired as exc:
            # 模型网关中断打断了某个 agent 阶段:保留检查点暂停,手动重试原地续跑
            # (语义同图像重试;错误码沿用 MODEL_TIMEOUT,前端归入"等待重试")。
            err = str(exc)[:500]
            error_code = TaskErrorCode.MODEL_TIMEOUT.value
        except AuthorTeamRetryRequired as exc:
            err = str(exc)[:500]
            error_code = TaskErrorCode.MODEL_INVALID_OUTPUT.value
        except TaskBudgetExceededError as exc:
            err = str(exc)[:500]
            error_code = TaskErrorCode.BUDGET_EXCEEDED.value
        except GraphRecursionError as exc:
            # 步数触顶=构建/修复循环失控:专属失因替代 UNKNOWN,检查点按失败语义
            # 保留;上限取值依据见 settings.GRAPH_RECURSION_LIMIT。
            err = str(exc)[:500]
            error_code = TaskErrorCode.RECURSION_LIMIT.value
            logger.exception(
                "generation graph exceeded recursion limit",
                extra={
                    "generation_task_id": task_id,
                    "recursion_limit": settings.GRAPH_RECURSION_LIMIT,
                },
            )
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:500]
            logger.exception(
                "generation pipeline failed",
                extra={"generation_task_id": task_id},
            )

        # 3) Finalize application state; retain checkpoints only for failures.
        db = SessionLocal()
        try:
            task = db.get(GenerationTask, task_id)
            if not task:
                clear_context()
                return
            if task.status == TaskStatus.CANCELLED:
                _cleanup_cancelled_artifacts(db, task, final)
                task.error_code = TaskErrorCode.CANCELLED.value
                _delete_checkpoint_best_effort(checkpointer, task_id)
                db.commit()
                publish_task_event(task_id, "cancelled")
                clear_context()
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
                if final.get("design_contract"):
                    task.contract_json = json.dumps(final["design_contract"], ensure_ascii=False)
                    task.contract_hash = final.get("contract_hash") or ((final.get("design_contract") or {}).get("meta") or {}).get("contract_hash")
                    task.contract_revision = final.get("contract_revision") or ((final.get("design_contract") or {}).get("meta") or {}).get("revision")
                if final.get("feedback_brief"):
                    task.feedback_brief = str(final["feedback_brief"])
                if final.get("status") == "succeeded" and final.get("game_id"):
                    task.result_game_id = final["game_id"]
                    task.version_id = final.get("version_id")
                    task.status = TaskStatus.SUCCEEDED
                    # Repairable stage failures may have populated these fields
                    # earlier in the same run.  They describe terminal failures,
                    # so retaining them on a successful task corrupts failure-rate
                    # analysis in both SQL and the finalized Opik root trace.
                    task.error = None
                    task.error_code = None
                    task.failed_stage = None
                    _delete_checkpoint_best_effort(checkpointer, task_id)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = final.get("error_message") or final.get("last_error") or "generation failed"
                    task.error_code = final.get("error_code") or TaskErrorCode.UNKNOWN.value
                    task.failed_stage = task.failed_stage or task.current_agent
            task.finished_at = now_utc()
            db.commit()
            publish_task_event(task_id, task.status)
        finally:
            db.close()
    clear_context()


def _finalize_generation_trace(task_id: str) -> None:
    """Backfill result identifiers so Opik can filter by game and version."""
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return
        game_id = task.result_game_id
        if not game_id and (task.task_kind or "generation") == "revision":
            game_id = task.base_game_id
        game = db.get(Game, game_id) if game_id else None
        version = db.get(GameVersion, task.version_id) if task.version_id else None
        status = str(task.status or "unknown")
        succeeded = task.status == TaskStatus.SUCCEEDED or status == "succeeded"
        trace_error_code = None if succeeded else task.error_code
        trace_failed_stage = None if succeeded else task.failed_stage
        metadata = {
            "task_id": task.id,
            "task_kind": task.task_kind or "generation",
            "status": status,
            "game_id": game_id,
            "game_title": game.title if game else None,
            "version": version.version if version else task.base_version,
            "version_id": task.version_id,
            "dimension": task.dimension,
            "error_code": trace_error_code,
            "failed_stage": trace_failed_stage,
            "decision_schema_version": DECISION_TRACE_SCHEMA_VERSION,
            "trace_contract_version": AGENT_STEP_CONTRACT_VERSION,
            "opik_trace_id": getattr(task, "opik_trace_id", None),
        }
        contract = _json_object(getattr(task, "contract_json", None))
        contract_metadata = opik_integration.contract_observability_metadata(
            state={
                "design_contract": contract,
                "contract_hash": getattr(task, "contract_hash", None),
                "contract_revision": getattr(task, "contract_revision", None),
            }
        )
        metadata.update(contract_metadata)
        cache_metadata = llm_accounting.cache_observability_metadata(
            session_factory=SessionLocal,
            task_id=task_id,
            logger=logger,
        )
        metadata.update(cache_metadata)
        output = {
            "status": status,
            "game_id": game_id,
            "version": version.version if version else task.base_version,
            "tokens": int(task.tokens_used or 0),
            "cost_usd": float(task.cost_usd) if task.cost_usd is not None else None,
            "error_code": trace_error_code,
            "contract_hash": getattr(task, "contract_hash", None),
            "contract_revision": getattr(task, "contract_revision", None),
            "design_contract_schema_version": contract_metadata.get(
                "design_contract_schema_version"
            ),
            "opik_trace_id": getattr(task, "opik_trace_id", None),
            "cache_observability": cache_metadata.get("llm_cache_metrics"),
        }
        display_name = game.title if game and game.title else task.id
        opik_integration.update_generation_trace(
            name=f"game-generation:{display_name}",
            output=output,
            metadata=metadata,
            tags=[
                "gameweave",
                "game-generation",
                f"task-kind:{task.task_kind or 'generation'}",
                f"dimension:{task.dimension}",
                f"status:{status}",
                *opik_integration.contract_observability_tags(contract_metadata),
            ],
            thread_id=f"game:{game_id}" if game_id else f"task:{task.id}",
        )
    finally:
        db.close()


def _persist_opik_trace_id(task_id: str, trace) -> None:
    trace_id = str(getattr(trace, "id", "") or "").strip()
    if not trace_id:
        return
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if task and task.opik_trace_id != trace_id:
            task.opik_trace_id = trace_id
            db.commit()
    except Exception:  # noqa: BLE001 - telemetry correlation must fail open
        db.rollback()
        logger.exception(
            "failed to persist Opik trace id",
            extra={"generation_task_id": task_id, "opik_trace_id": trace_id},
        )
    finally:
        db.close()


def run_generation(task_id: str, expected_dispatch_generation: int | None = None) -> None:
    """Run one generation inside a searchable Opik task-level root trace."""
    try:
        with opik_integration.generation_trace(
            task_id=task_id,
            dispatch_generation=expected_dispatch_generation,
        ) as trace:
            try:
                if trace is not None:
                    _persist_opik_trace_id(task_id, trace)
                _run_generation(task_id, expected_dispatch_generation)
            finally:
                if trace is not None:
                    _finalize_generation_trace(task_id)
    finally:
        opik_integration.flush()
