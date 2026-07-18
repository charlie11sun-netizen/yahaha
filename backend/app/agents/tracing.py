"""节点级实时追踪：每个节点开始写 running 步骤、结束翻 done，前端可见"正在运行"。

用装饰器包住每个 LangGraph 节点（graph.py），节点内部无需感知 DB。
每次写库用独立短事务，安全（图内节点串行执行）。
"""
import json
import logging
import time

from app.agents import opik_integration
from app.agents.decision_trace import build_decision, json_text
from app.agents.state import STEP_META
from app.core.config import settings
from app.core.telemetry import agent_span, bind_context, get_context
from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, GenerationTask, LLMCall
from app.models.common import StepStatus, TaskStatus, now_utc
from app.services.agent_logs import append_agent_log
from app.services.task_events import publish_task_event
from sqlalchemy import func

logger = logging.getLogger(__name__)


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
    "Generate Game Assets": "routing generated images, audio, video, and tilemaps through configured providers",
    "Game Design": "planning screen layout, entities, rules, and HUD behavior",
    "Content Plan": "building waves, pickups, hazards, tutorial beats, and puzzle content",
    "Balance Plan": "setting round length, score target, lives, spawn rate, and difficulty thresholds",
    "Design Contract": "compiling the complete frozen design contract from planning evidence",
    "Contract Gate": "checking schema, intent coverage, runtime consumers, and acceptance mappings",
    "Code Generation": "rendering HTML, CSS, and game.js for the browser runtime",
    "Project Build": "building a generated Phaser/Vite source project into static dist artifacts",
    "Build Validation": "checking required files, forbidden APIs, references, and bundle size",
    "Gameplay QA": "checking restart, scoring, timer, input response, and difficulty readability",
    "Gameplay Repair": "retuning balance and regenerating when playtest thresholds fail",
    "Publish Artifact": "uploading files, writing manifest metadata, and saving preview records",
}


def begin_step(task_id: str, agent: str, display: str) -> str | None:
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
        if "Repair" in agent or "Repair" in display:
            max_attempts = int(task.max_repair_attempts or 0)
            repair_kind = (
                "gameplay"
                if "Gameplay" in agent or "Gameplay" in display
                else "revision"
                if "Revision" in agent or "Revision" in display
                else "build"
            )
            db.add(
                AgentLog(
                    step_id=step.id,
                    seq=1,
                    line=f"repair attempt {attempt}/{max_attempts or '?'} started",
                    payload_json=_payload_json(
                        {
                            "type": "repair_attempt_started",
                            "agent": agent,
                            "operation": "repairing",
                            "repair_kind": repair_kind,
                            "attempt": attempt,
                            "max_attempts": max_attempts or None,
                            "caused_by_step_id": caused_by_step_id,
                            "status": "running",
                        }
                    ),
                )
            )
        task.current_step = seq
        task.current_agent = agent
        db.commit()
        publish_task_event(task_id, "step_started")
        bind_context(task_id=task_id, step_id=step.id, agent=agent, node_name=display)
        return step.id
    finally:
        db.close()


def current_step_id() -> str | None:
    return get_context().get("step_id")


def _payload_json(payload: dict | None) -> str | None:
    if payload is None:
        return None
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return None


def record_step_log(
    line: str,
    *,
    step_id: str | None = None,
    level: str = "info",
    payload: dict | None = None,
) -> bool:
    target_step_id = step_id or current_step_id()
    return append_agent_log(
        line,
        step_id=target_step_id,
        payload=payload,
        level=level,
        session_factory=SessionLocal,
        publish_task_event=publish_task_event,
        logger=logger,
        sleep=time.sleep,
    )


