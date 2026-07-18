from __future__ import annotations

import json

import opik
import pytest

from app.agents import opik_integration
from app.agents.decision_trace import (
    AGENT_STEP_CONTRACT_VERSION,
    DECISION_TRACE_SCHEMA_VERSION,
    build_decision,
)


class _FakeContext:
    def __init__(self, value=None):
        self.value = value
        self.exit_args = None

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        self.exit_args = args
        return False


def _enable(monkeypatch):
    monkeypatch.setattr(opik_integration.settings, "OPIK_ENABLED", True)
    monkeypatch.setattr(
        opik_integration.settings,
        "OPIK_URL_OVERRIDE",
        "http://localhost:15173/api",
    )
    monkeypatch.setattr(opik_integration.settings, "OPIK_PROJECT_NAME", "test-project")
    monkeypatch.setattr(opik_integration.settings, "OPIK_ENVIRONMENT", "test")


def test_generation_trace_has_searchable_task_identity(monkeypatch):
    _enable(monkeypatch)
    captured = {}
    context = _FakeContext(value={"trace": True})

    def start_trace(**kwargs):
        captured.update(kwargs)
        return context

    monkeypatch.setattr(opik, "start_as_current_trace", start_trace)

    with opik_integration.generation_trace(
        task_id="task-123", dispatch_generation=4
    ) as trace:
        assert trace == {"trace": True}

    assert captured["name"] == "game-generation"
    assert captured["thread_id"] == "task:task-123"
    assert captured["metadata"]["task_id"] == "task-123"
    assert captured["metadata"]["schema_version"] == "gameweave.opik.generation/2.1"
    assert captured["metadata"]["trace_contract_version"] == AGENT_STEP_CONTRACT_VERSION
    assert context.exit_args == (None, None, None)


def test_generation_trace_preserves_generation_errors(monkeypatch):
    _enable(monkeypatch)
    context = _FakeContext()
    monkeypatch.setattr(opik, "start_as_current_trace", lambda **_: context)

    with pytest.raises(RuntimeError, match="generation failed"):
        with opik_integration.generation_trace(task_id="task-error"):
            raise RuntimeError("generation failed")

    assert context.exit_args[0] is RuntimeError
    assert str(context.exit_args[1]) == "generation failed"


def test_generation_span_retains_task_metadata(monkeypatch):
    _enable(monkeypatch)
    updates = []
    captured = {}
    context = _FakeContext(value={"span": True})

    def start_span(**kwargs):
        captured.update(kwargs)
        return context

    monkeypatch.setattr(opik, "start_as_current_span", start_span)
    monkeypatch.setattr(
        opik.opik_context,
        "update_current_span",
        lambda **kwargs: updates.append(kwargs),
    )

    with opik_integration.generation_span(
        node_name="intent_spec",
        task_id="task-456",
        step_id="step-1",
        agent="IntentSpecAgent",
        display_name="Intent Spec",
        metadata={"contract_hash": "hash-1", "design_contract_revision": 3},
    ):
        opik_integration.update_generation_span(
            output={"status": "completed"},
            metadata={"failed": False},
            tags=["status:completed"],
        )

    assert updates[0]["metadata"]["task_id"] == "task-456"
    assert updates[0]["metadata"]["step_id"] == "step-1"
    assert updates[0]["metadata"]["contract_hash"] == "hash-1"
    assert captured["metadata"]["design_contract_revision"] == 3
    assert captured["metadata"]["trace_contract_version"] == AGENT_STEP_CONTRACT_VERSION
    assert "contract-revision:3" in captured["tags"]
    assert updates[-1]["output"] == {"status": "completed"}
    assert updates[-1]["metadata"] == {"failed": False}


def test_generation_trace_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(opik_integration.settings, "OPIK_ENABLED", False)
    with opik_integration.generation_trace(task_id="task-disabled") as trace:
        assert trace is None


