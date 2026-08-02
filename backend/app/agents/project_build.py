"""Build generated source projects into browser-ready runtime artifacts."""
from __future__ import annotations

from app.services import sandbox_client
from app.services.artifacts import ArtifactError, artifact_size
from app.services.vite_projects import (
    VITE_PROJECT_FORMAT,
    prepare_vite_runtime_files,
    validate_vite_project,
)


def project_build_node(state: dict) -> dict:
    if state.get("artifact_format") != VITE_PROJECT_FORMAT:
        return {
            "build_result": {"ok": True, "skipped": True, "format": "legacy-bundle"},
            "_agent": "ProjectBuildAgent",
            "_logs": ["project build skipped: generated files are already browser-ready"],
        }

    project_files = state.get("project_files") or []
    errors = validate_vite_project(project_files)
    if errors:
        return {
            "generated_files": [],
            "build_result": {"ok": False, "errors": errors, "format": VITE_PROJECT_FORMAT},
            "last_error": "; ".join(errors),
            "_agent": "ProjectBuildAgent",
            "_logs": ["Vite source validation failed"] + errors[:8],
        }
    try:
        result = sandbox_client.build_vite_project(project_files)
    except sandbox_client.SandboxUnavailableError as exc:
        return {
            "generated_files": [],
            "build_result": {"ok": False, "errors": [str(exc)], "format": VITE_PROJECT_FORMAT},
            "last_error": str(exc),
            "_agent": "ProjectBuildAgent",
            "_logs": [f"Vite build sandbox unavailable: {exc}"],
        }
    if not result.ok:
        errors = result.errors or [result.detail or "Vite build failed"]
        return {
            "generated_files": [],
            "build_result": {
                "ok": False,
                "errors": errors,
                "warnings": result.warnings,
                "duration_ms": result.duration_ms,
                "timed_out": result.timed_out,
                "format": VITE_PROJECT_FORMAT,
            },
            "last_error": "; ".join(errors[:5]),
            "_agent": "ProjectBuildAgent",
            "_logs": ["Vite build failed"] + result.logs[-8:] + errors[:8],
        }
    try:
        runtime_files = prepare_vite_runtime_files(result.files)
    except ArtifactError as exc:
        return {
            "generated_files": [],
            "build_result": {"ok": False, "errors": [str(exc)], "format": VITE_PROJECT_FORMAT},
            "last_error": str(exc),
            "_agent": "ProjectBuildAgent",
            "_logs": [f"Vite runtime packaging failed: {exc}"],
        }
    total = sum(artifact_size(item) for item in runtime_files)
    return {
        "generated_files": runtime_files,
        "build_result": {
            "ok": True,
            "files": len(runtime_files),
            "bytes": total,
            "warnings": result.warnings,
            "duration_ms": result.duration_ms,
            "format": VITE_PROJECT_FORMAT,
        },
        "last_error": None,
        "_agent": "ProjectBuildAgent",
        "_logs": [
            f"Vite build succeeded in {result.duration_ms}ms",
            f"dist artifacts: {len(runtime_files)} file(s), {total} bytes",
        ] + result.logs[-8:],
    }


__all__ = ["project_build_node"]
