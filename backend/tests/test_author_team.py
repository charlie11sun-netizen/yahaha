"""Offline coverage for the bounded modular project author team."""

from __future__ import annotations

import json
import posixpath
import re
import sys
import threading
from types import ModuleType

import pytest

from app.agents import author_team, code_agent
from app.agents.agent_tools import _make_tools
from app.services.phaser_projects import create_modular_phaser_project
from app.services.vite_projects import validate_vite_project


def _project() -> list[dict]:
    return create_modular_phaser_project(
        {
            "title": "Contract Test",
            "genre": "strategy",
            "core_loop": "place, simulate, adapt",
        },
        {"signature_twist": "storms reroute units"},
        {},
        {},
    )


def _outcome(
    session,
    *,
    note="DONE",
    tokens=1,
    turns=1,
    checks_ok=False,
    stop_reason=None,
    raw_output=None,
):
    if raw_output is None and str(note).lstrip().startswith("{"):
        raw_output = json.loads(note)
    return code_agent.RepairOutcome(
        files=session.to_files(),
        changed=sorted(session.changed),
        tokens=tokens,
        logs=list(session.log_lines),
        note=note,
        checks_ok=checks_ok,
        turns=turns,
        stop_reason=stop_reason
        or ("max_turns" if str(note).lower().startswith("max turns") else "completed"),
        quality_state="valid" if session.changed or checks_ok else "empty",
        raw_output=raw_output,
    )


def _contract_note() -> str:
    return json.dumps(
        {
            "game_loop": "place defenses, advance the simulation, react to storms",
            "timing_model": "turn_based",
            "state": [
                {
                    "name": "turn",
                    "type": "number",
                    "owner": "RulesAndSimulationCoder",
                    "meaning": "current turn",
                }
            ],
            "events": [
                {
                    "name": "turn:resolved",
                    "payload": "TurnResult",
                    "producer": "RulesAndSimulationCoder",
                    "consumers": ["PresentationAndInteractionCoder"],
                }
            ],
            "modules": [
                {
                    "owner": "RulesAndSimulationCoder",
                    "responsibility": "resolve turns",
                    "exports": ["TurnResolver"],
                    "depends_on": [],
                    "acceptance_ids": ["REQ-RULES"],
                },
                {
                    "owner": "WorldAndContentCoder",
                    "responsibility": "storm content",
                    "exports": ["StormBeacon"],
                    "depends_on": [],
                    "acceptance_ids": ["REQ-WORLD"],
                },
                {
                    "owner": "PresentationAndInteractionCoder",
                    "responsibility": "turn feedback",
                    "exports": ["TurnHud"],
                    "depends_on": ["TurnResolver"],
                    "acceptance_ids": ["REQ-PRESENTATION"],
                },
                {
                    "owner": "IntegrationAgent",
                    "responsibility": "compose scene",
                    "exports": ["PlayScene"],
                    "depends_on": ["TurnResolver", "StormBeacon", "TurnHud"],
                    "acceptance_ids": ["REQ-INTEGRATION"],
                }
            ],
            "integration_order": ["create contracts", "compose scene", "run checks"],
            "acceptance": [
                {
                    "id": "REQ-RULES",
                    "owner": "RulesAndSimulationCoder",
                    "requirement": "turn resolution changes state",
                    "observable": "advancing a turn changes the simulation",
                    "verification": "invoke TurnResolver and inspect the next turn",
                },
                {
                    "id": "REQ-WORLD",
                    "owner": "WorldAndContentCoder",
                    "requirement": "storms are concrete playable content",
                    "observable": "storm beacons appear in the game",
                    "verification": "instantiate StormBeacon during a run",
                },
                {
                    "id": "REQ-PRESENTATION",
                    "owner": "PresentationAndInteractionCoder",
                    "requirement": "turn feedback is readable",
                    "observable": "the HUD displays the current turn",
                    "verification": "advance a turn and observe TurnHud update",
                },
                {
                    "id": "REQ-INTEGRATION",
                    "owner": "IntegrationAgent",
                    "requirement": "role modules are composed into play",
                    "observable": "the Play scene starts the integrated loop",
                    "verification": "start PlayScene and exercise one complete turn",
                },
            ],
        }
    )


