"""Runner and prompt assembly for repair and author code agents."""
from __future__ import annotations

import json
import threading
import time

from app.agents import llm, tracing
from app.agents.agent_tools import _make_tools
from app.agents.repair_session import RepairOutcome, RepairSession, _bundle_context_text, available_skills
from app.core.config import settings

_HEARTBEAT_INTERVAL_SECONDS = 12.0

_INSTRUCTIONS = """You repair a small self-contained HTML5 game bundle (index.html, style.css, game.js) that just failed one of GameWeave's quality gates — static build validation or browser gameplay QA (the task input states which).

Hard sandbox contract (any violation fails validation again):
- Forbidden everywhere: eval(), new Function, fetch(), XMLHttpRequest, WebSocket, EventSource, navigator.sendBeacon, dynamic import(), localStorage, sessionStorage, document.cookie, window.parent/window.top access (postMessage is the only exception), and any external http(s) URL including <script src="http...">.
- Entry files index.html, style.css, game.js always exist; a bundle may also carry flat .js/.css modules. Every .js must be referenced by a <script src> in index.html; each file <= 400KB.
- Graphics/sound must be procedural or data:/blob: URIs. Report score only via window.parent.postMessage({type:"gameweave:score", points:<int>}, "*").
- game.js top-level code also runs once in a stubbed V8 smoke test (no real DOM, requestAnimationFrame/setTimeout are no-ops): it must not throw at load time.

Method — work in small verified steps:
1. read_file the files implicated by the error (start with game.js).
2. Make the smallest edit that fixes the reported errors; keep gameplay and structure intact. Edit via apply_patch in V4A format (*** Update File: + @@ locators + context lines, no line numbers), touching only the lines that must change. Never rewrite a whole file.
3. run_checks after every patch. Repeat until it reports ALL CHECKS PASSED.
4. Finish with exactly one line: "FIXED: <what you changed>". If genuinely impossible, finish with "GIVEUP: <why>".
Never rewrite the game from scratch; repair causes, not symptoms."""

_3D_NOTE = (
    'This is a 3D game: index.html loads the self-hosted engine via <script src="three.min.js"></script> '
    "before game.js, and game.js uses the global THREE. Keep that script tag and never switch to a CDN."
)

# 作者模式 instructions。必须保持模块级静态常量（不做任何插值）：它与固定的工具
# schema 序构成每轮请求的稳定前缀，是多轮循环 prompt cache 命中率的根基。动态内容
# （spec/design/骨架清单）一律走 _build_author_input。
_AUTHOR_INSTRUCTIONS = """You are GameCodeAuthor, a senior HTML5 game developer. Starting from a skeleton bundle, BUILD the complete, polished browser game described by the task's GameSpec/GameDesign, growing the bundle with your tools until run_checks passes and every designed system exists.

You decide the file layout:
- The entry trio index.html, style.css, game.js always stays. Add one flat .js module per big system (e.g. shop.js, upgrades.js, waves.js, hud.js) with write_file; extra .css files are allowed too. Max 12 files, each <= 400KB.
- Wire every .js into index.html with a <script src> tag in dependency order (helpers before their users). An unreferenced .js fails validation.
- write_file creates or fully replaces one file; apply_patch (V4A) makes surgical edits and can also '*** Add File:' / '*** Delete File:'.

Hard sandbox contract (the outer gate re-checks all of it):
- Forbidden everywhere: eval(), new Function, fetch(), XMLHttpRequest, WebSocket, EventSource, navigator.sendBeacon, dynamic import(), localStorage, sessionStorage, document.cookie, window.parent/window.top access (postMessage is the only exception), and any external http(s) URL.
- Graphics/sound are procedural or data:/blob: URIs only. Report score only via window.parent.postMessage({type:"gameweave:score", points:<int>}, "*").
- Top-level code of every .js runs once in a stubbed V8 smoke test (no real DOM, rAF/timers are no-ops): it must not throw at load time; gameplay setup lives in init/scene callbacks.

Method — small verified increments:
1. Build the playable core loop in game.js first; run_checks until green before adding systems.
2. Then add ONE system per module file, wiring index.html immediately; run_checks after each file.
3. When the design includes progression/economy it is mandatory, not optional: in-run currency, a shop/upgrade screen reachable from play (buy weapons, ammo, gear), prices and effects tied to the design's balance numbers. Keep all persistence in memory — no storage APIs.
4. Polish is part of done: particle bursts, screen shake, hit-flash, score pops, smooth easing, a living background; WebAudio oscillator sound for key events.
5. Finish with exactly one line: "DONE: <files written + systems implemented>". If genuinely impossible, "GIVEUP: <why>".
Never finish while run_checks is failing or any .js is unreferenced."""

