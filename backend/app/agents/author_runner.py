"""Runner and prompt assembly for repair and author code agents."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

from app.agents import detailed_trace, llm, tracing
from app.agents.agent_tools import _make_tools
from app.agents.repair_session import RepairOutcome, RepairSession, _bundle_context_text, available_skills
from app.core.config import settings
from app.core.telemetry import get_context

_HEARTBEAT_INTERVAL_SECONDS = 12.0
_STREAM_TRACE_INTERVAL_SECONDS = 5.0
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
}

_INSTRUCTIONS = """You repair a small self-contained HTML5 game bundle (index.html, style.css, game.js) that just failed one of GameWeave's quality gates — static build validation or browser gameplay QA (the task input states which).

Hard sandbox contract (any violation fails validation again):
- Forbidden everywhere: eval(), new Function, fetch(), XMLHttpRequest, WebSocket, EventSource, navigator.sendBeacon, dynamic import(), localStorage, sessionStorage, document.cookie, window.parent/window.top access (postMessage is the only exception), and any external http(s) URL including <script src="http...">.
- Entry files index.html, style.css, game.js always exist; a bundle may also carry flat .js/.css modules. Every .js must be referenced by a <script src> in index.html; each file <= 400KB.
- Graphics/sound must be procedural or data:/blob: URIs. Report score only via window.parent.postMessage({type:"gameweave:score", points:<int>}, "*").
- game.js top-level code also runs once in a stubbed V8 smoke test (no real DOM, requestAnimationFrame/setTimeout are no-ops): it must not throw at load time.

Method — work in small verified steps:
1. read_files the files implicated by the error in one call (start with game.js).
2. Make the smallest edit that fixes the reported errors; keep gameplay and structure intact. Use apply_patch for one file or apply_patch_set for a coordinated atomic multi-file change. V4A diffs contain @@ locators plus context lines, without a Begin/Update/End envelope. Never rewrite a whole file.
3. run_checks after every patch or patch set. Repeat until it reports ALL CHECKS PASSED.
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
- write_file creates or fully replaces one file; apply_patch makes one surgical operation; apply_patch_set applies coordinated multi-file operations atomically.

Hard sandbox contract (the outer gate re-checks all of it):
- Forbidden everywhere: eval(), new Function, fetch(), XMLHttpRequest, WebSocket, EventSource, navigator.sendBeacon, dynamic import(), localStorage, sessionStorage, document.cookie, window.parent/window.top access (postMessage is the only exception), and any external http(s) URL.
- Graphics/sound are procedural or data:/blob: URIs only. Report score only via window.parent.postMessage({type:"gameweave:score", points:<int>}, "*").
- Top-level code of every .js runs once in a stubbed V8 smoke test (no real DOM, rAF/timers are no-ops): it must not throw at load time; gameplay setup lives in init/scene callbacks.

Method — small verified increments:
1. Build the playable core loop in game.js first; run_checks until green before adding systems.
2. Then add cohesive systems in small batches. Use apply_patch_set when imports, callers, and implementations must change together, then run_checks once for the batch.
3. When the design includes progression/economy it is mandatory, not optional: in-run currency, a shop/upgrade screen reachable from play (buy weapons, ammo, gear), prices and effects tied to the design's balance numbers. Keep all persistence in memory — no storage APIs.
4. Polish is part of done: particle bursts, screen shake, hit-flash, score pops, smooth easing, a living background; WebAudio oscillator sound for key events.
5. Finish with exactly one line: "DONE: <files written + systems implemented>". If genuinely impossible, "GIVEUP: <why>".
Never finish while run_checks is failing or any .js is unreferenced."""

_PROJECT_REPAIR_INSTRUCTIONS = """You repair a generated Phaser 3.90 + Vite + TypeScript project that failed source validation, typecheck, build, or browser gameplay QA.