def _apply_decision(step: AgentStep, decision: dict | None) -> None:
    if not decision:
        return
    step.contract_version = decision.get("contract_version")
    step.contract_hash = decision.get("contract_hash")
    step.prompt_version = decision.get("prompt_version")
    step.model = decision.get("model")
    step.provider = decision.get("provider")
    input_ids = decision.get("input_artifact_ids") or []
    output_ids = decision.get("output_artifact_ids") or []
    step.input_artifact_id = input_ids[0] if input_ids else None
    step.output_artifact_id = output_ids[0] if output_ids else None
    step.input_artifact_ids_json = json_text(input_ids)
    step.output_artifact_ids_json = json_text(output_ids)
    step.adopted_plan = json_text(decision.get("adopted_plan"))
    step.rejected_plans_json = json_text(decision.get("rejected_plans"))
    step.asset_request_count = int(decision.get("asset_request_count") or 0)
    step.qa_result_json = json_text(decision.get("qa_result"))
    step.repair_reason = json_text(decision.get("repair_reason"))
    step.impact_scope_json = json_text(decision.get("impact_scope"))
    step.latency_ms = int(decision.get("latency_ms") or 0)
    step.cost_usd = decision.get("cost_usd")
    step.runtime_consumed = decision.get("runtime_consumed")
    step.decision_json = json_text(decision)


