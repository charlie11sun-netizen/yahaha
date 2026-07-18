"""Typed design-contract boundary and deterministic contract emission."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict

from app.agents.planning_spec import structured_text
from app.agents.validation import FORBIDDEN_PATTERNS
from .author_prompts import (
    _ACCEPTANCE_EVIDENCE_PATH,
    _AUTHOR_CONTRACT_PATH,
    _CONTRACT_CAPTURE_LIMIT,
    _OWNERSHIP,
    _RESERVED_PATHS,
    _RoleDefinition,
)

class _StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ContractStateOutput(_StrictContractModel):
    name: str
    type: str
    owner: str
    meaning: str


class _ContractEventOutput(_StrictContractModel):
    name: str
    payload: str
    producer: str
    consumers: list[str]


class _ContractModuleOutput(_StrictContractModel):
    owner: Literal[
        "RulesAndSimulationCoder",
        "WorldAndContentCoder",
        "PresentationAndInteractionCoder",
        "IntegrationAgent",
    ]
    responsibility: str
    exports: list[str]
    depends_on: list[str]
    acceptance_ids: list[str]


class _ContractAcceptanceOutput(_StrictContractModel):
    id: str
    owner: Literal[
        "RulesAndSimulationCoder",
        "WorldAndContentCoder",
        "PresentationAndInteractionCoder",
        "IntegrationAgent",
    ]
    requirement: str
    observable: str
    verification: str


class _DesignContractOutput(_StrictContractModel):
    game_loop: str
    timing_model: Literal[
        "realtime",
        "fixed_timestep",
        "turn_based",
        "discrete",
        "narrative",
    ]
    state: list[_ContractStateOutput]
    events: list[_ContractEventOutput]
    modules: list[_ContractModuleOutput]
    integration_order: list[str]
    acceptance: list[_ContractAcceptanceOutput]


@dataclass(frozen=True)
class _ContractState:
    name: str
    type: str
    owner: str
    meaning: str


@dataclass(frozen=True)
class _ContractEvent:
    name: str
    payload: str
    producer: str
    consumers: tuple[str, ...]


@dataclass(frozen=True)
class _ContractModule:
    owner: str
    responsibility: str
    exports: tuple[str, ...]
    depends_on: tuple[str, ...]
    acceptance_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ContractAcceptance:
    id: str
    owner: str
    requirement: str
    observable: str
    verification: str


@dataclass(frozen=True)
class _FrozenContract:
    """Validated immutable boundary shared by every implementation role."""

    contract_version: int
    game_loop: str
    timing_model: str
    state: tuple[_ContractState, ...]
    events: tuple[_ContractEvent, ...]
    modules: tuple[_ContractModule, ...]
    integration_order: tuple[str, ...]
    acceptance: tuple[_ContractAcceptance, ...]
    ownership: tuple[tuple[str, tuple[str, ...]], ...]
    reserved_paths: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "contract_version": self.contract_version,
            "game_loop": self.game_loop,
            "timing_model": self.timing_model,
            "state": [
                {
                    "name": item.name,
                    "type": item.type,
                    "owner": item.owner,
                    "meaning": item.meaning,
                }
                for item in self.state
            ],
            "events": [
                {
                    "name": item.name,
                    "payload": item.payload,
                    "producer": item.producer,
                    "consumers": list(item.consumers),
                }
                for item in self.events
            ],
            "modules": [
                {
                    "owner": item.owner,
                    "responsibility": item.responsibility,
                    "exports": list(item.exports),
                    "depends_on": list(item.depends_on),
                    "acceptance_ids": list(item.acceptance_ids),
                }

                for item in self.modules
            ],
            "integration_order": list(self.integration_order),
            "acceptance": [
                {
                    "id": item.id,
                    "owner": item.owner,
                    "requirement": item.requirement,
                    "observable": item.observable,
                    "verification": item.verification,
                }
                for item in self.acceptance
            ],
            "ownership": {owner: list(paths) for owner, paths in self.ownership},
            "reserved_paths": list(self.reserved_paths),
        }

    def __getitem__(self, key: str):
        # Backward-compatible convenience for the focused offline tests.
        return self.as_dict()[key]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _snapshot_revision(files: list[dict]) -> str:
    rows = sorted(
        (str(item.get("path") or ""), str(item.get("content") or ""))
        for item in files or []
    )
    return hashlib.sha256(_canonical_json(rows).encode("utf-8")).hexdigest()


def _json_object(text: str) -> dict | None:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```")
        raw = raw.rsplit("```", 1)[0].strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _structured_contract_payload(value: object) -> dict | None:
    """Consume the SDK's typed final output without reparsing the display note."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, dict):
        return dict(value)
    return None


