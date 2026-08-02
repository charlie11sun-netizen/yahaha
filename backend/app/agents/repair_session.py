"""In-memory repair workspace and pure tool implementations for code agents."""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher, unified_diff
from fnmatch import fnmatch

from app.agents import smoke, tracing, validation
from app.agents.patch_execution import (
    AppliedPatchDelta,
    PatchFileChange,
    PatchOperationKind,
    VerifiedPatch,
    verify_patch_operation,
)
from app.agents.patch_parser import _PatchError

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
_PROTECTED_FILES = ("index.html", "style.css", "game.js", "package.json", "src/main.ts")
# 新建文件：平铺文件名（天然排除 / 与 ..），只允许 .js/.css 模块
_NEW_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(?:js|css)$")
_PROJECT_NEW_PATH_RE = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9][A-Za-z0-9._/-]{0,179}"
    r"\.(?:js|mjs|ts|tsx|css|json|md)$"
)
_SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"']", re.I)
_MAX_ERRORS_SHOWN = 8
_HEARTBEAT_INTERVAL_SECONDS = 12.0
_MAX_SEARCH_MATCHES = 24
_MAX_DIFF_CHARS = 12000
_MAX_PATCH_OPERATIONS = 16
_MAX_READ_PATHS = 16
_MAX_SOURCE_DIAGNOSTICS_SHOWN = 12


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text else 0


def _line_delta(old: str, new: str) -> tuple[int, int]:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    added = 0
    deleted = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=old_lines, b=new_lines).get_opcodes():
        if tag in {"replace", "delete"}:
            deleted += i2 - i1
        if tag in {"replace", "insert"}:
            added += j2 - j1
    return added, deleted


def _delta_text(added: int, deleted: int) -> str:
    return f"+{max(0, added)} -{max(0, deleted)}"


def _script_refs(html: str) -> list[str]:
    refs: list[str] = []
    for raw in _SCRIPT_SRC_RE.findall(html or ""):
        path = raw.strip().split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        if path and "://" not in path:
            refs.append(path)
    return refs


def _file_kind(path: str) -> str:
    if path.endswith(".html"):
        return "html"
    if path.endswith(".css"):
        return "css"
    if path.endswith((".js", ".mjs", ".ts", ".tsx")):
        return "script"
    return "asset"


def _bundle_file_rows(contents: dict[str, str], order: list[str]) -> list[dict]:
    refs = set(_script_refs(contents.get("index.html", "")))
    project_mode = "src/main.ts" in contents or "src/main.js" in contents
    rows = []
    for path in order:
        body = contents.get(path, "")
        rows.append(
            {
                "path": path,
                "bytes": len(body.encode("utf-8")),
                "lines": _line_count(body),
                "kind": _file_kind(path),
                "referenced": path in _PROTECTED_FILES or path in refs or project_mode,
            }
        )
    return rows


def _bundle_context_text(files: list[dict]) -> str:
    contents = {str(f.get("path")): str(f.get("content") or "") for f in files or []}
    order = [str(f.get("path")) for f in files or [] if f.get("path")]
    rows = _bundle_file_rows(contents, order)
    refs = _script_refs(contents.get("index.html", ""))
    lines = [
        "Workspace is the generated game bundle only; do not assume access to the GameWeave platform repository.",
        "Bundle files:",
    ]
    lines.extend(
        f"- {row['path']} ({row['kind']}, {row['bytes']}B, {row['lines']} line(s), "
        f"{'referenced' if row['referenced'] else 'unreferenced'})"
        for row in rows
    )
    if refs:
        lines.append("index.html script order: " + " -> ".join(refs))
    return "\n".join(lines)


def _compact_diff(path: str, old: str, new: str) -> tuple[str | None, str]:
    if old == new:
        return None, "empty"
    diff = "".join(
        unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )
    if not diff:
        return None, "empty"
    if len(diff) > _MAX_DIFF_CHARS:
        return None, "omitted_large"
    return diff, "unified"

@dataclass
class RepairOutcome:
    files: list[dict]
    changed: list[str]
    tokens: int
    logs: list[str]
    note: str
    checks_ok: bool
    turns: int = 0
    # Backward-compatible terminal metadata.  Existing callers that only care
    # about files/tokens keep their old construction shape, while orchestrators
    # no longer have to infer MaxTurns or deadline stops from display text.
    stop_reason: str = "completed"
    quality_state: str = "unknown"
    raw_output: object | None = None