def test_contract_observability_metadata_flattens_gate_acceptance_and_frame_audit():
    metadata = opik_integration.contract_observability_metadata(
        state={
            "design_contract": {
                "meta": {
                    "schema_version": 1,
                    "revision": 4,
                    "parent_hash": "parent-hash",
                    "contract_hash": "contract-hash",
                }
            },
            "contract_hash": "contract-hash",
            "contract_revision": 4,
            "contract_diff": {
                "asset_impacted": True,
                "code_impacted": True,
                "acceptance_impacted": False,
                "added_semantic_ids": ["player.victory"],
                "removed_semantic_ids": [],
                "changed_semantic_ids": ["player.idle"],
                "changed_requirement_ids": ["REQ-4"],
            },
            "contract_gate": {
                "passed": True,
                "code": None,
                "issues": [],
                "metrics": {
                    "required_intent_coverage": 1.0,
                    "required_asset_state_count": 8,
                    "orphan_semantic_id": 0,
                },
            },
            "acceptance_plan": {"tests": [{"id": "AT-1"}, {"id": "AT-2"}]},
            "gameplay_qa_result": {
                "metrics": {"required_acceptance_pass": 0.5},
                "acceptance_results": [
                    {"id": "AT-1", "passed": True},
                    {"id": "AT-2", "passed": False},
                ],
            },
            "asset_manifest": {
                "assets": [
                    {
                        "frame_audit": {
                            "failed_frame_ids": ["player.idle"],
                            "required_asset_coverage": 0.875,
                        },
                        "regeneration_plan": [{"semantic_id": "player.idle"}],
                    }
                ]
            },
        }
    )

    assert metadata["contract_hash"] == "contract-hash"
    assert metadata["design_contract_revision"] == 4
    assert metadata["contract_gate_passed"] is True
    assert metadata["contract_diff_changed_semantic_count"] == 1
    assert metadata["acceptance_failed_count"] == 1
    assert metadata["required_acceptance_pass"] == 0.5
    assert metadata["failed_semantic_ids"] == ["player.idle"]
    assert metadata["regeneration_cell_count"] == 1
    assert metadata["regeneration_semantic_ids"] == ["player.idle"]
    assert metadata["frame_audit_metrics"]["required_asset_coverage_min"] == 0.875
    assert opik_integration.contract_observability_tags(metadata) == [
        "contract-revision:4",
        "contract-gate:passed",
        "frame-audit:failed",
        "acceptance:failed",
    ]


def test_contract_only_metadata_does_not_replace_missing_stage_metrics_with_zeroes():
    metadata = opik_integration.contract_observability_metadata(
        state={
            "design_contract": {
                "meta": {
                    "schema_version": 1,
                    "revision": 5,
                    "contract_hash": "contract-only-hash",
                }
            }
        }
    )

    assert metadata["contract_hash"] == "contract-only-hash"
    assert "acceptance_test_count" not in metadata
    assert "frame_audit_asset_count" not in metadata
    assert "contract_diff_changed_semantic_count" not in metadata
    assert "contract_gate_issue_count" not in metadata


def test_contract_observability_promotes_fields_from_nested_decision_payload():
    metadata = opik_integration.contract_observability_metadata(
        decision={
            "contract_hash": "nested-contract-hash",
            "design_contract_revision": 8,
            "design_contract_schema_version": 1,
            "contract_gate": {"passed": False, "issues": ["missing intent"]},
            "qa_result": {
                "metrics": {"required_acceptance_pass": 0.75},
                "acceptance_results": [{"id": "AT-8", "passed": False}],
            },
            "adopted_plan": {
                "assets": [
                    {
                        "frame_audit": {
                            "failed_frame_ids": ["enemy.attack"],
                            "required_asset_coverage": 0.75,
                        },
                        "regeneration_plan": [{"semantic_id": "enemy.attack"}],
                    }
                ]
            },
        }
    )

    assert metadata["design_contract_revision"] == 8
    assert metadata["contract_gate_passed"] is False
    assert metadata["required_acceptance_pass"] == 0.75
    assert metadata["failed_semantic_ids"] == ["enemy.attack"]
    assert metadata["regeneration_semantic_ids"] == ["enemy.attack"]