def _list_of_dicts(value: object, *, limit: int = 40) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:limit] if isinstance(item, dict)]


def _list_of_text(value: object, *, limit: int = 40) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value[:limit] if str(item).strip()]


def _text_tuple(value: object, *, limit: int = 20, width: int = 300) -> tuple[str, ...]:
    rows = value if isinstance(value, list) else [value]
    return tuple(
        str(item).strip()[:width] for item in rows[:limit] if str(item or "").strip()
    )


def _safe_contract_text(value: object, *, width: int) -> str:
    text = str(value or "").strip()[:width]
    for pattern, _label in FORBIDDEN_PATTERNS:
        text = re.sub(pattern, "[blocked-api]", text, flags=re.IGNORECASE)
    return text


_TYPESCRIPT_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_GENERIC_EXPORT_NAMES = {
    "api",
    "data",
    "export",
    "exports",
    "module",
    "service",
    "system",
    "type",
    "typed",
}


def _contract_identifiers(value: object, *, limit: int = 20) -> tuple[str, ...]:
    identifiers = _text_tuple(value, limit=limit, width=120)
    if not identifiers:
        raise ValueError("contract module must declare concrete TypeScript exports")
    invalid = [
        item
        for item in identifiers
        if not _TYPESCRIPT_IDENTIFIER.fullmatch(item)
        or item.lower() in _GENERIC_EXPORT_NAMES
    ]
    if invalid:
        raise ValueError(
            "contract module has non-concrete TypeScript exports: "
            + ", ".join(invalid)
        )
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("contract module repeats a TypeScript export")
    return identifiers