@dataclass
class RepairSession:
    """agent 的工具面：bundle 快照 + 编辑集 + 检查结果。纯 Python，便于单测。"""

    contents: dict[str, str]
    order: list[str]
    changed: set = field(default_factory=set)
    log_lines: list = field(default_factory=list)
    checks_ok: bool = False
    live_step_id: str | None = None
    last_tool_at: float = field(default_factory=time.perf_counter)
    context_files: dict[str, dict] = field(default_factory=dict)
    event_seq: int = 0
    last_patch_delta: AppliedPatchDelta | None = None
    patch_deltas: list[AppliedPatchDelta] = field(default_factory=list)

    @classmethod
    def from_files(cls, files: list[dict], *, live_step_id: str | None = None) -> "RepairSession":
        contents: dict[str, str] = {}
        order: list[str] = []
        for f in files or []:
            path = str(f.get("path"))
            contents[path] = str(f.get("content") or "")
            order.append(path)
        return cls(contents=contents, order=order, live_step_id=live_step_id)

    def to_files(self) -> list[dict]:
        return [{"path": p, "content": self.contents[p]} for p in self.order]

    def _log(self, line: str, *, heartbeat: bool = False, event: dict | None = None) -> None:
        if not heartbeat:
            self.last_tool_at = time.perf_counter()
        self.log_lines.append(line)
        tracing.record_step_log(line, step_id=self.live_step_id, payload=event)

    def _next_event_seq(self) -> int:
        self.event_seq += 1
        return self.event_seq

    def _event(self, event_type: str, **payload) -> dict:
        return {"type": event_type, "seq": self._next_event_seq(), **payload}

    def _turn(self, phase: str, message: str, **payload) -> None:
        self._log(
            f"agent state: {phase} - {message}",
            event=self._event("turn_state", phase=phase, message=message, **payload),
        )

    def _track_file_context(self, path: str, source: str) -> None:
        now_ms = int(time.time() * 1000)
        exists = path in self.contents
        entry = dict(self.context_files.get(path) or {})
        entry.update(
            {
                "path": path,
                "record_state": "active" if exists else "stale",
                "record_source": source,
                "bytes": len(self.contents.get(path, "").encode("utf-8")),
                "lines": _line_count(self.contents.get(path, "")),
                "deleted": not exists,
                "updated_at": now_ms,
            }
        )
        if source == "read_tool":
            entry["cline_read_date"] = now_ms
        elif source == "cline_edited":
            entry["cline_edit_date"] = now_ms
        self.context_files[path] = entry

    def context_snapshot(self) -> list[dict]:
        return [self.context_files[path] for path in sorted(self.context_files)]

    def bundle_metadata(self) -> dict:
        return {
            "files": _bundle_file_rows(self.contents, self.order),
            "script_refs": _script_refs(self.contents.get("index.html", "")),
            "files_in_context": self.context_snapshot(),
        }

    # ---- 工具实现（SDK 包装见 run_repair；保持纯函数便于离线单测）----
    def list_files(self) -> str:
        metadata = self.bundle_metadata()
        rows = metadata["files"]
        self._log(
            f"agent listed files ({len(rows)} file(s))",
            event=self._event(
                "tool",
                tool="list_files",
                cline_tool="listFilesTopLevel",
                status="done",
                files=rows,
                script_refs=metadata["script_refs"],
                files_in_context=metadata["files_in_context"],
            ),
        )
        lines = []
        for row in rows:
            lines.append(
                f"- {row['path']} ({row['kind']}, {row['bytes']}B, {row['lines']} line(s), "
                f"{'referenced' if row['referenced'] else 'unreferenced'})"
            )
        if metadata["script_refs"]:
            lines.append("script order: " + " -> ".join(metadata["script_refs"]))
        return "\n".join(lines) if lines else "bundle is empty"

    def read_file(self, path: str) -> str:
        if path not in self.contents:
            return f"error: no such file {path!r}; bundle has: {', '.join(self.order)}"
        body = self.contents[path]
        size = len(body.encode("utf-8"))
        self._track_file_context(path, "read_tool")
        self._log(
            f"agent read {path} ({size}B)",
            event=self._event(
                "tool",
                tool="read_file",
                cline_tool="readFile",
                path=path,
                bytes=size,
                status="done",
                files_in_context=self.context_snapshot(),
            ),
        )
        return body

    def read_files(self, paths: list[str]) -> str:
        requested: list[str] = []
        for raw in paths or []:
            path = str(raw or "").strip()
            if path and path not in requested:
                requested.append(path)
        if not requested:
            return "error: paths must name at least one bundle file"
        if len(requested) > _MAX_READ_PATHS:
            return f"error: too many files requested ({len(requested)}); max {_MAX_READ_PATHS}"
        sections: list[str] = []
        found: list[dict] = []
        missing: list[str] = []
        for path in requested:
            if path not in self.contents:
                missing.append(path)
                sections.append(
                    f"=== {path} ===\nerror: no such file {path!r}; bundle has: {', '.join(self.order)}"
                )
                continue
            body = self.contents[path]
            size = len(body.encode("utf-8"))
            found.append({"path": path, "bytes": size})
            self._track_file_context(path, "read_tool")
            sections.append(f"=== {path} ({size}B) ===\n{body}")
        total = sum(item["bytes"] for item in found)
        summary = f"agent read {len(found)} file(s) in one call ({total}B)"
        if missing:
            summary += "; missing: " + ", ".join(missing)
        self._log(
            summary,
            event=self._event(
                "tool",
                tool="read_files",
                cline_tool="readFile",
                paths=requested,
                files=found,
                missing=missing,
                bytes=total,
                status="done",
                files_in_context=self.context_snapshot(),
            ),
        )
        return "\n\n".join(sections)

    def search_files(self, query: str, file_pattern: str = "") -> str:
        needle = str(query or "").strip()
        if len(needle) < 2:
            return "error: query must be at least 2 characters"
        pattern = str(file_pattern or "*").strip() or "*"
        matches = []
        lower = needle.lower()
        for path in self.order:
            if not fnmatch(path, pattern):
                continue
            body = self.contents.get(path, "")
            for line_no, line in enumerate(body.splitlines(), start=1):
                if lower in line.lower():
                    matches.append({"path": path, "line": line_no, "text": line.strip()[:220]})
                    if len(matches) >= _MAX_SEARCH_MATCHES:
                        break
            if len(matches) >= _MAX_SEARCH_MATCHES:
                break
        self._log(
            f"agent searched files for {needle!r} ({len(matches)} match(es))",
            event=self._event(
                "tool",
                tool="search_files",
                cline_tool="searchFiles",
                query=needle,
                file_pattern=pattern,
                matches=matches,
                status="done",
            ),
        )
        if not matches:
            return f"no matches for {needle!r}"
        return "\n".join(f"{m['path']}:{m['line']}: {m['text']}" for m in matches)

    @staticmethod
    def _diagnostic_key(item: dict) -> tuple[str, str]:
        return str(item.get("code") or ""), str(item.get("rule") or "")

    def _introduced_source_diagnostics(
        self,
        path: str,
        old_content: str | None,
        new_content: str,
    ) -> list[dict]:
        """Return defects introduced by an edit, allowing incremental repair.

        A repair session may start from source that already fails a gate. Comparing
        counts by stable rule lets an agent remove those defects over several edits
        without permitting a clean author candidate to introduce a new one.
        """

        proposed = validation.validate_source_edit(
            path,
            new_content,
            max_bytes=validation.MAX_FILE_BYTES,
        )
        if old_content is None or not proposed:
            return proposed
        previous = Counter(
            self._diagnostic_key(item)
            for item in validation.validate_source_edit(
                path,
                old_content,
                max_bytes=validation.MAX_FILE_BYTES,
            )
        )
        introduced: list[dict] = []
        for item in proposed:
            key = self._diagnostic_key(item)
            if previous[key] > 0:
                previous[key] -= 1
            else:
                introduced.append(item)
        return introduced

    @staticmethod
    def _patch_error_diagnostic(path: str, message: str) -> dict:
        lower = message.lower()
        if "over the" in lower or "exceeds" in lower:
            code, rule = "file_too_large", "max_file_bytes"
        elif "files (max" in lower or "file" in lower and "max" in lower:
            code, rule = "too_many_files", "max_bundle_files"
        elif any(
            marker in lower
            for marker in (
                "invalid new file path",
                "path escapes",
                "cannot move",
                "cannot delete",
                "does not exist",
                "not found",
            )
        ):
            code, rule = "invalid_path", "patch_path"
        else:
            code, rule = "invalid_patch", "patch_operation"
        return {
            "code": code,
            "path": str(path or ""),
            "line": None,
            "column": None,
            "rule": rule,
            "message": message,
        }

    def _validation_rejection(
        self,
        *,
        tool: str,
        message: str,
        diagnostics: list[dict],
        operation: int | None = None,
    ) -> str:
        shown = diagnostics[:_MAX_SOURCE_DIAGNOSTICS_SHOWN]
        payload = {
            "code": "candidate_source_validation",
            "diagnostics": shown,
            "diagnostics_omitted": max(0, len(diagnostics) - len(shown)),
        }
        path = str((shown[0] if shown else {}).get("path") or "")
        self._log(
            f"agent rejected {tool} edit"
            + (f" for {path}" if path else "")
            + f": {message}",
            event=self._event(
                "validation_rejection",
                tool=tool,
                path=path or None,
                diagnostics=shown,
                diagnostics_omitted=payload["diagnostics_omitted"],
                status="failed",
            ),
        )
        prefix = f"operation {operation}: " if operation is not None else ""
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"error: {prefix}{message}; validation={encoded}"

    def write_file(self, path: str, content: str) -> str:
        name = str(path or "").strip().strip('"').replace("\\", "/")
        if name.startswith("./"):
            name = name[2:]
        project_mode = "src/main.ts" in self.contents or "src/main.js" in self.contents
        allowed = _PROJECT_NEW_PATH_RE if project_mode else _NEW_PATH_RE
        if name not in self.contents and not allowed.match(name):
            message = f"invalid new file path {path!r}; use a safe path supported by this workspace"
            return self._validation_rejection(
                tool="write_file",
                message=message,
                diagnostics=[
                    {
                        "code": "invalid_path",
                        "path": name,
                        "line": None,
                        "column": None,
                        "rule": "workspace_path",
                        "message": message,
                    }
                ],
            )
        body = str(content or "")
        size = len(body.encode("utf-8"))
        if size > validation.MAX_FILE_BYTES:
            message = (
                f"{name} would be {size}B, over the "
                f"{validation.MAX_FILE_BYTES // 1000}KB limit"
            )
            return self._validation_rejection(
                tool="write_file",
                message=message,
                diagnostics=[
                    {
                        "code": "file_too_large",
                        "path": name,
                        "line": None,
                        "column": None,
                        "rule": "max_file_bytes",
                        "message": message,
                    }
                ],
            )
        created = name not in self.contents
        if created and len(self.contents) >= validation.MAX_BUNDLE_FILES:
            message = (
                f"bundle already has {len(self.contents)} files "
                f"(max {validation.MAX_BUNDLE_FILES})"
            )
            return self._validation_rejection(
                tool="write_file",
                message=message,
                diagnostics=[
                    {
                        "code": "too_many_files",
                        "path": name,
                        "line": None,
                        "column": None,
                        "rule": "max_bundle_files",
                        "message": message,
                    }
                ],
            )
        if not created and body == self.contents[name]:
            return f"error: {name} already has exactly this content"
        old_body = self.contents.get(name, "")
        introduced = self._introduced_source_diagnostics(
            name,
            None if created else old_body,
            body,
        )
        if introduced:
            return self._validation_rejection(
                tool="write_file",
                message="candidate source validation failed before commit",
                diagnostics=introduced,
            )
        added_lines, deleted_lines = _line_delta(old_body, body)
        diff, diff_format = _compact_diff(name, old_body, body)
        self.contents[name] = body
        if created:
            self.order.append(name)
        self.changed.add(name)
        self._track_file_context(name, "cline_edited")
        self.checks_ok = False
        action = "created" if created else "modified"
        detail = f"{size}B{', new file' if created else ''}"
        self._log(
            f"agent wrote {name} ({_delta_text(added_lines, deleted_lines)}, {detail})",
            event=self._event(
                "file_change",
                tool="write_file",
                cline_tool="newFileCreated" if created else "editedExistingFile",
                action=action,
                path=name,
                added=added_lines,
                deleted=deleted_lines,
                bytes=size,
                detail=detail,
                diff=diff,
                diff_format=diff_format,
                files_in_context=self.context_snapshot(),
                status="done",
            ),
        )
        wiring = (
            " Import it from an existing module next."
            if created and project_mode and name.endswith((".ts", ".tsx", ".js"))
            else " Wire it into index.html with a <script src> tag next."
            if created and name.endswith(".js")
            else ""
        )
        return (
            f"wrote {name} ({size}B).{wiring} Source guard passed. "
            "Call run_checks after the candidate is complete only if that tool is available."
        )

    def plan_patch_operation(
        self,
        operation_type: PatchOperationKind,
        *,
        path: str,
        diff: str | None = None,
        move_to: str | None = None,
    ) -> VerifiedPatch:
        """Validate one SDK operation without serializing it back into patch text."""

        return verify_patch_operation(
            operation_type,
            path,
            diff,
            move_to,
            self.contents,
            max_file_bytes=validation.MAX_FILE_BYTES,
            max_bundle_files=validation.MAX_BUNDLE_FILES,
        )

    def _commit_patch_plan(self, plan: VerifiedPatch) -> AppliedPatchDelta:
        """Commit a verified plan atomically to the in-memory workspace."""

        original_contents = dict(self.contents)
        original_order = list(self.order)
        original_changed = set(self.changed)
        try:
            for change in plan.changes:
                if change.kind == "update":
                    self.contents[change.path] = change.new_content or ""
                    self.changed.add(change.path)
                elif change.kind == "move":
                    destination = change.move_to or ""
                    index = self.order.index(change.path)
                    del self.contents[change.path]
                    self.contents[destination] = change.new_content or ""
                    self.order[index] = destination
                    self.changed.update((change.path, destination))
                elif change.kind == "delete":
                    del self.contents[change.path]
                    self.order.remove(change.path)
                    self.changed.add(change.path)
                elif change.kind == "add":
                    self.contents[change.path] = change.new_content or ""
                    self.order.append(change.path)
                    self.changed.add(change.path)
        except Exception as exc:  # noqa: BLE001 - rollback keeps the bundle atomic
            self.contents = original_contents
            self.order = original_order
            self.changed = original_changed
            raise _PatchError(f"patch commit failed and was rolled back: {exc}") from exc
        return AppliedPatchDelta(changes=plan.changes, exact=True)

    def _record_patch_change(self, change: PatchFileChange) -> str:
        diff_path = change.move_to or change.path
        diff, diff_format = _compact_diff(
            diff_path,
            change.old_content or "",
            change.new_content or "",
        )
        delta = _delta_text(change.added_lines, change.deleted_lines)
        if change.kind == "update":
            self._track_file_context(change.path, "cline_edited")
            detail = f"{change.chunk_count} chunk(s), {change.size}B"
            message = f"agent patched {change.path} ({delta}, {detail})"
            summary = f"{change.path} ({delta}, {detail})"
            action = "modified"
            cline_tool = "editedExistingFile"
        elif change.kind == "move":
            self._track_file_context(change.path, "cline_edited")
            self._track_file_context(change.move_to or "", "cline_edited")
            detail = f"{change.chunk_count} chunk(s), {change.size}B"
            message = f"agent moved {change.path} -> {change.move_to} ({delta}, {detail})"
            summary = f"moved {change.path} -> {change.move_to} ({delta}, {detail})"
            action = "moved"
            cline_tool = "editedExistingFile"
        elif change.kind == "delete":
            self._track_file_context(change.path, "cline_edited")
            detail = delta
            message = f"agent deleted {change.path} ({delta})"
            summary = f"deleted {change.path}"
            action = "deleted"
            cline_tool = "fileDeleted"
        else:
            self._track_file_context(change.path, "cline_edited")
            detail = f"{change.size}B"
            message = f"agent added {change.path} ({delta}, {detail})"
            summary = f"added {change.path} ({delta}, {detail})"
            action = "created"
            cline_tool = "newFileCreated"
        self._log(
            message,
            event=self._event(
                "file_change",
                tool="apply_patch",
                cline_tool=cline_tool,
                action=action,
                path=change.path,
                move_to=change.move_to,
                added=change.added_lines,
                deleted=change.deleted_lines,
                bytes=change.size,
                chunks=change.chunk_count,
                detail=detail,
                diff=diff,
                diff_format=diff_format,
                files_in_context=self.context_snapshot(),
                status="done",
            ),
        )
        return summary

    def _apply_verified_patch(
        self,
        plan: VerifiedPatch,
        *,
        tool: str = "apply_patch",
    ) -> str:
        diagnostics: list[dict] = []
        for change_index, change in enumerate(plan.changes, start=1):
            if change.new_content is None:
                continue
            change_diagnostics = self._introduced_source_diagnostics(
                change.move_to or change.path,
                change.old_content,
                change.new_content,
            )
            if tool == "apply_patch_set":
                change_diagnostics = [
                    {**item, "operation": change_index}
                    for item in change_diagnostics
                ]
            diagnostics.extend(change_diagnostics)
        if diagnostics:
            return self._validation_rejection(
                tool=tool,
                message="candidate source validation failed before commit",
                diagnostics=diagnostics,
            )
        delta = self._commit_patch_plan(plan)
        self.last_patch_delta = delta
        self.patch_deltas.append(delta)
        summaries = [self._record_patch_change(change) for change in plan.changes]
        if plan.fuzz:
            self._log(f"agent patch matched with fuzz {plan.fuzz}")
        self.checks_ok = False
        return (
            f"patched {', '.join(summaries)}. Source guard passed. "
            "Call run_checks after the candidate is complete only if that tool is available."
        )

    def apply_patch_operation(
        self,
        operation_type: PatchOperationKind,
        *,
        path: str,
        diff: str | None = None,
        move_to: str | None = None,
    ) -> str:
        """Apply one structured SDK operation through the shared verified commit layer."""

        self.last_patch_delta = None
        try:
            plan = self.plan_patch_operation(
                operation_type,
                path=path,
                diff=diff,
                move_to=move_to,
            )
            return self._apply_verified_patch(plan)
        except _PatchError as exc:
            message = str(exc)
            diagnostic_path = move_to if move_to and move_to in message else path
            return self._validation_rejection(
                tool="apply_patch",
                message=message,
                diagnostics=[
                    self._patch_error_diagnostic(diagnostic_path, message)
                ],
            )

    def apply_patch_operations(self, operations: list[dict]) -> str:
        """Validate and commit a coordinated multi-file patch atomically."""

        self.last_patch_delta = None
        if not operations:
            return "error: operations must contain at least one patch"
        if len(operations) > _MAX_PATCH_OPERATIONS:
            return f"error: too many patch operations ({len(operations)}); max {_MAX_PATCH_OPERATIONS}"

        staged_contents = dict(self.contents)
        changes: list[PatchFileChange] = []
        fuzz = 0
        operation_index = 0
        try:
            for operation_index, raw in enumerate(operations, start=1):
                operation = dict(raw or {})
                operation_type = str(operation.get("operation_type") or "").strip()
                path = str(operation.get("path") or "").strip()
                diff = operation.get("diff")
                move_to = str(operation.get("move_to") or "").strip() or None
                plan = verify_patch_operation(
                    operation_type,
                    path,
                    None if diff is None else str(diff),
                    move_to,
                    staged_contents,
                    max_file_bytes=validation.MAX_FILE_BYTES,
                    max_bundle_files=validation.MAX_BUNDLE_FILES,
                )
                for change in plan.changes:
                    if change.kind == "update":
                        staged_contents[change.path] = change.new_content or ""
                    elif change.kind == "move":
                        del staged_contents[change.path]
                        staged_contents[change.move_to or ""] = change.new_content or ""
                    elif change.kind == "delete":
                        del staged_contents[change.path]
                    elif change.kind == "add":
                        staged_contents[change.path] = change.new_content or ""
                changes.extend(plan.changes)
                fuzz += plan.fuzz
        except _PatchError as exc:
            message = str(exc)
            failed_operation = operation if "operation" in locals() else {}
            failed_path = str(failed_operation.get("path") or "")
            failed_move = str(failed_operation.get("move_to") or "")
            diagnostic_path = (
                failed_move if failed_move and failed_move in message else failed_path
            )
            return self._validation_rejection(
                tool="apply_patch_set",
                message=message,
                diagnostics=[
                    self._patch_error_diagnostic(
                        diagnostic_path,
                        message,
                    )
                ],
                operation=operation_index,
            )

        try:
            return self._apply_verified_patch(
                VerifiedPatch(changes=tuple(changes), fuzz=fuzz),
                tool="apply_patch_set",
            )
        except _PatchError as exc:
            message = str(exc)
            return self._validation_rejection(
                tool="apply_patch_set",
                message=message,
                diagnostics=[
                    self._patch_error_diagnostic("", message)
                ],
            )

    def run_checks(self) -> str:
        from app.services.vite_projects import is_vite_project, validate_vite_project

        if is_vite_project(self.to_files()):
            from app.services import sandbox_client

            errors = validate_vite_project(self.to_files())
            if errors:
                self.checks_ok = False
                detail = "; ".join(errors[:_MAX_ERRORS_SHOWN])
                self._log(
                    f"agent project checks: source validation failed ({len(errors)} error(s))",
                    event=self._event(
                        "check",
                        tool="run_checks",
                        static_ok=False,
                        static_errors=len(errors),
                        checks_ok=False,
                        bundle=self.bundle_metadata(),
                        status="done",
                    ),
                )
                return f"source validation: {detail}\n=> CHECKS FAILED"
            try:
                result = sandbox_client.build_vite_project(self.to_files())
            except sandbox_client.SandboxUnavailableError as exc:
                self.checks_ok = False
                return f"typecheck/build unavailable: {exc}\n=> CHECKS FAILED"
            self.checks_ok = bool(result.ok)
            details = result.errors or result.warnings or [result.detail or "build completed"]
            check_summary = "typecheck/build OK" if result.ok else (
                "typecheck/build failed: " + "; ".join(str(item) for item in details[:2])
            )
            self._log(
                "agent project checks: " + check_summary,
                event=self._event(
                    "check",
                    tool="run_checks",
                    static_ok=True,
                    build_ok=bool(result.ok),
                    checks_ok=self.checks_ok,
                    errors=list(result.errors or [])[:_MAX_ERRORS_SHOWN],
                    warnings=list(result.warnings or [])[:_MAX_ERRORS_SHOWN],
                    duration_ms=result.duration_ms,
                    timed_out=result.timed_out,
                    bundle=self.bundle_metadata(),
                    status="done",
                ),
            )
            verdict = "ALL CHECKS PASSED" if self.checks_ok else "CHECKS FAILED"
            build_line = "OK" if result.ok else "; ".join(details[:_MAX_ERRORS_SHOWN])
            return f"source validation: OK\ntypecheck/build: {build_line}\n=> {verdict}"

        result = validation.validate_files(self.to_files())
        errors = [str(e)[:160] for e in (result.get("errors") or [])][:_MAX_ERRORS_SHOWN]
        ok_smoke, smoke_detail = smoke.run_smoke_files(self.to_files())
        self.checks_ok = bool(result.get("valid")) and ok_smoke
        self._log(
            "agent checks: static "
            + ("OK" if result.get("valid") else f"{len(result.get('errors') or [])} error(s)")
            + " · smoke "
            + ("ok" if ok_smoke else "crashed"),
            event=self._event(
                "check",
                tool="run_checks",
                static_ok=bool(result.get("valid")),
                static_errors=len(result.get("errors") or []),
                smoke_ok=ok_smoke,
                checks_ok=self.checks_ok,
                bundle=self.bundle_metadata(),
                status="done",
            ),
        )
        static_line = "OK" if result.get("valid") else "; ".join(errors)
        smoke_line = smoke_detail if ok_smoke else f"crashed: {smoke_detail}"
        verdict = "ALL CHECKS PASSED" if self.checks_ok else "CHECKS FAILED"
        return f"static validation: {static_line}\nsmoke test: {smoke_line}\n=> {verdict}"

    def list_skills(self) -> str:
        names = available_skills()
        return ", ".join(names) if names else "no skills available"

    def read_skill(self, name: str) -> str:
        if not _skill_name_ok(name):
            return f"unknown skill {name!r}; available: {self.list_skills()}"
        path = os.path.join(_SKILLS_DIR, name, "SKILL.md")
        if not os.path.isfile(path):
            return f"unknown skill {name!r}; available: {self.list_skills()}"
        self._log(
            f"agent read skill {name}",
            event=self._event("tool", tool="read_skill", cline_tool="useSkill", name=name, status="done"),
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()


def _skill_name_ok(name: str) -> bool:
    return bool(name) and all(ch.isalnum() or ch in "-_" for ch in name)


def available_skills() -> list[str]:
    try:
        return sorted(
            entry
            for entry in os.listdir(_SKILLS_DIR)
            if os.path.isfile(os.path.join(_SKILLS_DIR, entry, "SKILL.md"))
        )
    except OSError:
        return []
