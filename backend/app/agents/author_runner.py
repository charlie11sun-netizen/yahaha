"""Runner and prompt assembly for repair and author code agents."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Literal

from app.agents import detailed_trace, llm, tracing
from app.agents.agent_tools import AgentToolPolicy, _make_tools
from app.agents.repair_session import RepairOutcome, RepairSession, _bundle_context_text, available_skills
from app.core.config import settings

logger = logging.getLogger(__name__)

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
    "TimeoutError",
}


class _AgentDeadlineExceeded(RuntimeError):
    """Raised only at a streamed event boundary when an execution deadline expires."""

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

Budget discipline: the task input already lists every bundle file — never call list_files. Go straight to one read_files batch (the implicated files plus their imported types), then patch.

Hard contract:
- Keep package.json, index.html, tsconfig.json, and src/main.ts. Do not add dependencies or Vite config.
- No external URLs, network APIs, direct browser storage APIs, eval, dynamic import, or parent/top access except window.parent.postMessage. The immutable src/systems/GameWeaveBridge.ts is the only allowed persistence capability; do not edit it.
- Read the reported file and its imported types together in one read_files call before editing. Use the smallest patch that fixes the root cause.
- If the failure is a gameplay-QA quality issue (missing feedback effects, placeholder gameplay never replaced), read the game-quality-bar skill and wire the scaffold's Juice/Sfx helpers into the offending events instead of inventing new systems.
- If the failure is a top-down humanoid that rolls/spins as it moves or aims, keep the body sprite at rotation 0, use pose frames/flipX for facing, keep aim separate from movement, and rotate only weapons/reticles/projectiles.
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
- When the design includes progression/economy, it is mandatory: working shop/upgrade screens with prices and effects tied to the design's balance. Keep live run state in memory; persist only the versioned snapshots explicitly requested through GameWeaveBridge.
- When the request includes persistence, settings, key rebinding, or volume, use the scaffold's immutable GameWeaveBridge for versioned save/settings snapshots and Sfx.setMasterVolume() for 0..1 gain. Never call browser storage directly. These screens and controls must be reachable and functional, not labels.
- Read the game-quality-bar skill (read_skill) before writing gameplay code.

Physics safety:
- Keep every spawned Arcade Physics body fully inside the configured world bounds, including its radius and body offset. For telegraphed or delayed spawns, include pending entities in wave caps and allow at most one pending spawn per timer so background-tab catch-up cannot burst a whole wave onto the arena edges.
- EVERY moving actor must handle the world edge explicitly with the scaffold's Bounds system (src/systems/Bounds.ts): Bounds.collideWorld for contained/bouncing actors, Bounds.clamp or Bounds.wrap in update() for steered actors, Bounds.despawnOutside for projectiles and spawned waves. Enemies must never drift out of the arena and linger offscreen.
- For top-down moving actors, explicitly disable gravity, keep bodies movable, and set velocity every gameplay tick; do not rely on an actor starting partly outside a world bound and correcting itself later.
- For top-down humanoid pose sheets, never rotate the whole player body toward movement/aim. Keep movement and aim as separate vectors; update last aim only from non-zero aim input, use movement only as fallback when no aim input exists, keep facing stable while idle, and use pose frames/flipX. Rotate weapons, reticles, telegraphs, and projectiles instead.

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
            "gradient fallback), src/systems/Probe.ts (Probe.spawn('enemy', id) when an actor enters play and "
            "Probe.emit('projectile:spawn', id) when a projectile fires — QA replays the game and reconciles probes "
            "against the design roster), src/systems/GameWeaveBridge.ts (immutable versioned save/settings bridge when requested), "
            "Sfx.setMasterVolume() (0..1 settings gain), src/config/gameConfig.ts (per-game palette + free-form params + generated sprite-sheet "
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
                model_name,
                u["input"],
                u["output"],
                latency_ms,
                cached_tokens=u["cached"],
                cache_write_tokens=u["cache_write"],
            )
        except Exception:  # noqa: BLE001 - accounting cannot abort generation
            logger.exception("legacy author usage accounting failed")
    return total


def _record_fallback_response(
    result,
    *,
    model_name: str,
    latency_ms: int,
    execution_run_id: str,
    agent_name: str,
    workflow_name: str,
    step_id: str | None,
) -> int:
    """Persist one aggregate row only when no response.completed event was emitted."""
    if result is None:
        return 0
    u = _usage_of(result)
    total = u["total"] or (u["input"] + u["output"])
    try:
        llm.record_response_usage(
            model=model_name,
            prompt_tokens=u["input"],
            completion_tokens=u["output"],
            cached_tokens=u["cached"],
            cache_write_tokens=u["cache_write"],
            latency_ms=latency_ms,
            step_id=step_id,
            run_id=execution_run_id,
            agent=agent_name,
            workflow_name=workflow_name,
            provider_response_id=getattr(result, "last_response_id", None),
            request_index=1,
        )
    except Exception:  # noqa: BLE001 - accounting cannot abort generation
        logger.exception("fallback author response accounting failed")
    return total


def _display_output(value: object, limit: int) -> str:
    """Keep typed/raw output intact while producing a bounded activity note."""
    if value is None:
        return ""
    try:
        if callable(getattr(value, "model_dump_json", None)):
            text = value.model_dump_json()
        elif isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=False, default=str)
        else:
            text = str(value)
    except Exception:  # noqa: BLE001 - display text is best effort
        text = str(value)
    return text.strip()[: max(1, int(limit or 1))]


def _quality_state(session: RepairSession, *, require_checks: bool) -> str:
    if not session.changed:
        return "empty"
    if require_checks and not session.checks_ok:
        return "unchecked"
    return "valid"


def _terminal_completion_components(
    session: RepairSession,
    *,
    require_checks: bool,
):
    """Build the optional SDK completion tool and guarded final-output policy."""
    try:
        from agents import ToolsToFinalOutputResult, function_tool
    except (ImportError, AttributeError):
        return None

    baseline_changed = set(session.changed)

    @function_tool(name_override="complete_work")
    def complete_work(summary: str) -> str:
        """Finish only after a real change and all required checks pass.

        A NOT_READY result is not terminal. Continue working, then call this
        tool again only after satisfying the stated condition.
        """
        changed_now = set(session.changed) - baseline_changed
        if not changed_now:
            return "NOT_READY: no new workspace change has been produced"
        if require_checks and not session.checks_ok:
            return "NOT_READY: run_checks must pass before completion"
        clean_summary = str(summary or "").strip() or "work completed"
        return f"READY: {clean_summary}"

    def tool_use_behavior(_context, tool_results):
        for tool_result in tool_results:
            tool = getattr(tool_result, "tool", None)
            name = getattr(tool, "name", None) or getattr(tool, "qualified_name", None)
            output = str(getattr(tool_result, "output", "") or "")
            if name != "complete_work" or not output.startswith("READY:"):
                continue
            final_output = output.removeprefix("READY:").strip() or "work completed"
            return ToolsToFinalOutputResult(
                is_final_output=True,
                final_output=final_output,
            )
        # In particular, NOT_READY must be sent back to the model so it continues.
        return ToolsToFinalOutputResult(is_final_output=False, final_output=None)

    return complete_work, tool_use_behavior


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


def _response_usage(response) -> dict[str, int]:
    usage = _field(response, "usage")
    details = _field(usage, "input_tokens_details")
    input_tokens = int(_field(usage, "input_tokens", 0) or 0)
    output_tokens = int(_field(usage, "output_tokens", 0) or 0)
    reported_total = int(_field(usage, "total_tokens", 0) or 0)
    if input_tokens + output_tokens <= 0 and reported_total > 0:
        # The ledger API persists input/output rather than an independent total.
        # Preserve providers that expose only total_tokens without losing usage.
        output_tokens = reported_total
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_tokens": int(_field(details, "cached_tokens", 0) or 0),
        "cache_write_tokens": int(
            _field(details, "cache_write_tokens", 0) or 0
        ),
    }


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

    def observe(self, event) -> tuple[dict, bool]:
        now = time.perf_counter()
        stream_type = str(_field(event, "type", "") or "")
        raw = _field(event, "data") if stream_type == "raw_response_event" else None
        event_type = str(_field(raw, "type", stream_type) or stream_type or "unknown")
        response = _field(raw, "response")
        response_id = _field(response, "id") or _field(raw, "response_id")
        sequence_number = _field(raw, "sequence_number")
        response_usage = _response_usage(response) if event_type == "response.completed" else None
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
    execution_run_id: str | None = None,
    workflow_name: str = "",
    model_name: str = "",
    step_id: str | None = None,
    deadline_at: float | None = None,
    safe_partial_stream_retry: bool = False,
):
    """Consume semantic SDK events and resume only safe failed model turns."""
    max_retries = max(0, int(settings.OPENAI_MAX_RETRIES or 0))
    execution_run_id = execution_run_id or str(uuid.uuid4())
    retry_input = task_input
    for retry_index in range(max_retries + 1):
        if _deadline_reached(deadline_at):
            raise _AgentDeadlineExceeded("agent execution deadline reached")
        attempt = retry_index + 1
        activity.begin_attempt(attempt)
        attempt_changed = set(session.changed)
        result = runner.run_streamed(agent, retry_input, **run_kwargs)
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
                completed = payload.get("completed_response")
                if completed is not None:
                    try:
                        llm.record_response_usage(
                            model=completed.get("model") or model_name,
                            prompt_tokens=completed["input_tokens"],
                            completion_tokens=completed["output_tokens"],
                            cached_tokens=completed["cached_tokens"],
                            cache_write_tokens=completed["cache_write_tokens"],
                            latency_ms=completed["latency_ms"],
                            step_id=step_id,
                            run_id=execution_run_id,
                            agent=agent_name,
                            workflow_name=workflow_name,
                            provider_response_id=completed["provider_response_id"],
                            request_index=completed["request_index"],
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
    stream_activity = _StreamActivity()
    heartbeat_stop, heartbeat_thread = _start_heartbeat(
        session,
        agent_name=agent_name,
        operation=operation,
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
                execution_run_id=execution_run_id,
                workflow_name=workflow_name,
                model_name=model_name,
                step_id=session.live_step_id,
                deadline_at=deadline_at,
                safe_partial_stream_retry=safe_partial_stream_retry,
            )
        )
        raw_output = result.final_output
        note = _display_output(raw_output, final_output_limit)
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
        from app.agents.author_team import run_project_author_team

        return run_project_author_team(
            files,
            spec=spec,
            design=design,
            runtime=runtime,
            dimension=dimension,
            qa_feedback=qa_feedback,
            max_turns=max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
            live_step_id=tracing.current_step_id(),
            deadline_at=deadline_at,
        )

    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameCodeAuthor",
        instructions=_AUTHOR_INSTRUCTIONS,
        author_tools=True,
        task_input=_build_author_input(files, spec, design, runtime, dimension, qa_feedback),
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
        operation="authoring",
        deadline_at=deadline_at,
    )
