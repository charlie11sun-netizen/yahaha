"""Runner and prompt assembly for repair and author code agents."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Literal

from app.agents import detailed_trace, llm, llm_cache, opik_integration, tracing
from app.agents.agent_tools import AgentToolPolicy, _make_tools
from app.agents.repair_session import RepairOutcome, RepairSession, _bundle_context_text, available_skills
from app.core.config import settings

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 12.0
_STREAM_PROGRESS_INTERVAL_SECONDS = 1.0
_STREAM_TRACE_INTERVAL_SECONDS = 5.0
_TASK_CANCEL_POLL_SECONDS = 0.5
_STREAM_TERMINAL_FAILURE_EVENTS = {
    "error",
    "response.error",
    "response.failed",
    "response.incomplete",
}
_STREAM_PERMANENT_ERROR_CODES = {
    "content_policy_violation",
    "context_length_exceeded",
    "insufficient_quota",
    "invalid_prompt",
    "invalid_request_error",
    "permission_denied",
    "unsupported_value",
}
_STREAM_PERMANENT_INCOMPLETE_REASONS = {"content_filter", "max_output_tokens"}
_STREAM_RETRYABLE_EXCEPTION_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConflictError",
    "InternalServerError",
    "RateLimitError",
    "TimeoutError",
}


class _AgentDeadlineExceeded(RuntimeError):
    """Raised only at a streamed event boundary when an execution deadline expires."""


# ── 拆分兼容面(2026-07-26)──────────────────────────────────────────────
# 指令常量、首轮输入装配与响应/用量记账已拆入 author_agent_io;这里显式回导,
# 既有调用方与测试(author_runner._build_author_input /
# _PROJECT_AUTHOR_INSTRUCTIONS 等)的导入路径不变。流式执行核心
# (_run_agent_streamed / _StreamActivity / _TASK_CANCEL_POLL_SECONDS)留在本
# 模块:测试的 monkeypatch 打在这个命名空间,其调用方也都在本模块内按模块全
# 局名解析。
from app.agents.author_agent_io import (  # noqa: F401 —— 兼容回导
    _3D_NOTE,
    _AUTHOR_INSTRUCTIONS,
    _INSTRUCTIONS,
    _PROJECT_AUTHOR_INSTRUCTIONS,
    _PROJECT_REPAIR_INSTRUCTIONS,
    _PROJECT_REVISION_INSTRUCTIONS,
    _build_author_input,
    _build_input,
    _close_client,
    _display_output,
    _field,
    _log_cache_hit,
    _quality_state,
    _record,
    _record_fallback_response,
    _response_usage,
    _stream_error_details,
    _terminal_completion_components,
    _usage_of,
)


def enabled(state: dict) -> bool:
    """agent 路径开关：显式 flag + 真模型任务（demo/mock 流水线不进 agent）。"""
    return bool(settings.CODE_AGENT_ENABLED and state.get("use_real"))


def author_enabled(state: dict) -> bool:
    """作者模式开关：agent 从骨架起步自定文件结构写整局游戏，失败回落单次整包生成。"""
    return bool(settings.CODE_AGENT_AUTHOR_ENABLED and state.get("use_real"))


class _StreamActivity:
    """Thread-safe, compact state for stream-aware heartbeats and retries."""

    def __init__(self) -> None:
        now = time.perf_counter()
        self._lock = threading.Lock()
        self.started_at = now
        self.last_event_at = now
        self.last_progress_at = now
        self.last_trace_at = 0.0
        self.attempt = 0
        self.event_type = "starting"
        self.response_id: str | None = None
        self.sequence_number: int | None = None
        self.terminal_failure: str | None = None
        self.error_code: str | None = None
        self.incomplete_reason: str | None = None
        self.error_message: str | None = None
        self.current_response_output_started = False
        self.current_response_chars = 0
        self.last_token_progress_at = now
        self._completed_response_ids: set[str] = set()
        self._response_started_at: dict[str, float] = {}
        self.completed_responses = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cached_tokens = 0
        self.cache_write_tokens = 0

    def begin_attempt(self, attempt: int) -> None:
        now = time.perf_counter()
        with self._lock:
            self.attempt = attempt
            self.last_event_at = now
            self.last_progress_at = now
            self.event_type = "connecting"
            self.terminal_failure = None
            self.error_code = None
            self.incomplete_reason = None
            self.error_message = None
            # A resumed run starts at a model boundary. Previous successful tool turns
            # are carried by RunState and must not block a safe request retry.
            self.current_response_output_started = False
            self.current_response_chars = 0
            self.last_token_progress_at = now

    def observe(self, event) -> tuple[dict, bool]:
        now = time.perf_counter()
        stream_type = str(_field(event, "type", "") or "")
        raw = _field(event, "data") if stream_type == "raw_response_event" else None
        event_type = str(_field(raw, "type", stream_type) or stream_type or "unknown")
        response = _field(raw, "response")
        response_id = _field(response, "id") or _field(raw, "response_id")
        sequence_number = _field(raw, "sequence_number")
        response_usage = _response_usage(response) if event_type == "response.completed" else None
        delta_text = ""
        if event_type.endswith(".delta") and stream_type == "raw_response_event":
            delta_text = str(_field(raw, "delta", "") or "")
        is_output_progress = (
            event_type.endswith(".delta")
            or event_type in {"response.output_item.added", "response.content_part.added"}
            or stream_type in {"run_item_stream_event", "agent_updated_stream_event"}
        )

        with self._lock:
            response_key = str(
                response_id
                or f"attempt-{self.attempt}-sequence-{sequence_number}"
            )
            if event_type == "response.created":
                self._response_started_at[response_key] = now
                self.current_response_output_started = False
                self.current_response_chars = 0
                self.last_token_progress_at = now
                self.terminal_failure = None
                self.error_code = None
                self.incomplete_reason = None
                self.error_message = None
            elif is_output_progress and stream_type == "raw_response_event":
                self.current_response_output_started = True
            elif event_type == "response.completed":
                # The next model request, if any, is safe to resume until it emits
                # its own output. Tool history is preserved through RunState.
                self.current_response_output_started = False

            provisional_tokens = None
            if delta_text:
                self.current_response_chars += len(delta_text)
                if now - self.last_token_progress_at >= _STREAM_PROGRESS_INTERVAL_SECONDS:
                    provisional_tokens = _estimate_stream_tokens(self.current_response_chars)
                    self.last_token_progress_at = now

            self.last_event_at = now
            if is_output_progress or event_type in {
                "response.created",
                "response.completed",
                "response.in_progress",
            }:
                self.last_progress_at = now
            self.event_type = event_type
            if response_id:
                self.response_id = str(response_id)
            if sequence_number is not None:
                try:
                    self.sequence_number = int(sequence_number)
                except (TypeError, ValueError):
                    self.sequence_number = None
            if event_type in _STREAM_TERMINAL_FAILURE_EVENTS:
                self.terminal_failure = event_type
                self.error_code, self.incomplete_reason, self.error_message = (
                    _stream_error_details(raw)
                )

            usage_updated = False
            completed_response = None
            if event_type == "response.completed" and response_key not in self._completed_response_ids:
                self._completed_response_ids.add(response_key)
                self.completed_responses += 1
                response_usage = response_usage or _response_usage(None)
                started_at = self._response_started_at.pop(response_key, self.last_progress_at)
                completed_response = {
                    **response_usage,
                    "provider_response_id": str(response_id) if response_id else None,
                    "request_index": self.completed_responses,
                    "model": str(_field(response, "model", "") or ""),
                    "latency_ms": max(0, int((now - started_at) * 1000)),
                }
                if response_usage["total_tokens"]:
                    self.input_tokens += response_usage["input_tokens"]
                    self.output_tokens += response_usage["output_tokens"]
                    self.total_tokens += response_usage["total_tokens"]
                    self.cached_tokens += response_usage["cached_tokens"]
                    self.cache_write_tokens += response_usage["cache_write_tokens"]
                    usage_updated = True

            trace_now = (
                event_type in _STREAM_TERMINAL_FAILURE_EVENTS
                or event_type in {"response.created", "response.completed"}
                or stream_type in {"run_item_stream_event", "agent_updated_stream_event"}
                or now - self.last_trace_at >= _STREAM_TRACE_INTERVAL_SECONDS
            )
            if trace_now:
                self.last_trace_at = now
            payload = {
                "attempt": self.attempt,
                "stream_type": stream_type,
                "event_type": event_type,
                "response_id": self.response_id,
                "sequence_number": self.sequence_number,
                "output_started": self.current_response_output_started,
                "error_code": self.error_code,
                "incomplete_reason": self.incomplete_reason,
                "usage_updated": usage_updated,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "cached_tokens": self.cached_tokens,
                "cache_write_tokens": self.cache_write_tokens,
                "response_count": self.completed_responses,
                "completed_response": completed_response,
                "provisional_tokens": provisional_tokens,
            }
        return payload, trace_now

    def snapshot(self) -> dict:
        now = time.perf_counter()
        with self._lock:
            return {
                "attempt": self.attempt,
                "event_type": self.event_type,
                "response_id": self.response_id,
                "sequence_number": self.sequence_number,
                "terminal_failure": self.terminal_failure,
                "error_code": self.error_code,
                "incomplete_reason": self.incomplete_reason,
                "error_message": self.error_message,
                "output_started": self.current_response_output_started,
                "response_count": self.completed_responses,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "cached_tokens": self.cached_tokens,
                "cache_write_tokens": self.cache_write_tokens,
                "event_idle_seconds": max(0, int(now - self.last_event_at)),
                "progress_idle_seconds": max(0, int(now - self.last_progress_at)),
            }


def _stream_failure_is_retryable(
    exc: BaseException,
    activity: _StreamActivity,
    *,
    allow_partial_output: bool = False,
) -> tuple[bool, str]:
    state = activity.snapshot()
    code = str(state["error_code"] or _field(exc, "code", "") or "").lower()
    reason = str(state["incomplete_reason"] or "").lower()
    if code in _STREAM_PERMANENT_ERROR_CODES:
        return False, f"non-retryable error code {code}"
    if reason in _STREAM_PERMANENT_INCOMPLETE_REASONS:
        return False, f"non-retryable incomplete reason {reason}"

    terminal = state["terminal_failure"]
    retry_reason: str | None = None
    if terminal == "response.incomplete":
        retry_reason = None
    elif terminal in {"response.failed", "response.error", "error"}:
        retry_reason = terminal

    status_code = _field(exc, "status_code")
    if isinstance(status_code, int) and (
        status_code in {408, 409, 429} or status_code >= 500
    ):
        retry_reason = f"HTTP {status_code}"
    elif type(exc).__name__ in _STREAM_RETRYABLE_EXCEPTION_NAMES:
        retry_reason = type(exc).__name__
    message = str(exc).lower()
    transient_markers = (
        "connection",
        "incomplete chunked read",
        "peer closed",
        "rate limit",
        "server error",
        "timed out",
        "timeout",
        "unexpected eof",
    )
    if retry_reason is None and any(marker in message for marker in transient_markers):
        retry_reason = "transient transport failure"
    if retry_reason is None:
        if terminal == "response.incomplete":
            return False, "incomplete response without a transient reason"
        return False, "non-transient stream failure"
    if state["output_started"] and not allow_partial_output:
        return False, "partial model output already emitted"
    if state["output_started"]:
        return True, retry_reason + " after discardable partial output"
    return True, retry_reason


def _deadline_reached(deadline_at: float | None) -> bool:
    return deadline_at is not None and time.monotonic() >= float(deadline_at)


def _estimate_stream_tokens(text_chars: int) -> int:
    """Estimate output tokens while a response is still streaming."""
    return max(1, round(max(0, text_chars) / 4))


async def _run_agent_streamed_inner(
    runner,
    agent,
    task_input,
    *,
    run_kwargs: dict,
    session: RepairSession,
    agent_name: str,
    activity: _StreamActivity,
    trace_recorder=None,
    execution_run_id: str | None = None,
    workflow_name: str = "",
    model_name: str = "",
    step_id: str | None = None,
    deadline_at: float | None = None,
    safe_partial_stream_retry: bool = False,
    chained_from_response_id: str | None = None,
    cache_metadata: dict | None = None,
):
    """Consume semantic SDK events and resume only safe failed model turns.

    Upstream planning context arrives replayed inside ``task_input`` (explicit
    input items) — the gateway drops server-side previous_response_id, so the
    id here is ledger lineage only and is never sent to the provider.
    """
    max_retries = max(0, int(settings.OPENAI_MAX_RETRIES or 0))
    execution_run_id = execution_run_id or str(uuid.uuid4())
    retry_input = task_input
    for retry_index in range(max_retries + 1):
        if _deadline_reached(deadline_at):
            raise _AgentDeadlineExceeded("agent execution deadline reached")
        attempt = retry_index + 1
        activity.begin_attempt(attempt)
        attempt_changed = set(session.changed)
        attempt_kwargs = dict(run_kwargs)
        result = runner.run_streamed(agent, retry_input, **attempt_kwargs)
        try:
            stream = result.stream_events().__aiter__()
            while True:
                try:
                    idle_timeout = max(
                        0.0,
                        float(settings.CODE_AGENT_STREAM_IDLE_TIMEOUT or 0),
                    )
                    wait_limits = [idle_timeout] if idle_timeout else []
                    deadline_is_wait_limit = False
                    if deadline_at is not None:
                        deadline_remaining = float(deadline_at) - time.monotonic()
                        if deadline_remaining <= 0:
                            raise _AgentDeadlineExceeded(
                                "agent execution deadline reached"
                            )
                        deadline_is_wait_limit = (
                            not idle_timeout or deadline_remaining <= idle_timeout
                        )
                        wait_limits.append(deadline_remaining)
                    if wait_limits:
                        # Keep the SDK async generator in this task. wait_for()
                        # creates a child task for anext(), and the Agents SDK's
                        # model_run_owner ContextVar cannot be reset when that
                        # generator is later finalized from the parent context.
                        async with asyncio.timeout(min(wait_limits)):
                            event = await anext(stream)
                    else:
                        event = await anext(stream)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    # The event loop may fire a short deadline timeout a few
                    # microseconds before a fresh monotonic() comparison reaches
                    # the same boundary. Remember which limit armed the timeout
                    # so a real deadline is never mislabeled as stream idleness.
                    if deadline_is_wait_limit or _deadline_reached(deadline_at):
                        raise _AgentDeadlineExceeded(
                            "agent execution deadline reached while waiting for a stream event"
                        ) from exc
                    state = activity.snapshot()
                    raise TimeoutError(
                        "agent model stream idle timeout after "
                        f"{idle_timeout:g}s without an event "
                        f"(last event: {state['event_type']})"
                    ) from exc
                payload, should_trace = activity.observe(event)
                if payload.get("provisional_tokens") is not None:
                    session._log(
                        f"stream_tokens={payload['provisional_tokens']}",
                        heartbeat=True,
                    )
                completed = payload.get("completed_response")
                if completed is not None:
                    try:
                        llm.record_response_usage(
                            model=completed.get("model") or model_name,
                            prompt_tokens=completed["input_tokens"],
                            completion_tokens=completed["output_tokens"],
                            cached_tokens=completed["cached_tokens"],
                            cache_write_tokens=completed["cache_write_tokens"],
                            cache_read_reported=completed["cache_read_reported"],
                            cache_write_reported=completed["cache_write_reported"],
                            latency_ms=completed["latency_ms"],
                            step_id=step_id,
                            run_id=execution_run_id,
                            agent=agent_name,
                            workflow_name=workflow_name,
                            provider_response_id=completed["provider_response_id"],
                            # Only the run's first request contains the replayed
                            # planning transcript; later turns chain run-internally.
                            previous_response_id=(
                                chained_from_response_id
                                if completed["request_index"] == 1
                                else None
                            ),
                            request_index=completed["request_index"],
                            retried=attempt > 1,
                            cache_metadata=cache_metadata,
                        )
                    except Exception:  # noqa: BLE001 - accounting cannot abort generation
                        logger.exception(
                            "streamed author response accounting failed",
                            extra={
                                "step_id": step_id,
                                "run_id": execution_run_id,
                                "provider_response_id": completed["provider_response_id"],
                            },
                        )
                if payload.get("usage_updated"):
                    session._log(
                        f"stream_tokens={payload['total_tokens']}",
                        event=session._event(
                            "usage_progress",
                            agent=agent_name,
                            input_tokens=payload["input_tokens"],
                            output_tokens=payload["output_tokens"],
                            total_tokens=payload["total_tokens"],
                            cached_tokens=payload["cached_tokens"],
                            cache_write_tokens=payload["cache_write_tokens"],
                            status="running",
                        ),
                    )
                if trace_recorder is not None and should_trace:
                    trace_recorder.record("llm_stream_event", payload)
                if _deadline_reached(deadline_at):
                    raise _AgentDeadlineExceeded("agent execution deadline reached")
            return result
        except Exception as exc:
            no_new_workspace_effects = set(session.changed) == attempt_changed
            retryable, reason = _stream_failure_is_retryable(
                exc,
                activity,
                allow_partial_output=(
                    safe_partial_stream_retry and no_new_workspace_effects
                ),
            )
            if not retryable or retry_index >= max_retries:
                raise
            state = activity.snapshot()
            if (
                state["output_started"]
                and safe_partial_stream_retry
                and no_new_workspace_effects
            ):
                # The failing model request did not execute a write/check tool.
                # Discard its truncated text/function arguments and restart from
                # the immutable prompt against the unchanged current workspace.
                retry_input = task_input
            else:
                try:
                    retry_input = result.to_state()
                except Exception:
                    # Restarting from the original prompt after prior tool turns can
                    # duplicate writes. If state cannot be preserved, fail safely.
                    raise exc

            delay = max(0.0, float(settings.OPENAI_RETRY_BACKOFF_SECONDS or 0)) * (
                2**retry_index
            )
            message = (
                f"{agent_name} stream failed ({reason}); retrying model turn "
                f"{attempt + 1}/{max_retries + 1}"
            )
            session._turn(
                "retrying",
                message,
                source="model_stream",
                attempt=attempt,
                next_attempt=attempt + 1,
                stream_event=state["terminal_failure"] or state["event_type"],
                error_code=state["error_code"],
                response_id=state["response_id"],
                status="retrying",
            )
            session._log(
                f"agent stream retry: {message}",
                event=session._event(
                    "retry",
                    source="model_stream",
                    attempt=attempt,
                    next_attempt=attempt + 1,
                    reason=reason,
                    stream_event=state["terminal_failure"] or state["event_type"],
                    error_code=state["error_code"],
                    response_id=state["response_id"],
                    delay_seconds=delay,
                    status="retrying",
                ),
            )
            if trace_recorder is not None:
                trace_recorder.record(
                    "llm_stream_retry",
                    {
                        **state,
                        "reason": reason,
                        "next_attempt": attempt + 1,
                        "delay_seconds": delay,
                        **detailed_trace.exception_payload(exc),
                    },
                )
            if delay:
                await asyncio.sleep(delay)
    raise RuntimeError("stream retry loop exhausted")  # pragma: no cover


async def _run_agent_streamed(*args, **kwargs):
    """Run one streamed agent with cooperative durable task cancellation.

    The stream iterator remains in the owner task so the Agents SDK can close
    its ContextVars in the same context. A separate watcher only polls the
    durable task flag and cancels that owner task when cancellation is observed.
    """
    task_id = tracing.current_task_id()
    if not task_id:
        return await _run_agent_streamed_inner(*args, **kwargs)

    owner_task = asyncio.current_task()
    cancellation_seen = asyncio.Event()

    async def watch_cancellation() -> None:
        while True:
            await asyncio.sleep(_TASK_CANCEL_POLL_SECONDS)
            try:
                cancelled = tracing.task_is_cancelled(task_id)
            except Exception:  # noqa: BLE001 - transient DB outage must not kill the watcher
                logger.exception(
                    "task cancellation poll failed",
                    extra={"generation_task_id": task_id},
                )
                continue
            if cancelled:
                cancellation_seen.set()
                if owner_task is not None:
                    owner_task.cancel()
                return

    watcher = asyncio.create_task(
        watch_cancellation(),
        name=f"task-cancellation:{task_id}",
    )
    try:
        tracing.raise_if_task_cancelled(task_id)
        return await _run_agent_streamed_inner(*args, **kwargs)
    except asyncio.CancelledError:
        if cancellation_seen.is_set() or tracing.task_is_cancelled(task_id):
            raise tracing.TaskCancelledError(task_id) from None
        raise
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass


def _heartbeat_status(session: RepairSession, activity: _StreamActivity | None = None) -> str:
    checks = "ok" if session.checks_ok else "pending"
    idle = int(time.perf_counter() - session.last_tool_at)
    stream = ""
    if activity is not None:
        state = activity.snapshot()
        stream = (
            f", stream={state['event_type']} ({state['event_idle_seconds']}s idle, "
            f"attempt {state['attempt']})"
        )
    return (
        f"{idle}s since last tool{stream}, bundle={len(session.contents)} file(s), "
        f"changed={len(session.changed)}, checks={checks}"
    )


def _start_heartbeat(
    session: RepairSession,
    *,
    agent_name: str,
    operation: Literal["authoring", "repairing"],
    activity: _StreamActivity | None = None,
    interval: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> tuple[threading.Event, threading.Thread | None]:
    stop = threading.Event()
    if not session.live_step_id or interval <= 0:
        return stop, None
    started = time.perf_counter()

    def run() -> None:
        while not stop.wait(interval):
            elapsed = int(time.perf_counter() - started)
            idle = int(time.perf_counter() - session.last_tool_at)
            checks = "ok" if session.checks_ok else "pending"
            stream_state = activity.snapshot() if activity is not None else {}
            session._log(
                f"agent {operation} waiting on model response: {elapsed}s elapsed, "
                f"{_heartbeat_status(session, activity)}",
                heartbeat=True,
                event=session._event(
                    "heartbeat",
                    agent=agent_name,
                    operation=operation,
                    phase=operation,
                    elapsed_seconds=elapsed,
                    idle_seconds=idle,
                    file_count=len(session.contents),
                    changed_count=len(session.changed),
                    checks=checks,
                    stream_event=stream_state.get("event_type"),
                    stream_event_idle_seconds=stream_state.get("event_idle_seconds"),
                    stream_progress_idle_seconds=stream_state.get("progress_idle_seconds"),
                    stream_attempt=stream_state.get("attempt"),
                    response_id=stream_state.get("response_id"),
                    status="waiting",
                ),
            )

    thread = threading.Thread(target=run, name=f"{agent_name}Heartbeat", daemon=True)
    thread.start()
    return stop, thread


def _stop_heartbeat(stop: threading.Event, thread: threading.Thread | None) -> None:
    stop.set()
    if thread is not None:
        thread.join(timeout=1.0)


def _prompt_cache_key(workflow_name: str) -> str | None:
    """任务级 prompt_cache_key。收益主体仍是跑内多轮共享同一缓存分片，但同任务的
    相邻跑（作者→修复→修复、retry 续跑）prompt 高度重合——后缀随跑随机会让后一跑
    整段重付 uncached（c166a81f 取证：两次修复相隔 35s 内容几乎相同，重付 ~1.85 万
    token）。workflow 段保留，不同 agent 家族不混分片；不同任务各占分片不挤热点；
    无任务上下文时回退每跑唯一。网关需按 key 做粘性路由此收益才稳定。"""
    return llm.prompt_cache_key(workflow_name)


def _execute_agent(
    session: RepairSession,
    *,
    agent_name: str,
    instructions: str,
    author_tools: bool,
    task_input: str,
    turns_limit: int,
    workflow_name: str,
    operation: Literal["authoring", "repairing"],
    tool_policy: AgentToolPolicy | None = None,
    final_output_limit: int = 200,
    output_type: object | None = None,
    deadline_at: float | None = None,
    terminal_completion: bool = True,
    completion_requires_checks: bool | None = None,
    safe_partial_stream_retry: bool = True,
    preserve_partial_on_error: bool = False,
    workspace_tools: bool = True,
    context_items: list[dict] | None = None,
    chained_from_response_id: str | None = None,
) -> RepairOutcome | None:
    """共享的 SDK 工具循环执行器。返回 None 表示不可用/异常（调用方回落旧路径）。

    注意：openai-agents 的顶层包名就是 `agents`（与 app.agents 无冲突，绝对导入
    只会命中 site-packages）。所有 SDK 符号惰性导入，未安装不影响主流程。
    cache 纪律：instructions 必须是模块级常量、工具序固定、循环 append-only ——
    三者共同构成跨轮稳定的请求前缀；动态内容一律放 task_input（首条 user 消息，
    进历史后同样被缓存复用）。整跑命中率由 _log_cache_hit 落日志。
    """
    model_name = settings.CODE_AGENT_MODEL or settings.MODEL_NAME
    trace_recorder = detailed_trace.create_recorder(
        source="agents_sdk",
        agent=agent_name,
        model=model_name,
        require_code_context=False,
    )
    try:
        from agents import Agent, ModelSettings, OpenAIResponsesModel, RunConfig, Runner
        from agents.exceptions import AgentsException, MaxTurnsExceeded
        from openai import AsyncOpenAI
    except Exception as exc:  # pragma: no cover —— SDK 未安装
        if trace_recorder:
            trace_recorder.record(
                "run_error",
                {"phase": "sdk_import", **detailed_trace.exception_payload(exc)},
            )
        session._turn("error", "agent runtime unavailable", source="sdk", status="failed")
        return None

    tools = (
        _make_tools(session, author=author_tools, policy=tool_policy)
        if workspace_tools
        else []
    )
    require_checks = (
        bool(completion_requires_checks)
        if completion_requires_checks is not None
        else bool(tool_policy.allow_checks) if tool_policy is not None else True
    )
    completion = (
        _terminal_completion_components(session, require_checks=require_checks)
        if terminal_completion and output_type is None
        else None
    )
    agent_instructions = instructions
    tool_use_behavior = None
    if completion is not None:
        completion_tool, tool_use_behavior = completion
        tools = [*tools, completion_tool]
        agent_instructions += (
            "\n\nCompletion protocol: do not end with ordinary prose. Call "
            "complete_work(summary) only after your workspace changes are finished. "
            "If it returns NOT_READY, continue editing or checking and call it again later."
        )

    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.OPENAI_TIMEOUT,
            # Stream failures are classified and resumed below. Keeping the SDK's
            # opaque retry loop enabled would multiply attempts and hide activity.
            max_retries=0,
            default_headers={"User-Agent": "GameWeave/1.0"},
        )
    except Exception as exc:  # noqa: BLE001 —— 缺 key 等配置问题
        if trace_recorder:
            trace_recorder.record(
                "run_error",
                {"phase": "client_init", **detailed_trace.exception_payload(exc)},
            )
        session._turn("error", "OpenAI client unavailable", source="client", status="failed")
        return None

    agent_kwargs = dict(
        name=agent_name,
        instructions=agent_instructions,
        model=OpenAIResponsesModel(model=model_name, openai_client=client),
        tools=tools,
    )
    if output_type is not None:
        agent_kwargs["output_type"] = output_type
    if tool_use_behavior is not None:
        agent_kwargs["tool_use_behavior"] = tool_use_behavior
    agent = Agent(**agent_kwargs)

    # Replay the upstream conversation as explicit input items ahead of the
    # task prompt. The stateless gateway ignores previous_response_id, so this
    # is the only transport that actually carries planning context downstream.
    run_input: object = task_input
    if context_items:
        run_input = [
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in context_items
        ] + [{"role": "user", "content": task_input}]

    start = time.perf_counter()
    execution_run_id = str(getattr(trace_recorder, "run_id", None) or uuid.uuid4())
    result = None
    hit_limit = False
    deadline_stop = False
    error_stop = False
    raw_output = None
    session._turn(
        "streaming",
        f"{agent_name} running with {len(tools)} tool(s)",
        agent=agent_name,
        operation=operation,
        tool_count=len(tools),
        bundle=session.bundle_metadata(),
        status="running",
    )
    if context_items:
        session._log(
            f"{agent_name} chained to prior conversation: {len(context_items)} "
            "replayed message(s)"
            + (
                f", from {chained_from_response_id}"
                if chained_from_response_id
                else ""
            )
        )
    stream_activity = _StreamActivity()
    heartbeat_stop, heartbeat_thread = _start_heartbeat(
        session,
        agent_name=agent_name,
        operation=operation,
        activity=stream_activity,
    )
    cache_metadata: dict | None = None
    try:
        prompt_cache_key = _prompt_cache_key(workflow_name)
        extra_args = {"prompt_cache_key": prompt_cache_key} if prompt_cache_key else None
        cache_metadata = llm_cache.cache_request_metadata(
            cache_key=prompt_cache_key,
            namespace=workflow_name,
            mode="routed_implicit" if prompt_cache_key else "provider_implicit",
            tools=[
                {
                    "type": getattr(tool, "type", type(tool).__name__),
                    "name": getattr(tool, "name", None),
                    "description": getattr(tool, "description", None),
                    "params_json_schema": getattr(tool, "params_json_schema", None),
                }
                for tool in tools
            ],
            bypass_reason=(None if prompt_cache_key else "cache_key_prefix_disabled"),
            base_url=settings.OPENAI_BASE_URL,
        )
        cache_metadata["prompt_version"] = workflow_name
        opik_agents_tracing = opik_integration.configure_agents_tracing()
        run_config = RunConfig(
            workflow_name=workflow_name,
            tracing_disabled=not opik_agents_tracing,
            model_settings=ModelSettings(
                parallel_tool_calls=False,
                include_usage=True,
                extra_args=extra_args,
            ),
        )
        if trace_recorder:
            trace_recorder.record(
                "run_start",
                detailed_trace.run_start_payload(
                    instructions=instructions,
                    task_input=task_input,
                    tools=tools,
                    workflow_name=workflow_name,
                    turns_limit=turns_limit,
                    prompt_cache_key=prompt_cache_key,
                    chained_from_response_id=chained_from_response_id,
                    context_items=context_items,
                ),
            )
        run_kwargs = {"max_turns": turns_limit, "run_config": run_config}
        run_hooks = detailed_trace.build_run_hooks(trace_recorder)
        if run_hooks is not None:
            run_kwargs["hooks"] = run_hooks
        result = asyncio.run(
            _run_agent_streamed(
                Runner,
                agent,
                run_input,
                run_kwargs=run_kwargs,
                session=session,
                agent_name=agent_name,
                activity=stream_activity,
                trace_recorder=trace_recorder,
                execution_run_id=execution_run_id,
                workflow_name=workflow_name,
                model_name=model_name,
                step_id=session.live_step_id,
                deadline_at=deadline_at,
                safe_partial_stream_retry=safe_partial_stream_retry,
                chained_from_response_id=chained_from_response_id,
                cache_metadata=cache_metadata,
            )
        )
        raw_output = result.final_output
        note = _display_output(raw_output, final_output_limit)
    except tracing.TaskCancelledError:
        raise
    except MaxTurnsExceeded as exc:
        hit_limit = True
        note = f"max turns ({turns_limit}) exhausted"
        if trace_recorder:
            trace_recorder.record(
                "run_error",
                {
                    "phase": "agent_loop",
                    "reason": "max_turns",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    **detailed_trace.exception_payload(exc),
                },
            )
    except _AgentDeadlineExceeded as exc:
        deadline_stop = True
        note = "agent execution deadline reached"
        if trace_recorder:
            trace_recorder.record(
                "run_error",
                {
                    "phase": "agent_loop",
                    "reason": "deadline",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    **detailed_trace.exception_payload(exc),
                },
            )
    except AgentsException as exc:
        message = str(exc)[:160]
        if trace_recorder:
            trace_recorder.record(
                "run_error",
                {
                    "phase": "agent_loop",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    **detailed_trace.exception_payload(exc),
                },
            )
        session._turn("error", message, source="agent", status="failed")
        session._log(
            f"agent aborted: {message}",
            event=session._event("error", source="agent", message=message, status="failed"),
        )
        if not (preserve_partial_on_error and session.changed):
            return None
        error_stop = True
        note = f"agent error after workspace changes: {message}"
    except Exception as exc:  # noqa: BLE001 —— 网络/供应商异常，一律回落旧路径
        message = str(exc)[:160]
        if trace_recorder:
            trace_recorder.record(
                "run_error",
                {
                    "phase": "model_or_hook",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    **detailed_trace.exception_payload(exc),
                },
            )
        session._turn("error", message, source="model", status="failed")
        session._log(
            f"agent failed: {message}",
            event=session._event("error", source="model", message=message, status="failed"),
        )
        if not (preserve_partial_on_error and session.changed):
            return None
        error_stop = True
        note = f"model stream failed after workspace changes: {message}"
    finally:
        _stop_heartbeat(heartbeat_stop, heartbeat_thread)
        _close_client(client)
        opik_integration.flush()

    latency_ms = int((time.perf_counter() - start) * 1000)
    stream_usage = stream_activity.snapshot()
    if stream_usage["response_count"]:
        tokens = int(stream_usage["total_tokens"] or 0)
    else:
        tokens = _record_fallback_response(
            result,
            model_name=model_name,
            latency_ms=latency_ms,
            execution_run_id=execution_run_id,
            agent_name=agent_name,
            workflow_name=workflow_name,
            step_id=session.live_step_id,
            retried=stream_usage["attempt"] > 1,
            chained_from_response_id=chained_from_response_id,
            cache_metadata=cache_metadata,
        )
    _log_cache_hit(session, result)
    if trace_recorder and result is not None:
        final_history = None
        to_input_list = getattr(result, "to_input_list", None)
        if callable(to_input_list):
            try:
                final_history = to_input_list()
            except Exception as exc:  # noqa: BLE001
                final_history = {"error": detailed_trace.exception_payload(exc)}
        trace_recorder.record(
            "run_end",
            {
                "final_output": result.final_output,
                "final_input_history": final_history,
                "last_response_id": getattr(result, "last_response_id", None),
                "usage": _usage_of(result),
                "latency_ms": latency_ms,
                "checks_ok": session.checks_ok,
                "changed": sorted(session.changed),
            },
        )
    if hit_limit:
        session._log(
            f"{agent_name} reached its turn budget; preserving partial work",
            event=session._event(
                "role_budget_exhausted",
                agent=agent_name,
                operation=operation,
                reason="max_turns",
                message=note,
                turns_limit=turns_limit,
                changed=sorted(session.changed),
                checks_ok=session.checks_ok,
                status="partial",
            ),
        )
    elif deadline_stop:
        session._log(
            f"{agent_name} reached its execution deadline; preserving partial work",
            event=session._event(
                "notice",
                agent=agent_name,
                operation=operation,
                reason="deadline",
                message=note,
                changed=sorted(session.changed),
                checks_ok=session.checks_ok,
                status="partial",
            ),
        )
    elif error_stop:
        session._log(
            f"{agent_name} failed after workspace changes; preserving candidate for validation",
            event=session._event(
                "role_stream_failed_partial",
                agent=agent_name,
                operation=operation,
                reason="stream_error",
                message=note,
                changed=sorted(session.changed),
                checks_ok=session.checks_ok,
                status="partial",
            ),
        )
    else:
        session._turn(
            "completed",
            note or f"{agent_name} finished",
            agent=agent_name,
            checks_ok=session.checks_ok,
            changed=sorted(session.changed),
            bundle=session.bundle_metadata(),
            status="done",
        )
    stop_reason = (
        "max_turns"
        if hit_limit
        else "deadline"
        if deadline_stop
        else "stream_error"
        if error_stop
        else "completed"
    )
    quality_state = _quality_state(session, require_checks=require_checks)
    result_usage = _usage_of(result) if result is not None else {"requests": 0}
    turns = int(stream_usage["response_count"] or result_usage["requests"] or 0)
    if hit_limit and turns <= 0:
        turns = turns_limit
    return RepairOutcome(
        files=session.to_files(),
        changed=sorted(session.changed),
        tokens=tokens,
        logs=list(session.log_lines),
        note=note,
        checks_ok=session.checks_ok,
        turns=turns,
        stop_reason=stop_reason,
        quality_state=quality_state,
        raw_output=raw_output,
    )


def execute_agent(*args, **kwargs) -> RepairOutcome | None:
    """Public adapter for orchestration modules that need an agent runner."""
    return _execute_agent(*args, **kwargs)


def run_repair(
    files: list[dict],
    *,
    error: str,
    dimension: str = "2d",
    task_note: str | None = None,
    failure_label: str = "Build validation",
    max_turns: int | None = None,
    deadline_at: float | None = None,
) -> RepairOutcome | None:
    """跑一轮修复 agent。返回 None 表示 agent 路径不可用/异常（调用方回落旧路径）。"""
    if not files:
        return None
    from app.services.vite_projects import is_vite_project

    project_mode = is_vite_project(files)
    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameProjectRepair" if project_mode else "GameCodeRepair",
        instructions=_PROJECT_REPAIR_INSTRUCTIONS if project_mode else _INSTRUCTIONS,
        author_tools=False,
        task_input=_build_input(files, error, dimension, task_note, failure_label),
        turns_limit=max_turns or settings.CODE_AGENT_MAX_TURNS,
        workflow_name="gameweave-project-repair" if project_mode else "gameweave-repair",
        operation="repairing",
        deadline_at=deadline_at,
    )


def run_author(
    files: list[dict],
    *,
    spec: dict,
    design: dict,
    runtime: str = "canvas",
    dimension: str = "2d",
    qa_feedback: list | None = None,
    max_turns: int | None = None,
    deadline_at: float | None = None,
    planning_context: dict | None = None,
    design_contract: dict | None = None,
    execution_views: dict | None = None,
) -> RepairOutcome | None:
    """作者模式：从骨架 bundle 起步，agent 自定文件结构逐文件写出完整游戏。

    每轮输出只是一个小 patch/文件，单请求远离网关超时墙；总代码量为各轮之和，
    不受单次响应解码预算限制。产物只是候选——外层 build_validation / gameplay QA
    门禁照常把关；返回 None 时调用方回落单次整包生成。
    """
    if not files:
        return None
    from app.services.vite_projects import is_vite_project

    project_mode = is_vite_project(files)
    if project_mode:
        # Keep the fixed outer LangGraph node and its checkpoint/log lifecycle.
        # The bounded team owns only the implementation inside GameCodeAgent.
        from app.agents.author_orchestration import run_project_author_team

        team_kwargs = {
            "spec": spec,
            "design": design,
            "runtime": runtime,
            "dimension": dimension,
            "qa_feedback": qa_feedback,
            "max_turns": max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
            "live_step_id": tracing.current_step_id(),
            "deadline_at": deadline_at,
            "_execute_agent_fn": execute_agent,
            "_tracing": tracing,
        }
        if planning_context:
            team_kwargs["planning_context"] = planning_context
        if design_contract:
            team_kwargs["design_contract"] = design_contract
        if execution_views:
            team_kwargs["execution_views"] = execution_views
        return run_project_author_team(files, **team_kwargs)

    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameCodeAuthor",
        instructions=_AUTHOR_INSTRUCTIONS,
        author_tools=True,
        task_input=_build_author_input(files, spec, design, runtime, dimension, qa_feedback)
        + (f"\nFrozen DesignContract:\n{json.dumps(design_contract, ensure_ascii=False)}" if design_contract else ""),
        turns_limit=max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
        workflow_name="gameweave-author",
        operation="authoring",
        deadline_at=deadline_at,
    )


def run_revision(
    files: list[dict],
    *,
    feedback: str,
    spec: dict,
    design: dict,
    max_turns: int | None = None,
    deadline_at: float | None = None,
    design_contract: dict | None = None,
) -> RepairOutcome | None:
    """Run a bounded, tool-using revision over a modular Vite project."""
    from app.services.vite_projects import is_vite_project

    if not files or not is_vite_project(files):
        return None
    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    task_input = "\n\n".join(
        [
            f"User feedback to implement:\n{feedback}",
            f"GameSpec:\n{json.dumps(spec, ensure_ascii=False)}",
            f"GameDesign:\n{json.dumps(design, ensure_ascii=False)}",
            (f"Frozen DesignContract:\n{json.dumps(design_contract, ensure_ascii=False)}" if design_contract else ""),
            _bundle_context_text(files),
            "Begin with list_files, search for the affected feature, read the relevant modules together with read_files, patch incrementally, and run_checks.",
        ]
    )
    return _execute_agent(
        session,
        agent_name="GameProjectRevision",
        instructions=_PROJECT_REVISION_INSTRUCTIONS,
        author_tools=True,
        task_input=task_input,
        turns_limit=max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
        workflow_name="gameweave-project-revision",
        operation="authoring",
        deadline_at=deadline_at,
    )
