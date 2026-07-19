"""LangGraph node adapters for the pure planning services."""

from pathlib import PurePosixPath

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
    settings,
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
            result = llm.chat(
                prompts.INTENT_SPEC_SYSTEM_PROMPT,
                prompts.build_intent_spec_prompt(
                    prompt,
                    len(state.get("asset_ids") or []),
                    state.get("memory_context") or "",
                ),
                timeout=max(30, int(settings.OPENAI_PLANNING_STREAM_IDLE_TIMEOUT or 180)),
                recover_partial_json=True,
                cache_namespace=prompts.PLANNING_PROMPT_CACHE_NAMESPACE,
                cache_prefix=prompts.PLANNING_SHARED_CACHE_PREFIX,
                # Task-scoped bucket: the upstream ignores writes to the shared
                # global key (all tasks' divergent tails churn it); a per-task
                # key is the only bucket where planning prefixes reliably hit.
                # This first call warms the constitution head for the chain.
                cache_task_scoped=True,
            )
            raw, tokens = result
            spec = _coerce_spec(_parse_json(raw), prompt)
            source = (
                "recovered complete model GameSpec JSON after interrupted stream"
                if getattr(result, "partial", False)
                else "model GameSpec JSON"
            )
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_tokens_delta": tokens, "_logs": _spec_log_lines(spec, source)}
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
            # The gateway strips store/previous_response_id, so the chain to the
            # design stage is carried client-side: this user turn plus the reply
            # become the transcript the next stage replays verbatim (as one
            # growing string — the upstream only prefix-caches string input).
            user_prompt = prompts.build_gameplay_planning_prompt(prompt, spec)
            result = llm.chat(
                prompts.PLANNING_CHAIN_SYSTEM_PROMPT,
                user_prompt,
                timeout=max(30, int(settings.OPENAI_PLANNING_STREAM_IDLE_TIMEOUT or 180)),
                recover_partial_json=True,
                cache_namespace=prompts.PLANNING_PROMPT_CACHE_NAMESPACE,
                cache_task_scoped=True,
            )
            raw, tokens = result
            parsed = _parse_json(raw)
            brief = _coerce_brief(parsed.get("expanded_brief") or {}, prompt, spec)
            plan = _coerce_mechanic_plan(parsed.get("mechanic_plan") or {}, spec, brief, prompt)
            return {
                "expanded_brief": brief,
                "mechanic_plan": plan,
                "planning_transcript": [
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": raw},
                ],
                "planning_response_id": getattr(result, "provider_response_id", None),
                "_agent": "GameplayPlanningAgent",
                "_tokens_delta": tokens,
                "_logs": _brief_log_lines(
                    brief,
                    "recovered complete model gameplay plan after interrupted stream"
                    if getattr(result, "partial", False)
                    else "model combined gameplay plan",
                )
                + _mechanic_log_lines(
                    plan,
                    "recovered complete model gameplay plan after interrupted stream"
                    if getattr(result, "partial", False)
                    else "model combined gameplay plan",
                ),
            }
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("GameplayPlanningAgent", exc, exc)
            brief = _heuristic_brief(prompt, spec)
            plan = _heuristic_mechanic_plan(spec, brief, prompt)
            return {
                "expanded_brief": brief,
                "mechanic_plan": plan,
                "planning_transcript": None,
                "planning_response_id": None,
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
        "planning_transcript": None,
        "planning_response_id": None,
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
            f"gameplay family tagged: {result['archetype']} ({result['label']}) — metadata only, design stays free",
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
    spec = state.get("spec_execution_view") or {}
    # The contract gate publishes the manifest; this node must not reinterpret
    # GameSpec/GameDesign or the original prompt after the freeze boundary.
    demand_manifest = dict(state.get("sprite_demand_manifest") or {})
    if not demand_manifest:
        return {
            "asset_manifest": {"assets": [], "contract_hash": state.get("contract_hash")},
            "sprite_demand_manifest": {},
            "_agent": "AssetAgent",
            "_logs": ["asset processing blocked: frozen SpriteDemandManifest is missing"],
            "status": "failed",
            "error_code": "contract_gap",
            "error_message": "frozen SpriteDemandManifest is required before asset processing",
        }
    asset_manifest = {
        "cover": _theme_cover((state.get("style_bible") or {}).get("theme") or spec.get("theme")),
        "assets": uploaded,
        "sprite_demand_manifest": demand_manifest,
        "asset_batch_specs": dict(state.get("asset_batch_specs") or {}),
        "style_bible": dict(state.get("style_bible") or {}),
        "contract_hash": state.get("contract_hash"),
    }
    return {"uploaded_assets": uploaded, "asset_manifest": asset_manifest, "sprite_demand_manifest": demand_manifest, "asset_batch_specs": dict(state.get("asset_batch_specs") or {}), "_agent": "AssetAgent", "_logs": _asset_log_lines(uploaded, asset_manifest, spec) + [f"consuming frozen contract {state.get('contract_hash')}"]}


def game_design_node(state: dict) -> dict:
    spec = state.get("game_spec") or {}
    is_3d = state.get("dimension") == "3d"
    if state.get("use_real"):
        try:
            transcript = list(state.get("planning_transcript") or [])
            chained = bool(transcript)
            design_prompt = prompts.build_game_design_prompt(
                spec,
                state.get("asset_manifest"),
                expanded_brief=state.get("expanded_brief"),
                mechanic_plan=state.get("mechanic_plan"),
                player_idea=state.get("normalized_prompt") or state.get("prompt"),
                memory_context=state.get("memory_context") or "",
                dimension="3d" if is_3d else "2d",
                chained=chained,
            )
            # Chained mode extends the gameplay-planning user string byte-for-
            # byte (upstream only prefix-caches string input; message arrays
            # cap at the instructions head).
            user_prompt = (
                prompts.build_planning_chain_input(transcript, design_prompt)
                if chained
                else design_prompt
            )
            result = llm.chat(
                prompts.PLANNING_CHAIN_SYSTEM_PROMPT,
                user_prompt,
                timeout=max(30, int(settings.OPENAI_PLANNING_STREAM_IDLE_TIMEOUT or 180)),
                recover_partial_json=True,
                cache_namespace=prompts.PLANNING_PROMPT_CACHE_NAMESPACE,
                cache_task_scoped=True,
                chained_from_response_id=state.get("planning_response_id") if chained else None,
            )
            raw, tokens = result
            design = _coerce_design(_parse_json(raw), spec)
            fed = [k for k, v in (("planning_transcript", chained or None), ("brief", state.get("expanded_brief")), ("mechanic_plan", state.get("mechanic_plan")), ("player_idea", state.get("normalized_prompt"))) if v]
            out = {"game_design": design,
                   "planning_transcript": transcript
                   + [{"role": "user", "content": design_prompt}, {"role": "assistant", "content": raw}],
                   "planning_response_id": getattr(result, "provider_response_id", None),
                   "_agent": "GameDesignAgent", "_tokens_delta": tokens,
                   "_logs": [f"source: {'recovered complete model GameDesign JSON after interrupted stream' if getattr(result, 'partial', False) else 'model GameDesign JSON'} ({'3D' if is_3d else '2D'})",
                             "design context fed: " + (", ".join(fed) or "spec only"),
                             (
                                 f"conversation chain: replayed {len(transcript)} planning message(s) from {state.get('planning_response_id')}"
                                 if chained
                                 else "conversation chain: standalone (no reusable planning transcript)"
                             )] + _design_log_lines(design)}
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
            return {"game_design": design, "planning_transcript": None, "planning_response_id": None,
                    "_agent": "GameDesignAgent", "_logs": [f"model failed: {_clip(exc, 120)}", "source: heuristic fallback"] + _design_log_lines(design)}
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


def design_contract_node(state: dict) -> dict:
    """Compile the complete design before any asset or code request.

    This node never asks an implementation agent to reinterpret the prompt.
    It emits a draft contract; ``contract_gate_node`` is the only place that
    may promote it to a frozen execution authority.
    """
    from app.agents.design_contract import (
        ContractCompileError,
        ScopeExceededError,
        build_intent_record,
        compile_design_contract,
        diff_design_contracts,
    )

    record = build_intent_record(state)
    parent_contract = state.get("design_contract") or None
    try:
        contract = compile_design_contract(
            state.get("game_spec") or {},
            state.get("game_design") or {},
            intent_record=record,
            parent=parent_contract,
        )
        contract_diff = diff_design_contracts(parent_contract, contract)
        if state.get("task_kind") == "revision":
            # Preserve the deterministic diff as evidence, but let the model's
            # contextual judgment decide whether this user amendment actually
            # requires new file-backed media.  This deliberately does not
            # inspect UI focus values or maintain a category/keyword table.
            deterministic_asset_impact = bool(contract_diff.get("asset_impacted"))
            impact = state.get("feedback_asset_impact") or {}
            llm_requires_assets = impact.get("requires_generation")
            contract_diff["contract_asset_impacted"] = deterministic_asset_impact
            if isinstance(llm_requires_assets, bool):
                contract_diff["asset_impacted"] = llm_requires_assets
                contract_diff["asset_impact_source"] = "llm"
                contract_diff["asset_impact_rationale"] = str(
                    impact.get("rationale") or ""
                )[:1000]
                contract_diff["asset_impact_confidence"] = impact.get("confidence")
                contract_diff["llm_affected_semantic_ids"] = list(
                    impact.get("affected_semantic_ids") or []
                )[:100]
            else:
                contract_diff["asset_impact_source"] = "contract_diff_fallback"
        payload = contract.model_dump(mode="json")
        return {
            "intent_record": record.model_dump(mode="json"),
            "design_contract": payload,
            "contract_revision": contract.meta.revision,
            "contract_diff": contract_diff,
            "contract_error": None,
            "_agent": "DesignContractCompilerAgent",
            "_logs": [
                f"compiled design contract {contract.meta.contract_id} revision {contract.meta.revision}",
                f"contract inputs: {len(contract.entities)} entities, {len(contract.systems)} systems, {len(contract.requirements)} requirements",
            ],
        }
    except ScopeExceededError as exc:
        return {
            "intent_record": record.model_dump(mode="json"),
            "contract_error": str(exc),
            "error_code": "scope_exceeded",
            "status": "failed",
            "_agent": "DesignContractCompilerAgent",
            "_logs": [f"contract scope exceeded: {exc}"],
        }
    except (ContractCompileError, ValueError) as exc:
        return {
            "intent_record": record.model_dump(mode="json"),
            "contract_error": str(exc),
            "error_code": "contract_gap",
            "status": "failed",
            "_agent": "DesignContractCompilerAgent",
            "_logs": [f"contract compilation gap: {exc}"],
        }


def contract_gate_node(state: dict) -> dict:
    """Validate and freeze the contract, then publish only derived views."""
    from app.agents.design_contract import (
        ContractCompileError,
        contract_to_design_payload,
        contract_to_spec_payload,
        derive_contract_views,
        freeze_contract,
        validate_contract,
    )

    if state.get("contract_error"):
        issue = str(state["contract_error"])
        result = {
            "passed": False,
            "issues": [issue],
            "metrics": {},
            "code": state.get("error_code") or "contract_gap",
        }
        return {
            "contract_gate": result,
            "status": "failed",
            "_agent": "ContractGateAgent",
            "_logs": [f"contract gate blocked stale contract reuse: {issue}"],
        }
    raw = state.get("design_contract") or {}
    if not raw:
        result = {"passed": False, "issues": ["design contract is missing"], "metrics": {}, "code": "contract_gap"}
        return {"contract_gate": result, "contract_error": result["issues"][0], "error_code": "contract_gap", "status": "failed", "_agent": "ContractGateAgent", "_logs": ["contract gate failed: design contract is missing"]}
    gate = validate_contract(raw)
    if not gate.passed:
        result = gate.to_dict()
        return {
            "contract_gate": result,
            "contract_error": "; ".join(gate.issues),
            "error_code": gate.code or "contract_gap",
            "status": "failed",
            "_agent": "ContractGateAgent",
            "_logs": ["contract gate failed:"] + list(gate.issues[:8]),
        }
    try:
        frozen = freeze_contract(raw)
    except ContractCompileError as exc:
        return {"contract_gate": {"passed": False, "issues": [str(exc)], "metrics": {}, "code": "contract_gap"}, "contract_error": str(exc), "error_code": "contract_gap", "status": "failed", "_agent": "ContractGateAgent", "_logs": [f"contract freeze failed: {exc}"]}
    views = derive_contract_views(frozen)
    frozen_payload = frozen.model_dump(mode="json")
    design_view = contract_to_design_payload(frozen)
    spec_view = contract_to_spec_payload(frozen)
    result = gate.to_dict()
    result["passed"] = True
    result["metrics"] = {**result.get("metrics", {}), "contract_hash": frozen.meta.contract_hash}
    return {
        "design_contract": frozen_payload,
        "contract_hash": frozen.meta.contract_hash,
        "contract_revision": frozen.meta.revision,
        "contract_gate": result,
        "contract_error": None,
        "design_execution_view": design_view,
        "spec_execution_view": spec_view,
        "sprite_demand_manifest": views["sprite_demand_manifest"],
        "asset_batch_specs": views["asset_batch_specs"],
        "style_bible": views["style_bible"],
        "author_role_contracts": views["author_role_contracts"],
        "acceptance_plan": views["acceptance_plan"],
        "runtime_asset_requirements": views["runtime_asset_requirements"],
        "_agent": "ContractGateAgent",
        "_logs": [
            f"contract gate passed: {frozen.meta.contract_id} v{frozen.meta.revision}",
            f"frozen contract hash: {frozen.meta.contract_hash}",
            f"derived views: {len(views['sprite_demand_manifest'].get('demands') or [])} semantic asset demand(s) in {len(views['asset_batch_specs'].get('batches') or [])} batch(es), {len(views['acceptance_plan'].get('tests') or [])} acceptance test(s)",
        ],
    }


_MEDIA_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
    ".mp3", ".wav", ".ogg", ".m4a", ".mp4", ".webm",
}