def enabled(state: dict) -> bool:
    """agent 路径开关：显式 flag + 真模型任务（demo/mock 流水线不进 agent）。"""
    return bool(settings.CODE_AGENT_ENABLED and state.get("use_real"))


def author_enabled(state: dict) -> bool:
    """作者模式开关：agent 从骨架起步自定文件结构写整局游戏，失败回落单次整包生成。"""
    return bool(settings.CODE_AGENT_AUTHOR_ENABLED and state.get("use_real"))


def _build_input(
    files: list[dict],
    error: str,
    dimension: str,
    task_note: str | None,
    failure_label: str = "Build validation",
) -> str:
    listing = "\n".join(
        f"- {f.get('path')} ({len(str(f.get('content') or '').encode('utf-8'))}B)" for f in files
    )
    parts = [
        f"{failure_label} failed with:\n{error}",
        f"Bundle files:\n{listing}",
        f"Bundle workspace context:\n{_bundle_context_text(files)}",
    ]
    if dimension == "3d":
        parts.append(_3D_NOTE)
    if task_note:
        parts.append(task_note)
    skills = available_skills()
    if skills:
        parts.append("Reference skills available via read_skill: " + ", ".join(skills))
    parts.append("Begin by calling list_files, then read or search the offending file(s), fix with apply_patch, and verify with run_checks.")
    return "\n\n".join(parts)


def _build_author_input(files: list[dict], spec: dict, design: dict, runtime: str, dimension: str) -> str:
    """作者任务的动态载荷（首条 user 消息）：spec/design/骨架清单 + 运行时注记。
    这里的内容进对话历史后同样被 cache 复用，跑内一次成本、跑间不共享。"""
    listing = "\n".join(
        f"- {f.get('path')} ({len(str(f.get('content') or '').encode('utf-8'))}B)" for f in files
    )
    parts = [
        "Author the complete game for this specification.",
        f"GameSpec:\n{json.dumps(spec, ensure_ascii=False)}",
        f"GameDesign to implement (entities, mechanics, balance):\n{json.dumps(design, ensure_ascii=False)}",
        f"Skeleton bundle already in place:\n{listing}",
        f"Bundle workspace context:\n{_bundle_context_text(files)}",
    ]
    if dimension == "3d":
        parts.append(_3D_NOTE)
    elif runtime == "phaser":
        parts.append(
            "Runtime: Phaser 4 via the global `Phaser`; index.html already loads phaser.min.js before game.js — "
            "keep that order and never fetch the engine. Structure play as Phaser Scenes (menu / play / shop or "
            "upgrade screens as the design demands) and read the phaser runtime skill before writing code."
        )
    else:
        parts.append("Runtime: vanilla Canvas 2D — no engine script tag; render everything yourself.")
    skills = available_skills()
    if skills:
        parts.append("Reference skills available via read_skill: " + ", ".join(skills))
    parts.append(
        "Begin now: call list_files, read index.html, write the core game.js, then grow one system per file with run_checks between steps."
    )
    return "\n\n".join(parts)


def _usage_of(result) -> dict:
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    details = getattr(usage, "input_tokens_details", None)
    return {
        "requests": int(getattr(usage, "requests", 0) or 0),
        "input": int(getattr(usage, "input_tokens", 0) or 0),
        "output": int(getattr(usage, "output_tokens", 0) or 0),
        "total": int(getattr(usage, "total_tokens", 0) or 0),
        "cached": int(getattr(details, "cached_tokens", 0) or 0),
    }


