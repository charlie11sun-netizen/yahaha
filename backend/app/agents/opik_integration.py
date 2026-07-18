"""Fail-open integration with a self-hosted Opik instance.

Opik is deliberately optional at import time. The existing PostgreSQL trace
tables remain the audit source, while this module adds a best-effort export
for Agent/LLM observability when OPIK_ENABLED and OPIK_URL_OVERRIDE are set.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse

from app.core.config import settings
from app.agents.decision_trace import (
    AGENT_STEP_CONTRACT_VERSION,
    DECISION_TRACE_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

_CONFIG_LOCK = threading.Lock()
_AGENTS_CONFIGURED = False
GENERATION_TRACE_SCHEMA_VERSION = "gameweave.opik.generation/2.0"


def enabled() -> bool:
    return bool(settings.OPIK_ENABLED and settings.OPIK_URL_OVERRIDE.strip())


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _build_contract_observability_metadata(
    *,
    state: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build bounded, searchable DesignContract metadata for Opik.

    Flat fields support filtering and dashboards.  The three nested summaries
    retain enough evidence for a trace detail view without exporting the full
    contract, prompts, generated files, or image payloads.
    """

    state_value = _mapping(state)
    result_value = _mapping(result)
    decision_value = _mapping(decision)
    contract = _mapping(result_value.get("design_contract") or state_value.get("design_contract"))
    contract_meta = _mapping(contract.get("meta"))
    contract_hash = (
        result_value.get("contract_hash")
        or decision_value.get("contract_hash")
        or state_value.get("contract_hash")
        or contract_meta.get("contract_hash")
    )
    contract_revision = (
        result_value.get("contract_revision")
        or decision_value.get("design_contract_revision")
        or state_value.get("contract_revision")
        or contract_meta.get("revision")
    )
    contract_schema_version = (
        contract_meta.get("schema_version")
        or decision_value.get("design_contract_schema_version")
    )
    parent_hash = contract_meta.get("parent_hash")

    contract_diff = _mapping(
        result_value.get("contract_diff")
        or state_value.get("contract_diff")
        or decision_value.get("contract_diff")
    )
    gate = _mapping(
        result_value.get("contract_gate")
        or state_value.get("contract_gate")
        or decision_value.get("contract_gate")
    )
    gate_metrics = _mapping(gate.get("metrics"))
    acceptance_plan = _mapping(
        result_value.get("acceptance_plan") or state_value.get("acceptance_plan")
    )
    acceptance_tests = [
        item for item in (acceptance_plan.get("tests") or []) if isinstance(item, Mapping)
    ]
    qa = _mapping(
        result_value.get("gameplay_qa_result")
        or result_value.get("qa_result")
        or state_value.get("gameplay_qa_result")
        or decision_value.get("qa_result")
    )
    qa_metrics = _mapping(qa.get("metrics"))
    acceptance_results = [
        item for item in (qa.get("acceptance_results") or []) if isinstance(item, Mapping)
    ]

    manifest = _mapping(result_value.get("asset_manifest") or state_value.get("asset_manifest"))
    decision_plan = _mapping(decision_value.get("adopted_plan"))
    asset_payload = (
        manifest.get("assets")
        or decision_plan.get("assets")
        or result_value.get("asset_trace")
        or state_value.get("asset_trace")
        or decision_value.get("asset_trace")
        or []
    )
    assets = [item for item in asset_payload if isinstance(item, Mapping)]
    failed_semantic_ids: list[str] = []
    regeneration_semantic_ids: list[str] = []
    frame_coverages: list[float] = []
    audited_asset_count = 0
    regeneration_cell_count = 0
    for asset in assets:
        audit = _mapping(asset.get("frame_audit"))
        if audit:
            audited_asset_count += 1
            failed_semantic_ids.extend(
                str(item) for item in (audit.get("failed_frame_ids") or []) if str(item)
            )
            coverage = audit.get("required_asset_coverage")
            if isinstance(coverage, (int, float)):
                frame_coverages.append(float(coverage))
        regeneration_plan = [
            item for item in (asset.get("regeneration_plan") or []) if isinstance(item, Mapping)
        ]
        regeneration_cell_count += len(regeneration_plan)
        regeneration_semantic_ids.extend(
            str(item.get("semantic_id"))
            for item in regeneration_plan
            if item.get("semantic_id")
        )

    if not any(
        (
            contract_hash,
            contract_revision,
            contract,
            contract_diff,
            gate,
            acceptance_tests,
            acceptance_results,
            audited_asset_count,
            regeneration_cell_count,
        )
    ):
        return {}

    acceptance_pass_rate = qa_metrics.get("required_acceptance_pass")
    failed_acceptance_count = sum(
        1 for item in acceptance_results if item.get("passed") is False
    )
    gate_passed = gate.get("passed") if gate else None
    metadata = {
        # Explicit names remove the old ambiguity with the decision envelope's
        # legacy `contract_version` field.
        "contract_hash": contract_hash,
        "contract_revision": contract_revision,
        "design_contract_hash": contract_hash,
        "design_contract_revision": contract_revision,
        "design_contract_schema_version": contract_schema_version,
        "design_contract_parent_hash": parent_hash,
    }

    if gate:
        gate_summary = {
            "passed": gate_passed,
            "code": gate.get("code"),
            "issue_count": len(gate.get("issues") or []),
            "metrics": gate_metrics,
        }
        metadata.update(
            {
                "contract_gate_passed": gate_passed,
                "contract_gate_code": gate.get("code"),
                "contract_gate_issue_count": gate_summary["issue_count"],
                "required_intent_coverage": gate_metrics.get("required_intent_coverage"),
                "required_asset_state_count": gate_metrics.get("required_asset_state_count"),
                "orphan_semantic_id": gate_metrics.get("orphan_semantic_id"),
                "contract_gate": gate_summary,
            }
        )

    if contract_diff:
        diff_summary = {
            "asset_impacted": contract_diff.get("asset_impacted"),
            "code_impacted": contract_diff.get("code_impacted"),
            "acceptance_impacted": contract_diff.get("acceptance_impacted"),
            "added_semantic_ids": list(contract_diff.get("added_semantic_ids") or [])[:100],
            "removed_semantic_ids": list(contract_diff.get("removed_semantic_ids") or [])[:100],
            "changed_semantic_ids": list(contract_diff.get("changed_semantic_ids") or [])[:100],
            "changed_requirement_ids": list(
                contract_diff.get("changed_requirement_ids") or []
            )[:100],
        }
        metadata.update(
            {
                "contract_diff_asset_impacted": contract_diff.get("asset_impacted"),
                "contract_diff_code_impacted": contract_diff.get("code_impacted"),
                "contract_diff_acceptance_impacted": contract_diff.get("acceptance_impacted"),
                "contract_diff_added_semantic_count": len(
                    contract_diff.get("added_semantic_ids") or []
                ),
                "contract_diff_removed_semantic_count": len(
                    contract_diff.get("removed_semantic_ids") or []
                ),
                "contract_diff_changed_semantic_count": len(
                    contract_diff.get("changed_semantic_ids") or []
                ),
                "contract_diff_changed_requirement_count": len(
                    contract_diff.get("changed_requirement_ids") or []
                ),
                "contract_diff": diff_summary,
            }
        )

    if acceptance_plan or acceptance_results or acceptance_pass_rate is not None:
        acceptance_summary = {
            "test_count": len(acceptance_tests),
            "result_count": len(acceptance_results),
            "failed_count": failed_acceptance_count,
            "required_pass_rate": acceptance_pass_rate,
        }
        metadata.update(
            {
                "acceptance_test_count": acceptance_summary["test_count"],
                "acceptance_result_count": acceptance_summary["result_count"],
                "acceptance_failed_count": acceptance_summary["failed_count"],
                "required_acceptance_pass": acceptance_pass_rate,
                "acceptance_metrics": acceptance_summary,
            }
        )

    if audited_asset_count or regeneration_cell_count:
        frame_audit_summary = {
            "audited_asset_count": audited_asset_count,
            "failed_frame_count": len(failed_semantic_ids),
            "failed_semantic_ids": list(dict.fromkeys(failed_semantic_ids))[:100],
            "required_asset_coverage_min": min(frame_coverages) if frame_coverages else None,
            "regeneration_cell_count": regeneration_cell_count,
            "regeneration_semantic_ids": list(
                dict.fromkeys(regeneration_semantic_ids)
            )[:100],
        }
        metadata.update(
            {
                "frame_audit_asset_count": audited_asset_count,
                "failed_frame_count": frame_audit_summary["failed_frame_count"],
                "failed_semantic_ids": frame_audit_summary["failed_semantic_ids"],
                "required_asset_coverage_min": frame_audit_summary[
                    "required_asset_coverage_min"
                ],
                "regeneration_cell_count": regeneration_cell_count,
                "regeneration_semantic_ids": frame_audit_summary[
                    "regeneration_semantic_ids"
                ],
                "frame_audit_metrics": frame_audit_summary,
            }
        )
    return {key: value for key, value in metadata.items() if value is not None}


