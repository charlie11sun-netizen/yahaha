"""In-memory repair workspace and pure tool implementations for code agents."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher, unified_diff
from fnmatch import fnmatch

from app.agents import smoke, tracing, validation
from app.agents.patch_parser import _PatchError, _V4AParser, _apply_chunks, _prepare_patch_lines

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
_PROTECTED_FILES = ("index.html", "style.css", "game.js")  # 入口三件套：可改不可删
# 新建文件：平铺文件名（天然排除 / 与 ..），只允许 .js/.css 模块
_NEW_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(?:js|css)$")
_SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"']", re.I)
_MAX_ERRORS_SHOWN = 8
_HEARTBEAT_INTERVAL_SECONDS = 12.0
_MAX_SEARCH_MATCHES = 24
_MAX_DIFF_CHARS = 12000


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
    if path.endswith(".js"):
        return "script"
    return "asset"


def _bundle_file_rows(contents: dict[str, str], order: list[str]) -> list[dict]:
    refs = set(_script_refs(contents.get("index.html", "")))
    rows = []
    for path in order:
        body = contents.get(path, "")
        rows.append(
            {
                "path": path,
                "bytes": len(body.encode("utf-8")),
                "lines": _line_count(body),
                "kind": _file_kind(path),
                "referenced": path in _PROTECTED_FILES or path in refs,
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

    def write_file(self, path: str, content: str) -> str:
        name = str(path or "").strip().strip('"').replace("\\", "/")
        if name.startswith("./"):
            name = name[2:]
        if name not in self.contents and not _NEW_PATH_RE.match(name):
            return f"error: invalid new file path {path!r}; use a flat filename ending in .js or .css"
        body = str(content or "")
        size = len(body.encode("utf-8"))
        if size > validation.MAX_FILE_BYTES:
            return f"error: {name} would be {size}B, over the {validation.MAX_FILE_BYTES // 1000}KB limit"
        created = name not in self.contents
        if created and len(self.contents) >= validation.MAX_BUNDLE_FILES:
            return f"error: bundle already has {len(self.contents)} files (max {validation.MAX_BUNDLE_FILES})"
        if not created and body == self.contents[name]:
            return f"error: {name} already has exactly this content"
        old_body = self.contents.get(name, "")
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
        wiring = " Wire it into index.html with a <script src> tag next." if created and name.endswith(".js") else ""
        return f"wrote {name} ({size}B).{wiring} Then run_checks."

    def apply_patch(self, patch: str) -> str:
        try:
            patch_lines = _prepare_patch_lines(patch)
            normalized = {p: c.replace("\r\n", "\n") for p, c in self.contents.items()}
            parser = _V4AParser(patch_lines=patch_lines, files=normalized, index=1)
            parser.parse()
            staged: dict[str, tuple[str, int, int]] = {}  # path -> (新内容, chunk 数, 字节数)
            for path, chunks in parser.updates.items():
                new_text = _apply_chunks(normalized[path], chunks, path)
                if "\r\n" in self.contents[path]:
                    new_text = new_text.replace("\n", "\r\n")
                if new_text == self.contents[path]:
                    continue
                size = len(new_text.encode("utf-8"))
                if size > validation.MAX_FILE_BYTES:
                    raise _PatchError(
                        f"{path} exceeds the {validation.MAX_FILE_BYTES // 1000}KB limit after this patch "
                        f"({size}B); apply a smaller patch"
                    )
                added_lines = sum(len(chunk.ins_lines) for chunk in chunks)
                deleted_lines = sum(len(chunk.del_lines) for chunk in chunks)
                staged[path] = (new_text, len(chunks), size, added_lines, deleted_lines)
            added: dict[str, tuple[str, int]] = {}  # path -> (内容, 字节数)
            for path, content in parser.adds.items():
                size = len(content.encode("utf-8"))
                if size > validation.MAX_FILE_BYTES:
                    raise _PatchError(
                        f"new file {path} would be {size}B, over the {validation.MAX_FILE_BYTES // 1000}KB limit"
                    )
                added[path] = (content, size)
            if added:
                projected = len(self.contents) + len(added) - len(parser.deletes)
                if projected > validation.MAX_BUNDLE_FILES:
                    raise _PatchError(
                        f"bundle would grow to {projected} files (max {validation.MAX_BUNDLE_FILES}); "
                        "consolidate systems into existing modules"
                    )
        except _PatchError as exc:
            return f"error: {exc}"
        if not staged and not added and not parser.deletes:
            return "error: patch made no changes"
        summaries = []
        for path, (content, chunk_count, size, added_lines, deleted_lines) in staged.items():
            old_body = self.contents[path]
            diff, diff_format = _compact_diff(path, old_body, content)
            self.contents[path] = content
            self.changed.add(path)
            self._track_file_context(path, "cline_edited")
            delta = _delta_text(added_lines, deleted_lines)
            detail = f"{chunk_count} chunk(s), {size}B"
            self._log(
                f"agent patched {path} ({delta}, {detail})",
                event=self._event(
                    "file_change",
                    tool="apply_patch",
                    cline_tool="editedExistingFile",
                    action="modified",
                    path=path,
                    added=added_lines,
                    deleted=deleted_lines,
                    bytes=size,
                    chunks=chunk_count,
                    detail=detail,
                    diff=diff,
                    diff_format=diff_format,
                    files_in_context=self.context_snapshot(),
                    status="done",
                ),
            )
            summaries.append(f"{path} ({delta}, {chunk_count} chunk(s), {size}B)")
        for path in parser.deletes:
            old_body = self.contents[path]
            diff, diff_format = _compact_diff(path, old_body, "")
            deleted_lines = _line_count(self.contents[path])
            del self.contents[path]
            self.order.remove(path)
            self.changed.add(path)
            self._track_file_context(path, "cline_edited")
            self._log(
                f"agent deleted {path} (+0 -{deleted_lines})",
                event=self._event(
                    "file_change",
                    tool="apply_patch",
                    cline_tool="fileDeleted",
                    action="deleted",
                    path=path,
                    added=0,
                    deleted=deleted_lines,
                    diff=diff,
                    diff_format=diff_format,
                    files_in_context=self.context_snapshot(),
                    status="done",
                ),
            )
            summaries.append(f"deleted {path}")
        for path, (content, size) in added.items():
            diff, diff_format = _compact_diff(path, "", content)
            self.contents[path] = content
            self.order.append(path)
            self.changed.add(path)
            self._track_file_context(path, "cline_edited")
            added_lines = _line_count(content)
            detail = f"{size}B"
            self._log(
                f"agent added {path} (+{added_lines} -0, {detail})",
                event=self._event(
                    "file_change",
                    tool="apply_patch",
                    cline_tool="newFileCreated",
                    action="created",
                    path=path,
                    added=added_lines,
                    deleted=0,
                    bytes=size,
                    detail=detail,
                    diff=diff,
                    diff_format=diff_format,
                    files_in_context=self.context_snapshot(),
                    status="done",
                ),
            )
            summaries.append(f"added {path} (+{added_lines} -0, {size}B)")
        if parser.fuzz:
            self._log(f"agent patch matched with fuzz {parser.fuzz}")
        self.checks_ok = False
        return f"patched {', '.join(summaries)}. Now call run_checks to verify."

    def run_checks(self) -> str:
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