def _fallback_contract(spec: dict, design: dict) -> dict:
    genre = str(spec.get("genre") or design.get("archetype") or "arcade").lower()
    if any(token in genre for token in ("card", "turn", "strategy", "tower_defense")):
        timing = "turn_based"
    elif "rhythm" in genre:
        timing = "fixed_timestep"
    elif any(token in genre for token in ("puzzle", "board", "grid")):
        timing = "discrete"
    elif any(token in genre for token in ("novel", "narrative", "story")):
        timing = "narrative"
    else:
        timing = "realtime"
    loop = structured_text(
        spec.get("core_loop")
        or design.get("signature_twist")
        or "play, react, progress",
        limit=1200,
    )
    acceptance = [
        {
            "id": "REQ-RULES-CORE",
            "owner": "RulesAndSimulationCoder",
            "requirement": f"Core rules implement the designed loop: {loop}",
            "observable": "Player input changes legal game state and produces progress.",
            "verification": "Exercise the primary action and observe a rules-owned state transition.",
        },
        {
            "id": "REQ-WORLD-CONTENT",
            "owner": "WorldAndContentCoder",
            "requirement": "Playable actors/content are represented by concrete typed data or factories.",
            "observable": "A run contains genre-appropriate interactive content rather than placeholder labels.",
            "verification": "Inspect the content registry/factory and observe it instantiated during play.",
        },
        {
            "id": "REQ-PRESENTATION-FEEDBACK",
            "owner": "PresentationAndInteractionCoder",
            "requirement": "Input, state feedback, and the essential HUD are usable.",
            "observable": "The player can understand controls, state changes, and important outcomes.",
            "verification": "Use the primary controls and observe HUD plus audiovisual feedback update.",
        },
        {
            "id": "REQ-RULES-WIN",
            "owner": "RulesAndSimulationCoder",
            "requirement": f"Win condition is reachable: {spec.get('win_condition') or (design.get('rules') or {}).get('win') or 'design-defined win'}",
            "observable": "Completing the objective enters a won terminal state.",

            "verification": "Reach the objective and observe the win result path.",
        },
        {
            "id": "REQ-RULES-LOSS",
            "owner": "RulesAndSimulationCoder",
            "requirement": f"Loss condition is reachable: {spec.get('lose_condition') or (design.get('rules') or {}).get('lose') or 'design-defined loss'}",
            "observable": "Failing the objective enters a lost terminal state.",
            "verification": "Trigger the failure condition and observe the loss result path.",
        },
        {
            "id": "REQ-INTEGRATION-RESTART",
            "owner": "IntegrationAgent",
            "requirement": "Restart works without reloading the page.",
            "observable": "A completed run can start a fresh playable state from the UI or bound control.",
            "verification": "Finish or fail a run, restart, and observe reset state and active input.",
        },
    ]
    twist = design.get("signature_twist")
    if twist:
        acceptance.append(
            {
                "id": "REQ-RULES-TWIST",
                "owner": "RulesAndSimulationCoder",
                "requirement": f"Signature twist is implemented: {twist}",
                "observable": "The twist changes decisions or outcomes during normal play.",
                "verification": "Trigger the twist and compare the resulting legal state or reward.",
            }
        )
    result = {
        "game_loop": loop,
        "timing_model": timing,
        "state": [
            {
                "name": "phase",
                "type": "string",
                "owner": "RulesAndSimulationCoder",
                "meaning": "current game phase",
            },
            {
                "name": "score",
                "type": "number",
                "owner": "RulesAndSimulationCoder",
                "meaning": "risk-reward score",
            },
            {
                "name": "outcome",
                "type": "'playing'|'won'|'lost'",
                "owner": "RulesAndSimulationCoder",
                "meaning": "terminal state",
            },
        ],
        "events": [
            {
                "name": "game:state-changed",
                "payload": "state snapshot",
                "producer": "RulesAndSimulationCoder",
                "consumers": ["PresentationAndInteractionCoder", "IntegrationAgent"],
            },
            {
                "name": "game:feedback",
                "payload": "feedback cue",
                "producer": "RulesAndSimulationCoder",
                "consumers": ["PresentationAndInteractionCoder"],
            },
        ],
        "modules": [
            {
                "owner": "RulesAndSimulationCoder",
                "responsibility": "genre rules and simulation",
                "exports": ["GameRules", "GameSimulationState"],
                "depends_on": [],
                "acceptance_ids": [
                    "REQ-RULES-CORE",
                    "REQ-RULES-WIN",
                    "REQ-RULES-LOSS",
                    *(["REQ-RULES-TWIST"] if twist else []),
                ],
            },
            {
                "owner": "WorldAndContentCoder",
                "responsibility": "actors and playable content",
                "exports": ["GameContentRegistry"],
                "depends_on": [],
                "acceptance_ids": ["REQ-WORLD-CONTENT"],
            },
            {
                "owner": "PresentationAndInteractionCoder",
                "responsibility": "input and presentation",
                "exports": ["GameInputAdapter", "GameHudView"],
                "depends_on": ["GameSimulationState"],
                "acceptance_ids": ["REQ-PRESENTATION-FEEDBACK"],
            },
            {
                "owner": "IntegrationAgent",
                "responsibility": "scene composition",
                "exports": ["PlayScene"],
                "depends_on": [
                    "GameRules",
                    "GameContentRegistry",
                    "GameInputAdapter",
                    "GameHudView",
                ],
                "acceptance_ids": ["REQ-INTEGRATION-RESTART"],
            },
        ],
        "integration_order": [
            "create shared types",
            "compose rules and content",
            "connect input and feedback",
            "wire scene lifecycle",
            "run checks",
        ],
        "acceptance": acceptance,
    }
    corpus = json.dumps({"spec": spec or {}, "design": design or {}}, ensure_ascii=False, default=str).lower()
    def mentions(*terms: str) -> bool:
        return any(term.lower() in corpus for term in terms)
    modules = result["modules"]
    presentation = next(item for item in modules if item["owner"] == "PresentationAndInteractionCoder")
    integration = next(item for item in modules if item["owner"] == "IntegrationAgent")
    world = next(item for item in modules if item["owner"] == "WorldAndContentCoder")
    inventory = []
    for label in ("cards", "enemies", "weapons", "relics", "rooms", "buildings", "recipes", "characters"):
        values = []
        for container in (spec or {}, design or {}):
            if isinstance(container, dict) and isinstance(container.get(label), list):
                values.extend(container[label])
        if values:
            inventory.append(f"{label}={len(values)}")
    if inventory:
        world_acceptance = next(item for item in acceptance if item["id"] == "REQ-WORLD-CONTENT")
        world_acceptance["requirement"] += " Preserve the designed inventory minimums: " + "; ".join(inventory) + "."
    if isinstance(twist, dict):
        twist_text = ", ".join(f"{key}: {value}" for key, value in twist.items())
        twist_acceptance = next((item for item in acceptance if item["id"] == "REQ-RULES-TWIST"), None)
        if twist_acceptance:
            twist_acceptance["requirement"] = "Signature twist is implemented: " + twist_text
    def add_acceptance(row: dict, module: dict, export: str | None = None) -> None:
        acceptance.append(row)
        module["acceptance_ids"].append(row["id"])
        if export and export not in module["exports"]:
            module["exports"].append(export)
    if mentions("save", "persistence", "存档", "保存"):
        add_acceptance({
            "id": "REQ-PRESENTATION-PERSISTENCE",
            "owner": "PresentationAndInteractionCoder",
            "requirement": "Provide versioned persistence through GameWeaveBridge load/save.",
            "observable": "Reachable gameplay restores and saves meaningful progress.",
            "verification": "Wire the service and observe versioned GameWeaveBridge load/save calls.",
        }, presentation, "GamePersistenceService")
    if mentions("settings", "options", "设置") or mentions("rebind", "remap", "key rebinding", "改键") or mentions("volume", "master volume"):
        requested = []
        if mentions("settings", "options", "设置"): requested.append("settings UI")
        if mentions("rebind", "remap", "key rebinding", "改键"): requested.append("key rebinding")
        if mentions("volume", "master volume"): requested.append("0..1 volume control")
        add_acceptance({
            "id": "REQ-PRESENTATION-SETTINGS",
            "owner": "PresentationAndInteractionCoder",
            "requirement": "Implement reachable " + ", ".join(requested) + ".",
            "observable": "The player can change settings and observe the applied behavior.",
            "verification": "Drive the settings/binding service from reachable UI and verify the applied state.",
        }, presentation, "SettingsService")
        if mentions("rebind", "remap", "key rebinding", "改键"):
            if "InputBindingService" not in presentation["exports"]:
                presentation["exports"].append("InputBindingService")
    if mentions("pause", "tutorial", "map screen", "minimap"):
        add_acceptance({
            "id": "REQ-PRESENTATION-FLOWS",
            "owner": "PresentationAndInteractionCoder",
            "requirement": "Implement the requested pause, tutorial, and map/navigation flows.",
            "observable": "Support screens open from normal play and resume safely.",
            "verification": "Open each requested flow and return to the same playable state.",
        }, presentation)
    if mentions("extensible", "extendable", "data-driven", "easy to add"):
        add_acceptance({
            "id": "REQ-INTEGRATION-EXTENSIBLE",
            "owner": "IntegrationAgent",
            "requirement": "Keep repeated content data-driven and easy to extend.",
            "observable": "Adding a content record does not require scene rewrites.",
            "verification": "Trace a registry record through the integrated scene.",
        }, integration)
    if "REQ-INTEGRATION-PLAYABLE" not in integration["acceptance_ids"]:
        add_acceptance({
            "id": "REQ-INTEGRATION-PLAYABLE",
            "owner": "IntegrationAgent",
            "requirement": "Replace the neutral placeholder with the genre-faithful playable loop.",
            "observable": "The first play session accepts input and reaches success and failure paths.",
            "verification": "Start PlayScene, perform the primary action, and exercise win/loss transitions.",
        }, integration)
    if "REQ-INTEGRATION-ASSETS" not in integration["acceptance_ids"]:
        add_acceptance({
            "id": "REQ-INTEGRATION-ASSETS",
            "owner": "IntegrationAgent",
            "requirement": "Use configured generated backgrounds, sprite sheets, frames, and animations in gameplay.",
            "observable": "Generated art remains visible behind readable gameplay surfaces.",
            "verification": "Trace configured assets into PlayScene-created visuals.",
        }, integration)
    return result


