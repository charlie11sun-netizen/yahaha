"""Author/repair agent instructions, first-turn input assembly, and usage accounting.

2026-07-26 拆分自 ``author_runner.py``:这里是无状态的 I/O 侧——静态 instruction
常量(保持逐字节稳定:它们与固定工具序构成每轮请求的稳定前缀,是 prompt
cache 命中率的根基)、首轮 user 输入装配、SDK 结果的用量/缓存记账与显示辅
助。流式执行核心(重试/心跳/死线/取消轮询)留在 ``author_runner``,它回导这
里的全部名字,调用方与测试的导入路径不变。
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.agents import llm, llm_cache
from app.agents.repair_session import (
    RepairSession,
    _bundle_context_text,
    available_skills,
)

logger = logging.getLogger(__name__)


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
- If QA reports authored modules never imported by the running game, the FIX is to WIRE those existing modules into PlayScene/main.ts per src/contracts/AuthorContract.ts — read them first; they usually contain the real designed gameplay. Never delete them and never satisfy the check by writing new placeholder gameplay: the cheapest correct patch is imports plus construction/update calls.
- If QA reports an unconsumed level_layout, build the stage from gameConfig.levelLayout via src/systems/LevelLayout.ts (buildStatics + colliders, paths() for patrol/lane routes, points() for spawns/objectives) — the painted backdrop matches that plan.
- If QA reports a visual review or text-probe readability issue, apply its concrete findings as focused layout patches. Compute cssScale=min(840/canvasWidth,470/canvasHeight,1) from the ACTUAL Phaser canvas and effectivePx=declaredFontPx*all object/container ancestor scales*cssScale; require primary >=16 CSS px and secondary >=14 after scaling (for a 1280x720 canvas with unscaled text, source fonts are >=25px and >=22px, not a guessed display percentage). Audit every essential HUD/instruction/choice/price/control label in start, active-play, pause/choice, and win/loss states; for dense CJK/Japanese/Korean glyphs at 16-24px use no stroke or 1px and never exceed 10% of font size (Latin: 16%), with opposite-luminance fill and stroke; prefer contrast panels over heavy outlines; measure wrapped text and grow/reflow the panel instead of enlarging text inside fixed-height cards; keep safe margins, stop overlap, and shrink or reposition panels that cover the play field.
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
- When gameConfig.levelLayout exists it is the SINGLE SOURCE OF TRUTH for level geometry — the painted backdrop was composed from the same plan, so following it makes the picture and the game agree. Build walls/cover as solid physics bodies from it (LevelLayout.buildStatics, or its walls/cover rects skinned with sheet frames), route enemy patrols/lanes along LevelLayout.paths() waypoints (enemies follow their designed routes — never generic random wandering), and place spawns/objectives/exits on LevelLayout.points(). Do NOT invent a second, conflicting set of level coordinates; gameplay QA fails authored games that ignore a provided levelLayout.

Quality bar (gameplay QA checks this):
- Essential HUD, objectives, instructions, choices, prices/upgrades, pause/restart, and win/loss text must remain legible after canvas and container scaling. Compute cssScale=min(840/canvasWidth,470/canvasHeight,1) for the compact embed and effectivePx=declaredFontPx*all object/container ancestor scales*cssScale; require primary >=16 effective CSS px and secondary >=14. Thus a 1280x720 canvas with unscaled text requires source fonts >=25px and >=22px, not a guessed display percentage. Inspect start, active-play, pause/choice, and win/loss states for safe margins, clipping, and overlap. For dense CJK/Japanese/Korean glyphs at 16-24px, prefer no stroke or 1px and never exceed 10% of font size (Latin: 16%); fill and stroke must have clearly opposite luminance. Prefer opaque/translucent contrast panels over heavy outlines. Measure wrapped text and grow, reflow, or paginate its panel; do not merely enlarge text inside a fixed-height card.
- Every meaningful event gets layered feedback via the scaffold kit: Juice (hitFlash, shake, hitStop, burst, floatText, pulse) and Sfx presets (pickup, hit, shoot, explosion, powerup, jump, select, win, lose; playPitched for rising combo tones). A hit = flash + particles + shake + sound; score gains get floatText.
- When gameConfig.sheet is present, build sprites and animations from its named frames (BootScene already preloads every spritesheet) instead of procedural circles. Each sheet's `animations` map groups the frames of one actor (first frame name -> all of its frames, guaranteed on the same texture): the player pose set (player_idle, player_move_a/player_move_b walk cycle, player_action, plus player_skill_2..5 per designed ability, player_hurt, player_jump, player_death, player_victory — switch to the matching pose on EVERY matching event: skills while firing, hurt during the invulnerability blink, jump while airborne, death before the game-over transition, victory on win), enemy groups ("grunt" -> ["grunt","grunt_b","grunt_move"]: run base+_move as the walk/patrol anim, flash the _b attack frame while attacking), boss groups (base/_b attack/_c special/_move — telegraph the special phase with the _c frame), and item idle+activated pairs (pulse the _b frame near pickup or on effect). Wire these into anims.create/setFrame so every actor visibly ANIMATES — a roster of static single-frame sprites wastes the generated art. Large rosters ship SEVERAL sheets: gameConfig.sheets lists them all and sheetFrame("name") from src/config/gameConfig.ts resolves any frame to its {key, index} — use it rather than assuming every frame lives on the first sheet. Fall back to procedural textures only when sheet is null. Gameplay QA fails authored games that preload the sheet without using it.
- Bind design entities through the semantic sprite manifest (`spriteFrame("object.state")` / `semanticFrame(...)`) and then use each sheet's frameMeta map as GROUND TRUTH for what the selected frame actually shows. NEVER bind by guessing from frame-name order or numeric sheet indices (entity_2, entity_3, frame 15): one off-by-one guess re-skins the whole roster with the wrong buildings/characters.
- When a sheet lists tileFamilies (connectable roads/pipes/rails/fences), draw that structure per grid cell with tileVariant(family, up, right, down, left) from src/config/gameConfig.ts — it returns the frame plus setAngle rotation for the orthogonal neighbor mask. Render tile frames at EXACTLY the grid cell size (no margins, no 0.9 shrink) so adjacent pieces join into a continuous network, and refresh the four neighbors of every cell the player changes. Never stamp one fixed variant (e.g. the crossing) on every cell, and never overlay identifying text labels on sprites as a substitute for the right art.
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
            "gradient fallback), src/systems/InputRouter.ts (InputRouter.worldPointer routes stage input so it never "
            "fires under HUD buttons; InputRouter.shield makes opaque panels swallow clicks — never attach world "
            "actions to a raw scene-level pointer listener), src/systems/AreaHint.ts (keyed in-world range/area "
            "affordances — AreaHint.circle/rect at selection, hover, and placement time; every range/radius/area "
            "number a rule consults must be visible when the player acts on it), src/systems/Probe.ts (Probe.spawn('enemy', id) when an actor enters play and "
            "Probe.emit('projectile:spawn', id) when a projectile fires — QA replays the game and reconciles probes "
            "against the design roster; it also verifies pointer input is processed, UI is not rebuilt every frame, "
            "no addKey call resolves to a dead key code, and display sizes stay normalized: size actors by the "
            "logical footprint they occupy (grid cell / slot / body) via setDisplaySize, and keep any later "
            "setScale RELATIVE to that base (setData('baseScale', ...) — an absolute setScale snaps sprites back "
            "to raw 256px art resolution), src/systems/GameWeaveBridge.ts (immutable versioned save/settings bridge when requested), "
            "Sfx.setMasterVolume() (0..1 settings gain), src/config/gameConfig.ts (per-game palette + free-form params + generated sprite-sheet "
            "frame maps: semanticFrame/spriteFrame resolve semantic IDs first; gameConfig.sheets lists every sheet, sheetFrame(name) remains a legacy compatibility helper, and "
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
        "cache_read_reported": llm_cache.usage_detail_reported(
            details, "cached_tokens"
        ),
        "cache_write_reported": llm_cache.usage_detail_reported(
            details, "cache_write_tokens"
        ),
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
                cache_read_reported=u["cache_read_reported"],
                cache_write_reported=u["cache_write_reported"],
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
    retried: bool = False,
    chained_from_response_id: str | None = None,
    cache_metadata: dict | None = None,
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
            cache_read_reported=u["cache_read_reported"],
            cache_write_reported=u["cache_write_reported"],
            latency_ms=latency_ms,
            step_id=step_id,
            run_id=execution_run_id,
            agent=agent_name,
            workflow_name=workflow_name,
            provider_response_id=getattr(result, "last_response_id", None),
            previous_response_id=chained_from_response_id,
            request_index=1,
            retried=retried,
            cache_metadata=cache_metadata,
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


def _response_usage(response) -> dict[str, int | bool]:
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
        "cache_read_reported": llm_cache.usage_detail_reported(
            details, "cached_tokens"
        ),
        "cache_write_reported": llm_cache.usage_detail_reported(
            details, "cache_write_tokens"
        ),
    }