def test_decision_trace_separates_envelope_version_from_design_contract_revision():
    decision = build_decision(
        {
            "design_contract": {
                "meta": {
                    "schema_version": 1,
                    "revision": 6,
                    "contract_hash": "decision-contract-hash",
                }
            },
            "contract_hash": "decision-contract-hash",
            "contract_revision": 6,
        },
        {},
        agent="IntentSpecAgent",
        display_name="Intent Spec",
    )

    assert decision["schema_version"] == DECISION_TRACE_SCHEMA_VERSION
    assert decision["contract_version"] == AGENT_STEP_CONTRACT_VERSION
    assert decision["trace_contract_version"] == AGENT_STEP_CONTRACT_VERSION
    assert decision["design_contract_revision"] == 6
    assert decision["design_contract_hash"] == "decision-contract-hash"


def test_finalize_root_trace_exposes_contract_identity(db_session_factory, monkeypatch):
    from app.agents import pipeline
    from app.models import GenerationTask, LLMCall, User
    from app.models.common import TaskStatus

    db = db_session_factory()
    user = User(
        email="opik-contract@example.com",
        password_hash="x",
        display_name="Opik Contract",
        avatar_initial="O",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(
        user_id=user.id,
        idea="trace the contract",
        status=TaskStatus.SUCCEEDED,
        contract_json=json.dumps(
            {
                "meta": {
                    "schema_version": 1,
                    "revision": 7,
                    "contract_hash": "root-contract-hash",
                    "parent_hash": "root-parent-hash",
                }
            }
        ),
        contract_hash="root-contract-hash",
        contract_revision=7,
        opik_trace_id="11111111-2222-4333-8444-555555555555",
    )
    db.add(task)
    db.flush()
    db.add(
        LLMCall(
            task_id=task.id,
            model="gpt-test",
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            cached_tokens=75,
            cache_write_tokens=5,
            cache_read_reported=True,
            cache_write_reported=True,
            latency_ms=250,
        )
    )
    db.commit()
    task_id = task.id
    db.close()

    captured = {}
    monkeypatch.setattr(pipeline, "SessionLocal", db_session_factory)
    monkeypatch.setattr(
        opik_integration,
        "update_generation_trace",
        lambda **kwargs: captured.update(kwargs),
    )

    pipeline._finalize_generation_trace(task_id)

    assert captured["metadata"]["contract_hash"] == "root-contract-hash"
    assert captured["metadata"]["contract_revision"] == 7
    assert captured["metadata"]["design_contract_schema_version"] == 1
    assert captured["metadata"]["trace_contract_version"] == AGENT_STEP_CONTRACT_VERSION
    assert captured["metadata"]["opik_trace_id"] == task.opik_trace_id
    assert captured["metadata"]["llm_cache_hit_rate"] == 0.75
    assert captured["metadata"]["llm_cache_read_reported_count"] == 1
    assert captured["output"]["contract_hash"] == "root-contract-hash"
    assert captured["output"]["contract_revision"] == 7
    assert captured["output"]["cache_observability"]["cached_tokens"] == 75
    assert "contract-revision:7" in captured["tags"]


def test_opik_trace_id_is_persisted_for_direct_correlation(
    db_session_factory, monkeypatch
):
    from types import SimpleNamespace

    from app.agents import pipeline
    from app.models import GenerationTask, User

    db = db_session_factory()
    user = User(
        email="opik-id@example.com",
        password_hash="x",
        display_name="Opik Id",
        avatar_initial="O",
    )
    db.add(user)
    db.flush()
    task = GenerationTask(user_id=user.id, idea="persist trace id")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    monkeypatch.setattr(pipeline, "SessionLocal", db_session_factory)
    pipeline._persist_opik_trace_id(
        task_id,
        SimpleNamespace(id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
    )

    db = db_session_factory()
    assert db.get(GenerationTask, task_id).opik_trace_id == (
        "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    )
    db.close()