def _repair_contract(raw: dict | None, spec: dict, design: dict) -> tuple[dict, list[str]]:
    """Repair common model omissions before the immutable freeze step."""
    fallback = _fallback_contract(spec, design)
    repaired = json.loads(json.dumps(raw or fallback, ensure_ascii=False, default=str))
    fixes: list[str] = []
    modules = repaired.setdefault("modules", [])
    acceptance = repaired.setdefault("acceptance", [])
    owners = {str(item.get("owner")) for item in modules if isinstance(item, dict)}
    if "IntegrationAgent" not in owners:
        fallback_module = next(item for item in fallback["modules"] if item["owner"] == "IntegrationAgent")
        fallback_module = json.loads(json.dumps(fallback_module))
        known_ids = {str(item.get("id") or "") for item in acceptance if isinstance(item, dict)}
        fallback_module["acceptance_ids"] = [item for item in fallback_module.get("acceptance_ids", []) if item in known_ids]
        if not fallback_module["acceptance_ids"]:
            fallback_module["acceptance_ids"] = ["__synthetic_integration__"]
            acceptance.append({
                "id": "__synthetic_integration__",
                "owner": "IntegrationAgent",
                "requirement": "Integrate the delivered role modules.",
                "observable": "The integrated scene is playable.",
                "verification": "Start the integrated scene and exercise one complete loop.",
            })
        modules.append(fallback_module)
        fixes.append("synthesized missing IntegrationAgent module")
    by_owner = {
        str(item.get("owner")): item
        for item in modules
        if isinstance(item, dict) and str(item.get("owner"))
    }
    covered = {
        str(identifier)
        for module in modules
        if isinstance(module, dict)
        for identifier in (module.get("acceptance_ids") or [])
    }
    for item in acceptance:
        if not isinstance(item, dict):
            continue
        acceptance_id = str(item.get("id") or "")
        owner = str(item.get("owner") or "")
        if acceptance_id and acceptance_id not in covered and owner in by_owner:
            by_owner[owner].setdefault("acceptance_ids", []).append(acceptance_id)
            covered.add(acceptance_id)
            fixes.append(f"attached uncovered acceptance {acceptance_id} to {owner}")
    repaired.setdefault("state", fallback["state"])
    repaired.setdefault("events", fallback["events"])
    repaired.setdefault("integration_order", fallback["integration_order"])
    repaired.setdefault("game_loop", fallback["game_loop"])
    repaired.setdefault("timing_model", fallback["timing_model"])
    return repaired, fixes


