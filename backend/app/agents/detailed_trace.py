"""Opt-in, bounded trace capture for code-agent model and tool activity.

Detailed traces intentionally live outside ``agent_logs``.  A code-agent run can
carry megabytes of prompt history and generated source; putting that payload on
the normal task DTO would make every poll/SSE snapshot equally large.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
import traceback
import uuid
from typing import Any, get_origin

from app.core.config import settings
from app.core.telemetry import get_context
from app.db.session import SessionLocal
from app.models import AgentTraceEvent
from app.agents.decision_trace import AGENT_STEP_CONTRACT_VERSION, json_text

logger = logging.getLogger(__name__)

_CODE_AGENT_CONTEXTS = {
    "GameCodeAgent",
    "GameCodeAgentRepair",
    "CodeRevisionAgent",
    "CodeRevisionRepairAgent",
    "GameplayRepairAgent",
}


def _first(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and value:
        return str(value[0])
    return str(value) if value else None


def _jsonable(value: Any) -> Any:
    """Convert SDK/Pydantic/dataclass values before the serialized size cap."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json"))
        except TypeError:
            return _jsonable(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable(to_dict())
        except Exception:  # noqa: BLE001
            pass
    if hasattr(value, "__dict__"):
        try:
            return {
                str(key): _jsonable(item)
                for key, item in vars(value).items()
                if not str(key).startswith("_")
            }
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def _serialize_payload(payload: Any) -> tuple[str, int, bool]:
    """Serialize one event and replace oversized JSON with a bounded preview."""
    payload_json = json.dumps(
        _jsonable(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    original_chars = len(payload_json)
    max_chars = max(256, int(settings.CODE_AGENT_TRACE_MAX_PAYLOAD_CHARS))
    if original_chars <= max_chars:
        return payload_json, original_chars, False

    envelope = {
        "_trace_payload_truncated": True,
        "original_chars": original_chars,
        "stored_limit_chars": max_chars,
        "json_preview": "",
    }
    bounded_json = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    preview_chars = max(0, max_chars - len(bounded_json))
    envelope["json_preview"] = payload_json[:preview_chars]
    bounded_json = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(bounded_json) > max_chars:
        overflow = len(bounded_json) - max_chars
        envelope["json_preview"] = envelope["json_preview"][:-overflow]
        bounded_json = json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return bounded_json, original_chars, True


def exception_payload(exc: BaseException) -> dict[str, Any]:
    """Preserve the complete local exception details for failed-run diagnosis."""
    return {
        "exception_type": type(exc).__name__,
        "exception_module": type(exc).__module__,
        "message": str(exc),
        "status_code": getattr(exc, "status_code", None),
        "code": getattr(exc, "code", None),
        "request_id": getattr(exc, "request_id", None),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def _tool_definition(tool: Any) -> dict[str, Any]:
    return {
        "type": getattr(tool, "type", type(tool).__name__),
        "name": getattr(tool, "name", None),
        "description": getattr(tool, "description", None),
        "params_json_schema": _jsonable(getattr(tool, "params_json_schema", None)),
    }


class TraceRecorder:
    """Fail-open writer for one detailed trace run."""

    def __init__(
        self,
        *,
        task_id: str,
        step_id: str,
        source: str,
        agent: str,
        model: str | None,
        provider: str | None = None,
        contract_version: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        self.task_id = task_id
        self.step_id = step_id
        self.source = source
        self.agent = agent
        self.model = model
        self.provider = provider or "openai"
        self.contract_version = contract_version or AGENT_STEP_CONTRACT_VERSION
        self.prompt_version = prompt_version or "prompt/v1"
        self.run_id = str(uuid.uuid4())
        self._seq = 0
        self._lock = threading.Lock()
        self._llm_input_items_seen = 0
        self._llm_system_prompt: Any = None
        self._has_llm_system_prompt = False

    def record(
        self,
        event_type: str,
        payload: Any,
        *,
        agent: str | None = None,
        model: str | None = None,
        decision: dict[str, Any] | None = None,
        asset: dict[str, Any] | None = None,
    ) -> bool:
        try:
            payload_value = payload
            if decision is not None or asset is not None:
                payload_value = dict(payload) if isinstance(payload, dict) else {"value": payload}
                if decision is not None:
                    payload_value["decision_chain"] = decision
                if asset is not None:
                    payload_value["asset_trace"] = asset
            payload_json, original_chars, truncated = _serialize_payload(payload_value)
            warn_chars = max(
                1,
                min(
                    int(settings.CODE_AGENT_TRACE_PAYLOAD_WARN_CHARS),
                    int(settings.CODE_AGENT_TRACE_MAX_PAYLOAD_CHARS),
                ),
            )
            if original_chars >= warn_chars:
                logger.warning(
                    "code agent detailed trace payload is large "
                    "event_type=%s chars=%s max_chars=%s truncated=%s",
                    event_type,
                    original_chars,
                    settings.CODE_AGENT_TRACE_MAX_PAYLOAD_CHARS,
                    truncated,
                )
            with self._lock:
                self._seq += 1
                seq = self._seq
            db = SessionLocal()
            try:
                db.add(
                    AgentTraceEvent(
                        task_id=self.task_id,
                        step_id=self.step_id,
                        run_id=self.run_id,
                        seq=seq,
                        source=self.source,
                        event_type=event_type,
                        agent=agent or self.agent,
                        model=model or self.model,
                        provider=(decision or {}).get("provider") if decision else self.provider,
                        contract_version=(decision or {}).get("contract_version") if decision else self.contract_version,
                        prompt_version=(decision or {}).get("prompt_version") if decision else self.prompt_version,
                        input_artifact_id=_first((decision or {}).get("input_artifact_ids")),
                        output_artifact_id=(asset or {}).get("output_artifact_id") or _first((decision or {}).get("output_artifact_ids")),
                        input_artifact_ids_json=json_text((decision or {}).get("input_artifact_ids")),
                        output_artifact_ids_json=json_text((decision or {}).get("output_artifact_ids")),
                        adopted_plan=json_text((decision or {}).get("adopted_plan")),
                        rejected_plans_json=json_text((decision or {}).get("rejected_plans")),
                        asset_request_count=int((decision or {}).get("asset_request_count") or 0),
                        qa_result_json=json_text((decision or {}).get("qa_result")),
                        repair_reason=json_text((decision or {}).get("repair_reason")),
                        impact_scope_json=json_text((decision or {}).get("impact_scope")),
                        latency_ms=int((decision or {}).get("latency_ms") or 0),
                        cost_usd=(decision or {}).get("cost_usd"),
                        runtime_consumed=(decision or {}).get("runtime_consumed"),
                        asset_id=(asset or {}).get("asset_id"),
                        prompt_hash=(asset or {}).get("prompt_hash"),
                        requested_states_json=json_text((asset or {}).get("requested_states")),
                        returned_dimensions=json_text((asset or {}).get("returned_dimensions")),
                        postprocess_checks_json=json_text((asset or {}).get("postprocess_checks")),
                        frame_count=(asset or {}).get("frame_count"),
                        consumer_refs_json=json_text((asset or {}).get("consumer_refs")),
                        coverage_result=json_text((asset or {}).get("coverage_result")),
                        decision_json=json_text(decision or asset),
                        payload_json=payload_json,
                        payload_chars=len(payload_json),
                    )
                )
                db.commit()
                return True
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("code agent detailed trace write failed")
                return False
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            logger.exception("code agent detailed trace serialization failed")
            return False

    async def record_async(
        self,
        event_type: str,
        payload: Any,
        *,
        agent: str | None = None,
        decision: dict[str, Any] | None = None,
        asset: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> bool:
        """Keep serialization and synchronous SQLAlchemy I/O off the event loop."""
        kwargs: dict[str, Any] = {}
        if agent is not None:
            kwargs["agent"] = agent
        if model is not None:
            kwargs["model"] = model
        if decision is not None:
            kwargs["decision"] = decision
        if asset is not None:
            kwargs["asset"] = asset
        return await asyncio.to_thread(self.record, event_type, payload, **kwargs)

    def record_llm_input(
        self,
        *,
        system_prompt: Any,
        input_items: Any,
        usage_before: Any,
        agent: str | None = None,
    ) -> bool:
        """Persist the first history snapshot and only newly appended items later."""
        with self._lock:
            if isinstance(input_items, (list, tuple)):
                total_items = len(input_items)
                if self._llm_input_items_seen and total_items >= self._llm_input_items_seen:
                    history_mode = "delta"
                    from_index = self._llm_input_items_seen
                else:
                    history_mode = "snapshot"
                    from_index = 0
                stored_items = list(input_items[from_index:])
                self._llm_input_items_seen = total_items
            else:
                history_mode = "snapshot"
                from_index = 0
                total_items = None
                stored_items = input_items

            system_prompt_reused = (
                self._has_llm_system_prompt and system_prompt == self._llm_system_prompt
            )
            if not system_prompt_reused:
                self._llm_system_prompt = system_prompt
                self._has_llm_system_prompt = True

        return self.record(
            "llm_input",
            {
                "system_prompt": None if system_prompt_reused else system_prompt,
                "system_prompt_reused": system_prompt_reused,
                "input_items": stored_items,
                "input_items_from_index": from_index,
                "input_items_total": total_items,
                "history_mode": history_mode,
                "usage_before": usage_before,
            },
            agent=agent,
        )

    async def record_llm_input_async(
        self,
        *,
        system_prompt: Any,
        input_items: Any,
        usage_before: Any,
        agent: str | None = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.record_llm_input,
            system_prompt=system_prompt,
            input_items=input_items,
            usage_before=usage_before,
            agent=agent,
        )


def create_recorder(
    *,
    source: str,
    agent: str,
    model: str | None,
    require_code_context: bool = True,
) -> TraceRecorder | None:
    if not settings.CODE_AGENT_DETAILED_LOGGING_ENABLED:
        return None
    context = get_context()
    task_id = context.get("task_id")
    step_id = context.get("step_id")
    context_agent = context.get("agent")
    if not task_id or not step_id:
        return None
    if require_code_context and context_agent not in _CODE_AGENT_CONTEXTS:
        return None
    return TraceRecorder(
        task_id=task_id,
        step_id=step_id,
        source=source,
        agent=agent or context_agent or "GameCodeAgent",
        model=model,
    )


def build_run_hooks(recorder: TraceRecorder | None):
    """Build public Agents SDK lifecycle hooks lazily; the SDK remains optional."""
    if recorder is None:
        return None
    from agents import RunHooks

    hooks_base = get_origin(RunHooks) or RunHooks

    class DetailedTraceHooks(hooks_base):
        async def on_agent_start(self, context, agent) -> None:
            await recorder.record_async(
                "agent_start",
                {"agent": getattr(agent, "name", type(agent).__name__)},
                agent=getattr(agent, "name", None),
            )

        async def on_agent_end(self, context, agent, output) -> None:
            await recorder.record_async(
                "agent_end",
                {"output": output},
                agent=getattr(agent, "name", None),
            )

        async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
            await recorder.record_llm_input_async(
                system_prompt=system_prompt,
                input_items=input_items,
                usage_before=getattr(context, "usage", None),
                agent=getattr(agent, "name", None),
            )

        async def on_llm_end(self, context, agent, response) -> None:
            await recorder.record_async(
                "llm_output",
                {
                    "response": response,
                    "usage_after": getattr(context, "usage", None),
                },
                agent=getattr(agent, "name", None),
                model=getattr(response, "model", None),
            )

        async def on_tool_start(self, context, agent, tool) -> None:
            await recorder.record_async(
                "tool_input",
                {
                    "tool": _tool_definition(tool),
                    "tool_call_id": getattr(context, "tool_call_id", None),
                    "tool_name": getattr(context, "tool_name", None),
                    "tool_arguments": getattr(context, "tool_arguments", None),
                },
                agent=getattr(agent, "name", None),
            )

        async def on_tool_end(self, context, agent, tool, result) -> None:
            await recorder.record_async(
                "tool_output",
                {
                    "tool": _tool_definition(tool),
                    "tool_call_id": getattr(context, "tool_call_id", None),
                    "tool_name": getattr(context, "tool_name", None),
                    "tool_arguments": getattr(context, "tool_arguments", None),
                    "result": result,
                },
                agent=getattr(agent, "name", None),
            )

        async def on_handoff(self, context, from_agent, to_agent) -> None:
            await recorder.record_async(
                "handoff",
                {
                    "from_agent": getattr(from_agent, "name", type(from_agent).__name__),
                    "to_agent": getattr(to_agent, "name", type(to_agent).__name__),
                },
            )

    return DetailedTraceHooks()


def run_start_payload(
    *,
    instructions: str,
    task_input: str,
    tools: list[Any],
    workflow_name: str,
    turns_limit: int,
    prompt_cache_key: str | None,
    chained_from_response_id: str | None = None,
    context_items: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "instructions": instructions,
        "task_input": task_input,
        "tools": [_tool_definition(tool) for tool in tools],
        "workflow_name": workflow_name,
        "turns_limit": turns_limit,
        "parallel_tool_calls": False,
        "prompt_cache_key": prompt_cache_key,
        # Client-side chain provenance: which response the replayed context
        # items came from, and the items themselves for verbatim verification.
        "chained_from_response_id": chained_from_response_id,
        "context_items": _jsonable(context_items) if context_items else None,
    }


__all__ = [
    "TraceRecorder",
    "build_run_hooks",
    "create_recorder",
    "exception_payload",
    "run_start_payload",
]
