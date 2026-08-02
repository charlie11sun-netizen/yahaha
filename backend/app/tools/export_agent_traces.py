"""Export opt-in code-agent traces as JSON Lines for offline analysis."""
from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.models import AgentTraceEvent


def _json_or_none(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", help="generation_tasks.id to export")
    parser.add_argument("--step-id", help="optionally restrict to one agent step")
    parser.add_argument("--run-id", help="optionally restrict to one trace run")
    parser.add_argument("--pretty", action="store_true", help="pretty-print one JSON array")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        query = db.query(AgentTraceEvent).filter(AgentTraceEvent.task_id == args.task_id)
        if args.step_id:
            query = query.filter(AgentTraceEvent.step_id == args.step_id)
        if args.run_id:
            query = query.filter(AgentTraceEvent.run_id == args.run_id)
        rows = query.order_by(
            AgentTraceEvent.created_at,
            AgentTraceEvent.run_id,
            AgentTraceEvent.seq,
        ).all()
        events = [
            {
                "id": row.id,
                "task_id": row.task_id,
                "step_id": row.step_id,
                "run_id": row.run_id,
                "seq": row.seq,
                "source": row.source,
                "event_type": row.event_type,
                "agent": row.agent,
                "model": row.model,
                "provider": row.provider,
                "contract_version": row.contract_version,
                "prompt_version": row.prompt_version,
                "input_artifact_id": row.input_artifact_id,
                "output_artifact_id": row.output_artifact_id,
                "input_artifact_ids": _json_or_none(row.input_artifact_ids_json),
                "output_artifact_ids": _json_or_none(row.output_artifact_ids_json),
                "adopted_plan": _json_or_none(row.adopted_plan),
                "rejected_plans": _json_or_none(row.rejected_plans_json),
                "asset_request_count": row.asset_request_count,
                "qa_result": _json_or_none(row.qa_result_json),
                "repair_reason": _json_or_none(row.repair_reason),
                "impact_scope": _json_or_none(row.impact_scope_json),
                "latency_ms": row.latency_ms,
                "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
                "runtime_consumed": row.runtime_consumed,
                "asset_id": row.asset_id,
                "prompt_hash": row.prompt_hash,
                "requested_states": _json_or_none(row.requested_states_json),
                "returned_dimensions": _json_or_none(row.returned_dimensions),
                "postprocess_checks": _json_or_none(row.postprocess_checks_json),
                "frame_count": row.frame_count,
                "consumer_refs": _json_or_none(row.consumer_refs_json),
                "coverage_result": _json_or_none(row.coverage_result),
                "payload_chars": row.payload_chars,
                "created_at": row.created_at.isoformat(),
                "payload": json.loads(row.payload_json),
            }
            for row in rows
        ]
        if args.pretty:
            print(json.dumps(events, ensure_ascii=False, indent=2))
        else:
            for event in events:
                print(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
