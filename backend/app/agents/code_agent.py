"""Compatibility facade for the bounded code-agent repair and author loops."""
from __future__ import annotations

from app.agents import llm, tracing, validation
from app.agents.agent_tools import _make_tools
from app.agents.author_runner import (
    _3D_NOTE,
    _AUTHOR_INSTRUCTIONS,
    _INSTRUCTIONS,
    _build_author_input,
    _build_input,
    _close_client,
    _execute_agent,
    _heartbeat_status,
    _log_cache_hit,
    _record,
    _start_heartbeat,
    _stop_heartbeat,
    _usage_of,
    author_enabled,
    enabled,
    run_author,
    run_repair,
)
from app.agents.patch_execution import (
    AppliedPatchDelta,
    PatchFileChange,
    PatchOperationKind,
    VerifiedPatch,
    verify_patch_operation,
)
from app.agents.repair_session import (
    RepairOutcome,
    RepairSession,
    _bundle_context_text,
    _bundle_file_rows,
    _compact_diff,
    _delta_text,
    _file_kind,
    _line_count,
    _line_delta,
    _script_refs,
    _skill_name_ok,
    available_skills,
)
from app.core.config import settings

__all__ = [
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
    "verify_patch_operation",
]