def _freeze_contract(raw: dict | None, spec: dict, design: dict) -> _FrozenContract:
    fallback = _fallback_contract(spec, design)
    source = raw or fallback
    state_rows = _list_of_dicts(source.get("state")) or fallback["state"]
    event_rows = _list_of_dicts(source.get("events")) or fallback["events"]
    module_rows = _list_of_dicts(source.get("modules")) or fallback["modules"]
    acceptance_rows = (
        _list_of_dicts(source.get("acceptance")) or fallback["acceptance"]
    )
    states = tuple(
        _ContractState(
            name=_safe_contract_text(item.get("name") or "state", width=120),
            type=_safe_contract_text(item.get("type") or "unknown", width=240),
            owner=_safe_contract_text(
                item.get("owner") or "RulesAndSimulationCoder", width=120
            ),
            meaning=_safe_contract_text(item.get("meaning"), width=300),
        )
        for item in state_rows[:24]
    )
    events = tuple(
        _ContractEvent(
            name=_safe_contract_text(item.get("name") or "game:event", width=160),
            payload=_safe_contract_text(item.get("payload") or "unknown", width=300),

            producer=_safe_contract_text(
                item.get("producer") or "RulesAndSimulationCoder", width=120
            ),
            consumers=tuple(
                _safe_contract_text(item, width=120)
                for item in _text_tuple(item.get("consumers"), limit=8, width=120)
            ),
        )
        for item in event_rows[:24]
    )
    modules = tuple(
        _ContractModule(
            owner=_safe_contract_text(
                item.get("owner") or "IntegrationAgent", width=120
            ),
            responsibility=_safe_contract_text(item.get("responsibility"), width=300),
            exports=_contract_identifiers(item.get("exports")),
            depends_on=tuple(
                _safe_contract_text(item, width=160)
                for item in _text_tuple(item.get("depends_on"), limit=8, width=160)
            ),
            acceptance_ids=tuple(
                _safe_contract_text(item, width=120)
                for item in _text_tuple(
                    item.get("acceptance_ids"), limit=64, width=120
                )
            ),
        )
        for item in module_rows[:20]
    )
    acceptance = tuple(
        _ContractAcceptance(
            id=_safe_contract_text(item.get("id"), width=120),
            owner=_safe_contract_text(item.get("owner"), width=120),
            requirement=_safe_contract_text(item.get("requirement"), width=500),
            observable=_safe_contract_text(item.get("observable"), width=500),
            verification=_safe_contract_text(item.get("verification"), width=500),
        )
        for item in acceptance_rows[:64]
    )
    valid_owners = set(_OWNERSHIP)
    if not modules or not acceptance:
        raise ValueError("contract must define modules and acceptance requirements")
    invalid_owners = sorted(
        {
            item.owner
            for item in (*modules, *acceptance)
        if item.owner not in valid_owners
        }
    )
    if invalid_owners:
        raise ValueError("contract has invalid owners: " + ", ".join(invalid_owners))
    for module in modules:
        if len(module.exports) > 6:
            raise ValueError(f"contract module for {module.owner} has too many exports")
    missing_module_owners = sorted(valid_owners - {item.owner for item in modules})
    if missing_module_owners:
        raise ValueError(
            "contract has no module for owners: " + ", ".join(missing_module_owners)
        )
    acceptance_ids = [item.id for item in acceptance]
    if any(not item for item in acceptance_ids):
        raise ValueError("contract acceptance ids must be non-empty")
    duplicate_ids = sorted(
        {item for item in acceptance_ids if acceptance_ids.count(item) > 1}
    )
    if duplicate_ids:
        raise ValueError(
            "contract repeats acceptance ids: " + ", ".join(duplicate_ids)
        )
    acceptance_by_id = {item.id: item for item in acceptance}
    referenced_ids = {
        acceptance_id for module in modules for acceptance_id in module.acceptance_ids
    }
    unknown_ids = sorted(referenced_ids - set(acceptance_by_id))
    if unknown_ids:
        raise ValueError(
            "contract modules reference unknown acceptance ids: "
            + ", ".join(unknown_ids)
        )
    uncovered_ids = sorted(set(acceptance_by_id) - referenced_ids)
    if uncovered_ids:
        raise ValueError(
            "contract acceptance ids have no module coverage: "
            + ", ".join(uncovered_ids)
        )
    missing_owner_coverage = sorted(
        acceptance_id
        for acceptance_id, acceptance_item in acceptance_by_id.items()
        if not any(
            module.owner == acceptance_item.owner
            and acceptance_id in module.acceptance_ids
            for module in modules
        )
    )
    if missing_owner_coverage:
        raise ValueError(
            "contract acceptance ids have no owner module coverage: "
            + ", ".join(missing_owner_coverage)
        )
    empty_module_coverage = [
        module.owner for module in modules if not module.acceptance_ids
    ]
    if empty_module_coverage:
        raise ValueError(
            "contract modules have no acceptance ids: "
            + ", ".join(empty_module_coverage)
        )
    return _FrozenContract(
        contract_version=2,
        game_loop=_safe_contract_text(
            source.get("game_loop") or fallback["game_loop"], width=1000
        ),
        timing_model=_safe_contract_text(
            source.get("timing_model") or fallback["timing_model"], width=80
        ),
        state=states,
        events=events,
        modules=modules,
        integration_order=tuple(
            _safe_contract_text(item, width=300)
            for item in (
                _list_of_text(source.get("integration_order"), limit=20)
                or fallback["integration_order"]
            )
        ),
        acceptance=acceptance,
        # Model output cannot widen these tool-enforced boundaries.
        ownership=tuple((owner, tuple(paths)) for owner, paths in _OWNERSHIP.items()),
        reserved_paths=tuple(_RESERVED_PATHS),
    )


