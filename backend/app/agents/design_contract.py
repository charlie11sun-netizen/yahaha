"""Frozen design-contract boundary for the generation pipeline.

The planning agents may use the original prompt as evidence, but every
downstream producer consumes this module's frozen contract or one of its
derived read-only views.  The implementation is intentionally deterministic:
the same spec/design/intent record produces the same canonical hash.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError


DESIGN_CONTRACT_SCHEMA_VERSION = 1
DESIGN_CONTRACT_STATUS = "frozen"
DESIGN_CONTRACT_VIEW_VERSION = "design-contract-views/v1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class IntentRecord(_Strict):
    """Immutable evidence retained for recompilation and audit."""

    raw_prompt: str
    normalized_prompt: str
    feedback: list[str] = Field(default_factory=list)
    uploaded_assets: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    planning_decisions: list[dict[str, Any]] = Field(default_factory=list)


class ContractMeta(_Strict):
    schema_version: int = DESIGN_CONTRACT_SCHEMA_VERSION
    contract_id: str
    revision: int = 1
    parent_hash: str | None = None
    source_intent_hash: str
    status: Literal["draft", "frozen"] = "draft"
    contract_hash: str | None = None


class ContractIntent(_Strict):
    experience_pillars: list[str] = Field(default_factory=list)
    must_haves: list[str] = Field(default_factory=list)
    must_not_haves: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class CoreLoop(_Strict):
    verbs: list[str] = Field(default_factory=list)
    success_signal: str
    failure_signal: str


class EntityState(_Strict):
    id: str
    semantic_id: str
    render_strategy: str = "generated"
    structure_change: bool = False
    base: str | None = None
    runtime_consumers: list[str] = Field(default_factory=list)


class ContractEntity(_Strict):
    id: str
    role: str
    footprint: list[int] = Field(default_factory=lambda: [1, 1])
    interactions: list[str] = Field(default_factory=list)
    states: list[EntityState] = Field(default_factory=list)
    visual_requirements: list[str] = Field(default_factory=list)
    runtime_consumers: list[str] = Field(default_factory=list)


class ContractSystem(_Strict):
    id: str
    purpose: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    runtime_consumers: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class ContractScene(_Strict):
    id: str
    systems: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    runtime_consumers: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class VisualStyle(_Strict):
    theme: str = "retro"
    palette: dict[str, Any] = Field(default_factory=dict)
    rendering: dict[str, Any] = Field(default_factory=dict)
    consistency_rules: list[str] = Field(default_factory=list)


class ContractRequirement(_Strict):
    id: str
    statement: str
    priority: Literal["required", "optional"] = "required"
    source_refs: list[str] = Field(default_factory=list)
    resolved_as: list[str] = Field(default_factory=list)
    acceptance_ids: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class AcceptanceTest(_Strict):
    id: str
    requirement_ids: list[str] = Field(default_factory=list)
    owner: str = "IntegrationAgent"
    observable: str
    verification: str
    runtime_evidence: list[str] = Field(default_factory=list)


class DesignContract(_Strict):
    meta: ContractMeta
    intent: ContractIntent
    core_loop: CoreLoop
    entities: list[ContractEntity] = Field(default_factory=list)
    systems: list[ContractSystem] = Field(default_factory=list)
    scenes: list[ContractScene] = Field(default_factory=list)
    visual_style: VisualStyle = Field(default_factory=VisualStyle)
    requirements: list[ContractRequirement] = Field(default_factory=list)
    acceptance_tests: list[AcceptanceTest] = Field(default_factory=list)


class ContractCompileError(ValueError):
    code = "contract_gap"


class ScopeExceededError(ContractCompileError):
    code = "scope_exceeded"


@dataclass(frozen=True)
class ContractGateResult:
    passed: bool
    issues: tuple[str, ...] = ()
    metrics: Mapping[str, Any] | None = None
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "metrics": dict(self.metrics or {}),
            "code": self.code,
        }


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_text(item) for item in value)
    return str(value)


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [{"id": key, **(item if isinstance(item, Mapping) else {"value": item})} for key, item in value.items()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _slug(value: Any, fallback: str = "game") -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if slug:
        return slug
    if not raw:
        return fallback
    # Semantic IDs stay ASCII for runtime/tool compatibility, while a stable
    # digest prevents distinct CJK (or other non-Latin) names collapsing to
    # the same generic fallback such as ``game``.
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{fallback}-{digest}"


def _canonical(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _record_hash(record: IntentRecord) -> str:
    return hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()


def build_intent_record(state: Mapping[str, Any]) -> IntentRecord:
    raw = str(state.get("prompt") or "")
    normalized = str(state.get("normalized_prompt") or raw).strip()
    feedback = (
        state.get("feedback")
        or state.get("feedback_text")
        or state.get("source_feedback")
        or []
    )
    if isinstance(feedback, str):
        feedback = [feedback] if feedback.strip() else []
    refs = state.get("source_refs") or ["intent:prompt"]
    decisions = state.get("planning_decisions") or []
    uploaded_assets = [
        dict(item)
        for item in (state.get("uploaded_assets") or [])
        if isinstance(item, Mapping)
    ]
    if not uploaded_assets:
        uploaded_assets = [
            {"id": str(asset_id), "source": "uploaded"}
            for asset_id in (state.get("asset_ids") or [])
        ]
    return IntentRecord(
        raw_prompt=raw,
        normalized_prompt=normalized,
        feedback=[str(item) for item in feedback],
        uploaded_assets=uploaded_assets,
        source_refs=[str(item) for item in refs if str(item).strip()],
        planning_decisions=[dict(item) for item in decisions if isinstance(item, Mapping)],
    )


def _entity_states(entity: Mapping[str, Any], entity_id: str, role: str) -> list[EntityState]:
    raw_states = entity.get("states") or entity.get("animation_states") or entity.get("semantic_states")
    if isinstance(raw_states, Mapping):
        raw_states = [{"id": key, **(value if isinstance(value, Mapping) else {})} for key, value in raw_states.items()]
    if isinstance(raw_states, str):
        raw_states = [raw_states]
    if not raw_states:
        role_lower = role.lower()
        defaults = ("idle", "move", "action") if role_lower.startswith("player") else ("idle", "attack") if role_lower.startswith(("enemy", "boss", "hazard")) else ("idle",)
        raw_states = list(defaults)
    consumers = entity.get("runtime_consumers") or {}
    if isinstance(consumers, Mapping):
        consumer_map = {str(key): [str(ref) for ref in _items(value)] for key, value in consumers.items()}
    else:
        consumer_map = {}
    result: list[EntityState] = []
    seen: set[str] = set()
    for raw in raw_states:
        item = raw if isinstance(raw, Mapping) else {"id": raw}
        state_id = _slug(item.get("id") or item.get("name") or "default", "default").replace("-", "_")
        if state_id in seen:
            raise ContractCompileError(f"duplicate entity state: {entity_id}.{state_id}")
        seen.add(state_id)
        semantic = str(item.get("semantic_id") or f"{_slug(entity_id)}.{state_id}")
        refs = item.get("runtime_consumers") or consumer_map.get(semantic) or consumer_map.get(state_id) or [f"{_slug(entity_id)}.renderer"]
        result.append(EntityState(
            id=state_id,
            semantic_id=semantic,
            render_strategy=str(item.get("render_strategy") or ("procedural" if item.get("base") else "generated")),
            structure_change=bool(item.get("structure_change", state_id.startswith("level_"))),
            base=str(item.get("base")) if item.get("base") is not None else None,
            runtime_consumers=[str(ref) for ref in _items(refs) if str(ref).strip()],
        ))
    return result


def _design_entities(design: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    player = design.get("player")
    if isinstance(player, Mapping):
        rows.append({"id": "player", "role": "player", **dict(player)})
    for row in _items(design.get("entities")):
        if isinstance(row, Mapping):
            rows.append(row)
    boss = design.get("boss")
    if isinstance(boss, Mapping) and boss.get("name") and not any(str(row.get("name") or row.get("id")) == str(boss.get("name")) for row in rows):
        rows.append({"id": _slug(boss.get("name"), "boss"), "role": "boss", **dict(boss)})
    return rows


def compile_design_contract(
    spec: Mapping[str, Any] | None,
    design: Mapping[str, Any] | None,
    *,
    intent_record: IntentRecord | Mapping[str, Any] | None = None,
    parent: DesignContract | Mapping[str, Any] | None = None,
    max_entities: int = 64,
) -> DesignContract:
    """Compile planning output into a complete, *draft* DesignContract.

    No list is silently clipped.  A plan over the configured scope returns
    ``scope_exceeded`` so the caller can recompile a smaller design explicitly.
    """
    spec = dict(spec or {})
    design = dict(design or {})
    record = intent_record if isinstance(intent_record, IntentRecord) else IntentRecord.model_validate(intent_record or build_intent_record({"prompt": spec.get("summary") or spec.get("title") or ""}), strict=True)
    rows = _design_entities(design)
    if len(rows) > max_entities:
        raise ScopeExceededError(f"scope_exceeded: {len(rows)} entities exceeds limit {max_entities}")
    contract_id = _slug(spec.get("contract_id") or spec.get("title") or design.get("title") or "game")
    parent_model = parent if isinstance(parent, DesignContract) else (DesignContract.model_validate(parent, strict=True) if parent else None)
    revision = (parent_model.meta.revision + 1) if parent_model else 1
    parent_hash = parent_model.meta.contract_hash if parent_model else None

    entities: list[ContractEntity] = []
    entity_ids: set[str] = set()
    for raw in rows:
        entity_id = _slug(raw.get("id") or raw.get("name") or "entity")
        if entity_id in entity_ids:
            raise ContractCompileError(f"duplicate entity id: {entity_id}")
        entity_ids.add(entity_id)
        role = _text(raw.get("role") or raw.get("type") or "entity")
        footprint = raw.get("footprint") or [1, 1]
        if not isinstance(footprint, (list, tuple)) or len(footprint) != 2:
            raise ContractCompileError(f"invalid footprint for entity: {entity_id}")
        interactions = raw.get("interactions") or []
        if isinstance(interactions, str):
            interactions = [interactions]
        states = _entity_states(raw, entity_id, role)
        consumers = [str(item) for item in (raw.get("runtime_consumers") or []) if str(item).strip()] if isinstance(raw.get("runtime_consumers"), (list, tuple, set)) else []
        if not consumers:
            consumers = sorted({ref for state in states for ref in state.runtime_consumers})
        visual = raw.get("visual_requirements") or ["transparent_background", "no_edge_bleed", "stable_ground_anchor"]
        entities.append(ContractEntity(
            id=entity_id,
            role=role,
            footprint=[int(footprint[0]), int(footprint[1])],
            interactions=[str(item) for item in interactions],
            states=states,
            visual_requirements=[str(item) for item in visual],
            runtime_consumers=consumers,
        ))
    if not entities:
        fallback = {"id": "player", "role": "player"}
        entities.append(ContractEntity(id="player", role="player", states=_entity_states(fallback, "player", "player"), runtime_consumers=["player.renderer"]))

    systems: list[ContractSystem] = []
    raw_systems = design.get("systems") or []
    if isinstance(raw_systems, Mapping):
        raw_systems = [{"id": key, **(value if isinstance(value, Mapping) else {})} for key, value in raw_systems.items()]
    for index, raw in enumerate(raw_systems):
        if not isinstance(raw, Mapping):
            continue
        sid = _slug(raw.get("id") or raw.get("name") or f"system-{index + 1}")
        systems.append(ContractSystem(id=sid, purpose=_text(raw.get("purpose") or raw.get("description") or sid), inputs=[str(item) for item in (raw.get("inputs") or [])], outputs=[str(item) for item in (raw.get("outputs") or [])], runtime_consumers=[str(item) for item in (raw.get("runtime_consumers") or [])], details=dict(raw)))
    if not systems:
        rules = design.get("rules") if isinstance(design.get("rules"), Mapping) else {}
        systems.append(ContractSystem(id="game-rules", purpose="resolve the designed core loop and terminal outcomes", inputs=["player_input"], outputs=["state_changed", "outcome"], runtime_consumers=["main.runtime"], details=dict(rules)))

    scenes: list[ContractScene] = []
    raw_scenes = design.get("scenes") or design.get("scene") or []
    if isinstance(raw_scenes, Mapping):
        raw_scenes = [{"id": "main", **dict(raw_scenes)}]
    for index, raw in enumerate(raw_scenes):
        if not isinstance(raw, Mapping):
            continue
        scene_id = _slug(raw.get("id") or raw.get("name") or f"scene-{index + 1}")
        scene_details = {
            "title": spec.get("title"),
            "genre": spec.get("genre"),
            "archetype": design.get("archetype") or spec.get("archetype"),
            **dict(raw),
        }
        scenes.append(ContractScene(id=scene_id, systems=[str(item) for item in (raw.get("systems") or [system.id for system in systems])], entities=[str(item) for item in (raw.get("entities") or [entity.id for entity in entities])], runtime_consumers=[str(item) for item in (raw.get("runtime_consumers") or [f"{scene_id}.runtime"])], details=scene_details))
    if not scenes:
        scenes.append(ContractScene(id="main", systems=[system.id for system in systems], entities=[entity.id for entity in entities], runtime_consumers=["main.runtime"], details={"title": spec.get("title"), "genre": spec.get("genre"), "archetype": design.get("archetype") or spec.get("archetype"), "layout": design.get("level_layout") or {}, "rules": design.get("rules") or {}, "ui": design.get("ui") or {}}))

    explicit_required = spec.get("must_haves") or design.get("must_haves") or []
    explicit_forbidden = spec.get("must_not_haves") or design.get("must_not_haves") or []
    # A revision is additive: unchanged requirements and their audit trail are
    # carried forward, while current planning output may replace a requirement
    # with the same stable ID.  This prevents a user amendment from erasing the
    # evidence that justified earlier implementation work.
    requirements: list[ContractRequirement] = (
        [item.model_copy() for item in parent_model.requirements]
        if parent_model
        else []
    )

    def upsert_requirement(requirement: ContractRequirement) -> None:
        for current_index, current in enumerate(requirements):
            if current.id == requirement.id:
                requirements[current_index] = requirement
                return
        requirements.append(requirement)

    for index, raw in enumerate(_items(design.get("requirements"))):
        if isinstance(raw, Mapping):
            rid = str(raw.get("id") or f"REQ-DESIGN-{index + 1:03d}")
            statement = _text(raw.get("statement") or raw.get("requirement") or rid)
            upsert_requirement(ContractRequirement(id=rid, statement=statement, priority="optional" if str(raw.get("priority") or "required") == "optional" else "required", source_refs=[str(item) for item in (raw.get("source_refs") or [f"design:requirements[{index}]"])], resolved_as=[str(item) for item in (raw.get("resolved_as") or [])], constraints=[str(item) for item in (raw.get("constraints") or [])]))
    for index, item in enumerate(explicit_required):
        if isinstance(item, Mapping):
            rid = str(item.get("id") or f"REQ-INTENT-{index + 1:03d}")
            statement = _text(item.get("statement") or item.get("requirement") or item.get("text") or rid)
            resolved = [str(value) for value in (item.get("resolved_as") or [])]
            source_refs = [str(value) for value in (item.get("source_refs") or [f"intent:must_have:{index + 1}"])]
        else:
            rid = str(item) if str(item).upper().startswith("REQ-") else f"REQ-INTENT-{index + 1:03d}"
            statement = str(item)
            resolved = []
            source_refs = [f"intent:must_have:{index + 1}"]
        upsert_requirement(ContractRequirement(id=rid, statement=statement, source_refs=source_refs, resolved_as=resolved))
    core = CoreLoop(verbs=[str(item) for item in (design.get("verbs") or spec.get("verbs") or _text(spec.get("core_loop") or design.get("core_loop") or "play, react, progress").split(","))], success_signal=_text(spec.get("win_condition") or (design.get("rules") or {}).get("win") or "complete the designed objective"), failure_signal=_text(spec.get("lose_condition") or (design.get("rules") or {}).get("lose") or "reach the designed failure state"))
    if not any(req.id == "REQ-CORE-LOOP" for req in requirements):
        requirements.append(ContractRequirement(id="REQ-CORE-LOOP", statement=f"Implement the core loop: {', '.join(core.verbs)}", source_refs=["intent:core_loop"], resolved_as=["game-rules"]))
    for index, item in enumerate(explicit_forbidden):
        rid = f"REQ-NOT-{index + 1:03d}"
        if not any(req.id == rid for req in requirements):
            requirements.append(ContractRequirement(id=rid, statement=f"Must not have: {_text(item)}", source_refs=[f"intent:must_not:{index + 1}"], constraints=[f"must_not:{_text(item)}"]))

    amendment_ids: list[str] = []
    for index, statement in enumerate(record.feedback):
        if not str(statement).strip():
            continue
        rid = f"REQ-AMENDMENT-{revision:03d}-{index + 1:03d}"
        amendment_ids.append(rid)
        upsert_requirement(
            ContractRequirement(
                id=rid,
                statement=_text(statement),
                source_refs=[f"intent:feedback:{index + 1}"],
                resolved_as=["contract-revision"],
                constraints=["preserve all contract behavior not superseded by this amendment"],
            )
        )

    raw_acceptance = _items(design.get("acceptance_tests"))
    acceptance: list[AcceptanceTest] = (
        [item.model_copy() for item in parent_model.acceptance_tests]
        if parent_model
        else []
    )
    for index, raw in enumerate(raw_acceptance):
        if not isinstance(raw, Mapping):
            continue
        aid = str(raw.get("id") or f"AT-{index + 1:03d}")
        req_ids = [str(item) for item in (raw.get("requirement_ids") or raw.get("requirements") or [])]
        candidate = AcceptanceTest(id=aid, requirement_ids=req_ids, owner=str(raw.get("owner") or "IntegrationAgent"), observable=_text(raw.get("observable") or raw.get("expected") or "The required behavior is observable during play."), verification=_text(raw.get("verification") or "Run the corresponding runtime check."), runtime_evidence=[str(item) for item in (raw.get("runtime_evidence") or [])])
        acceptance = [item for item in acceptance if item.id != aid]
        acceptance.append(candidate)
    for index, req in enumerate(requirements):
        if not any(req.id in test.requirement_ids for test in acceptance):
            next_number = len(acceptance) + 1
            aid = f"AT-{next_number:03d}"
            while any(item.id == aid for item in acceptance):
                next_number += 1
                aid = f"AT-{next_number:03d}"
            acceptance.append(AcceptanceTest(id=aid, requirement_ids=[req.id], owner="IntegrationAgent", observable=f"{req.statement} is observable during play.", verification=f"Exercise the behavior and verify requirement {req.id}.", runtime_evidence=["runtime evidence"]))
    acceptance_ids = {test.id for test in acceptance}
    requirements = [req.model_copy(update={"acceptance_ids": [test.id for test in acceptance if req.id in test.requirement_ids]}) for req in requirements]
    parent_must_haves = list(parent_model.intent.must_haves) if parent_model else []
    current_must_haves = [str(item.get("id") if isinstance(item, Mapping) and item.get("id") else item) for item in explicit_required]
    parent_must_not = list(parent_model.intent.must_not_haves) if parent_model else []
    intent = ContractIntent(experience_pillars=[str(item) for item in (spec.get("experience_pillars") or design.get("experience_pillars") or [])], must_haves=list(dict.fromkeys([*parent_must_haves, *current_must_haves, *amendment_ids])), must_not_haves=list(dict.fromkeys([*parent_must_not, *[_text(item) for item in explicit_forbidden]])), preferences=[str(item) for item in (spec.get("preferences") or [])], unresolved=[str(item) for item in (spec.get("unresolved") or design.get("unresolved") or [])])
    visual = VisualStyle(theme=_text(spec.get("theme") or design.get("theme") or "retro"), palette=dict(design.get("palette") or {}) if isinstance(design.get("palette"), Mapping) else {}, rendering=dict(design.get("visual_style") or {}) if isinstance(design.get("visual_style"), Mapping) else { }, consistency_rules=["one semantic ID per cell", "transparent background", "stable ground anchor", "no edge bleed"])
    meta = ContractMeta(contract_id=contract_id, revision=revision, parent_hash=parent_hash, source_intent_hash=_record_hash(record), status="draft")
    return DesignContract(meta=meta, intent=intent, core_loop=core, entities=entities, systems=systems, scenes=scenes, visual_style=visual, requirements=requirements, acceptance_tests=acceptance)


def _without_hash(contract: DesignContract) -> dict[str, Any]:
    payload = contract.model_dump(mode="json")
    payload.get("meta", {}).pop("contract_hash", None)
    return payload


def compute_contract_hash(contract: DesignContract | Mapping[str, Any]) -> str:
    model = contract if isinstance(contract, DesignContract) else DesignContract.model_validate(contract, strict=True)
    return hashlib.sha256(_canonical(_without_hash(model)).encode("utf-8")).hexdigest()


def diff_design_contracts(
    parent: DesignContract | Mapping[str, Any] | None,
    current: DesignContract | Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic invalidation summary between contract versions."""

    current_model = current if isinstance(current, DesignContract) else DesignContract.model_validate(current, strict=True)
    if not parent:
        semantic_ids = sorted(
            state.semantic_id
            for entity in current_model.entities
            for state in entity.states
        )
        return {
            "parent_hash": None,
            "added_semantic_ids": semantic_ids,
            "removed_semantic_ids": [],
            "changed_semantic_ids": [],
            "changed_requirement_ids": [item.id for item in current_model.requirements],
            "visual_style_changed": True,
            "asset_impacted": bool(semantic_ids),
            "code_impacted": True,
            "acceptance_impacted": bool(current_model.acceptance_tests),
        }
    parent_model = parent if isinstance(parent, DesignContract) else DesignContract.model_validate(parent, strict=True)

    def states(model: DesignContract) -> dict[str, dict[str, Any]]:
        return {
            state.semantic_id: state.model_dump(mode="json")
            for entity in model.entities
            for state in entity.states
        }

    old_states, new_states = states(parent_model), states(current_model)
    added = sorted(set(new_states) - set(old_states))
    removed = sorted(set(old_states) - set(new_states))
    changed = sorted(
        semantic_id
        for semantic_id in set(old_states) & set(new_states)
        if old_states[semantic_id] != new_states[semantic_id]
    )
    old_requirements = {
        item.id: item.model_dump(mode="json") for item in parent_model.requirements
    }
    new_requirements = {
        item.id: item.model_dump(mode="json") for item in current_model.requirements
    }
    changed_requirements = sorted(
        requirement_id
        for requirement_id in set(old_requirements) | set(new_requirements)
        if old_requirements.get(requirement_id) != new_requirements.get(requirement_id)
    )
    visual_style_changed = parent_model.visual_style != current_model.visual_style
    visual_terms = (
        "visual", "style", "art", "sprite", "palette", "color", "lighting",
        "appearance", "texture", "画风", "视觉", "美术", "素材", "颜色", "色彩",
        "光照", "外观", "贴图", "像素",
    )
    visual_amendment = any(
        any(ref.startswith("intent:feedback:") for ref in requirement.source_refs)
        and any(term in requirement.statement.lower() for term in visual_terms)
        for requirement in current_model.requirements
        if requirement.id in changed_requirements
    )
    systems_changed = parent_model.systems != current_model.systems
    scenes_changed = parent_model.scenes != current_model.scenes
    core_changed = parent_model.core_loop != current_model.core_loop
    acceptance_changed = parent_model.acceptance_tests != current_model.acceptance_tests
    return {
        "parent_hash": parent_model.meta.contract_hash,
        "added_semantic_ids": added,
        "removed_semantic_ids": removed,
        "changed_semantic_ids": changed,
        "changed_requirement_ids": changed_requirements,
        "visual_style_changed": visual_style_changed,
        "visual_amendment": visual_amendment,
        "asset_impacted": bool(added or removed or changed or visual_style_changed or visual_amendment),
        "code_impacted": bool(added or removed or changed or changed_requirements or systems_changed or scenes_changed or core_changed),
        "acceptance_impacted": acceptance_changed,
    }


