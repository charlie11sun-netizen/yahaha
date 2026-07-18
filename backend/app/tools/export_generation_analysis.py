"""Export one generation's complete stored audit trail and cache analysis as JSON."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, AgentTraceEvent, GenerationTask, LLMCall


def _value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _json_or_raw(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _cache_rollup(calls: list[dict[str, Any]]) -> dict[str, Any]:
    prompt_tokens = sum(int(call["prompt_tokens"] or 0) for call in calls)
    completion_tokens = sum(int(call["completion_tokens"] or 0) for call in calls)
    cached_tokens = min(
        prompt_tokens,
        sum(int(call["cached_tokens"] or 0) for call in calls),
    )
    cache_write_tokens = sum(int(call["cache_write_tokens"] or 0) for call in calls)
    uncached_tokens = max(0, prompt_tokens - cached_tokens)
    count = len(calls)
    return {
        "call_count": count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "uncached_tokens": uncached_tokens,
        "weighted_cache_hit_rate": round(cached_tokens / prompt_tokens, 6)
        if prompt_tokens
        else None,
        "cache_write_rate": round(cache_write_tokens / uncached_tokens, 6)
        if uncached_tokens
        else None,
        "cache_hit_call_count": sum(
            1 for call in calls if int(call["cached_tokens"] or 0) > 0
        ),
        "cache_read_reported_count": sum(
            1 for call in calls if call["cache_read_reported"]
        ),
        "cache_write_reported_count": sum(
            1 for call in calls if call["cache_write_reported"]
        ),
        "cache_read_reporting_coverage": round(
            sum(1 for call in calls if call["cache_read_reported"]) / count, 6
        )
        if count
        else None,
        "cache_write_reporting_coverage": round(
            sum(1 for call in calls if call["cache_write_reported"]) / count, 6
        )
        if count
        else None,
        "latency_ms_total": sum(int(call["latency_ms"] or 0) for call in calls),
        "cost_usd": round(sum(float(call["cost_usd"] or 0) for call in calls), 6),
        "retry_count": sum(1 for call in calls if call["retried"]),
    }


def _group_rollups(
    calls: list[dict[str, Any]], key: str
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in calls:
        label = call.get(key)
        groups["<missing>" if label is None else str(label)].append(call)
    return [
        {key: label, **_cache_rollup(rows)}
        for label, rows in sorted(groups.items(), key=lambda item: item[0])
    ]


def _call_out(call: LLMCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "task_id": call.task_id,
        "step_id": call.step_id,
        "run_id": call.run_id,
        "agent": call.agent,
        "workflow_name": call.workflow_name,
        "provider_response_id": call.provider_response_id,
        "previous_response_id": call.previous_response_id,
        "request_index": call.request_index,
        "status": call.status,
        "error_code": call.error_code,
        "model": call.model,
        "provider": call.provider,
        "provider_route": call.provider_route,
        "prompt_version": call.prompt_version,
        "contract_hash": call.contract_hash,
        "contract_revision": call.contract_revision,
        "prompt_cache_key_hash": call.prompt_cache_key_hash,
        "prompt_cache_namespace": call.prompt_cache_namespace,
        "prompt_cache_mode": call.prompt_cache_mode,
        "prompt_cache_ttl": call.prompt_cache_ttl,
        "cache_prefix_hash": call.cache_prefix_hash,
        "toolset_hash": call.toolset_hash,
        "cache_bypass_reason": call.cache_bypass_reason,
        "prompt_tokens": int(call.prompt_tokens or 0),
        "completion_tokens": int(call.completion_tokens or 0),
        "total_tokens": int(call.total_tokens or 0),
        "cached_tokens": int(call.cached_tokens or 0),
        "cache_write_tokens": int(call.cache_write_tokens or 0),
        "cache_read_reported": bool(call.cache_read_reported),
        "cache_write_reported": bool(call.cache_write_reported),
        "latency_ms": int(call.latency_ms or 0),
        "retried": bool(call.retried),
        "cost_usd": _value(call.cost_usd),
        "created_at": _value(call.created_at),
    }


def _step_out(step: AgentStep, logs: list[AgentLog]) -> dict[str, Any]:
    return {
        "id": step.id,
        "seq": step.seq,
        "agent": step.agent,
        "name": step.name,
        "status": step.status,
        "attempt": step.attempt,
        "caused_by_step_id": step.caused_by_step_id,
        "tokens": int(step.tokens or 0),
        "contract_version": step.contract_version,
        "contract_hash": step.contract_hash,
        "prompt_version": step.prompt_version,
        "model": step.model,
        "provider": step.provider,
        "input_artifact_ids": _json_or_raw(step.input_artifact_ids_json),
        "output_artifact_ids": _json_or_raw(step.output_artifact_ids_json),
        "adopted_plan": _json_or_raw(step.adopted_plan),
        "rejected_plans": _json_or_raw(step.rejected_plans_json),
        "asset_request_count": int(step.asset_request_count or 0),
        "qa_result": _json_or_raw(step.qa_result_json),
        "repair_reason": _json_or_raw(step.repair_reason),
        "impact_scope": _json_or_raw(step.impact_scope_json),
        "latency_ms": int(step.latency_ms or 0),
        "cost_usd": _value(step.cost_usd),
        "runtime_consumed": step.runtime_consumed,
        "decision": _json_or_raw(step.decision_json),
        "started_at": _value(step.started_at),
        "finished_at": _value(step.finished_at),
        "created_at": _value(step.created_at),
        "logs": [
            {
                "id": log.id,
                "seq": log.seq,
                "level": log.level,
                "line": log.line,
                "payload": _json_or_raw(log.payload_json),
                "created_at": _value(log.created_at),
            }
            for log in logs
        ],
    }


def _trace_event_out(event: AgentTraceEvent) -> dict[str, Any]:
    payload = _json_or_raw(event.payload_json)
    return {
        "id": event.id,
        "task_id": event.task_id,
        "step_id": event.step_id,
        "run_id": event.run_id,
        "seq": event.seq,
        "source": event.source,
        "event_type": event.event_type,
        "agent": event.agent,
        "model": event.model,
        "provider": event.provider,
        "contract_version": event.contract_version,
        "prompt_version": event.prompt_version,
        "input_artifact_id": event.input_artifact_id,
        "output_artifact_id": event.output_artifact_id,
        "input_artifact_ids": _json_or_raw(event.input_artifact_ids_json),
        "output_artifact_ids": _json_or_raw(event.output_artifact_ids_json),
        "adopted_plan": _json_or_raw(event.adopted_plan),
        "rejected_plans": _json_or_raw(event.rejected_plans_json),
        "asset_request_count": int(event.asset_request_count or 0),
        "qa_result": _json_or_raw(event.qa_result_json),
        "repair_reason": _json_or_raw(event.repair_reason),
        "impact_scope": _json_or_raw(event.impact_scope_json),
        "latency_ms": int(event.latency_ms or 0),
        "cost_usd": _value(event.cost_usd),
        "runtime_consumed": event.runtime_consumed,
        "asset_id": event.asset_id,
        "prompt_hash": event.prompt_hash,
        "requested_states": _json_or_raw(event.requested_states_json),
        "returned_dimensions": _json_or_raw(event.returned_dimensions),
        "postprocess_checks": _json_or_raw(event.postprocess_checks_json),
        "frame_count": event.frame_count,
        "consumer_refs": _json_or_raw(event.consumer_refs_json),
        "coverage_result": _json_or_raw(event.coverage_result),
        "decision": _json_or_raw(event.decision_json),
        "payload_chars": int(event.payload_chars or 0),
        "payload_truncated": bool(
            isinstance(payload, dict) and payload.get("_trace_payload_truncated")
        ),
        "payload": payload,
        "created_at": _value(event.created_at),
    }


def build_analysis_bundle(
    db,
    task_id: str,
    *,
    include_trace_events: bool = True,
) -> dict[str, Any]:
    task = db.get(GenerationTask, task_id)
    if task is None:
        raise LookupError(f"generation task not found: {task_id}")

    steps = (
        db.query(AgentStep)
        .filter(AgentStep.task_id == task_id)
        .order_by(AgentStep.seq, AgentStep.created_at)
        .all()
    )
    step_ids = [step.id for step in steps]
    logs = (
        db.query(AgentLog)
        .filter(AgentLog.step_id.in_(step_ids))
        .order_by(AgentLog.step_id, AgentLog.seq)
        .all()
        if step_ids
        else []
    )
    logs_by_step: dict[str, list[AgentLog]] = defaultdict(list)
    for log in logs:
        logs_by_step[log.step_id].append(log)

    call_rows = (
        db.query(LLMCall)
        .filter(LLMCall.task_id == task_id)
        .order_by(LLMCall.created_at, LLMCall.id)
        .all()
    )
    calls = [_call_out(call) for call in call_rows]
    events = []
    if include_trace_events:
        events = [
            _trace_event_out(event)
            for event in (
                db.query(AgentTraceEvent)
                .filter(AgentTraceEvent.task_id == task_id)
                .order_by(
                    AgentTraceEvent.created_at,
                    AgentTraceEvent.run_id,
                    AgentTraceEvent.seq,
                )
                .all()
            )
        ]

    cache_analysis = {
        "overall": _cache_rollup(calls),
        "by_workflow": _group_rollups(calls, "workflow_name"),
        "by_agent": _group_rollups(calls, "agent"),
        "by_request_index": _group_rollups(calls, "request_index"),
        "by_cache_key_hash": _group_rollups(calls, "prompt_cache_key_hash"),
        "by_toolset_hash": _group_rollups(calls, "toolset_hash"),
        "missing_dimensions": {
            field: sum(1 for call in calls if call.get(field) is None)
            for field in (
                "run_id",
                "agent",
                "workflow_name",
                "request_index",
                "provider_route",
                "prompt_cache_key_hash",
                "prompt_cache_namespace",
                "prompt_cache_mode",
                "toolset_hash",
                "prompt_version",
                "contract_hash",
                "contract_revision",
            )
        },
        "cache_bypass_reasons": {
            reason: sum(1 for call in calls if call.get("cache_bypass_reason") == reason)
            for reason in sorted(
                {
                    str(call["cache_bypass_reason"])
                    for call in calls
                    if call.get("cache_bypass_reason")
                }
            )
        },
    }
    truncated_count = sum(1 for event in events if event["payload_truncated"])
    return {
        "schema_version": "gameweave.generation-analysis/1.0",
        "exported_at": datetime.now().astimezone().isoformat(),
        "task": {
            "id": task.id,
            "user_id": task.user_id,
            "task_kind": task.task_kind,
            "idea": task.idea,
            "feedback_text": task.feedback_text,
            "feedback_brief": task.feedback_brief,
            "dimension": task.dimension,
            "status": task.status,
            "dispatch_generation": task.dispatch_generation,
            "current_step": task.current_step,
            "current_agent": task.current_agent,
            "result_game_id": task.result_game_id,
            "version_id": task.version_id,
            "base_game_id": task.base_game_id,
            "base_version": task.base_version,
            "tokens_used": int(task.tokens_used or 0),
            "cost_usd": _value(task.cost_usd),
            "error": task.error,
            "error_code": task.error_code,
            "failed_stage": task.failed_stage,
            "repair_attempts": task.repair_attempts,
            "replan_attempts": task.replan_attempts,
            "spec": _json_or_raw(task.spec_json),
            "design": _json_or_raw(task.design_json),
            "design_contract": _json_or_raw(task.contract_json),
            "contract_hash": task.contract_hash,
            "contract_revision": task.contract_revision,
            "opik_trace_id": task.opik_trace_id,
            "created_at": _value(task.created_at),
            "started_at": _value(task.started_at),
            "finished_at": _value(task.finished_at),
        },
        "assets": [
            {
                "id": asset.id,
                "filename": asset.filename,
                "kind": asset.kind,
                "content_type": asset.content_type,
                "size_bytes": int(asset.size_bytes or 0),
                "scan_status": asset.scan_status,
                "created_at": _value(asset.created_at),
            }
            for asset in task.assets
        ],
        "steps": [_step_out(step, logs_by_step[step.id]) for step in steps],
        "llm_calls": calls,
        "cache_analysis": cache_analysis,
        "trace_events_included": include_trace_events,
        "trace_event_count": len(events),
        "truncated_trace_event_count": truncated_count,
        "trace_completeness": (
            "stored_payloads_include bounded previews for truncated events"
            if truncated_count
            else "all stored trace payloads are included"
        )
        if include_trace_events
        else "trace events were excluded by request",
        "trace_events": events,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", help="generation_tasks.id to export")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    parser.add_argument(
        "--without-trace-events",
        action="store_true",
        help="omit the potentially large detailed trace event array",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        try:
            bundle = build_analysis_bundle(
                db,
                args.task_id,
                include_trace_events=not args.without_trace_events,
            )
        except LookupError as exc:
            raise SystemExit(str(exc)) from exc
        print(
            json.dumps(
                bundle,
                ensure_ascii=False,
                indent=2 if args.pretty else None,
                separators=None if args.pretty else (",", ":"),
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