def _log_cache_hit(session: RepairSession, result) -> None:
    """多轮循环的成本命门是 prompt cache：稳定前缀（静态 instructions + 固定工具序）
    加 append-only 历史应让命中率随轮数上升。把整跑命中率写进日志，退化能被看见。"""
    if result is None:
        return
    u = _usage_of(result)
    if u["input"]:
        pct = u["cached"] * 100 // u["input"]
        session._log(
            f"agent prompt cache: {u['cached']}/{u['input']} input tokens cached ({pct}%) over {u['requests']} request(s)",
            event=session._event(
                "usage",
                input_tokens=u["input"],
                output_tokens=u["output"],
                total_tokens=u["total"],
                cached_tokens=u["cached"],
                requests=u["requests"],
                cache_percent=pct,
                status="done",
            ),
        )


def _record(result, model_name: str, latency_ms: int) -> int:
    if result is None:
        return 0
    u = _usage_of(result)
    total = u["total"] or (u["input"] + u["output"])
    if total:
        try:
            llm.record_usage(model_name, u["input"], u["output"], latency_ms)
        except Exception:  # noqa: BLE001 —— 记账失败不影响修复结果
            pass
    return total


def _close_client(client) -> None:
    try:
        import asyncio

        asyncio.run(client.close())
    except Exception:  # noqa: BLE001
        pass


def _heartbeat_status(session: RepairSession) -> str:
    checks = "ok" if session.checks_ok else "pending"
    idle = int(time.perf_counter() - session.last_tool_at)
    return f"{idle}s since last tool, bundle={len(session.contents)} file(s), changed={len(session.changed)}, checks={checks}"