def validate_contract(contract: DesignContract | Mapping[str, Any], *, require_frozen: bool = False) -> ContractGateResult:
    try:
        model = contract if isinstance(contract, DesignContract) else DesignContract.model_validate(contract, strict=True)
    except ValidationError as exc:
        return ContractGateResult(False, (f"schema_invalid: {exc}",), {}, "contract_gap")
    issues: list[str] = []
    if require_frozen and model.meta.status != DESIGN_CONTRACT_STATUS:
        issues.append("contract must be frozen before downstream execution")
    if model.meta.status == DESIGN_CONTRACT_STATUS:
        expected_hash = compute_contract_hash(model)
        if not model.meta.contract_hash or model.meta.contract_hash != expected_hash:
            issues.append("contract hash mismatch: frozen contract was modified after the gate")
    ids: list[str] = []
    for group in (model.entities, model.systems, model.scenes, model.requirements, model.acceptance_tests):
        ids.extend(str(item.id) for item in group)
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        issues.append("duplicate ids: " + ", ".join(duplicates))
    entity_ids = {entity.id for entity in model.entities}
    semantic_ids: set[str] = set()
    for entity in model.entities:
        if not entity.states:
            issues.append(f"entity {entity.id} has no semantic states")
        for state in entity.states:
            if state.semantic_id in semantic_ids:
                issues.append(f"duplicate semantic_id: {state.semantic_id}")
            semantic_ids.add(state.semantic_id)
            if not state.runtime_consumers:
                issues.append(f"required state has no runtime consumer: {state.semantic_id}")
    requirement_ids = {req.id for req in model.requirements}
    acceptance_ids = {test.id for test in model.acceptance_tests}
    for req in model.requirements:
        if not req.source_refs:
            issues.append(f"requirement {req.id} has no source_refs")
        if req.priority == "required" and not req.acceptance_ids:
            issues.append(f"required requirement has no acceptance: {req.id}")
        if any(aid not in acceptance_ids for aid in req.acceptance_ids):
            issues.append(f"requirement {req.id} references an unknown acceptance test")
        if any("…" in value or "..." in value for value in [req.statement, *req.source_refs]):
            issues.append(f"silent truncation marker in requirement: {req.id}")
    for test in model.acceptance_tests:
        if not test.requirement_ids or any(req_id not in requirement_ids for req_id in test.requirement_ids):
            issues.append(f"acceptance {test.id} has invalid requirement_ids")
        if not test.observable.strip() or not test.verification.strip():
            issues.append(f"acceptance {test.id} requires observable and verification")
    must_haves = list(model.intent.must_haves)
    covered = 0
    for item in must_haves:
        if any(item == req.id or item in req.source_refs or item.lower() in req.statement.lower() for req in model.requirements):
            covered += 1
    coverage = covered / len(must_haves) if must_haves else 1.0
    if coverage < 1.0:
        issues.append(f"required intent coverage is {coverage:.4f}, expected 1.0")
    for item in model.intent.must_not_haves:
        if not any(item.lower() in req.statement.lower() and req.constraints for req in model.requirements):
            issues.append(f"must_not_have is not an explicit constraint: {item}")
    if model.intent.unresolved:
        issues.append("required intent remains unresolved: " + ", ".join(model.intent.unresolved))
    metrics = {
        "required_intent_coverage": round(coverage, 4),
        "required_asset_state_count": len(semantic_ids),
        "required_acceptance_count": sum(1 for req in model.requirements if req.priority == "required"),
        "orphan_semantic_id": 0,
        "contract_hash": model.meta.contract_hash,
        "entity_count": len(entity_ids),
    }
    return ContractGateResult(not issues, tuple(issues), metrics, "contract_gap" if issues else None)