def _contract_typescript(contract: _FrozenContract, contract_hash: str) -> str:
    payload = json.dumps(contract.as_dict(), ensure_ascii=False, indent=2)
    return f"""// Generated by GameCodeAgent. This owner boundary is immutable.
// Contract hash: {contract_hash}
export interface AuthorContractState {{
  readonly name: string;
  readonly type: string;
  readonly owner: string;
  readonly meaning: string;
}}


export interface AuthorContractEvent {{
  readonly name: string;
  readonly payload: string;
  readonly producer: string;
  readonly consumers: readonly string[];
}}

export interface AuthorContractModule {{
  readonly owner: string;
  readonly responsibility: string;
  readonly exports: readonly string[];
  readonly depends_on: readonly string[];
  readonly acceptance_ids: readonly string[];
}}

export interface AuthorContractAcceptance {{
  readonly id: string;
  readonly owner: string;
  readonly requirement: string;
  readonly observable: string;
  readonly verification: string;
}}

export interface AuthorGameContract {{
  readonly contract_version: number;
  readonly game_loop: string;
  readonly timing_model: string;
  readonly state: readonly AuthorContractState[];
  readonly events: readonly AuthorContractEvent[];
  readonly modules: readonly AuthorContractModule[];
  readonly integration_order: readonly string[];
  readonly acceptance: readonly AuthorContractAcceptance[];
  readonly ownership: Readonly<Record<string, readonly string[]>>;
  readonly reserved_paths: readonly string[];
}}

const contractData = {payload} as const satisfies AuthorGameContract;

export const AUTHOR_GAME_CONTRACT: AuthorGameContract = Object.freeze(contractData);
export const AUTHOR_GAME_CONTRACT_HASH = {json.dumps(contract_hash)} as const;
"""


