"""Opt-in, lossless trace capture for code-agent model and tool activity.

Detailed traces intentionally live outside ``agent_logs``.  A code-agent run can
carry megabytes of prompt history and generated source; putting that payload on
the normal task DTO would make every poll/SSE snapshot equally large.
"""
from __future__ import annotations

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

logger = logging.getLogger(__name__)

_CODE_AGENT_CONTEXTS = {
    "GameCodeAgent",
    "GameCodeAgentRepair",
    "CodeRevisionAgent",
    "CodeRevisionRepairAgent",
    "GameplayRepairAgent",
}


def _jsonable(value: Any) -> Any:
    """Convert SDK/Pydantic/dataclass values without intentionally truncating them."""
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
    ) -> None:
        self.task_id = task_id
        self.step_id = step_id
        self.source = source
        self.agent = agent
        self.model = model
        self.run_id = str(uuid.uuid4())
        self._seq = 0
        self._lock = threading.Lock()

    def record(
        self,
        event_type: str,
        payload: Any,
        *,
        agent: str | None = None,
        model: str | None = None,
    ) -> bool:
        try:
            normalized = _jsonable(payload)
            payload_json = json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
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
            recorder.record(
                "agent_start",
                {"agent": getattr(agent, "name", type(agent).__name__)},
                agent=getattr(agent, "name", None),
            )

        async def on_agent_end(self, context, agent, output) -> None:
            recorder.record(
                "agent_end",
                {"output": output},
                agent=getattr(agent, "name", None),
            )

        async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
            recorder.record(
                "llm_input",
                {
                    "system_prompt": system_prompt,
                    "input_items": input_items,
                    "usage_before": getattr(context, "usage", None),
                },
                agent=getattr(agent, "name", None),
            )

        async def on_llm_end(self, context, agent, response) -> None:
            recorder.record(
                "llm_output",
                {
                    "response": response,
                    "usage_after": getattr(context, "usage", None),
                },
                agent=getattr(agent, "name", None),
                model=getattr(response, "model", None),
            )

        async def on_tool_start(self, context, agent, tool) -> None:
            recorder.record(
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
            recorder.record(
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
            recorder.record(
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
) -> dict[str, Any]:
    return {
        "instructions": instructions,
        "task_input": task_input,
        "tools": [_tool_definition(tool) for tool in tools],
        "workflow_name": workflow_name,
        "turns_limit": turns_limit,
        "parallel_tool_calls": False,
        "prompt_cache_key": prompt_cache_key,
    }


__all__ = [
    "TraceRecorder",
    "build_run_hooks",
    "create_recorder",
    "exception_payload",
    "run_start_payload",
]