The project is modular: src/main.ts wires scenes; src/scenes owns lifecycle; src/entities owns actors; src/systems owns rules/state; src/ui owns presentation; src/config owns typed generated configuration. Preserve these boundaries.

Hard contract:
- Keep package.json, index.html, tsconfig.json, and src/main.ts. Do not add dependencies or Vite config.
- No external URLs, network APIs, storage APIs, eval, dynamic import, or parent/top access except window.parent.postMessage.
- Read the reported file and its imported types together in one read_files call before editing. Use the smallest patch that fixes the root cause.
- If the failure is a gameplay-QA quality issue (missing feedback effects, placeholder gameplay never replaced), read the game-quality-bar skill and wire the scaffold's Juice/Sfx helpers into the offending events instead of inventing new systems.
- Use apply_patch_set for fixes spanning imports, types, and callers. Run run_checks after every patch or patch set; it performs source validation, TypeScript checking, and an isolated Vite build.
- Finish only when checks pass, with: FIXED: <summary>."""

_PROJECT_AUTHOR_INSTRUCTIONS = """You are GameProjectAuthor. Starting from a NEUTRAL Phaser 3.90 + Vite + TypeScript stage, implement the requested GameSpec/GameDesign as a maintainable multi-file game.

Architecture contract:
- src/main.ts only composes Phaser configuration and scene registration.
- Put lifecycle and level flow in src/scenes, actors in src/entities, reusable rules in src/systems, HUD/components in src/ui, and typed values in src/config.
- Scenes orchestrate; behavior lives in focused modules. Give each distinct responsibility the design names (weapon behaviors, enemy AI, room/level generation, upgrade/relic effects, save/settings) its own module in src/systems or src/entities, so adding one more weapon/enemy/room later means adding a module or config entry — not editing a sprawling PlayScene. Split by responsibility, never by line count: a coherent system stays in one file however large, and never manufacture modules that own no behavior.
- Read existing files before modifying them (read_files fetches several at once). Extend the scaffold instead of replacing it with a monolithic file.
- You may create safe nested .ts/.tsx/.css/.json files. Every module must be imported from the project graph.
- Keep package.json dependencies fixed and do not create vite.config.* or use external URLs/network/storage/eval/dynamic import.

The stage is deliberately NOT a game yet:
- src/scenes/PlayScene.ts holds a small placeholder loop marked GW_PLACEHOLDER_GAMEPLAY. REPLACE that gameplay entirely with the designed game (keep the scene key "PlayScene" and the Boot -> Title -> Play -> GameOver flow). Shipping the placeholder, or a thin reskin of it, fails gameplay QA.
- Implement the design's ACTUAL genre physics: platformers set arcade gravity and jump arcs, top-down games keep zero gravity, grid games move in discrete steps, wave/defense games script escalating spawns along paths. Never flatten the idea into generic collect-and-dodge.
- Implement the design's signature_twist as real, visible rules — it is the game's identity, not decoration.