def finish_step(task_id, step_id, logs, tokens=0, repair=None, replan=None, failed=False,
                spec=None, design=None, decision: dict | None = None) -> None:
    db = SessionLocal()
    try:
        if step_id:
            step = (
                db.query(AgentStep)
                .filter(AgentStep.id == step_id)
                .with_for_update()
                .one_or_none()
            )
            if step:
                step.status = StepStatus.FAILED if failed else StepStatus.DONE
                llm_call_count, llm_token_total = (
                    db.query(func.count(LLMCall.id), func.coalesce(func.sum(LLMCall.total_tokens), 0))
                    .filter(LLMCall.step_id == step_id)
                    .one()
                )
                # LLM calls update step/task counters when they are persisted.  At
                # the terminal boundary, reconcile from that durable ledger rather
                # than adding the node's aggregate `_tokens_delta` a second time.
                step.tokens = (
                    int(llm_token_total or 0)
                    if int(llm_call_count or 0) > 0
                    else int(tokens or 0)
                )
                llm_cost, llm_latency = (
                    db.query(func.coalesce(func.sum(LLMCall.cost_usd), 0), func.coalesce(func.sum(LLMCall.latency_ms), 0))
                    .filter(LLMCall.step_id == step_id)
                    .one()
                )
                if decision is None:
                    decision = {}
                if not decision.get("latency_ms"):
                    decision["latency_ms"] = int(llm_latency or 0)
                if decision.get("cost_usd") is None and llm_cost:
                    decision["cost_usd"] = llm_cost
                _apply_decision(step, decision)
                step.finished_at = now_utc()
                # Live log writes may already contain lines from this step.  Consume
                # those occurrences one-for-one so finalization does not duplicate
                # realtime rows while still preserving legitimate repeated lines in
                # the terminal batch.
                existing_line_counts: dict[str, int] = {}
                for log in step.logs or []:
                    existing_line_counts[log.line] = existing_line_counts.get(log.line, 0) + 1
                latest_seq = (
                    db.query(func.max(AgentLog.seq))
                    .filter(AgentLog.step_id == step_id)
                    .scalar()
                )
                next_seq = int(latest_seq) + 1 if latest_seq is not None else 0
                for line in logs or []:
                    text = str(line)
                    existing_count = existing_line_counts.get(text, 0)
                    if existing_count:
                        existing_line_counts[text] = existing_count - 1
                        continue
                    db.add(AgentLog(step_id=step_id, seq=next_seq, line=text))
                    next_seq += 1
        task = db.get(GenerationTask, task_id)
        if task:
            db.flush()
            task.tokens_used = int(
                db.query(func.coalesce(func.sum(AgentStep.tokens), 0))
                .filter(AgentStep.task_id == task_id)
                .scalar()
                or 0
            )
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
        if step_id and step and decision:
            from app.models import AgentTraceEvent

            decision_payload = dict(decision)
            decision_payload["event_type"] = "decision"
            input_ids = decision.get("input_artifact_ids") or []
            output_ids = decision.get("output_artifact_ids") or []
            db.add(
                AgentTraceEvent(
                    task_id=task_id,
                    step_id=step_id,
                    run_id=task_id,
                    seq=int(step.seq or 0),
                    source="pipeline",
                    event_type="decision",
                    agent=step.agent,
                    model=decision.get("model"),
                    provider=decision.get("provider"),
                    contract_version=decision.get("contract_version"),
                    prompt_version=decision.get("prompt_version"),
                    input_artifact_id=input_ids[0] if input_ids else None,
                    output_artifact_id=output_ids[0] if output_ids else None,
                    input_artifact_ids_json=json_text(input_ids),
                    output_artifact_ids_json=json_text(output_ids),
                    adopted_plan=json_text(decision.get("adopted_plan")),
                    rejected_plans_json=json_text(decision.get("rejected_plans")),
                    asset_request_count=int(decision.get("asset_request_count") or 0),
                    qa_result_json=json_text(decision.get("qa_result")),
                    repair_reason=json_text(decision.get("repair_reason")),
                    impact_scope_json=json_text(decision.get("impact_scope")),
                    latency_ms=int(decision.get("latency_ms") or 0),
                    cost_usd=decision.get("cost_usd"),
                    runtime_consumed=decision.get("runtime_consumed"),
                    decision_json=json_text(decision_payload),
                    payload_json=json_text(decision_payload) or "{}",
                    payload_chars=len(json_text(decision_payload) or "{}"),
                )
            )
            for asset in decision.get("asset_trace") or []:
                if not isinstance(asset, dict):
                    continue
                asset_payload = dict(asset)
                asset_payload["event_type"] = "asset_generation"
                asset_id = asset.get("asset_id")
                existing_asset_event = (
                    db.query(AgentTraceEvent)
                    .filter(
                        AgentTraceEvent.task_id == task_id,
                        AgentTraceEvent.asset_id == asset_id,
                        AgentTraceEvent.event_type == "asset_generation",
                    )
                    .order_by(AgentTraceEvent.created_at.desc())
                    .first()
                    if asset_id
                    else None
                )
                if existing_asset_event is not None:
                    existing_asset_event.consumer_refs_json = json_text(asset.get("consumer_refs"))
                    existing_asset_event.coverage_result = json_text(asset.get("coverage_result"))
                    existing_asset_event.runtime_consumed = asset.get("runtime_consumed")
                    existing_asset_event.decision_json = json_text(asset_payload)
                    existing_asset_event.payload_json = json_text(asset_payload) or "{}"
                    existing_asset_event.payload_chars = len(existing_asset_event.payload_json)
                    continue
                db.add(
                    AgentTraceEvent(
                        task_id=task_id,
                        step_id=step_id,
                        run_id=task_id,
                        seq=int(step.seq or 0) * 1000 + len(asset_payload),
                        source="pipeline",
                        event_type="asset_generation",
                        agent=step.agent,
                        model=asset.get("model") or decision.get("model"),
                        provider=asset.get("provider") or decision.get("provider"),
                        contract_version=decision.get("contract_version"),
                        prompt_version=decision.get("prompt_version"),
                        output_artifact_id=asset.get("output_artifact_id"),
                        output_artifact_ids_json=json_text([asset.get("output_artifact_id")]),
                        asset_request_count=1,
                        latency_ms=int(asset.get("latency_ms") or decision.get("latency_ms") or 0),
                        runtime_consumed=asset.get("runtime_consumed"),
                        asset_id=asset.get("asset_id"),
                        prompt_hash=asset.get("prompt_hash"),
                        requested_states_json=json_text(asset.get("requested_states")),
                        returned_dimensions=json_text(asset.get("returned_dimensions")),
                        postprocess_checks_json=json_text(asset.get("postprocess_checks")),
                        frame_count=asset.get("frame_count"),
                        consumer_refs_json=json_text(asset.get("consumer_refs")),
                        coverage_result=json_text(asset.get("coverage_result")),
                        decision_json=json_text(asset_payload),
                        payload_json=json_text(asset_payload) or "{}",
                        payload_chars=len(json_text(asset_payload) or "{}"),
                    )
                )
        db.commit()
        publish_task_event(task_id, "step_finished")
    finally:
        db.close()


