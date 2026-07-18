import pytest

from app.agents.design_contract import (
    ContractCompileError,
    IntentRecord,
    ScopeExceededError,
    compile_design_contract,
    compute_contract_hash,
    derive_contract_views,
    diff_design_contracts,
    enforce_execution_boundary,
    freeze_contract,
    revision_directive_from_state,
    validate_contract,
)
from app.agents.planning_nodes import (
    contract_gate_node,
    should_continue_after_contract_gate,
)
from app.agents.codegen import _prepare_generated_artifacts


def _contract(*, parent=None, feedback=None):
    return compile_design_contract(
        {
            "title": "City Builder",
            "must_haves": ["REQ-HOUSING"],
            "must_not_haves": ["instant bankruptcy"],
            "win_condition": "reach five stars",
            "lose_condition": "bankruptcy",
        },
        {
            "player": {"visual": "mayor", "states": ["idle", "selected"]},
            "entities": [
                {
                    "id": "residential",
                    "role": "placeable_building",
                    "states": [
                        {"id": "level_1", "semantic_id": "residential.level_1", "structure_change": True},
                        {"id": "level_2", "semantic_id": "residential.level_2", "structure_change": True},
                    ],
                }
            ],
            "requirements": [
                {
                    "id": "REQ-HOUSING",
                    "statement": "Housing has two visibly distinct levels.",
                    "source_refs": ["intent:paragraph_1"],
                    "resolved_as": ["residential.level_1", "residential.level_2"],
                }
            ],
        },
        intent_record=IntentRecord(
            raw_prompt="build a city",
            normalized_prompt="build a city",
            feedback=list(feedback or []),
        ),
        parent=parent,
    )


def test_design_contract_gate_freezes_and_hashes_without_truncation():
    draft = _contract()
    gate = validate_contract(draft)
    assert gate.passed
    frozen = freeze_contract(draft)
    assert frozen.meta.status == "frozen"
    assert frozen.meta.contract_hash == compute_contract_hash(frozen)
    assert frozen.meta.contract_hash


def test_derived_views_carry_the_same_contract_hash_and_semantic_ids():
    frozen = freeze_contract(_contract())
    views = derive_contract_views(frozen)
    assert views["style_bible"]["contract_hash"] == frozen.meta.contract_hash
    assert views["asset_batch_specs"]["contract_hash"] == frozen.meta.contract_hash
    assert views["acceptance_plan"]["contract_hash"] == frozen.meta.contract_hash
    ids = set(views["runtime_asset_requirements"]["semantic_ids"])
    assert {"residential.level_1", "residential.level_2"}.issubset(ids)
    assert views["sprite_demand_manifest"]["contract_hash"] == frozen.meta.contract_hash


def test_gate_rejects_unresolved_required_intent():
    draft = _contract().model_copy(update={
        "intent": _contract().intent.model_copy(update={"unresolved": ["need a tutorial"]})
    })
    result = validate_contract(draft)
    assert not result.passed
    assert any("unresolved" in issue for issue in result.issues)


def test_unknown_contract_fields_are_rejected():
    raw = _contract().model_dump(mode="json")
    raw["unexpected"] = True
    try:
        compile_design_contract({}, {}, intent_record=IntentRecord(raw_prompt="x", normalized_prompt="x"))
        # The compiler emits a valid contract; strict rejection is exercised by
        # the public model boundary below.
        from app.agents.design_contract import DesignContract

        DesignContract.model_validate(raw, strict=True)
    except Exception as exc:
        assert "unexpected" in str(exc)
    else:
        raise AssertionError("unknown DesignContract fields must be rejected")


def test_revision_preserves_parent_requirements_and_compiles_feedback_amendment():
    parent = freeze_contract(_contract())
    revision = freeze_contract(
        _contract(parent=parent, feedback=["Add a visible day and night cycle."])
    )
    requirement_ids = {item.id for item in revision.requirements}
    assert "REQ-HOUSING" in requirement_ids
    assert "REQ-AMENDMENT-002-001" in requirement_ids
    assert revision.meta.revision == 2
    assert revision.meta.parent_hash == parent.meta.contract_hash
    directive = revision_directive_from_state(
        {"design_contract": revision.model_dump(mode="json")}
    )
    assert "day and night cycle" in directive


def test_contract_diff_routes_visual_amendments_through_asset_invalidation():
    parent = freeze_contract(_contract())
    visual_revision = freeze_contract(
        _contract(parent=parent, feedback=["Change the visual style to hand-painted art."])
    )
    visual_diff = diff_design_contracts(parent, visual_revision)
    assert visual_diff["asset_impacted"]
    assert should_continue_after_contract_gate(
        {
            "task_kind": "revision",
            "contract_gate": {"passed": True},
            "contract_diff": visual_diff,
        }
    ) == "asset_processing"

    rules_revision = freeze_contract(
        _contract(parent=parent, feedback=["Award ten points after each upgrade."])
    )
    assert not diff_design_contracts(parent, rules_revision)["asset_impacted"]


def test_frozen_contract_hash_detects_mutation_and_mixed_view_hashes():
    frozen = freeze_contract(_contract())
    payload = frozen.model_dump(mode="json")
    payload["requirements"][0]["statement"] = "tampered"
    gate = validate_contract(payload, require_frozen=True)
    assert not gate.passed
    assert any("hash mismatch" in issue for issue in gate.issues)

    views = derive_contract_views(frozen)
    with pytest.raises(ContractCompileError, match="style_bible contract hash mismatch"):
        enforce_execution_boundary(
            {
                "design_contract": frozen.model_dump(mode="json"),
                "contract_hash": frozen.meta.contract_hash,
                "style_bible": {**views["style_bible"], "contract_hash": "wrong"},
            }
        )


def test_scope_exceeded_is_explicit_instead_of_silently_clipping_entities():
    entities = [
        {"id": f"entity-{index}", "role": "prop"}
        for index in range(65)
    ]
    with pytest.raises(ScopeExceededError, match="65 entities exceeds limit 64"):
        compile_design_contract(
            {"title": "Too Large"},
            {"entities": entities},
            intent_record=IntentRecord(raw_prompt="all entities", normalized_prompt="all entities"),
        )


def test_contract_gate_never_reuses_parent_after_revision_compile_error():
    parent = freeze_contract(_contract())
    result = contract_gate_node(
        {
            "design_contract": parent.model_dump(mode="json"),
            "contract_error": "scope_exceeded: amendment is too large",
            "error_code": "scope_exceeded",
        }
    )
    assert not result["contract_gate"]["passed"]
    assert result["status"] == "failed"


def test_visual_revision_replaces_existing_asset_at_same_project_path():
    files = [
        {"path": "package.json", "content": "{}"},
        {"path": "index.html", "content": "<main></main>"},
        {"path": "src/main.ts", "content": "boot()"},
        {"path": "public/assets/sheet.png", "content_b64": "old"},
    ]
    prepared = _prepare_generated_artifacts(
        files,
        {
            "generated_assets": [
                {"path": "public/assets/sheet.png", "content_b64": "new"}
            ]
        },
    )
    sheets = [
        item
        for item in prepared["project_files"]
        if item["path"] == "public/assets/sheet.png"
    ]
    assert sheets == [{"path": "public/assets/sheet.png", "content_b64": "new"}]