def freeze_contract(contract: DesignContract | Mapping[str, Any]) -> DesignContract:
    model = contract if isinstance(contract, DesignContract) else DesignContract.model_validate(contract, strict=True)
    result = validate_contract(model)
    if not result.passed:
        raise ContractCompileError("contract_gap: " + "; ".join(result.issues))
    frozen = model.model_copy(update={"meta": model.meta.model_copy(update={"status": DESIGN_CONTRACT_STATUS})})
    return frozen.model_copy(update={"meta": frozen.meta.model_copy(update={"contract_hash": compute_contract_hash(frozen)})})


def contract_to_design_payload(contract: DesignContract | Mapping[str, Any]) -> dict[str, Any]:
    model = contract if isinstance(contract, DesignContract) else DesignContract.model_validate(contract, strict=True)
    entities = []
    for entity in model.entities:
        row = {"id": entity.id, "name": entity.id, "role": entity.role, "footprint": entity.footprint, "interactions": entity.interactions, "states": [state.id for state in entity.states], "runtime_consumers": entity.runtime_consumers, "visual_requirements": entity.visual_requirements}
        if entity.role.lower().startswith("player"):
            row["visual"] = "player avatar"
        entities.append(row)
    scene_details = model.scenes[0].details if model.scenes else {}
    payload = {
        "title": scene_details.get("title") or model.meta.contract_id,
        "archetype": scene_details.get("archetype") or scene_details.get("genre") or "design_driven",
        "core_loop": ", ".join(model.core_loop.verbs),
        "entities": entities,
        "systems": [system.model_dump(mode="json") for system in model.systems],
        "scenes": [scene.model_dump(mode="json") for scene in model.scenes],
        "visual_style": model.visual_style.model_dump(mode="json"),
        "palette": model.visual_style.palette,
        "rules": next((system.details for system in model.systems if system.id == "game-rules"), {}),
        "requirements": [item.model_dump(mode="json") for item in model.requirements],
        "sprite_demand_manifest": derive_sprite_demand_manifest(model),
        "contract_hash": model.meta.contract_hash,
    }
    player = next((entity for entity in entities if str(entity.get("role", "")).lower().startswith("player")), None)
    if player:
        payload["player"] = player
    return payload