def _with_contract_file(
    files: list[dict], contract: _FrozenContract, contract_hash: str
) -> list[dict]:
    generated = _contract_typescript(contract, contract_hash)
    result: list[dict] = []
    replaced = False
    for item in files:
        if item.get("path") == _AUTHOR_CONTRACT_PATH:
            result.append({"path": _AUTHOR_CONTRACT_PATH, "content": generated})
            replaced = True
        else:
            result.append(dict(item))
    if not replaced:
        result.append({"path": _AUTHOR_CONTRACT_PATH, "content": generated})
    return result


def _compact_brief(spec: dict, design: dict) -> dict:
    brief = {
        "title": spec.get("title"),
        "genre": spec.get("genre") or design.get("archetype"),
        "core_loop": spec.get("core_loop"),
        "signature_twist": design.get("signature_twist"),
    }
    # 实现作者看不到完整 design,但关卡几何不能少:level_layout 是"画出来的
    # 背景 = 碰撞几何 = 敌人路线"的共同事实源(gameConfig.levelLayout 里有
    # 换算好的像素版,LevelLayout.ts 直接消费)。
    if design.get("level_layout"):
        brief["level_layout"] = design["level_layout"]
    return brief


def _contract_input(
    spec: dict,
    design: dict,
    runtime: str,
    dimension: str,
    qa_feedback: list | None,
    chained: bool = False,
) -> str:
    parts = [
        "Produce the frozen architecture contract for this generated game project.",
        f"GameSpec:\n{json.dumps(spec, ensure_ascii=False)}",
        f"GameDesign:\n{json.dumps(design, ensure_ascii=False)}",
        f"Runtime: {runtime}; dimension: {dimension}",
        "Do not inspect workspace files or call tools; use the supplied scaffold context and return JSON only.",
    ]
    if chained:
        # The replayed planning conversation contains the raw pre-merge design
        # draft; the JSON in this message has balance/content plans merged in.
        parts.insert(
            1,
            "The planning conversation above explains the intent behind this design. "
            "Where the GameSpec/GameDesign JSON below differs from any earlier draft "
            "in that conversation, the JSON below is canonical and wins.",
        )
    if qa_feedback:
        parts.insert(
            4 if chained else 3,
            "Previous gameplay QA findings:\n"
            + "\n".join(f"- {item}" for item in qa_feedback),
        )
    return "\n\n".join(parts)


