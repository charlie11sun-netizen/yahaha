"""Compatibility facade for the modular author-team implementation."""

from __future__ import annotations

from app.agents import tracing
from app.agents import author_contract, author_merge, author_orchestration, author_prompts, author_runner


_LEGACY_PRIVATE_MODULES = (
    author_prompts,
    author_contract,
    author_merge,
    author_orchestration,
    author_runner,
)


def __getattr__(name: str):
    """Resolve legacy implementation helpers without wildcard re-exports."""
    for module in _LEGACY_PRIVATE_MODULES:
        if hasattr(module, name) and name.startswith("_"):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


def run_project_author_team(
    files: list[dict],
    *,
    spec: dict,
    design: dict,
    runtime: str,
    dimension: str,
    qa_feedback: list | None,
    max_turns: int,
    live_step_id: str | None,
    team_deadline_seconds: float | None = None,
    team_token_budget: int | None = None,
    team_changed_file_budget: int | None = None,
    deadline_at: float | None = None,
):
    # A direct assignment is honored for old callers that monkeypatch the
    # runner.  Normal application code uses the public runner entry point.
    execute_agent = globals().get("_execute_agent", author_runner.execute_agent)
    return author_orchestration.run_project_author_team(
        files, spec=spec, design=design, runtime=runtime, dimension=dimension,
        qa_feedback=qa_feedback, max_turns=max_turns, live_step_id=live_step_id,
        team_deadline_seconds=team_deadline_seconds, team_token_budget=team_token_budget,
        team_changed_file_budget=team_changed_file_budget, deadline_at=deadline_at,
        _execute_agent_fn=execute_agent, _tracing=tracing,
    )


__all__ = [
    "run_project_author_team",
]