def contract_to_spec_payload(contract: DesignContract | Mapping[str, Any]) -> dict[str, Any]:
    model = contract if isinstance(contract, DesignContract) else DesignContract.model_validate(contract, strict=True)
    details = model.scenes[0].details if model.scenes else {}
    return {
        "title": details.get("title") or model.meta.contract_id,
        "genre": details.get("genre") or "design_driven",
        "archetype": details.get("archetype") or "design_driven",
        "theme": model.visual_style.theme,
        "visual_style": model.visual_style.model_dump(mode="json"),
        "core_loop": ", ".join(model.core_loop.verbs),
        "win_condition": model.core_loop.success_signal,
        "lose_condition": model.core_loop.failure_signal,
        "contract_hash": model.meta.contract_hash,
    }


def execution_design_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    view = state.get("design_execution_view")
    if isinstance(view, Mapping) and view:
        return dict(view)
    contract = state.get("design_contract")
    if isinstance(contract, Mapping) and contract:
        return contract_to_design_payload(contract)
    return dict(state.get("game_design") or {})


def execution_spec_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    view = state.get("spec_execution_view")
    if isinstance(view, Mapping) and view:
        return dict(view)
    contract = state.get("design_contract")
    if isinstance(contract, Mapping) and contract:
        return contract_to_spec_payload(contract)
    return dict(state.get("game_spec") or {})