def contract_observability_metadata(
    *,
    state: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail-open public wrapper for DesignContract trace metadata."""

    try:
        return _build_contract_observability_metadata(
            state=state,
            result=result,
            decision=decision,
        )
    except Exception as exc:  # noqa: BLE001 - telemetry must never stop generation
        logger.warning("Opik contract metadata extraction failed: %s", exc)
        return {}


def contract_observability_tags(metadata: Mapping[str, Any] | None) -> list[str]:
    value = _mapping(metadata)
    tags: list[str] = []
    if value.get("design_contract_revision") is not None:
        tags.append(f"contract-revision:{value['design_contract_revision']}")
    if value.get("contract_gate_passed") is not None:
        tags.append(
            "contract-gate:passed" if value["contract_gate_passed"] else "contract-gate:failed"
        )
    if value.get("failed_frame_count"):
        tags.append("frame-audit:failed")
    if value.get("required_acceptance_pass") is not None:
        try:
            passed = float(value["required_acceptance_pass"]) >= 1.0
        except (TypeError, ValueError):
            passed = False
        tags.append("acceptance:passed" if passed else "acceptance:failed")
    return tags


def _apply_environment() -> bool:
    if not enabled():
        return False
    url_override = settings.OPIK_URL_OVERRIDE.strip()
    os.environ["OPIK_URL_OVERRIDE"] = url_override
    os.environ["OPIK_PROJECT_NAME"] = settings.OPIK_PROJECT_NAME.strip() or "gameweave-agent"
    os.environ["OPIK_WORKSPACE"] = settings.OPIK_WORKSPACE.strip() or "default"
    if settings.OPIK_ENVIRONMENT.strip():
        os.environ["OPIK_ENVIRONMENT"] = settings.OPIK_ENVIRONMENT.strip()
    # Self-hosted Opik does not require a Comet API key.
    os.environ.pop("OPIK_API_KEY", None)
    # The desktop environment may expose an HTTP proxy globally.  A local
    # self-hosted Opik endpoint must bypass it; otherwise httpx can return a
    # proxy-generated 503 even though the Opik service is healthy.
    host = urlparse(url_override).hostname
    if host:
        bypass_hosts = {"localhost", "127.0.0.1", host}
        existing = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
        bypass_hosts.update(part.strip() for part in existing.split(",") if part.strip())
        no_proxy = ",".join(sorted(bypass_hosts))
        os.environ["NO_PROXY"] = no_proxy
        os.environ["no_proxy"] = no_proxy
    return True


@contextmanager
def _fail_open_context(manager_factory, *, label: str) -> Iterator[Any | None]:
    """Enter an Opik context without letting telemetry break generation."""
    try:
        manager = manager_factory()
        value = manager.__enter__()
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik %s unavailable: %s", label, exc)
        yield None
        return

    try:
        yield value
    except BaseException:  # preserve the generation exception after recording it
        exc_info = sys.exc_info()
        try:
            manager.__exit__(*exc_info)
        except Exception as telemetry_exc:  # noqa: BLE001
            logger.warning("Opik %s error finalization failed: %s", label, telemetry_exc)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - observability must fail open
            logger.warning("Opik %s finalization failed: %s", label, exc)


@contextmanager
def generation_trace(
    *,
    task_id: str,
    dispatch_generation: int | None = None,
) -> Iterator[Any | None]:
    """Create the task-level root trace used to group one generation flow."""
    if not _apply_environment():
        yield None
        return

    try:
        from opik import start_as_current_trace
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik generation root trace unavailable: %s", exc)
        yield None
        return

    metadata = {
        "schema_version": GENERATION_TRACE_SCHEMA_VERSION,
        "decision_schema_version": DECISION_TRACE_SCHEMA_VERSION,
        "trace_contract_version": AGENT_STEP_CONTRACT_VERSION,
        "task_id": task_id,
        "dispatch_generation": dispatch_generation,
        "environment": settings.OPIK_ENVIRONMENT.strip() or None,
    }
    tags = ["gameweave", "game-generation"]
    with _fail_open_context(
        lambda: start_as_current_trace(
            name="game-generation",
            input={"task_id": task_id},
            metadata=metadata,
            tags=tags,
            project_name=settings.OPIK_PROJECT_NAME.strip() or "gameweave-agent",
            thread_id=f"task:{task_id}",
        ),
        label="generation root trace",
    ) as trace:
        yield trace


@contextmanager
def generation_span(
    *,
    node_name: str,
    task_id: str,
    step_id: str | None,
    agent: str,
    display_name: str,
    metadata: Mapping[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Create a stage span below the active generation root trace."""
    if not _apply_environment():
        yield None
        return

    try:
        from opik import start_as_current_span
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik stage span unavailable: %s", exc)
        yield None
        return

    stage_metadata = {
        "schema_version": GENERATION_TRACE_SCHEMA_VERSION,
        "decision_schema_version": DECISION_TRACE_SCHEMA_VERSION,
        "trace_contract_version": AGENT_STEP_CONTRACT_VERSION,
        "task_id": task_id,
        "step_id": step_id,
        "node_name": node_name,
        "agent": agent,
        "display_name": display_name,
        **_mapping(metadata),
    }
    stage_tags = [
        "gameweave-stage",
        f"agent:{agent}",
        *contract_observability_tags(stage_metadata),
    ]
    with _fail_open_context(
        lambda: start_as_current_span(
            name=f"stage.{node_name}",
            input={"task_id": task_id, "step_id": step_id},
            metadata=stage_metadata,
            tags=stage_tags,
        ),
        label=f"stage span {node_name}",
    ) as span:
        if span is not None:
            try:
                from opik import opik_context

                # Opik 2.1.x applies metadata/tags supplied to the context
                # manager at span finalization; update the active span now so
                # the searchable task identifiers are retained even when a
                # later update only adds terminal status fields.
                opik_context.update_current_span(
                    metadata=stage_metadata,
                    tags=stage_tags,
                )
            except Exception as exc:  # noqa: BLE001 - observability must fail open
                logger.warning("Opik stage span metadata update failed: %s", exc)
        yield span


def update_generation_trace(
    *,
    name: str | None = None,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    thread_id: str | None = None,
) -> None:
    """Merge searchable task/game fields into the active root trace."""
    if not enabled():
        return
    try:
        from opik import opik_context

        opik_context.update_current_trace(
            name=name,
            input=input,
            output=output,
            metadata=metadata,
            tags=tags,
            thread_id=thread_id,
        )
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik generation trace update failed: %s", exc)


def update_generation_span(
    *,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> None:
    """Merge terminal stage data into the active stage span."""
    if not enabled():
        return
    try:
        from opik import opik_context

        opik_context.update_current_span(output=output, metadata=metadata, tags=tags)
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik generation span update failed: %s", exc)


def configure_agents_tracing() -> bool:
    """Register the OpenAI Agents processor once per worker process."""
    global _AGENTS_CONFIGURED
    if not _apply_environment():
        return False
    with _CONFIG_LOCK:
        if _AGENTS_CONFIGURED:
            return True
        try:
            from agents import set_trace_processors
            from opik.integrations.openai.agents import OpikTracingProcessor

            set_trace_processors(processors=[OpikTracingProcessor()])
        except Exception as exc:  # noqa: BLE001 - observability must fail open
            logger.warning("Opik Agents tracing unavailable: %s", exc)
            return False
        _AGENTS_CONFIGURED = True
        logger.info(
            "Opik Agents tracing enabled project=%s url=%s",
            settings.OPIK_PROJECT_NAME,
            settings.OPIK_URL_OVERRIDE,
        )
        return True


def wrap_openai_client(client: Any) -> Any:
    """Wrap an OpenAI client so Responses API calls are sent to Opik."""
    if not _apply_environment():
        return client
    try:
        from opik.integrations.openai import track_openai

        return track_openai(
            client,
            project_name=settings.OPIK_PROJECT_NAME.strip() or "gameweave-agent",
        )
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik OpenAI tracing unavailable: %s", exc)
        return client


def flush() -> None:
    """Flush the SDK batch queue at a Celery task/run boundary."""
    if not enabled():
        return
    try:
        from opik import flush_tracker

        flush_tracker()
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik trace flush failed: %s", exc)


__all__ = [
    "GENERATION_TRACE_SCHEMA_VERSION",
    "contract_observability_metadata",
    "contract_observability_tags",
    "configure_agents_tracing",
    "enabled",
    "flush",
    "generation_span",
    "generation_trace",
    "update_generation_span",
    "update_generation_trace",
    "wrap_openai_client",
]