def _contract_payload(session) -> dict:
    source = session.contents[author_team._AUTHOR_CONTRACT_PATH]
    match = re.search(
        r"const contractData = (\{.*\}) as const satisfies AuthorGameContract;",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _write_standard_candidate(session, agent_name: str) -> None:
    if agent_name == "RulesAndSimulationCoder":
        session.write_file(
            "src/systems/rules/TurnResolver.ts",
            "export class TurnResolver { resolve(turn: number): number { return turn + 1; } }",
        )
    elif agent_name == "WorldAndContentCoder":
        session.write_file(
            "src/entities/StormBeacon.ts",
            "export class StormBeacon { constructor(public strength = 1) {} }",
        )
    elif agent_name == "PresentationAndInteractionCoder":
        session.write_file(
            "src/ui/TurnHud.ts",
            "export class TurnHud { setTurn(_turn: number): void {} }",
        )


def _integrate_with_evidence(session) -> None:
    contract = _contract_payload(session)
    contract_hash = re.search(
        r"Contract hash: ([a-f0-9]+)",
        session.contents[author_team._AUTHOR_CONTRACT_PATH],
    ).group(1)
    assigned_exports = {
        requirement["id"]: {
            identifier
            for module in contract["modules"]
            if requirement["id"] in module["acceptance_ids"]
            for identifier in module["exports"]
        }
        for requirement in contract["acceptance"]
    }
    export_paths: dict[str, str] = {}
    for acceptance_exports in assigned_exports.values():
        for identifier in acceptance_exports:
            for path, source in session.contents.items():
                if path.startswith("src/contracts/"):
                    continue
                if re.search(
                    rf"\bexport\s+(?:default\s+)?(?:class|interface|type|const|function)\s+{re.escape(identifier)}\b",
                    source,
                ):
                    export_paths[identifier] = path
                    break

    play_path = "src/scenes/PlayScene.ts"
    play_source = session.contents[play_path].replace(
        "GW_PLACEHOLDER_GAMEPLAY", "GW_TEAM_GAMEPLAY"
    )
    runtime_exports = sorted(
        {
            identifier
            for requirement in contract["acceptance"]
            if requirement["owner"] != "IntegrationAgent"
            for identifier in assigned_exports[requirement["id"]]
        }
    )
    imports = []
    for identifier in runtime_exports:
        export_path = export_paths[identifier]
        relative = posixpath.relpath(
            export_path.removesuffix(".ts"), posixpath.dirname(play_path)
        )
        if not relative.startswith("."):
            relative = "./" + relative
        imports.append(f"import {{ {identifier} }} from '{relative}';")
    if runtime_exports:
        # Real usage-position wiring (constructing every export) — import lines
        # and inert `void X;` references no longer count as consumption.
        wiring_lines = [
            f"export const gwWired{index} = new {identifier}();"
            for index, identifier in enumerate(runtime_exports)
        ]
        play_source = (
            "\n".join(imports) + "\n" + play_source + "\n" + "\n".join(wiring_lines) + "\n"
        )
    session.write_file(play_path, play_source)

    requirements = []
    for requirement in contract["acceptance"]:
        identifiers = sorted(assigned_exports[requirement["id"]])
        runtime_symbol = identifiers[0]
        evidence = []
        if requirement["owner"] != "IntegrationAgent":
            evidence.append(
                {"path": export_paths[runtime_symbol], "symbols": [runtime_symbol]}
            )
        evidence.append({"path": play_path, "symbols": [runtime_symbol]})
        requirements.append(
            {
                "id": requirement["id"],
                "owner": requirement["owner"],
                "status": "implemented",
                "verification": requirement["verification"],
                "evidence": evidence,
            }
        )
    session.write_file(
        author_team._ACCEPTANCE_EVIDENCE_PATH,
        json.dumps(
            {"contract_hash": contract_hash, "requirements": requirements},
            ensure_ascii=False,
        ),
    )


def _completed_evidence_project():
    contract = author_team._freeze_contract(json.loads(_contract_note()), {}, {})
    contract_hash = "e" * 64
    session = code_agent.RepairSession.from_files(
        author_team._with_contract_file(_project(), contract, contract_hash)
    )
    for role in author_team._IMPLEMENTATION_ROLES:
        _write_standard_candidate(session, role.name)
    _integrate_with_evidence(session)
    return session, contract, contract_hash


def test_design_contract_uses_strict_typed_raw_output_not_display_note():
    raw = json.loads(_contract_note())
    raw["state"][0]["meaning"] = "current turn"
    raw["modules"][0]["depends_on"] = ["role exports"]
    typed = author_team._DesignContractOutput.model_validate(raw, strict=True)

    payload = author_team._structured_contract_payload(typed)

    assert payload is not None
    assert payload["game_loop"].startswith("place defenses")
    assert payload["modules"][0]["depends_on"] == ["role exports"]
    assert author_team._structured_contract_payload("clipped display note") is None


def test_role_tool_policies_enforce_real_file_ownership():
    assert author_team._RULES_POLICY.allows_write("src/systems/rules/TurnResolver.ts")
    assert not author_team._RULES_POLICY.allows_write("src/scenes/PlayScene.ts")
    assert not author_team._RULES_POLICY.allows_write(
        "src/systems/../scenes/PlayScene.ts"
    )
    assert not author_team._RULES_POLICY.allows_write("src/systems/Juice.ts")
    assert author_team._WORLD_POLICY.allows_write("src/entities/Card.ts")
    assert not author_team._WORLD_POLICY.allows_write("src/ui/Hud.ts")
    assert author_team._PRESENTATION_POLICY.allows_write("src/ui/Hud.ts")
    assert not author_team._PRESENTATION_POLICY.allows_write("src/systems/GameState.ts")
    assert author_team._INTEGRATION_POLICY.allows_write("src/scenes/PlayScene.ts")
    assert author_team._INTEGRATION_POLICY.allows_write("src/adapters/RulesAdapter.ts")
    # write_file power over role modules stays forbidden; surgical patches for
    # build fixes are allowed, except on the immutable scaffold kit/contract.
    assert not author_team._INTEGRATION_POLICY.allows_write("src/ui/Hud.ts")
    assert author_team._INTEGRATION_POLICY.allows_write("src/ui/Hud.ts", via_patch=True)
    assert author_team._INTEGRATION_POLICY.allows_write(
        "src/systems/GameState.ts", via_patch=True
    )
    assert not author_team._INTEGRATION_POLICY.allows_write(
        "src/systems/Juice.ts", via_patch=True
    )
    assert not author_team._INTEGRATION_POLICY.allows_write(
        author_team._AUTHOR_CONTRACT_PATH
    )
    assert not author_team._INTEGRATION_POLICY.allows_write(
        author_team._AUTHOR_CONTRACT_PATH, via_patch=True
    )
    assert author_team._INTEGRATION_POLICY.allow_patch is True

    tools = _make_tools(
        code_agent.RepairSession.from_files(_project()),
        policy=author_team._READ_ONLY_POLICY,
    )
    names = [getattr(tool, "name", None) for tool in tools]
    assert names == ["list_files", "read_file", "read_files", "search_files"]

    integration_tools = _make_tools(
        code_agent.RepairSession.from_files(_project()),
        policy=author_team._INTEGRATION_POLICY,
    )
    integration_names = [getattr(tool, "name", None) for tool in integration_tools]
    assert "write_file" in integration_names
    assert "apply_patch" in integration_names
    assert "apply_patch_set" in integration_names


def test_tool_wrapper_rejects_unowned_patch_before_session_mutation(monkeypatch):
    fake_agents = ModuleType("agents")
    fake_agents.function_tool = lambda fn: fn
    monkeypatch.setitem(sys.modules, "agents", fake_agents)
    session = code_agent.RepairSession.from_files(_project())
    original = session.contents["src/scenes/PlayScene.ts"]
    tools = _make_tools(session, author=True, policy=author_team._RULES_POLICY)
    apply_patch = next(tool for tool in tools if tool.__name__ == "apply_patch")

    result = apply_patch(
        "update_file",
        "src/scenes/PlayScene.ts",
        "-export class PlayScene\n+export class BrokenScene",
    )

    assert "RulesAndSimulationCoder cannot modify" in result
    assert session.contents["src/scenes/PlayScene.ts"] == original
    assert session.changed == set()


def test_model_contract_cannot_widen_tool_ownership():
    contract = author_team._freeze_contract(
        {
            "game_loop": "test",
            "ownership": {"RulesAndSimulationCoder": ["src/scenes/**"]},
        },
        {},
        {},
    )

    assert contract["ownership"]["RulesAndSimulationCoder"] == list(
        author_team._RULES_POLICY.write_patterns
    )
    assert "src/scenes/**" not in contract["ownership"]["RulesAndSimulationCoder"]


def test_contract_rejects_uncovered_or_wrong_owner_acceptance_ids():
    raw = json.loads(_contract_note())
    rules_module = next(
        item for item in raw["modules"] if item["owner"] == "RulesAndSimulationCoder"
    )
    rules_module["acceptance_ids"] = []

    with pytest.raises(ValueError, match="no module coverage|no acceptance ids"):
        author_team._freeze_contract(raw, {}, {})

    raw = json.loads(_contract_note())
    next(item for item in raw["acceptance"] if item["id"] == "REQ-RULES")[
        "owner"
    ] = "WorldAndContentCoder"
    with pytest.raises(ValueError, match="no owner module coverage"):
        author_team._freeze_contract(raw, {}, {})


def test_contract_allows_integration_and_dependency_modules_to_reference_requirements():
    raw = json.loads(_contract_note())
    integration_module = next(
        item for item in raw["modules"] if item["owner"] == "IntegrationAgent"
    )
    world_module = next(
        item for item in raw["modules"] if item["owner"] == "WorldAndContentCoder"
    )
    integration_module["acceptance_ids"].extend(["REQ-RULES", "REQ-WORLD"])
    world_module["acceptance_ids"].append("REQ-RULES")

    contract = author_team._freeze_contract(raw, {}, {})

    assert contract.contract_version == 2
    assert "REQ-RULES" in next(
        item for item in contract.modules if item.owner == "IntegrationAgent"
    ).acceptance_ids


def test_role_dependencies_ignore_integration_owned_exports_until_integration_phase():
    raw = json.loads(_contract_note())
    presentation = next(
        item
        for item in raw["modules"]
        if item["owner"] == "PresentationAndInteractionCoder"
    )
    presentation["depends_on"].append("PlayScene")
    contract = author_team._freeze_contract(raw, {}, {})

    dependencies = author_team._role_dependencies(contract)
    components = author_team._dependency_components(dependencies)

    assert all("IntegrationAgent" not in owners for owners in dependencies.values())
    assert {role for component in components for role in component} == {
        role.name for role in author_team._IMPLEMENTATION_ROLES
    }


def test_candidate_requires_owned_changes_and_reports_export_gaps():
    contract = author_team._freeze_contract(json.loads(_contract_note()), {}, {})
    contract_hash = "c" * 64
    base = author_team._with_contract_file(_project(), contract, contract_hash)
    base_revision = author_team._snapshot_revision(base)
    role = author_team._IMPLEMENTATION_ROLES[0]
    empty_session = code_agent.RepairSession.from_files(base)
    changes, error, missing = author_team._candidate_changes(
        author_team._RoleCandidate(
            role=role,
            outcome=_outcome(empty_session),
            base_revision=base_revision,
            contract_hash=contract_hash,
        ),
        base,
        expected_base_revision=base_revision,
        expected_contract_hash=contract_hash,
        contract=contract,
    )
    assert changes is None
    assert "no owned changes" in error
    assert missing == ()

    # Partial delivery: real owned work with a missing assigned export is
    # accepted, and the gap is reported for a targeted retry / integration.
    wrong_export_session = code_agent.RepairSession.from_files(base)
    wrong_export_session.write_file(
        "src/systems/rules/WrongRules.ts", "export class DifferentResolver {}"
    )
    changes, error, missing = author_team._candidate_changes(
        author_team._RoleCandidate(
            role=role,
            outcome=_outcome(wrong_export_session),
            base_revision=base_revision,
            contract_hash=contract_hash,
        ),
        base,
        expected_base_revision=base_revision,
        expected_contract_hash=contract_hash,
        contract=contract,
    )
    assert error is None
    assert set(changes) == {"src/systems/rules/WrongRules.ts"}
    assert missing == ("TurnResolver",)


def test_acceptance_evidence_requires_real_owner_and_runtime_symbols():
    session, contract, contract_hash = _completed_evidence_project()
    assert (
        author_team._acceptance_evidence_issues(
            session.to_files(), contract, contract_hash
        )
        == []
    )

    manifest = json.loads(session.contents[author_team._ACCEPTANCE_EVIDENCE_PATH])
    manifest["contract_hash"] = "wrong"
    session.write_file(
        author_team._ACCEPTANCE_EVIDENCE_PATH, json.dumps(manifest)
    )
    assert any(
        "contract_hash" in issue
        for issue in author_team._acceptance_evidence_issues(
            session.to_files(), contract, contract_hash
        )
    )

    session, contract, contract_hash = _completed_evidence_project()
    manifest = json.loads(session.contents[author_team._ACCEPTANCE_EVIDENCE_PATH])
    rules_row = next(item for item in manifest["requirements"] if item["id"] == "REQ-RULES")
    rules_row["owner"] = "WorldAndContentCoder"
    rules_row["evidence"] = [
        {
            "path": "src/systems/rules/TurnResolver.ts",
            "symbols": ["TurnResolver"],
        }
    ]
    session.write_file(
        author_team._ACCEPTANCE_EVIDENCE_PATH, json.dumps(manifest)
    )
    issues = author_team._acceptance_evidence_issues(
        session.to_files(), contract, contract_hash
    )
    assert any("owner does not match" in issue for issue in issues)
    assert any("lacks runtime wiring evidence" in issue for issue in issues)

    session, contract, contract_hash = _completed_evidence_project()
    manifest = json.loads(session.contents[author_team._ACCEPTANCE_EVIDENCE_PATH])
    rules_row = next(item for item in manifest["requirements"] if item["id"] == "REQ-RULES")
    session.write_file(
        "src/adapters/FakeWiring.ts", "// TurnResolver is wired at runtime"
    )
    rules_row["evidence"][1] = {
        "path": "src/adapters/FakeWiring.ts",
        "symbols": ["TurnResolver"],
    }
    session.write_file(
        author_team._ACCEPTANCE_EVIDENCE_PATH, json.dumps(manifest)
    )
    issues = author_team._acceptance_evidence_issues(
        session.to_files(), contract, contract_hash
    )
    assert any("symbol is absent" in issue for issue in issues)
    assert any("lacks runtime wiring evidence" in issue for issue in issues)


def test_acceptance_evidence_rejects_import_only_and_void_laundering():
    """The e7ee0742 exploit: `import X` + trailing `void X;` counted as two
    occurrences and passed the old >=2 wiring rule while X stayed dead."""
    session, contract, contract_hash = _completed_evidence_project()
    play_path = "src/scenes/PlayScene.ts"
    source = session.contents[play_path]
    source = re.sub(r"export const gwWired\d+ = new [A-Za-z_$][\w$]*\(\);\n?", "", source)
    session.write_file(
        play_path,
        source + "\nvoid TurnResolver;\nvoid StormBeacon;\nvoid TurnHud;\n",
    )
    issues = author_team._acceptance_evidence_issues(
        session.to_files(), contract, contract_hash
    )
    assert any(
        "appears only in import/re-export statements or inert" in issue
        for issue in issues
    )
    assert any("inert reference laundering" in issue for issue in issues)
    assert any("lacks runtime wiring evidence" in issue for issue in issues)


def test_usage_identifiers_strip_imports_reexports_and_bare_void():
    source = """
import { Alpha } from "./alpha";
import Beta, { Gamma as G } from "./beta";
import "./side-effect";
export { Alpha } from "./alpha";
export * from "./everything";
const beta = new Beta();
void Alpha;
void beta.ready;
"""
    usage = author_team._usage_identifiers(source)
    assert "Alpha" not in usage
    assert "Beta" in usage
    assert "beta" in usage


def test_merge_rejects_stale_candidate_envelope():
    base = _project()
    session = code_agent.RepairSession.from_files(base)
    session.write_file(
        "src/systems/rules/StaleRules.ts",
        "export const stale = true;",
    )
    candidate = author_team._RoleCandidate(
        role=author_team._IMPLEMENTATION_ROLES[0],
        outcome=_outcome(session),
        base_revision="old-base",
        contract_hash="contract-v1",
    )

    merged, accepted, logs = author_team._merge_candidates(
        base,
        [candidate],
        base_revision="current-base",
        contract_hash="contract-v1",
    )

    assert {item["path"]: item["content"] for item in merged} == {
        item["path"]: item["content"] for item in base
    }
    assert accepted == set()
    assert any("base revision is stale" in line for line in logs)


def test_dependency_aware_merge_holds_a_valid_dependent_for_owner_salvage():
    raw = json.loads(_contract_note())
    rules_module = next(
        item for item in raw["modules"] if item["owner"] == "RulesAndSimulationCoder"
    )
    rules_module["exports"] = ["RuleState"]
    presentation_module = next(
        item
        for item in raw["modules"]
        if item["owner"] == "PresentationAndInteractionCoder"
    )
    presentation_module["exports"] = ["RuleHud"]
    presentation_module["depends_on"] = ["RuleState"]
    contract = author_team._freeze_contract(raw, {}, {})
    contract_hash = "contract-hash"
    base = author_team._with_contract_file(_project(), contract, contract_hash)
    base_revision = author_team._snapshot_revision(base)
    presentation_session = code_agent.RepairSession.from_files(base)
    presentation_session.write_file("src/ui/RuleHud.ts", "export class RuleHud {}")
    world_session = code_agent.RepairSession.from_files(base)
    world_session.write_file(
        "src/entities/StormBeacon.ts", "export class StormBeacon {}"
    )
    candidates = [
        author_team._RoleCandidate(
            role=author_team._IMPLEMENTATION_ROLES[0],
            outcome=None,
            base_revision=base_revision,
            contract_hash=contract_hash,
        ),
        author_team._RoleCandidate(
            role=author_team._IMPLEMENTATION_ROLES[1],
            outcome=_outcome(world_session),
            base_revision=base_revision,
            contract_hash=contract_hash,
        ),
        author_team._RoleCandidate(
            role=author_team._IMPLEMENTATION_ROLES[2],
            outcome=_outcome(presentation_session),
            base_revision=base_revision,
            contract_hash=contract_hash,
        ),
    ]

    result = author_team._merge_candidate_report(
        base,
        candidates,
        base_revision=base_revision,
        contract_hash=contract_hash,
        contract=contract,
    )

    # The dependent's valid work is salvaged rather than withheld: its missing
    # dependency owner becomes an explicit integration gap instead of a reason
    # to drop delivered modules.
    assert result.accepted_roles == {
        "WorldAndContentCoder",
        "PresentationAndInteractionCoder",
    }
    assert result.blocked_roles == {}
    assert "src/ui/RuleHud.ts" in result.accepted_paths
    assert any(
        "despite unmet dependencies RulesAndSimulationCoder" in line
        for line in result.logs
    )


def test_dependency_aware_merge_accepts_cyclic_owner_group_atomically():
    raw = json.loads(_contract_note())
    rules_module = next(
        item for item in raw["modules"] if item["owner"] == "RulesAndSimulationCoder"
    )
    rules_module["exports"] = ["RuleState"]
    rules_module["depends_on"] = ["RuleHud"]
    presentation_module = next(
        item
        for item in raw["modules"]
        if item["owner"] == "PresentationAndInteractionCoder"
    )
    presentation_module["exports"] = ["RuleHud"]
    presentation_module["depends_on"] = ["RuleState"]
    contract = author_team._freeze_contract(raw, {}, {})
    contract_hash = "contract-hash"
    base = author_team._with_contract_file(_project(), contract, contract_hash)
    base_revision = author_team._snapshot_revision(base)
    sessions = {
        role.name: code_agent.RepairSession.from_files(base)
        for role in author_team._IMPLEMENTATION_ROLES
    }
    sessions["RulesAndSimulationCoder"].write_file(
        "src/systems/rules/CyclicRules.ts", "export class RuleState {}"
    )
    sessions["PresentationAndInteractionCoder"].write_file(
        "src/ui/CyclicHud.ts", "export class RuleHud {}"
    )
    sessions["WorldAndContentCoder"].write_file(
        "src/entities/StormBeacon.ts", "export class StormBeacon {}"
    )
    candidates = [
        author_team._RoleCandidate(
            role=role,
            outcome=_outcome(sessions[role.name]),
            base_revision=base_revision,
            contract_hash=contract_hash,
        )
        for role in author_team._IMPLEMENTATION_ROLES
    ]

    result = author_team._merge_candidate_report(
        base,
        candidates,
        base_revision=base_revision,
        contract_hash=contract_hash,
        contract=contract,
    )

    assert result.accepted_roles == {
        "RulesAndSimulationCoder",
        "WorldAndContentCoder",
        "PresentationAndInteractionCoder",
    }
    assert result.blocked_roles == {}
    assert "src/systems/rules/CyclicRules.ts" in result.accepted_paths
    assert "src/ui/CyclicHud.ts" in result.accepted_paths
    assert any("atomic dependency group" in line for line in result.logs)


def test_author_team_runs_isolated_roles_then_one_integration_agent(monkeypatch):
    base = _project()
    base_paths = {item["path"] for item in base} | {author_team._AUTHOR_CONTRACT_PATH}
    calls = []
    coder_start_paths = {}
    coder_barrier = threading.Barrier(3)

    def fake_execute(session, *, agent_name, task_input, tool_policy, **kwargs):
        calls.append((agent_name, tool_policy.name, task_input))
        if agent_name == "DesignContractAgent":
            assert kwargs["output_type"] is author_team._DesignContractOutput
            assert kwargs["terminal_completion"] is False
            assert isinstance(kwargs["deadline_at"], float)
            assert kwargs["workspace_tools"] is False
            assert "Do not inspect workspace files or call tools" in task_input
            return _outcome(session, note=_contract_note(), tokens=5)

        if agent_name != "IntegrationAgent":
            assert "Available source paths" in task_input
            assert "- src/scenes/PlayScene.ts" in task_input
            coder_start_paths[agent_name] = set(session.contents)
            coder_barrier.wait(timeout=2)
        if agent_name == "RulesAndSimulationCoder":
            _write_standard_candidate(session, agent_name)
            return _outcome(session, tokens=7)
        if agent_name == "WorldAndContentCoder":
            _write_standard_candidate(session, agent_name)
            return _outcome(session, tokens=11)
        if agent_name == "PresentationAndInteractionCoder":
            _write_standard_candidate(session, agent_name)
            return _outcome(session, tokens=13)
        assert agent_name == "IntegrationAgent"
        assert "src/systems/rules/TurnResolver.ts" in session.contents
        assert "src/entities/StormBeacon.ts" in session.contents
        assert "src/ui/TurnHud.ts" in session.contents
        _integrate_with_evidence(session)
        session.checks_ok = True
        return _outcome(session, tokens=17, turns=2, checks_ok=True)

    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    outcome = author_team.run_project_author_team(
        base,
        spec={"title": "Contract Test", "genre": "strategy"},
        design={"signature_twist": "storms reroute units"},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=32,
        live_step_id=None,
    )

    assert outcome is not None and outcome.checks_ok
    names = [name for name, _, _ in calls]
    assert names[0] == "DesignContractAgent"
    assert names[-1] == "IntegrationAgent"
    assert set(names[1:-1]) == {
        "RulesAndSimulationCoder",
        "WorldAndContentCoder",
        "PresentationAndInteractionCoder",
    }
    # Every coder starts from exactly the same frozen scaffold, not a previous
    # role's growing conversation/workspace.
    assert all(paths == base_paths for paths in coder_start_paths.values())
    assert outcome.tokens == 53
    assert author_team._AUTHOR_CONTRACT_PATH in outcome.changed
    assert "src/scenes/PlayScene.ts" in outcome.changed
    assert "GW_PLACEHOLDER_GAMEPLAY" not in next(
        item["content"]
        for item in outcome.files
        if item["path"] == "src/scenes/PlayScene.ts"
    )
    assert outcome.note.startswith("TEAM DONE: contract ")


def test_author_team_rejects_candidate_that_bypasses_role_policy(monkeypatch):
    base = _project()
    integration_saw = {}
    rules_runs = 0
    retry_turns = []

    def fake_execute(session, *, agent_name, **kwargs):
        nonlocal rules_runs
        if agent_name == "DesignContractAgent":
            return _outcome(session, note=_contract_note())
        if agent_name == "RulesAndSimulationCoder":
            rules_runs += 1
            if rules_runs == 1:
                # Simulate a compromised/misbehaving tool wrapper. The merge gate
                # must independently catch the scene edit.
                session.contents[
                    "src/scenes/PlayScene.ts"
                ] += "\n// BAD_RULES_SCENE_EDIT"
                session.changed.add("src/scenes/PlayScene.ts")
            else:
                retry_turns.append(kwargs["turns_limit"])
                # Targeted retry starts from a sanitized owner-only salvage base.
                assert (
                    "BAD_RULES_SCENE_EDIT"
                    not in session.contents["src/scenes/PlayScene.ts"]
                )
                session.write_file(
                    "src/systems/rules/RecoveredRules.ts",
                    "export class TurnResolver { resolve(turn: number): number { return turn + 1; } }",
                )
            return _outcome(session)
        if agent_name in {"WorldAndContentCoder", "PresentationAndInteractionCoder"}:
            _write_standard_candidate(session, agent_name)
            return _outcome(session)
        integration_saw["bad_edit"] = (
            "BAD_RULES_SCENE_EDIT" in session.contents["src/scenes/PlayScene.ts"]
        )
        _integrate_with_evidence(session)
        session.checks_ok = True
        return _outcome(session, checks_ok=True)

    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    outcome = author_team.run_project_author_team(
        base,
        spec={"title": "Contract Test"},
        design={},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=20,
        live_step_id=None,
    )

    assert outcome is not None
    assert rules_runs == 2
    assert retry_turns == [
        min(
            author_team._OWNER_RETRY_MAX_TURNS,
            max(1, author_team._turn_allocation(20).retry_reserve),
        )
    ]
    assert integration_saw["bad_edit"] is False
    assert any("crossed file ownership" in line for line in outcome.logs)


def test_run_author_routes_vite_projects_to_bounded_team(monkeypatch):
    expected = _outcome(code_agent.RepairSession.from_files(_project()))
    captured = {}

    def fake_team(files, **kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(author_team, "run_project_author_team", fake_team)
    planning_context = {
        "items": [
            {"role": "user", "content": "plan the puzzle"},
            {"role": "assistant", "content": '{"expanded_brief": {}}'},
        ],
        "response_id": "resp-game-design",
    }
    outcome = code_agent.run_author(
        _project(),
        spec={"genre": "puzzle"},
        design={"signature_twist": "rewind"},
        runtime="phaser-vite",
        max_turns=21,
        planning_context=planning_context,
    )

    assert outcome is expected
    assert captured["max_turns"] == 21
    assert captured["runtime"] == "phaser-vite"
    assert captured["planning_context"] == planning_context


def test_project_author_team_replays_planning_transcript_into_design_contract(
    monkeypatch,
):
    """The stateless gateway drops previous_response_id, so the planning
    conversation must reach DesignContractAgent as explicit input items."""
    captured = {}

    def fake_execute(session, **kwargs):
        if kwargs.get("agent_name") == "DesignContractAgent":
            captured.update(kwargs)
        return None

    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    transcript = [
        {"role": "user", "content": "plan the strategy game"},
        {"role": "assistant", "content": '{"expanded_brief": {}}'},
    ]
    author_team.run_project_author_team(
        _project(),
        spec={"genre": "strategy"},
        design={"signature_twist": "storms reroute units"},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=8,
        live_step_id=None,
        planning_context={"items": transcript, "response_id": "resp-design"},
    )

    assert captured["context_items"] == transcript
    assert captured["chained_from_response_id"] == "resp-design"
    # The replayed transcript carries the raw pre-merge design draft; the
    # contract prompt must declare its own JSON canonical on conflict.
    assert "canonical and wins" in captured["task_input"]


def test_contract_input_marks_canonical_design_only_when_chained():
    chained = author_team._contract_input(
        {"genre": "strategy"}, {"waves": []}, "phaser-vite", "2d", None, chained=True
    )
    standalone = author_team._contract_input(
        {"genre": "strategy"}, {"waves": []}, "phaser-vite", "2d", None
    )
    assert "canonical and wins" in chained
    assert "canonical and wins" not in standalone


def test_frozen_contract_generates_an_immutable_valid_typescript_boundary():
    raw = json.loads(_contract_note())
    raw["acceptance"].append(
        {
            "id": "REQ-INTEGRATION-SAFE",
            "owner": "IntegrationAgent",
            "requirement": "Do not call localStorage or fetch()",
            "observable": "the game remains inside the bridge sandbox",
            "verification": "scan integrated sources for forbidden browser APIs",
        }
    )
    next(
        item for item in raw["modules"] if item["owner"] == "IntegrationAgent"
    )["acceptance_ids"].append("REQ-INTEGRATION-SAFE")
    contract = author_team._freeze_contract(
        raw,
        {"genre": "strategy"},
        {},
    )
    contract_hash = "a" * 64
    files = author_team._with_contract_file(_project(), contract, contract_hash)
    source = next(
        item["content"]
        for item in files
        if item["path"] == author_team._AUTHOR_CONTRACT_PATH
    )

    assert isinstance(contract.state, tuple)
    assert isinstance(contract.events[0].consumers, tuple)
    assert contract.contract_version == 2
    assert "readonly state" in source
    assert "readonly acceptance_ids" in source
    assert "AuthorContractAcceptance" in source
    assert "as const satisfies AuthorGameContract" in source
    assert "Object.freeze(contractData)" in source
    assert contract_hash in source
    assert "localStorage" not in source
    assert "fetch(" not in source
    assert validate_vite_project(files) == []


def test_frozen_contract_rejects_export_explosion_per_owner():
    raw = json.loads(_contract_note())
    world_module = next(
        item for item in raw["modules"] if item["owner"] == "WorldAndContentCoder"
    )
    world_module["exports"] = [f"EnemyVariant{index}" for index in range(9)]

    with pytest.raises(ValueError, match="too many exports"):
        author_team._freeze_contract(raw, {"genre": "action_roguelite"}, {})


def test_contract_capture_is_not_limited_by_the_old_20k_display_clip(monkeypatch):
    base = _project()
    raw = json.loads(_contract_note())
    integration_module = next(
        item for item in raw["modules"] if item["owner"] == "IntegrationAgent"
    )
    for index in range(24):
        acceptance_id = f"REQ-LONG-{index}"
        marker = "TAIL_CONTRACT_MARKER-" if index == 23 else ""
        raw["acceptance"].append(
            {
                "id": acceptance_id,
                "owner": "IntegrationAgent",
                "requirement": marker + f"requirement-{index}-" + ("x" * 900),
                "observable": "the integrated behavior is player reachable",
                "verification": "start PlayScene and inspect the requested behavior",
            }
        )
        integration_module["acceptance_ids"].append(acceptance_id)
    long_contract = json.dumps(raw, ensure_ascii=False)
    assert len(long_contract) > 20_000
    captured = {"contract_seen": []}

    def fake_execute(session, *, agent_name, final_output_limit=200, **kwargs):
        if agent_name == "DesignContractAgent":
            captured["limit"] = final_output_limit
            return _outcome(session, note=long_contract)
        if agent_name != "IntegrationAgent":
            captured["contract_seen"].append(
                "TAIL_CONTRACT_MARKER"
                in session.contents[author_team._AUTHOR_CONTRACT_PATH]
            )
            _write_standard_candidate(session, agent_name)
            return _outcome(session)
        _integrate_with_evidence(session)
        session.checks_ok = True
        return _outcome(session, checks_ok=True)

    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    outcome = author_team.run_project_author_team(
        base,
        spec={"title": "Long Contract", "genre": "strategy"},
        design={},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=20,
        live_step_id=None,
    )

    assert outcome is not None and outcome.checks_ok
    assert captured["limit"] > len(long_contract)
    assert captured["contract_seen"] == [True, True, True]


def test_budget_exhausted_roles_are_partial_not_team_failures(monkeypatch):
    events = []

    def record(line, *, step_id=None, payload=None):
        events.append((line, payload or {}))
        return True

    def fake_execute(session, *, agent_name, **kwargs):
        if agent_name == "DesignContractAgent":
            return _outcome(session, note=_contract_note())
        if agent_name == "IntegrationAgent":
            _integrate_with_evidence(session)
            session.checks_ok = True
            return _outcome(
                session,
                note="max turns (8) exhausted",
                checks_ok=True,
                turns=2,
            )
        _write_standard_candidate(session, agent_name)
        return _outcome(session, note="max turns (5) exhausted")

    monkeypatch.setattr(author_team.tracing, "record_step_log", record)
    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    outcome = author_team.run_project_author_team(
        _project(),
        spec={"title": "Budget Semantics"},
        design={},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=20,
        live_step_id="step-1",
    )

    assert outcome is not None and outcome.checks_ok
    event_names = [payload.get("event") for _line, payload in events]
    assert event_names.count("role_budget_exhausted") == 4
    assert "team_failed" not in event_names
    team_event = next(
        payload for _line, payload in events if payload.get("event") == "team_completed"
    )
    assert team_event["status"] == "done"


def test_missing_owner_degrades_to_explicit_integration_bridging(monkeypatch):
    """A dead owner no longer kills the run: the team degrades loudly and
    IntegrationAgent receives the missing assignment as an explicit gap."""
    events = []
    integration_inputs = []

    def fake_execute(session, *, agent_name, **kwargs):
        if agent_name == "DesignContractAgent":
            return _outcome(session, note=_contract_note())
        if agent_name == "RulesAndSimulationCoder":
            return None
        if agent_name == "IntegrationAgent":
            integration_inputs.append(kwargs.get("task_input") or "")
            # Bridge the missing rules owner inside integration-owned paths,
            # exactly as the ROLE GAPS note instructs.
            session.write_file(
                "src/composition/BridgedRules.ts",
                "export class TurnResolver { resolve(turn: number): number { return turn + 1; } }",
            )
            _integrate_with_evidence(session)
            session.checks_ok = True
            return _outcome(session, checks_ok=True)
        _write_standard_candidate(session, agent_name)
        return _outcome(session)

    monkeypatch.setattr(
        author_team.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: events.append(payload or {})
        or True,
    )
    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    outcome = author_team.run_project_author_team(
        _project(),
        spec={"title": "Missing Owner"},
        design={},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=20,
        live_step_id="step-1",
    )

    assert outcome is not None
    degraded = next(item for item in events if item.get("event") == "team_degraded")
    assert degraded["reason"] == "missing_required_roles"
    assert "RulesAndSimulationCoder" in degraded["missing_roles"]
    assert "team_failed" not in {item.get("event") for item in events}
    assert integration_inputs and "ROLE GAPS" in integration_inputs[0]
    assert "RulesAndSimulationCoder" in integration_inputs[0]
    assert "TurnResolver" in integration_inputs[0]


def test_gap_bridged_evidence_accepts_integration_owned_owner_files():
    session, contract, contract_hash = _completed_evidence_project()
    # Simulate the rules owner never delivering: its module lives in an
    # integration-owned composition path instead, cited as owner evidence.
    manifest = json.loads(session.contents[author_team._ACCEPTANCE_EVIDENCE_PATH])
    rules_row = next(
        item for item in manifest["requirements"] if item["id"] == "REQ-RULES"
    )
    session.write_file(
        "src/composition/BridgedRules.ts",
        "export class TurnResolver { resolve(turn: number): number { return turn + 1; } }",
    )
    rules_row["evidence"][0] = {
        "path": "src/composition/BridgedRules.ts",
        "symbols": ["TurnResolver"],
    }
    session.write_file(
        author_team._ACCEPTANCE_EVIDENCE_PATH, json.dumps(manifest)
    )

    strict_issues = author_team._acceptance_evidence_issues(
        session.to_files(), contract, contract_hash
    )
    assert any("lacks owner implementation evidence" in issue for issue in strict_issues)

    bridged_issues = author_team._acceptance_evidence_issues(
        session.to_files(), contract, contract_hash, {"REQ-RULES"}
    )
    assert bridged_issues == []


def test_team_token_budget_stops_at_a_stage_boundary(monkeypatch):
    calls = []
    events = []

    def fake_execute(session, *, agent_name, **kwargs):
        calls.append(agent_name)
        return _outcome(session, note=_contract_note(), tokens=10)

    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    monkeypatch.setattr(
        author_team.tracing,
        "record_step_log",
        lambda line, *, step_id=None, payload=None: events.append(payload or {})
        or True,
    )
    outcome = author_team.run_project_author_team(
        _project(),
        spec={"title": "Budget Stop"},
        design={},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=20,
        live_step_id="step-1",
        team_token_budget=5,
    )

    assert outcome is None
    assert calls == ["DesignContractAgent"]
    exhausted = next(
        item for item in events if item.get("event") == "team_budget_exhausted"
    )
    assert "tokens" in exhausted["reasons"]


def test_turn_plan_reserves_retry_without_exceeding_total_budget():
    for total in (5, 10, 20, 32, 56):
        plan = author_team._turn_allocation(total)
        assert (
            plan.planner + sum(plan.coders) + plan.retry_reserve + plan.integration
            == total
        )
        assert all(turns >= 1 for turns in plan.coders)

    production = author_team._turn_allocation(56)
    assert production.planner == 1
    assert production.retry_reserve == 6
    assert production.integration >= 14
    # Freed retry reserve flows to the first coder pass: incomplete first
    # passes were the dominant production failure mode.
    assert min(production.coders) >= 11

    production = author_team._turn_allocation(64)
    assert production.planner == 1
    assert production.retry_reserve == 6
    assert production.integration >= 16
    assert min(production.coders) >= 13


def test_each_invalid_owner_receives_full_reserved_targeted_retry(monkeypatch):
    base = _project()
    runs = {role.name: 0 for role in author_team._IMPLEMENTATION_ROLES}
    retry_turns = {}
    integration_turns = []

    def fake_execute(session, *, agent_name, turns_limit, **kwargs):
        if agent_name == "DesignContractAgent":
            return _outcome(
                session,
                note=_contract_note(),
                turns=turns_limit,
            )
        if agent_name == "IntegrationAgent":
            integration_turns.append(turns_limit)
            _integrate_with_evidence(session)
            session.checks_ok = True
            return _outcome(session, turns=turns_limit, checks_ok=True)

        runs[agent_name] += 1
        if runs[agent_name] == 1:
            # Spend the whole initial allocation but leave an invalid empty
            # candidate, matching the worst-case budget accounting path.
            return _outcome(session, turns=turns_limit)
        retry_turns[agent_name] = turns_limit
        _write_standard_candidate(session, agent_name)
        return _outcome(session, turns=turns_limit)

    monkeypatch.setattr(author_team, "_execute_agent", fake_execute)
    outcome = author_team.run_project_author_team(
        base,
        spec={"title": "Reserved Retries"},
        design={},
        runtime="phaser-vite",
        dimension="2d",
        qa_feedback=None,
        max_turns=56,
        live_step_id=None,
    )

    assert outcome is not None and outcome.checks_ok
    expected_retry = min(
        author_team._OWNER_RETRY_MAX_TURNS,
        author_team._turn_allocation(56).retry_reserve
        // len(author_team._IMPLEMENTATION_ROLES),
    )
    assert retry_turns == {role.name: expected_retry for role in author_team._IMPLEMENTATION_ROLES}
    assert integration_turns == [author_team._turn_allocation(56).integration]


def test_contract_repair_synthesizes_missing_integration_module():
    raw = json.loads(_contract_note())
    raw["modules"] = [
        item for item in raw["modules"] if item["owner"] != "IntegrationAgent"
    ]
    raw["acceptance"] = [
        item for item in raw["acceptance"] if item["owner"] != "IntegrationAgent"
    ]
    with pytest.raises(ValueError):
        author_team._freeze_contract(raw, {}, {})

    repaired, fixes = author_team._repair_contract(raw, {}, {})
    contract = author_team._freeze_contract(repaired, {}, {})
    assert any("synthesized missing IntegrationAgent module" in fix for fix in fixes)
    integration_modules = [
        item for item in contract.modules if item.owner == "IntegrationAgent"
    ]
    assert integration_modules and "PlayScene" in integration_modules[0].exports
    # The model's game-specific rows survive untouched.
    assert any(item.id == "REQ-RULES" for item in contract.acceptance)


def test_contract_repair_attaches_uncovered_acceptance_ids():
    raw = json.loads(_contract_note())
    raw["acceptance"].append(
        {
            "id": "REQ-RULES-EXTRA",
            "owner": "RulesAndSimulationCoder",
            "requirement": "combo scoring multiplies risk",
            "observable": "chained actions raise the multiplier",
            "verification": "chain two actions and compare the reward",
        }
    )
    with pytest.raises(ValueError):
        author_team._freeze_contract(raw, {}, {})

    repaired, fixes = author_team._repair_contract(raw, {}, {})
    contract = author_team._freeze_contract(repaired, {}, {})
    assert any("REQ-RULES-EXTRA" in fix for fix in fixes)
    rules_module = next(
        item for item in contract.modules if item.owner == "RulesAndSimulationCoder"
    )
    assert "REQ-RULES-EXTRA" in rules_module.acceptance_ids


def test_fallback_contract_preserves_cross_genre_product_requirements():
    contract = author_team._fallback_contract(
        {
            "title": "Workshop Campaign",
            "genre": "strategy",
            "summary": (
                "An extensible campaign with save persistence, settings, key rebinding, "
                "volume control, pause, tutorial, and a map screen."
            ),
            "core_loop": {"campaign": "choose a route", "combat": "play tactical cards"},
        },
        {
            "cards": [{"id": f"card-{index}"} for index in range(24)],
            "enemies": [{"name": f"enemy-{index}"} for index in range(6)],
            "signature_twist": {"name": "interrupt intent", "rule": "change the board"},
        },
    )

    acceptance = {item["id"]: item for item in contract["acceptance"]}
    assert {
        "REQ-PRESENTATION-PERSISTENCE",
        "REQ-PRESENTATION-SETTINGS",
        "REQ-PRESENTATION-FLOWS",
        "REQ-INTEGRATION-PLAYABLE",
        "REQ-INTEGRATION-ASSETS",
        "REQ-INTEGRATION-EXTENSIBLE",
    } <= set(acceptance)
    presentation = next(
        item
        for item in contract["modules"]
        if item["owner"] == "PresentationAndInteractionCoder"
    )
    assert {"SettingsService", "InputBindingService", "GamePersistenceService"} <= set(
        presentation["exports"]
    )
    assert "cards=24" in acceptance["REQ-WORLD-CONTENT"]["requirement"]
    assert "enemies=6" in acceptance["REQ-WORLD-CONTENT"]["requirement"]
    assert "{" not in contract["game_loop"]
    assert "name: interrupt intent" in acceptance["REQ-RULES-TWIST"]["requirement"]


def test_author_roles_require_incremental_recoverable_tool_calls():
    for instructions in (
        author_team._RULES_INSTRUCTIONS,
        author_team._WORLD_INSTRUCTIONS,
        author_team._PRESENTATION_INSTRUCTIONS,
        author_team._INTEGRATION_INSTRUCTIONS,
    ):
        assert "32KB / 600 lines" in instructions
        assert "cannot be recovered after a transport interruption" in instructions
        assert "Use write_file for a new file" in instructions
    assert "at most one source file per tool call" in author_team._RULES_INSTRUCTIONS
    assert "at most one source file per tool call" in author_team._WORLD_INSTRUCTIONS
    assert "at most one source file per tool call" in author_team._PRESENTATION_INSTRUCTIONS
    assert "at most one adapter" in author_team._INTEGRATION_INSTRUCTIONS
    assert "first source-changing tool call must be write_file" in author_team._INTEGRATION_INSTRUCTIONS
    # Patches are a bounded escape hatch for role-module build errors, never a
    # license to rewrite role work.
    assert "smallest mechanical fix" in author_team._INTEGRATION_INSTRUCTIONS
    assert (
        "Never restructure, rewrite, or extend role modules through patches"
        in author_team._INTEGRATION_INSTRUCTIONS
    )