def revision_directive_from_state(state: Mapping[str, Any]) -> str:
    """Return revision instructions from the frozen contract, never raw input.

    Legacy tasks without a DesignContract keep their historical feedback path;
    gated tasks expose amendments as traceable contract requirements.
    """

    contract = state.get("design_contract")
    if not isinstance(contract, Mapping) or not contract:
        return str(state.get("source_feedback") or state.get("prompt") or "")
    model = DesignContract.model_validate(contract, strict=True)
    amendments = [
        requirement.statement
        for requirement in model.requirements
        if any(ref.startswith("intent:feedback:") for ref in requirement.source_refs)
    ]
    instruction = (
        "; ".join(amendments)
        if amendments
        else "Implement the frozen DesignContract exactly and preserve all required behavior."
    )
    return f"DesignContract revision {model.meta.revision}: {instruction}"


def enforce_execution_boundary(state: Mapping[str, Any]) -> None:
    """Reject a stale, modified, or mixed-hash downstream execution state."""

    contract = state.get("design_contract")
    if not isinstance(contract, Mapping) or not contract:
        return
    model = DesignContract.model_validate(contract, strict=True)
    gate = validate_contract(model, require_frozen=True)
    if not gate.passed:
        raise ContractCompileError("contract_gap: " + "; ".join(gate.issues))
    expected = model.meta.contract_hash
    if state.get("contract_hash") != expected:
        raise ContractCompileError("contract_gap: execution state contract hash mismatch")
    for key in (
        "sprite_demand_manifest",
        "asset_batch_specs",
        "style_bible",
        "author_role_contracts",
        "acceptance_plan",
        "runtime_asset_requirements",
    ):
        view = state.get(key)
        if isinstance(view, Mapping) and view and view.get("contract_hash") != expected:
            raise ContractCompileError(f"contract_gap: {key} contract hash mismatch")


