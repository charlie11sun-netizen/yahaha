"""V4A operation-diff parsing for the native OpenAI Agents SDK patch tool."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_PROTECTED_FILES = ("index.html", "style.css", "game.js", "package.json", "src/main.ts")
_NEW_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(?:js|css)$")
_PROJECT_NEW_PATH_RE = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9][A-Za-z0-9._/-]{0,179}"
    r"\.(?:js|mjs|ts|tsx|css|json|md)$"
)
_EOF_MARK = "*** End of File"
_FULL_PATCH_PREFIXES = (
    "*** Begin Patch",
    "*** End Patch",
    "*** Update File: ",
    "*** Add File: ",
    "*** Delete File: ",
    "*** Move to: ",
)


class _PatchError(ValueError):
    """Validation failure returned to the model as an actionable retry message."""


@dataclass
class _Chunk:
    orig_index: int = -1
    del_lines: list[str] = field(default_factory=list)
    ins_lines: list[str] = field(default_factory=list)


def _prepare_operation_diff_lines(diff: str | None) -> list[str]:
    """Normalize one SDK operation diff and reject the removed full-patch protocol."""

    text = str(diff or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not text:
        return []
    lines = text.split("\n")
    if any(line.startswith(_FULL_PATCH_PREFIXES) for line in lines):
        raise _PatchError(
            "SDK operation diff must contain only V4A content/context lines, not a full patch envelope"
        )
    return lines


def _resolve_bundle_path(raw: str, files: dict[str, str]) -> str:
    path = str(raw or "").strip().strip('"').replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if path not in files and os.path.basename(path) in files:
        path = os.path.basename(path)
    if path not in files:
        raise _PatchError(f"no such file {raw!r}; bundle has: {', '.join(files)}")
    return path


def _validate_new_bundle_path(raw: str, files: dict[str, str]) -> str:
    path = str(raw or "").strip().strip('"').replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    if path in files:
        raise _PatchError(f"{path!r} already exists; update that file instead")
    project_mode = "src/main.ts" in files or "src/main.js" in files
    allowed = _PROJECT_NEW_PATH_RE if project_mode else _NEW_PATH_RE
    if not allowed.match(path):
        raise _PatchError(
            f"invalid new file path {str(raw or '').strip()!r}; use a safe relative project path ending in "
            ".js, .ts, .tsx, .css, .json, or .md"
        )
    return path


def _peek_section(lines: list[str], index: int) -> tuple[list[str], list[_Chunk], int, bool]:
    """Read one update section into matching context and structured chunks."""

    old: list[str] = []
    del_lines: list[str] = []
    ins_lines: list[str] = []
    chunks: list[_Chunk] = []
    mode = "keep"
    start_index = index
    while index < len(lines):
        raw = lines[index]
        if raw.startswith("@@") or raw == _EOF_MARK or raw == "***":
            break
        if raw.startswith("***"):
            raise _PatchError(f"invalid patch line: {raw[:60]!r}")
        index += 1
        last_mode = mode
        line = raw or " "
        if line[0] == "+":
            mode = "add"
        elif line[0] == "-":
            mode = "delete"
        elif line[0] == " ":
            mode = "keep"
        else:
            raise _PatchError(
                f"invalid patch line {line[:60]!r}; every line must start with ' ', '+' or '-'"
            )
        content = line[1:]
        if mode == "keep" and last_mode != mode:
            if ins_lines or del_lines:
                chunks.append(
                    _Chunk(
                        orig_index=len(old) - len(del_lines),
                        del_lines=del_lines,
                        ins_lines=ins_lines,
                    )
                )
            del_lines, ins_lines = [], []
        if mode == "delete":
            del_lines.append(content)
            old.append(content)
        elif mode == "add":
            ins_lines.append(content)
        else:
            old.append(content)
    if ins_lines or del_lines:
        chunks.append(
            _Chunk(
                orig_index=len(old) - len(del_lines),
                del_lines=del_lines,
                ins_lines=ins_lines,
            )
        )
    if index < len(lines) and lines[index] == _EOF_MARK:
        return old, chunks, index + 1, True
    if index == start_index:
        raise _PatchError("empty '@@' section in patch")
    return old, chunks, index, False


def _find_context_core(lines: list[str], context: list[str], start: int) -> tuple[int, int]:
    if not context:
        return start, 0
    for index in range(start, len(lines)):
        if lines[index : index + len(context)] == context:
            return index, 0
    for index in range(start, len(lines)):
        if [line.rstrip() for line in lines[index : index + len(context)]] == [
            line.rstrip() for line in context
        ]:
            return index, 1
    for index in range(start, len(lines)):
        if [line.strip() for line in lines[index : index + len(context)]] == [
            line.strip() for line in context
        ]:
            return index, 100
    return -1, 0


def _find_context(lines: list[str], context: list[str], start: int, eof: bool) -> tuple[int, int]:
    if eof:
        new_index, fuzz = _find_context_core(lines, context, max(0, len(lines) - len(context)))
        if new_index != -1:
            return new_index, fuzz
        new_index, fuzz = _find_context_core(lines, context, start)
        return new_index, fuzz + 10_000
    return _find_context_core(lines, context, start)


def _parse_create_diff(diff: str | None, path: str) -> str:
    """Parse a create_file operation whose content lines must start with '+'."""

    lines = _prepare_operation_diff_lines(diff)
    if not lines:
        raise _PatchError(f"create_file for {path!r} has no '+' content lines")
    body: list[str] = []
    for line in lines:
        if not line.startswith("+"):
            raise _PatchError(
                f"in create_file for {path!r} every content line must start with '+'; got {line[:60]!r}"
            )
        body.append(line[1:])
    return "\n".join(body)


def _seek_anchor(file_lines: list[str], index: int, anchor: str) -> tuple[int, int]:
    if anchor not in file_lines[:index]:
        for candidate in range(index, len(file_lines)):
            if file_lines[candidate] == anchor:
                return candidate + 1, 0
    if anchor.strip() not in [line.strip() for line in file_lines[:index]]:
        for candidate in range(index, len(file_lines)):
            if file_lines[candidate].strip() == anchor.strip():
                return candidate + 1, 1
    return index, 0


def _parse_update_diff(diff: str | None, text: str, path: str) -> tuple[list[_Chunk], int]:
    """Parse one update_file operation directly into chunks and fuzz metadata."""

    patch_lines = _prepare_operation_diff_lines(diff)
    file_lines = text.split("\n")
    chunks: list[_Chunk] = []
    patch_index = 0
    file_index = 0
    fuzz = 0
    while patch_index < len(patch_lines):
        current = patch_lines[patch_index]
        if current == _EOF_MARK:
            break
        anchor = ""
        bare_anchor = False
        if current.startswith("@@ "):
            anchor = current[3:]
            patch_index += 1
        elif current.strip() == "@@":
            bare_anchor = True
            patch_index += 1
        if not (anchor or bare_anchor or file_index == 0):
            raise _PatchError(
                f"invalid line in update diff: {current[:60]!r}; each later block needs an '@@' locator"
            )
        if anchor.strip():
            file_index, anchor_fuzz = _seek_anchor(file_lines, file_index, anchor)
            fuzz += anchor_fuzz
        context, section_chunks, end_index, eof = _peek_section(patch_lines, patch_index)
        new_index, context_fuzz = _find_context(file_lines, context, file_index, eof)
        if new_index == -1:
            shown = "\n".join(context[:8])
            raise _PatchError(
                f"context not found in {path}{' at end of file' if eof else ''}:\n{shown}\n"
                "-> read_file again, copy the context lines exactly, and keep sections in file order"
            )
        fuzz += context_fuzz
        for chunk in section_chunks:
            chunk.orig_index += new_index
            chunks.append(chunk)
        file_index = new_index + len(context)
        patch_index = end_index
    return chunks, fuzz


def _apply_chunks(text: str, chunks: list[_Chunk], path: str) -> str:
    orig_lines = text.split("\n")
    dest: list[str] = []
    at = 0
    for chunk in chunks:
        if chunk.orig_index > len(orig_lines):
            raise _PatchError(f"{path}: patch refers past end of file")
        if at > chunk.orig_index:
            raise _PatchError(f"{path}: overlapping patch sections; merge them and resend")
        dest.extend(orig_lines[at : chunk.orig_index])
        at = chunk.orig_index
        dest.extend(chunk.ins_lines)
        at += len(chunk.del_lines)
    dest.extend(orig_lines[at:])
    return "\n".join(dest)
