"""Compatibility facade for the bounded code-agent repair and author loops."""
from __future__ import annotations

from app.agents import agent_tools, author_runner, llm, repair_session, tracing, validation
from app.agents.patch_execution import (
    AppliedPatchDelta,
    PatchFileChange,
    PatchOperationKind,
    VerifiedPatch,
    verify_patch_operation,
)
from app.core.config import settings

# Public facade surface.  Keep the implementation modules behind module
# objects so a future split cannot accidentally turn an underscore helper into
# a cross-module import contract.
AgentToolPolicy = agent_tools.AgentToolPolicy
RepairOutcome = repair_session.RepairOutcome
RepairSession = repair_session.RepairSession
available_skills = repair_session.available_skills
author_enabled = author_runner.author_enabled
enabled = author_runner.enabled
run_repair = author_runner.run_repair
run_revision = author_runner.run_revision


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
    planning_context: dict | None = None,
) -> RepairOutcome | None:
    """Route project authoring through the public team facade when needed.

    ``planning_context`` = {"items": [...], "response_id": str | None} — the
    gameplay-planning/game-design transcript replayed into DesignContractAgent
    as explicit input items (the gateway drops server-side chaining).
    """
    if not files:
        return None
    from app.services.vite_projects import is_vite_project

    if not is_vite_project(files):
        author_kwargs = {
            "spec": spec,
            "design": design,
            "runtime": runtime,
            "dimension": dimension,
            "qa_feedback": qa_feedback,
            "max_turns": max_turns,
            "deadline_at": deadline_at,
        }
        if planning_context:
            author_kwargs["planning_context"] = planning_context
        return author_runner.run_author(files, **author_kwargs)

    from app.agents import author_team

    team_kwargs = {
        "spec": spec,
        "design": design,
        "runtime": runtime,
        "dimension": dimension,
        "qa_feedback": qa_feedback,
        "max_turns": max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
        "live_step_id": tracing.current_step_id(),
        "deadline_at": deadline_at,
    }
    if planning_context:
        team_kwargs["planning_context"] = planning_context
    return author_team.run_project_author_team(files, **team_kwargs)


_LEGACY_PRIVATE_ATTRS = {
    # Kept solely for older in-package callers and tests.  These names are
    # resolved lazily and are intentionally absent from __all__ and __dir__.
    name: (module, name)
    for module, names in (
        (agent_tools, ("_make_tools",)),
        (
            author_runner,
            (
                "_3D_NOTE",
                "_AUTHOR_INSTRUCTIONS",
                "_INSTRUCTIONS",
                "_build_author_input",
                "_build_input",
                "_close_client",
                "_execute_agent",
                "_heartbeat_status",
                "_log_cache_hit",
                "_record",
                "_start_heartbeat",
                "_stop_heartbeat",
                "_usage_of",
            ),
        ),
        (
            repair_session,
            (
                "_bundle_context_text",
                "_bundle_file_rows",
                "_compact_diff",
                "_delta_text",
                "_file_kind",
                "_line_count",
                "_line_delta",
                "_script_refs",
                "_skill_name_ok",
            ),
        ),
    )
    for name in names
}


def __getattr__(name: str):
    """Resolve pre-facade private names without importing them across modules."""
    target = _LEGACY_PRIVATE_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(*target)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "AgentToolPolicy",
    "AppliedPatchDelta",
    "PatchFileChange",
    "PatchOperationKind",
    "RepairOutcome",
    "RepairSession",
    "VerifiedPatch",
    "available_skills",
    "author_enabled",
    "enabled",
    "run_author",
    "run_repair",
    "run_revision",
    "verify_patch_operation",
]