def derive_sprite_demand_manifest(contract: DesignContract | Mapping[str, Any]) -> dict[str, Any]:
    from app.services.sprite_pipeline import SpriteDemand, SpriteDemandManifest

    model = contract if isinstance(contract, DesignContract) else DesignContract.model_validate(contract, strict=True)
    demands = []
    runtime_consumers: dict[str, tuple[str, ...]] = {}
    for entity in model.entities:
        for state in entity.states:
            refs = tuple(dict.fromkeys(state.runtime_consumers or entity.runtime_consumers))
            runtime_consumers[state.semantic_id] = refs
            demands.append(SpriteDemand(
                semantic_id=state.semantic_id,
                frame_id=state.semantic_id.replace(".", "_"),
                object_name=entity.id,
                state=state.id,
                consumer_refs=refs,
                required=True,
                animated=state.id not in {"idle", "default"},
                batch_group=entity.id,
                variant_strategy=state.render_strategy,
                anchor=(0.5, 1.0),
                metadata={"role": entity.role, "visual_requirements": entity.visual_requirements},
            ))
    manifest = SpriteDemandManifest(tuple(demands), model.visual_style.model_dump(mode="json"), runtime_consumers)
    payload = manifest.to_dict()
    payload["contract_hash"] = model.meta.contract_hash
    return payload


