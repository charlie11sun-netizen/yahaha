"""LangGraph node adapters for the pure planning services."""

import json

from app.agents.nodes_common import (
    MAX_GAMEPLAY_REPAIR,
    MAX_REPAIR,
    MAX_REPLAN,
    TaskErrorCode,
    _ARCHETYPES_3D,
    _clip,
    _parse_json,
    _real_model_fallback_or_raise,
    llm,
    prompts,
)
from app.agents.planning_brief import (
    _coerce_brief,
    _coerce_mechanic_plan,
    _content_plan,
    _heuristic_brief,
    _heuristic_mechanic_plan,
)
from app.agents.planning_logs import (
    _asset_log_lines,
    _balance_log_lines,
    _brief_log_lines,
    _content_log_lines,
    _design_log_lines,
    _mechanic_log_lines,
    _spec_log_lines,
)
from app.agents.planning_routing import (
    _balance_plan,
    _merge_balance_into_design,
    _reconcile_archetype_3d,
    _route_archetype,
    _route_archetype_3d,
)
from app.agents.planning_spec import (
    _coerce_design,
    _coerce_spec,
    _heuristic_design,
    _heuristic_spec,
    _theme_cover,
)


def intent_spec_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(
                prompts.INTENT_SPEC_SYSTEM_PROMPT,
                prompts.build_intent_spec_prompt(
                    prompt,
                    len(state.get("asset_ids") or []),
                    state.get("memory_context") or "",
                ),
            )
            spec = _coerce_spec(_parse_json(raw), prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_tokens_delta": tokens, "_logs": _spec_log_lines(spec, "model GameSpec JSON")}
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("IntentSpecAgent", exc, exc)
            spec = _heuristic_spec(prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_logs": [f"model failed: {_clip(exc, 120)}"] + _spec_log_lines(spec, "heuristic fallback")}
    spec = _heuristic_spec(prompt)
    return {"game_spec": spec, "_agent": "IntentSpecAgent", "_logs": _spec_log_lines(spec, "offline heuristic")}


def gameplay_planning_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = state.get("game_spec") or {}
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(
                (
                    "You are GameplayPlanningAgent. Expand the player's GameSpec into one coherent, bounded plan "
                    "for a small Phaser game. Preserve the requested genre and fantasy. Choose one proven core "
                    "loop plus exactly one implementable signature twist. Do not add unsafe APIs."
                ),
                (
                    "Return JSON with exactly two top-level objects. expanded_brief keys: player_fantasy, "
                    "objective, core_verbs, mechanic_requirements, reward_loop, difficulty_beats, feedback, "
                    "keywords, minimum_content. mechanic_plan keys: archetype_hint, primary_action, "
                    "secondary_action, signature_twist, risk_model, reward_model, enemy_behaviors, reward_items, "
                    "powerups, feedback, skill_tests. Make mechanic_plan realize expanded_brief without "
                    "contradicting the GameSpec. "
                    f"Prompt: {prompt}\nSpec: {json.dumps(spec, ensure_ascii=False)}"
                ),
            )
            parsed = _parse_json(raw)
            brief = _coerce_brief(parsed.get("expanded_brief") or {}, prompt, spec)
            plan = _coerce_mechanic_plan(parsed.get("mechanic_plan") or {}, spec, brief, prompt)
            return {
                "expanded_brief": brief,
                "mechanic_plan": plan,
                "_agent": "GameplayPlanningAgent",
                "_tokens_delta": tokens,
                "_logs": _brief_log_lines(brief, "model combined gameplay plan")
                + _mechanic_log_lines(plan, "model combined gameplay plan"),
            }
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("GameplayPlanningAgent", exc, exc)
            brief = _heuristic_brief(prompt, spec)
            plan = _heuristic_mechanic_plan(spec, brief, prompt)
            return {
                "expanded_brief": brief,
                "mechanic_plan": plan,
                "_agent": "GameplayPlanningAgent",
                "_logs": [f"model failed: {_clip(exc, 120)}"]
                + _brief_log_lines(brief, "heuristic fallback")
                + _mechanic_log_lines(plan, "heuristic fallback"),
            }
    brief = _heuristic_brief(prompt, spec)
    plan = _heuristic_mechanic_plan(spec, brief, prompt)
    return {
        "expanded_brief": brief,
        "mechanic_plan": plan,
        "_agent": "GameplayPlanningAgent",
        "_logs": _brief_log_lines(brief, "offline heuristic")
        + _mechanic_log_lines(plan, "offline heuristic"),
    }


def archetype_router_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = dict(state.get("game_spec") or {})
    is_3d = state.get("dimension") == "3d"
    if is_3d:
        spec["dimension"] = "3d"
        spec["target_runtime"] = "webgl"
        result = _route_archetype_3d(spec, prompt, state.get("expanded_brief"), state.get("mechanic_plan"))
    else:
        spec["dimension"] = "2d"
        result = _route_archetype(spec, prompt, state.get("expanded_brief"), state.get("mechanic_plan"))
    # archetype 只是元数据（QA 启发式 / replan 兜底 / 参考选取用），不再覆写模型
    # 已经给出的 genre/core_loop —— 早期把创意压进四原型是产出趋同的主因之一。
    spec["archetype"] = result["archetype"]
    filled = []
    for key in ("genre", "core_loop"):
        if not spec.get(key):
            spec[key] = result[key]
            filled.append(key)
    tags = [str(tag) for tag in (spec.get("tags") or [])]
    for tag in [str(spec.get("genre") or result["genre"]), result["archetype"].replace("_", "-")]:
        if tag and tag not in tags:
            tags.append(tag)
    spec["tags"] = tags[:5]
    return {
        "game_spec": spec,
        "archetype_result": result,
        "_agent": "ArchetypeRouterAgent",
        "_logs": [
            f"archetype tagged: {result['archetype']} ({result['label']}) — metadata only, design stays free",
            f"routing reason: {result['reason']}",
            (
                f"filled missing spec keys from archetype defaults: {', '.join(filled)}"
                if filled
                else f"spec genre/core_loop kept from model: {spec.get('genre')} / {_clip(spec.get('core_loop'), 80)}"
            ),
            (
                "runtime: 3D WebGL (Three.js, self-hosted) — model-authored, no template fallback"
                if is_3d
                else "runtime: neutral Phaser 3.90 + TypeScript stage, no network or storage"
            ),
        ],
    }


def asset_processing_node(state: dict) -> dict:
    from app.db.session import SessionLocal
    from app.models import Asset
    from app.services.upload_safety import presigned_asset_url

    ids = state.get("asset_ids") or []
    uploaded = []
    if ids:
        db = SessionLocal()
        try:
            for asset in db.query(Asset).filter(Asset.id.in_(ids)).all():
                url = presigned_asset_url(asset)
                if url:
                    uploaded.append({"id": asset.id, "key": asset.filename, "type": asset.kind, "url": url, "source": "uploaded"})
        finally:
            db.close()
    spec = state.get("game_spec") or {}
    asset_manifest = {"cover": _theme_cover(spec.get("theme")), "assets": uploaded}
    return {"uploaded_assets": uploaded, "asset_manifest": asset_manifest, "_agent": "AssetAgent", "_logs": _asset_log_lines(uploaded, asset_manifest, spec)}


def game_design_node(state: dict) -> dict:
    spec = state.get("game_spec") or {}
    is_3d = state.get("dimension") == "3d"
    if state.get("use_real"):
        try:
            sys_prompt = prompts.GAME_DESIGN_SYSTEM_PROMPT_3D if is_3d else prompts.GAME_DESIGN_SYSTEM_PROMPT
            raw, tokens = llm.chat(sys_prompt, prompts.build_game_design_prompt(
                spec,
                state.get("asset_manifest"),
                expanded_brief=state.get("expanded_brief"),
                mechanic_plan=state.get("mechanic_plan"),
                player_idea=state.get("normalized_prompt") or state.get("prompt"),
                memory_context=state.get("memory_context") or "",
            ))
            design = _coerce_design(_parse_json(raw), spec)
            fed = [k for k, v in (("brief", state.get("expanded_brief")), ("mechanic_plan", state.get("mechanic_plan")), ("player_idea", state.get("normalized_prompt"))) if v]
            out = {"game_design": design, "_agent": "GameDesignAgent", "_tokens_delta": tokens,
                   "_logs": [f"source: model GameDesign JSON ({'3D' if is_3d else '2D'})",
                             "design context fed: " + (", ".join(fed) or "spec only")] + _design_log_lines(design)}
            if is_3d:
                new_arch = _reconcile_archetype_3d(spec, design)
                if new_arch != spec.get("archetype"):
                    meta = _ARCHETYPES_3D[new_arch]
                    out["game_spec"] = {**spec, "archetype": new_arch, "genre": meta["genre"], "core_loop": meta["loop"]}
                    out["_logs"].append(f"3D archetype reconciled from design camera -> {new_arch}")
            return out
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("GameDesignAgent", exc, exc)
            design = _heuristic_design(spec)
            return {"game_design": design, "_agent": "GameDesignAgent", "_logs": [f"model failed: {_clip(exc, 120)}", "source: heuristic fallback"] + _design_log_lines(design)}
    design = _heuristic_design(spec)
    return {"game_design": design, "_agent": "GameDesignAgent", "_logs": ["source: offline heuristic"] + _design_log_lines(design)}


def content_plan_node(state: dict) -> dict:
    spec = state.get("game_spec") or {}
    brief = state.get("expanded_brief") or _heuristic_brief(state.get("normalized_prompt") or state.get("prompt", ""), spec)
    mechanics = state.get("mechanic_plan") or _heuristic_mechanic_plan(spec, brief, state.get("normalized_prompt") or state.get("prompt", ""))
    archetype = spec.get("archetype") or (state.get("archetype_result") or {}).get("archetype") or mechanics.get("archetype_hint") or "topdown_collect"
    plan = _content_plan(archetype, spec, brief, mechanics)
    design = dict(state.get("game_design") or _heuristic_design(spec))
    design["mechanic_plan"] = mechanics
    # 罐头 content plan 只补缺：模型设计已有 waves/节奏时不再覆盖——固定的
    # 3-4 波时间轴曾让所有游戏共用同一副节奏骨架。
    if not design.get("waves"):
        design["content_plan"] = plan
        logs = _content_log_lines(plan)
    else:
        logs = ["model design already provides waves/pacing; canned content plan kept out of the design"]
    return {
        "game_design": design,
        "content_plan": plan,
        "_agent": "ContentPlanAgent",
        "_logs": logs,
    }


def balance_plan_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = dict(state.get("game_spec") or {})
    archetype = spec.get("archetype") or (state.get("archetype_result") or {}).get("archetype") or "topdown_collect"
    balance = _balance_plan(archetype, spec, prompt)
    design = _merge_balance_into_design(state.get("game_design") or _heuristic_design(spec), archetype, balance)
    if state.get("mechanic_plan"):
        design["mechanic_plan"] = state["mechanic_plan"]
    if state.get("content_plan"):
        design["content_plan"] = state["content_plan"]
    return {
        "game_spec": spec,
        "game_design": design,
        "balance_config": balance,
        "_agent": "BalanceAgent",
        "_logs": _balance_log_lines(archetype, balance),
    }


def feedback_understanding_node(state: dict) -> dict:
    feedback = state.get("source_feedback") or state.get("prompt") or ""
    tokens = 0
    if state.get("use_real"):
        try:
            brief, tokens = llm.chat(
                prompts.FEEDBACK_UNDERSTANDING_SYSTEM_PROMPT,
                prompts.build_feedback_understanding_prompt(
                    feedback,
                    state.get("game_spec") or {},
                    state.get("game_design") or {},
                    state.get("memory_context") or "",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("FeedbackUnderstandingAgent", exc, exc)
            brief = f"Change goal\n{feedback}\n\nPreserve\nAll behavior not mentioned by the player.\n\nUncertainties\nModel interpretation failed: {_clip(exc, 120)}"
    else:
        brief = f"Change goal\n{feedback}\n\nPreserve\nAll behavior not mentioned by the player.\n\nUncertainties\nNone inferred in offline mode."
    return {
        "feedback_brief": brief,
        "_agent": "FeedbackUnderstandingAgent",
        "_tokens_delta": tokens,
        "_logs": [
            f"preserved raw feedback: {_clip(feedback, 180)}",
            f"natural-language change brief: {_clip(brief, 240)}",
        ],
    }


def failed_node(state: dict) -> dict:
    msg = state.get("error_message") or state.get("last_error") or "generation failed"
    return {
        "status": "failed",
        "error_message": msg,
        "error_code": state.get("error_code") or TaskErrorCode.UNKNOWN.value,
        "_agent": "FailureHandler",
        "_logs": [
            f"task failed: {_clip(msg, 220)}",
            f"repair attempts used: {state.get('repair_attempts', 0)}/{MAX_REPAIR}",
            f"gameplay repair attempts used: {state.get('gameplay_repair_attempts', 0)}/{MAX_GAMEPLAY_REPAIR}",
            f"replan attempts used: {state.get('replan_attempts', 0)}/{MAX_REPLAN}",
        ],
    }


def done_node(state: dict) -> dict:
    return {
        "status": "succeeded",
        "_agent": "DoneHandler",
        "_logs": [f"generation succeeded for game_id={state.get('game_id', 'unknown')}", f"preview url: {state.get('preview_url', 'pending')}"],
    }


def should_continue_after_safety(state: dict) -> str:
    if state.get("status") == "failed":
        return "failed"
    return "memory_retrieval"


__all__ = [
    "intent_spec_node",
    "gameplay_planning_node",
    "archetype_router_node",
    "asset_processing_node",
    "game_design_node",
    "content_plan_node",
    "balance_plan_node",
    "feedback_understanding_node",
    "failed_node",
    "done_node",
    "should_continue_after_safety",
]