def _feedback_asset_context(state: dict) -> dict:
    contract = state.get("design_contract") or {}
    semantic_ids = [
        str(item.get("semantic_id"))
        for entity in (contract.get("entities") or [])
        if isinstance(entity, dict)
        for item in (entity.get("states") or [])
        if isinstance(item, dict) and item.get("semantic_id")
    ]
    asset_paths = []
    for item in state.get("existing_files") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if PurePosixPath(path).suffix.lower() in _MEDIA_SUFFIXES:
            asset_paths.append(path)
    return {
        "contract_hash": ((contract.get("meta") or {}).get("contract_hash")),
        "contract_revision": ((contract.get("meta") or {}).get("revision")),
        "visual_style": contract.get("visual_style") or {},
        "semantic_asset_ids": semantic_ids[:200],
        "existing_media_paths": asset_paths[:200],
    }


def _brief_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _structured_feedback(raw: str, feedback: str) -> tuple[str, dict]:
    parsed = _parse_json(raw)
    goal = str(parsed.get("change_goal") or "").strip()
    preserve = _brief_list(parsed.get("preserve"))
    likely = _brief_list(parsed.get("likely_impact"))
    uncertainties = _brief_list(parsed.get("uncertainties"))
    asset = parsed.get("asset_impact")
    asset = asset if isinstance(asset, dict) else {}
    requires_generation = asset.get("requires_generation")
    confidence = asset.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None
    elif confidence is not None:
        confidence = max(0.0, min(1.0, float(confidence)))
    semantic_ids = _brief_list(asset.get("affected_semantic_ids"))[:100]
    rationale = str(asset.get("rationale") or "").strip()
    decision = {
        "requires_generation": (
            requires_generation if isinstance(requires_generation, bool) else None
        ),
        "affected_semantic_ids": semantic_ids,
        "rationale": rationale,
        "confidence": confidence,
        "source": "llm" if isinstance(requires_generation, bool) else "contract_diff_fallback",
    }
    if not goal:
        return (
            raw.strip()
            or f"Change goal\n{feedback}\n\nPreserve\nAll behavior not mentioned by the player.",
            decision,
        )
    lines = ["Change goal", goal, "", "Preserve"]
    lines.extend(preserve or ["All behavior not mentioned by the player."])
    lines.extend(["", "Likely impact"])
    lines.extend(likely or ["Implementation details to be determined from the existing project."])
    lines.extend(["", "Uncertainties"])
    lines.extend(uncertainties or ["None identified."])
    return "\n".join(lines), decision


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
                    _feedback_asset_context(state),
                ),
                timeout=max(30, int(settings.OPENAI_PLANNING_STREAM_IDLE_TIMEOUT or 180)),
                response_format={"type": "json_object"},
                recover_partial_json=True,
            )
            brief, impact = _structured_feedback(brief, feedback)
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("FeedbackUnderstandingAgent", exc, exc)
            brief = f"Change goal\n{feedback}\n\nPreserve\nAll behavior not mentioned by the player.\n\nUncertainties\nModel interpretation failed: {_clip(exc, 120)}"
            impact = {
                "requires_generation": None,
                "affected_semantic_ids": [],
                "rationale": "LLM impact judgment unavailable; use the deterministic contract diff.",
                "confidence": None,
                "source": "contract_diff_fallback",
            }
    else:
        brief = f"Change goal\n{feedback}\n\nPreserve\nAll behavior not mentioned by the player.\n\nUncertainties\nNone inferred in offline mode."
        impact = {
            "requires_generation": None,
            "affected_semantic_ids": [],
            "rationale": "No real LLM was enabled; use the deterministic contract diff.",
            "confidence": None,
            "source": "contract_diff_fallback",
        }
    return {
        "feedback_brief": brief,
        "feedback_asset_impact": impact,
        "_agent": "FeedbackUnderstandingAgent",
        "_tokens_delta": tokens,
        "_logs": [
            f"preserved raw feedback: {_clip(feedback, 180)}",
            f"natural-language change brief: {_clip(brief, 240)}",
            "asset impact judgment: "
            + (
                f"llm requires_generation={str(impact['requires_generation']).lower()}, "
                f"confidence={impact.get('confidence')}, rationale={_clip(impact.get('rationale'), 180)}"
                if impact.get("source") == "llm"
                else "deterministic contract diff fallback"
            ),
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


def should_continue_after_contract_gate(state: dict) -> str:
    if state.get("task_kind") in {"revision", "remix"}:
        if not (state.get("contract_gate") or {}).get("passed"):
            return "failed"
        return "asset_processing" if (state.get("contract_diff") or {}).get("asset_impacted") else "code_revision"
    return "asset_processing" if (state.get("contract_gate") or {}).get("passed") else "failed"


def should_continue_after_asset_generation(state: dict) -> str:
    return "code_revision" if state.get("task_kind") in {"revision", "remix"} else "code_generation"


__all__ = [
    "intent_spec_node",
    "gameplay_planning_node",
    "archetype_router_node",
    "asset_processing_node",
    "game_design_node",
    "content_plan_node",
    "balance_plan_node",
    "design_contract_node",
    "contract_gate_node",
    "feedback_understanding_node",
    "failed_node",
    "done_node",
    "should_continue_after_safety",
    "should_continue_after_contract_gate",
    "should_continue_after_asset_generation",
]