Quality bar (gameplay QA checks this):
- Every meaningful event gets layered feedback via the scaffold kit: Juice (hitFlash, shake, hitStop, burst, floatText, pulse) and Sfx presets (pickup, hit, shoot, explosion, powerup, jump, select, win, lose; playPitched for rising combo tones). A hit = flash + particles + shake + sound; score gains get floatText.
- When gameConfig.sheet is present, build sprites and animations from its named frames (BootScene already preloads every spritesheet) instead of procedural circles. Each sheet's `animations` map groups the frames of one actor (first frame name -> all of its frames, guaranteed on the same texture): the player pose set (player_idle, player_move_a/player_move_b walk cycle, player_action, plus player_skill_2..5 per designed ability, player_hurt, player_jump, player_death, player_victory — switch to the matching pose on EVERY matching event: skills while firing, hurt during the invulnerability blink, jump while airborne, death before the game-over transition, victory on win), enemy groups ("grunt" -> ["grunt","grunt_b","grunt_move"]: run base+_move as the walk/patrol anim, flash the _b attack frame while attacking), boss groups (base/_b attack/_c special/_move — telegraph the special phase with the _c frame), and item idle+activated pairs (pulse the _b frame near pickup or on effect). Wire these into anims.create/setFrame so every actor visibly ANIMATES — a roster of static single-frame sprites wastes the generated art. Large rosters ship SEVERAL sheets: gameConfig.sheets lists them all and sheetFrame("name") from src/config/gameConfig.ts resolves any frame to its {key, index} — use it rather than assuming every frame lives on the first sheet. Fall back to procedural textures only when sheet is null. Gameplay QA fails authored games that preload the sheet without using it.
- When the design declares obstacle/cover entities (crates, barricades, walls), they are MANDATORY gameplay: spawn them as static (or destructible) Arcade Physics bodies using their sheet frames, colliding with the player, enemies, AND projectiles so they create real cover tactics; place them per the design's arena description with fair spacing around spawns. Gameplay QA fails authored games whose designs declare obstacles that never appear in code.
- When gameConfig.tilemap is present, draw it as ground decor beneath gameplay (the TilemapInfo doc in gameConfig.ts shows the three-line Phaser recipe; depth -15 keeps it above the Backdrop and below actors). For maze/grid designs its solidGids may double as wall collision via map.setCollision.
- Keep the generated background visible: Backdrop.draw(this) covers the camera with the generated background image (dimmed for contrast) and falls back to a palette gradient automatically. Do not replace it with a flat fill. Several scene variants usually exist — gameConfig.assetKeys.backgrounds lists them in order (main stage, high-intensity/boss phase, alternate zone). Make the stage visibly EVOLVE: keep the image returned by Backdrop.draw and call Backdrop.swap(this, current, gameConfig.assetKeys.backgrounds[1]) on phase changes (boss spawn, late-game wave tier, level/zone change) for a crossfade; pair the swap with a Juice flash so the transition reads as an event.
- Use gameConfig.palette for every color so the game keeps its own visual identity; tune with gameConfig.params and the design's balance numbers.
- Ease motion and UI tweens (Back/Quad/Elastic) — nothing pops in or moves linearly-only.
- Scoring encodes risk-reward (combo multipliers, proximity bonuses, costs for playing safe). Difficulty: safe opening (~8s), then escalating speed/density/complexity. Win AND loss must both be reachable; restart works without reloading.
- When the design includes progression/economy, it is mandatory: working shop/upgrade screens with prices and effects tied to the design's balance, all state in memory.
- Read the game-quality-bar skill (read_skill) before writing gameplay code.

Physics safety:
- Keep every spawned Arcade Physics body fully inside the configured world bounds, including its radius and body offset. For telegraphed or delayed spawns, include pending entities in wave caps and allow at most one pending spawn per timer so background-tab catch-up cannot burst a whole wave onto the arena edges.
- EVERY moving actor must handle the world edge explicitly with the scaffold's Bounds system (src/systems/Bounds.ts): Bounds.collideWorld for contained/bouncing actors, Bounds.clamp or Bounds.wrap in update() for steered actors, Bounds.despawnOutside for projectiles and spawned waves. Enemies must never drift out of the arena and linger offscreen.
- For top-down moving actors, explicitly disable gravity, keep bodies movable, and set velocity every gameplay tick; do not rely on an actor starting partly outside a world bound and correcting itself later.

Method:
- Work in small coherent increments. Use apply_patch_set for coordinated multi-file edits, then call run_checks. It performs source validation, TypeScript checking, and an isolated Vite build.
- Finish only after checks pass, with: DONE: <files and systems implemented>."""

_PROJECT_REVISION_INSTRUCTIONS = """You revise an existing Phaser 3.90 + Vite + TypeScript game from user feedback.