def _role_input(
    role: _RoleDefinition,
    spec: dict,
    design: dict,
    contract_hash: str,
    base_revision: str,
    qa_feedback: list | None,
    available_paths: Iterable[str] = (),
) -> str:
    path_inventory = sorted({str(path) for path in available_paths if str(path)})
    parts = [
        f"Implement the {role.name} portion of this frozen project snapshot.",
        f"Base revision: {base_revision}",
        f"Contract hash: {contract_hash}",
        f"Immutable contract file: {_AUTHOR_CONTRACT_PATH}",
        f"Compact brief:\n{json.dumps(_compact_brief(spec, design), ensure_ascii=False)}",
        "Available source paths (use these exact names; do not guess absent files):\n"
        + "\n".join(f"- {path}" for path in path_inventory[:100]),
        f"Begin with exactly ONE read_files batch: {_AUTHOR_CONTRACT_PATH} plus the scaffold types needed by {role.name}.",
        "Do not wire scenes. Your output is an isolated candidate patch for IntegrationAgent.",
    ]
    if qa_feedback:
        parts.insert(
            5,
            "Gameplay QA findings this implementation must address:\n"
            + "\n".join(f"- {item}" for item in qa_feedback),
        )
    return "\n\n".join(parts)


def _retry_role_input(
    role: _RoleDefinition,
    *,
    contract_hash: str,
    base_revision: str,
    error: str,
) -> str:
    return "\n\n".join(
        [
            f"Repair the rejected {role.name} candidate once; do not broaden its scope.",
            f"Base revision: {base_revision}",
            f"Contract hash: {contract_hash}",
            f"Immutable contract file: {_AUTHOR_CONTRACT_PATH}",
            f"Candidate rejection: {error}",
            "Read the immutable contract and the previously edited owned files, remove the precise violation, and finish with DONE: <exports produced>.",
        ]
    )
