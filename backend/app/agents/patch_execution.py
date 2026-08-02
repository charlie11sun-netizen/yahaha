"""Codex-style patch verification and structured in-memory deltas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agents.patch_parser import (
    _PROTECTED_FILES,
    _PatchError,
    _apply_chunks,
    _parse_create_diff,
    _parse_update_diff,
    _resolve_bundle_path,
    _validate_new_bundle_path,
)


PatchChangeKind = Literal["add", "update", "delete", "move"]
PatchOperationKind = Literal["create_file", "update_file", "delete_file"]


@dataclass(frozen=True)
class PatchFileChange:
    """One verified file mutation, including enough state to audit or revert it."""

    kind: PatchChangeKind
    path: str
    old_content: str | None
    new_content: str | None
    move_to: str | None = None
    added_lines: int = 0
    deleted_lines: int = 0
    chunk_count: int = 0
    size: int = 0


@dataclass(frozen=True)
class VerifiedPatch:
    """A fully validated patch plan that is safe to commit to the bundle."""

    changes: tuple[PatchFileChange, ...]
    fuzz: int = 0


@dataclass(frozen=True)
class AppliedPatchDelta:
    """Textual mutations known to have committed, modelled after Codex's delta."""

    changes: tuple[PatchFileChange, ...]
    exact: bool = True


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text else 0


def verify_patch_operation(
    operation_type: PatchOperationKind,
    path: str,
    diff: str | None,
    move_to: str | None,
    contents: dict[str, str],
    *,
    max_file_bytes: int,
    max_bundle_files: int,
) -> VerifiedPatch:
    """Validate one structured SDK operation directly into the shared commit plan."""

    if operation_type == "create_file":
        target = _validate_new_bundle_path(path, contents)
        new_content = _parse_create_diff(diff, target)
        size = len(new_content.encode("utf-8"))
        if size > max_file_bytes:
            raise _PatchError(
                f"new file {target} would be {size}B, over the {max_file_bytes // 1000}KB limit"
            )
        if len(contents) + 1 > max_bundle_files:
            raise _PatchError(
                f"bundle would grow to {len(contents) + 1} files (max {max_bundle_files}); "
                "consolidate systems into existing modules"
            )
        return VerifiedPatch(
            changes=(
                PatchFileChange(
                    kind="add",
                    path=target,
                    old_content=None,
                    new_content=new_content,
                    added_lines=_line_count(new_content),
                    size=size,
                ),
            )
        )

    if operation_type == "delete_file":
        target = _resolve_bundle_path(path, contents)
        if target in _PROTECTED_FILES:
            raise _PatchError(
                f"cannot delete {target}; entry files {', '.join(_PROTECTED_FILES)} must stay"
            )
        old_content = contents[target]
        return VerifiedPatch(
            changes=(
                PatchFileChange(
                    kind="delete",
                    path=target,
                    old_content=old_content,
                    new_content=None,
                    deleted_lines=_line_count(old_content),
                ),
            )
        )

    if operation_type != "update_file":
        raise _PatchError(f"unsupported apply_patch operation {operation_type!r}")

    target = _resolve_bundle_path(path, contents)
    destination = None
    if move_to:
        if target in _PROTECTED_FILES:
            raise _PatchError(
                f"cannot move {target}; protected entry files must stay at their original paths"
            )
        destination = _validate_new_bundle_path(move_to, contents)

    old_content = contents[target]
    normalized = old_content.replace("\r\n", "\n")
    chunks, fuzz = _parse_update_diff(diff, normalized, target)
    new_content = _apply_chunks(normalized, chunks, target)
    if "\r\n" in old_content:
        new_content = new_content.replace("\n", "\r\n")
    if new_content == old_content and destination is None:
        raise _PatchError("patch made no changes")
    size = len(new_content.encode("utf-8"))
    if size > max_file_bytes:
        raise _PatchError(
            f"{target} exceeds the {max_file_bytes // 1000}KB limit after this patch "
            f"({size}B); apply a smaller patch"
        )
    return VerifiedPatch(
        changes=(
            PatchFileChange(
                kind="move" if destination else "update",
                path=target,
                move_to=destination,
                old_content=old_content,
                new_content=new_content,
                added_lines=sum(len(chunk.ins_lines) for chunk in chunks),
                deleted_lines=sum(len(chunk.del_lines) for chunk in chunks),
                chunk_count=len(chunks),
                size=size,
            ),
        ),
        fuzz=fuzz,
    )