def _start_heartbeat(
    session: RepairSession,
    *,
    agent_name: str,
    interval: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> tuple[threading.Event, threading.Thread | None]:
    stop = threading.Event()
    if not session.live_step_id or interval <= 0:
        return stop, None
    verb = "authoring" if "Author" in agent_name else "repairing"
    started = time.perf_counter()

    def run() -> None:
        while not stop.wait(interval):
            elapsed = int(time.perf_counter() - started)
            idle = int(time.perf_counter() - session.last_tool_at)
            checks = "ok" if session.checks_ok else "pending"
            session._log(
                f"agent {verb} waiting on model response: {elapsed}s elapsed, {_heartbeat_status(session)}",
                heartbeat=True,
                event=session._event(
                    "heartbeat",
                    phase=verb,
                    elapsed_seconds=elapsed,
                    idle_seconds=idle,
                    file_count=len(session.contents),
                    changed_count=len(session.changed),
                    checks=checks,
                    files_in_context=session.context_snapshot(),
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


def _execute_agent(
    session: RepairSession,
    *,
    agent_name: str,
    instructions: str,
    author_tools: bool,
    task_input: str,
    turns_limit: int,
    workflow_name: str,
) -> RepairOutcome | None:
    """共享的 SDK 工具循环执行器。返回 None 表示不可用/异常（调用方回落旧路径）。

    注意：openai-agents 的顶层包名就是 `agents`（与 app.agents 无冲突，绝对导入
    只会命中 site-packages）。所有 SDK 符号惰性导入，未安装不影响主流程。
    cache 纪律：instructions 必须是模块级常量、工具序固定、循环 append-only ——
    三者共同构成跨轮稳定的请求前缀；动态内容一律放 task_input（首条 user 消息，
    进历史后同样被缓存复用）。整跑命中率由 _log_cache_hit 落日志。
    """
    try:
        from agents import Agent, OpenAIResponsesModel, RunConfig, Runner
        from agents.exceptions import AgentsException, MaxTurnsExceeded
        from openai import AsyncOpenAI
    except Exception:  # pragma: no cover —— SDK 未安装
        session._turn("error", "agent runtime unavailable", source="sdk", status="failed")
        return None

    model_name = settings.CODE_AGENT_MODEL or settings.MODEL_NAME
    tools = _make_tools(session, author=author_tools)

    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.OPENAI_TIMEOUT,
            default_headers={"User-Agent": "GameWeave/1.0"},
        )
    except Exception:  # noqa: BLE001 —— 缺 key 等配置问题
        session._turn("error", "OpenAI client unavailable", source="client", status="failed")
        return None

    agent = Agent(
        name=agent_name,
        instructions=instructions,
        model=OpenAIResponsesModel(model=model_name, openai_client=client),
        tools=tools,
    )

    start = time.perf_counter()
    result = None
    hit_limit = False
    session._turn(
        "streaming",
        f"{agent_name} running with {len(tools)} tool(s)",
        agent=agent_name,
        tool_count=len(tools),
        bundle=session.bundle_metadata(),
        status="running",
    )
    heartbeat_stop, heartbeat_thread = _start_heartbeat(session, agent_name=agent_name)
    try:
        result = Runner.run_sync(
            agent,
            task_input,
            max_turns=turns_limit,
            run_config=RunConfig(workflow_name=workflow_name, tracing_disabled=True),
        )
        note = str(result.final_output or "").strip()[:200]
    except MaxTurnsExceeded:
        hit_limit = True
        note = f"max turns ({turns_limit}) exhausted"
    except AgentsException as exc:
        message = str(exc)[:160]
        session._turn("error", message, source="agent", status="failed")
        session._log(
            f"agent aborted: {message}",
            event=session._event("error", source="agent", message=message, status="failed"),
        )
        return None
    except Exception as exc:  # noqa: BLE001 —— 网络/供应商异常，一律回落旧路径
        message = str(exc)[:160]
        session._turn("error", message, source="model", status="failed")
        session._log(
            f"agent failed: {message}",
            event=session._event("error", source="model", message=message, status="failed"),
        )
        return None
    finally:
        _stop_heartbeat(heartbeat_stop, heartbeat_thread)
        _close_client(client)

    latency_ms = int((time.perf_counter() - start) * 1000)
    tokens = _record(result, model_name, latency_ms)
    _log_cache_hit(session, result)
    if hit_limit:
        session._turn("error", note, reason="max_turns", status="stopped")
        session._log(
            f"agent stopped: {note}",
            event=session._event("notice", reason="max_turns", message=note, status="stopped"),
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
    return RepairOutcome(
        files=session.to_files(),
        changed=sorted(session.changed),
        tokens=tokens,
        logs=list(session.log_lines),
        note=note,
        checks_ok=session.checks_ok,
        turns=_usage_of(result)["requests"] if result is not None else turns_limit,
    )


def run_repair(
    files: list[dict],
    *,
    error: str,
    dimension: str = "2d",
    task_note: str | None = None,
    failure_label: str = "Build validation",
    max_turns: int | None = None,
) -> RepairOutcome | None:
    """跑一轮修复 agent。返回 None 表示 agent 路径不可用/异常（调用方回落旧路径）。"""
    if not files:
        return None
    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameCodeRepair",
        instructions=_INSTRUCTIONS,
        author_tools=False,
        task_input=_build_input(files, error, dimension, task_note, failure_label),
        turns_limit=max_turns or settings.CODE_AGENT_MAX_TURNS,
        workflow_name="gameweave-repair",
    )


def run_author(
    files: list[dict],
    *,
    spec: dict,
    design: dict,
    runtime: str = "canvas",
    dimension: str = "2d",
    max_turns: int | None = None,
) -> RepairOutcome | None:
    """作者模式：从骨架 bundle 起步，agent 自定文件结构逐文件写出完整游戏。

    每轮输出只是一个小 patch/文件，单请求远离网关超时墙；总代码量为各轮之和，
    不受单次响应解码预算限制。产物只是候选——外层 build_validation / gameplay QA
    门禁照常把关；返回 None 时调用方回落单次整包生成。
    """
    if not files:
        return None
    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameCodeAuthor",
        instructions=_AUTHOR_INSTRUCTIONS,
        author_tools=True,
        task_input=_build_author_input(files, spec, design, runtime, dimension),
        turns_limit=max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
        workflow_name="gameweave-author",
    )