def derive_contract_views(contract: DesignContract | Mapping[str, Any]) -> dict[str, Any]:
    from app.services.sprite_pipeline import SpriteDemandManifest, build_batch_specs

    model = contract if isinstance(contract, DesignContract) else DesignContract.model_validate(contract, strict=True)
    sprite = derive_sprite_demand_manifest(model)
    batches = {
        "schema_version": DESIGN_CONTRACT_VIEW_VERSION,
        "contract_hash": model.meta.contract_hash,
        "batches": [
            item.to_dict()
            for item in build_batch_specs(SpriteDemandManifest.from_dict(sprite))
        ],
    }
    acceptance = {"schema_version": DESIGN_CONTRACT_VIEW_VERSION, "contract_hash": model.meta.contract_hash, "tests": [test.model_dump(mode="json") for test in model.acceptance_tests]}
    role_names = sorted({test.owner for test in model.acceptance_tests} | {"IntegrationAgent"})
    role_contracts = {"schema_version": DESIGN_CONTRACT_VIEW_VERSION, "contract_hash": model.meta.contract_hash, "roles": [{"role": role, "requirements": [req.id for req in model.requirements if any(test.owner == role and req.id in test.requirement_ids for test in model.acceptance_tests)], "read_only": True} for role in role_names]}
    runtime = {"schema_version": DESIGN_CONTRACT_VIEW_VERSION, "contract_hash": model.meta.contract_hash, "semantic_ids": [state.semantic_id for entity in model.entities for state in entity.states], "consumers": {state.semantic_id: list(state.runtime_consumers) for entity in model.entities for state in entity.states}}
    style = {"schema_version": DESIGN_CONTRACT_VIEW_VERSION, "contract_hash": model.meta.contract_hash, **model.visual_style.model_dump(mode="json")}
    return {"contract_hash": model.meta.contract_hash, "sprite_demand_manifest": sprite, "asset_batch_specs": batches, "style_bible": style, "author_role_contracts": role_contracts, "acceptance_plan": acceptance, "runtime_asset_requirements": runtime}