def logged(node_name: str):
    """把节点包成：begin(running) → 跑 → finish(done/failed)。"""
    agent, display = STEP_META.get(node_name, (node_name, node_name))

    def deco(fn):
        def wrapper(state: dict):
            task_id = state.get("task_id")
            sid = begin_step(task_id, agent, display)
            started = time.perf_counter()
            if not state.get("use_real"):
                time.sleep(0.45)  # mock 节点太快，停顿让 running 态可见
            with opik_integration.generation_span(
                node_name=node_name,
                task_id=task_id,
                step_id=sid,
                agent=agent,
                display_name=display,
            ), agent_span(
                f"agent.{node_name}",
                {"agent": agent, "task_id": task_id, "step_id": sid},
            ) as span:
                try:
                    result = fn(state)
                except Exception as exc:  # noqa: BLE001
                    span.record_exception(exc)
                    opik_integration.update_generation_span(
                        output={"status": "failed", "error": str(exc)[:500]},
                        metadata={"failed": True},
                        tags=["status:failed"],
                    )
                    decision = build_decision(
                        state,
                        {"error_message": str(exc), "status": "failed"},
                        agent=agent,
                        display_name=display,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                    finish_step(task_id, sid, [f"error: {exc}"], failed=True, decision=decision)
                    bind_context(step_id=None, agent=None, node_name=None)
                    raise
                tokens = int(result.get("_tokens_delta", 0) or 0)
                failed = result.get("status") == "failed" or bool(result.get("_step_failed"))
                span.set_attribute("tokens", tokens)
                span.set_attribute("failed", failed)
                span.set_attribute("repair_attempts", result.get("repair_attempts", state.get("repair_attempts", 0)))
                span.set_attribute("replan_attempts", result.get("replan_attempts", state.get("replan_attempts", 0)))
                # 面板上的修复次数 = 构建修复 + 玩法修复两条回环之和；玩法修复节点
                # 只返回 gameplay_repair_attempts，不合并的话 task.repair_attempts
                # 永远停在 0（2026-07-13 实测），用户看不到回环在推进。
                rep = result.get("repair_attempts")
                gp = result.get("gameplay_repair_attempts")
                repair_total = None
                if rep is not None or gp is not None:
                    repair_total = int(rep if rep is not None else state.get("repair_attempts") or 0) + int(
                        gp if gp is not None else state.get("gameplay_repair_attempts") or 0
                    )
                stage_status = "failed" if failed else "completed"
                decision = build_decision(
                    state,
                    result,
                    agent=agent,
                    display_name=display,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                opik_integration.update_generation_span(
                    output={
                        "status": stage_status,
                        "tokens": tokens,
                        "repair_attempts": repair_total,
                        "replan_attempts": result.get("replan_attempts"),
                        "decision_chain": decision,
                    },
                    metadata={
                        "failed": failed,
                        "tokens": tokens,
                        "repair_attempts": repair_total,
                        "replan_attempts": result.get("replan_attempts"),
                        "contract_version": decision.get("contract_version"),
                        "prompt_version": decision.get("prompt_version"),
                        "model": decision.get("model"),
                        "provider": decision.get("provider"),
                        "input_artifact_ids": decision.get("input_artifact_ids"),
                        "output_artifact_ids": decision.get("output_artifact_ids"),
                        "adopted_plan": decision.get("adopted_plan"),
                        "rejected_plans": decision.get("rejected_plans"),
                        "asset_request_count": decision.get("asset_request_count"),
                        "qa_result": decision.get("qa_result"),
                        "repair_reason": decision.get("repair_reason"),
                        "impact_scope": decision.get("impact_scope"),
                        "latency_ms": decision.get("latency_ms"),
                        "cost_usd": decision.get("cost_usd"),
                        "runtime_consumed": decision.get("runtime_consumed"),
                    },
                    tags=[f"status:{stage_status}"],
                )
                finish_step(
                    task_id, sid, result.get("_logs"), tokens,
                    repair=repair_total, replan=result.get("replan_attempts"),
                    failed=failed,
                    spec=result.get("game_spec"), design=result.get("game_design"),
                    decision=decision,
                )
                bind_context(step_id=None, agent=None, node_name=None)
                return result

        return wrapper

    return deco