Read the relevant config, scene, entity, system, and UI modules before editing. Preserve the modular architecture and existing working behavior. Implement the requested change with focused patches; create a new nested module only when it has a clear responsibility. Do not add dependencies, Vite config, external URLs, network/storage APIs, eval, or dynamic import. Run run_checks until TypeScript and the isolated Vite build pass. Finish with: UPDATED: <summary>."""

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
    parts.append("Begin by calling list_files, then read_files every offending file in one call, fix with apply_patch or one atomic apply_patch_set, and verify with run_checks.")
    return "\n\n".join(parts)


def _build_author_input(
    files: list[dict],
    spec: dict,
    design: dict,
    runtime: str,
    dimension: str,
    qa_feedback: list | None = None,
) -> str:
    """作者任务的动态载荷（首条 user 消息）：spec/design/骨架清单 + 运行时注记。
    这里的内容进对话历史后同样被 cache 复用，跑内一次成本、跑间不共享。"""
    listing = "\n".join(
        f"- {f.get('path')} ({len(str(f.get('content') or '').encode('utf-8'))}B)" for f in files
    )
    parts = [
        "Author the complete game for this specification.",
        f"GameSpec:\n{json.dumps(spec, ensure_ascii=False)}",
        f"GameDesign to implement (entities, mechanics, balance):\n{json.dumps(design, ensure_ascii=False)}",
    ]
    if qa_feedback:
        findings = "\n".join(f"- {item}" for item in qa_feedback)
        parts.append(
            "A previous attempt at this game FAILED gameplay QA with the findings below. "
            "Your rewrite MUST resolve every one of them:\n" + findings
        )
    parts += [
        f"Skeleton bundle already in place:\n{listing}",
        f"Bundle workspace context:\n{_bundle_context_text(files)}",
    ]
    if dimension == "3d":
        parts.append(_3D_NOTE)
    elif runtime == "phaser-vite":
        parts.append(
            "Runtime: native Phaser 3.90 + Vite + TypeScript. The scaffold is a neutral stage with a quality kit: "
            "src/systems/Juice.ts (hitFlash/shake/hitStop/burst/floatText/pulse), src/systems/Sfx.ts (procedural sound "
            "presets), src/systems/Bounds.ts (world-edge handling: collideWorld/clamp/wrap/despawnOutside — every "
            "moving actor uses one), src/systems/Backdrop.ts (Backdrop.draw shows the generated background image, "
            "gradient fallback), src/config/gameConfig.ts (per-game palette + free-form params + generated sprite-sheet "
            "frame maps: gameConfig.sheets lists every sheet, sheetFrame(name) resolves a frame across them, and "
            "gameConfig.tilemap describes the generated ground-decor tilemap when present), and a Boot -> Title -> "
            "Play -> GameOver scene flow. src/scenes/PlayScene.ts is a placeholder marked GW_PLACEHOLDER_GAMEPLAY — "
            "replace its gameplay with the designed game. Preserve the scenes/entities/systems/ui/config boundaries."
        )
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
    if runtime == "phaser-vite":
        parts.append(
            "Begin now: call list_files, then one read_files call covering src/config/gameConfig.ts, src/main.ts and "
            "the relevant scene/entity/system files, read_skill('game-quality-bar'), then implement coherent module "
            "batches with apply_patch_set and run_checks between batches."
        )
    else:
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
        "cache_write": int(getattr(details, "cache_write_tokens", 0) or 0),
    }


def _log_cache_hit(session: RepairSession, result) -> None:
    """多轮循环的成本命门是 prompt cache：稳定前缀（静态 instructions + 固定工具序）
    加 append-only 历史应让命中率随轮数上升。把整跑命中率写进日志，退化能被看见。"""
    if result is None:
        return
    u = _usage_of(result)
    if u["input"]:
        pct = u["cached"] * 100 // u["input"]
        uncached = max(0, u["input"] - u["cached"])
        session._log(
            f"agent prompt cache: {u['cached']}/{u['input']} read ({pct}%), "
            f"{u['cache_write']} written, {uncached} uncached over {u['requests']} request(s)",
            event=session._event(
                "usage",
                input_tokens=u["input"],
                output_tokens=u["output"],
                total_tokens=u["total"],
                cached_tokens=u["cached"],
                cache_write_tokens=u["cache_write"],
                uncached_tokens=uncached,
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
            llm.record_usage(
                model_name, u["input"], u["output"], latency_ms, cached_tokens=u["cached"]
            )
        except Exception:  # noqa: BLE001 —— 记账失败不影响修复结果
            pass
    return total


def _close_client(client) -> None:
    try:
        asyncio.run(client.close())
    except Exception:  # noqa: BLE001
        pass


def _field(value, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _stream_error_details(raw_event) -> tuple[str | None, str | None, str | None]:
    response = _field(raw_event, "response")
    error = _field(response, "error") or _field(raw_event, "error") or raw_event
    incomplete = _field(response, "incomplete_details")
    code = _field(error, "code") or _field(error, "type")
    message = _field(error, "message")
    reason = _field(incomplete, "reason")
    return (
        str(code).strip() if code else None,
        str(reason).strip() if reason else None,
        str(message).strip() if message else None,
    )


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

    def observe(self, event) -> tuple[dict, bool]:
        now = time.perf_counter()
        stream_type = str(_field(event, "type", "") or "")
        raw = _field(event, "data") if stream_type == "raw_response_event" else None
        event_type = str(_field(raw, "type", stream_type) or stream_type or "unknown")
        response = _field(raw, "response")
        response_id = _field(response, "id") or _field(raw, "response_id")
        sequence_number = _field(raw, "sequence_number")
        is_output_progress = (
            event_type.endswith(".delta")
            or event_type in {"response.output_item.added", "response.content_part.added"}
            or stream_type in {"run_item_stream_event", "agent_updated_stream_event"}
        )

        with self._lock:
            if event_type == "response.created":
                self.current_response_output_started = False
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
                "event_idle_seconds": max(0, int(now - self.last_event_at)),
                "progress_idle_seconds": max(0, int(now - self.last_progress_at)),
            }


def _stream_failure_is_retryable(
    exc: BaseException,
    activity: _StreamActivity,
) -> tuple[bool, str]:
    state = activity.snapshot()
    if state["output_started"]:
        return False, "partial model output already emitted"

    code = str(state["error_code"] or _field(exc, "code", "") or "").lower()
    reason = str(state["incomplete_reason"] or "").lower()
    if code in _STREAM_PERMANENT_ERROR_CODES:
        return False, f"non-retryable error code {code}"
    if reason in _STREAM_PERMANENT_INCOMPLETE_REASONS:
        return False, f"non-retryable incomplete reason {reason}"

    terminal = state["terminal_failure"]
    if terminal == "response.incomplete":
        return False, "incomplete response without a transient reason"
    if terminal in {"response.failed", "response.error", "error"}:
        return True, terminal

    status_code = _field(exc, "status_code")
    if isinstance(status_code, int) and (
        status_code in {408, 409, 429} or status_code >= 500
    ):
        return True, f"HTTP {status_code}"
    if type(exc).__name__ in _STREAM_RETRYABLE_EXCEPTION_NAMES:
        return True, type(exc).__name__
    message = str(exc).lower()
    transient_markers = ("connection", "rate limit", "server error", "timed out", "timeout")
    if any(marker in message for marker in transient_markers):
        return True, "transient transport failure"
    return False, "non-transient stream failure"


async def _run_agent_streamed(
    runner,
    agent,
    task_input,
    *,
    run_kwargs: dict,
    session: RepairSession,
    agent_name: str,
    activity: _StreamActivity,
    trace_recorder=None,
):
    """Consume semantic SDK events and resume only safe failed model turns."""
    max_retries = max(0, int(settings.OPENAI_MAX_RETRIES or 0))
    retry_input = task_input
    for retry_index in range(max_retries + 1):
        attempt = retry_index + 1
        activity.begin_attempt(attempt)
        result = runner.run_streamed(agent, retry_input, **run_kwargs)
        try:
            async for event in result.stream_events():
                payload, should_trace = activity.observe(event)
                if trace_recorder is not None and should_trace:
                    trace_recorder.record("llm_stream_event", payload)
            return result
        except Exception as exc:
            retryable, reason = _stream_failure_is_retryable(exc, activity)
            if not retryable or retry_index >= max_retries:
                raise
            try:
                retry_input = result.to_state()
            except Exception:
                # Restarting from the original prompt after prior tool turns can
                # duplicate writes. If state cannot be preserved, fail safely.
                raise exc

            delay = max(0.0, float(settings.OPENAI_RETRY_BACKOFF_SECONDS or 0)) * (
                2**retry_index
            )
            state = activity.snapshot()
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
                event_type=state["terminal_failure"] or state["event_type"],
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
    activity: _StreamActivity | None = None,
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
            stream_state = activity.snapshot() if activity is not None else {}
            session._log(
                f"agent {verb} waiting on model response: {elapsed}s elapsed, "
                f"{_heartbeat_status(session, activity)}",
                heartbeat=True,
                event=session._event(
                    "heartbeat",
                    phase=verb,
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


def _prompt_cache_key(workflow_name: str) -> str | None:
    """任务级 prompt_cache_key。收益主体仍是跑内多轮共享同一缓存分片，但同任务的
    相邻跑（作者→修复→修复、retry 续跑）prompt 高度重合——后缀随跑随机会让后一跑
    整段重付 uncached（c166a81f 取证：两次修复相隔 35s 内容几乎相同，重付 ~1.85 万
    token）。workflow 段保留，不同 agent 家族不混分片；不同任务各占分片不挤热点；
    无任务上下文时回退每跑唯一。网关需按 key 做粘性路由此收益才稳定。"""
    prefix = str(settings.CODE_AGENT_PROMPT_CACHE_KEY_PREFIX or "").strip().rstrip(":")
    if not prefix:
        return None
    task_scope = str(get_context().get("task_id") or "").replace("-", "")[:12]
    scope = task_scope or uuid.uuid4().hex[:12]
    return f"{prefix}:{workflow_name}:{scope}"


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

    tools = _make_tools(session, author=author_tools)

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
    stream_activity = _StreamActivity()
    heartbeat_stop, heartbeat_thread = _start_heartbeat(
        session,
        agent_name=agent_name,
        activity=stream_activity,
    )
    try:
        prompt_cache_key = _prompt_cache_key(workflow_name)
        extra_args = {"prompt_cache_key": prompt_cache_key} if prompt_cache_key else None
        run_config = RunConfig(
            workflow_name=workflow_name,
            tracing_disabled=True,
            model_settings=ModelSettings(
                parallel_tool_calls=False,
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
                task_input,
                run_kwargs=run_kwargs,
                session=session,
                agent_name=agent_name,
                activity=stream_activity,
                trace_recorder=trace_recorder,
            )
        )
        note = str(result.final_output or "").strip()[:200]
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
        return None
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
        return None
    finally:
        _stop_heartbeat(heartbeat_stop, heartbeat_thread)
        _close_client(client)

    latency_ms = int((time.perf_counter() - start) * 1000)
    tokens = _record(result, model_name, latency_ms)
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
    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameProjectAuthor" if project_mode else "GameCodeAuthor",
        instructions=_PROJECT_AUTHOR_INSTRUCTIONS if project_mode else _AUTHOR_INSTRUCTIONS,
        author_tools=True,
        task_input=_build_author_input(files, spec, design, runtime, dimension, qa_feedback),
        turns_limit=max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
        workflow_name="gameweave-project-author" if project_mode else "gameweave-author",
    )


def run_revision(
    files: list[dict],
    *,
    feedback: str,
    spec: dict,
    design: dict,
    max_turns: int | None = None,
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
    )