def compile_and_freeze_design_contract(*args: Any, **kwargs: Any) -> tuple[DesignContract, dict[str, Any]]:
    draft = compile_design_contract(*args, **kwargs)
    gate = validate_contract(draft)
    if not gate.passed:
        raise ContractCompileError("contract_gap: " + "; ".join(gate.issues))
    return freeze_contract(draft), gate.to_dict()


# Friendly aliases used by nodes and external tooling.
contract_gate = validate_contract
hash_contract = compute_contract_hash


__all__ = [
    "DESIGN_CONTRACT_SCHEMA_VERSION",
    "DESIGN_CONTRACT_STATUS",
    "DESIGN_CONTRACT_VIEW_VERSION",
    "IntentRecord",
    "DesignContract",
    "ContractMeta",
    "ContractIntent",
    "CoreLoop",
    "ContractEntity",
    "EntityState",
    "ContractSystem",
    "ContractScene",
    "VisualStyle",
    "ContractRequirement",
    "AcceptanceTest",
    "ContractGateResult",
    "ContractCompileError",
    "ScopeExceededError",
    "build_intent_record",
    "compile_design_contract",
    "compile_and_freeze_design_contract",
    "validate_contract",
    "contract_gate",
    "freeze_contract",
    "compute_contract_hash",
    "diff_design_contracts",
    "hash_contract",
    "contract_to_design_payload",
    "contract_to_spec_payload",
    "execution_design_from_state",
    "execution_spec_from_state",
    "revision_directive_from_state",
    "enforce_execution_boundary",
    "derive_sprite_demand_manifest",
    "derive_contract_views",
]
