"""V4A patch parsing and application for generated game bundles."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_PROTECTED_FILES = ("index.html", "style.css", "game.js")
_NEW_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(?:js|css)$")

# ---- V4A 补丁解析/应用。改编自 OpenAI GPT-4.1 prompting guide 的 apply_patch 参考
#      实现（openai-cookbook，MIT）——模型被专门训练过这个格式，解析算法保持与官方
#      一致（@@ 锚点、上下文匹配的 fuzz 级联、EOF 段）。适配点：支持 Update/Add/Delete
#      （Move 不支持；新路径限平铺 .js/.css 且有配额）、目标是内存文件字典而非磁盘、
#      全部文件应用成功才原子提交、保留原文件的 CRLF。----

_BEGIN_PATCH = "*** Begin Patch"
_END_PATCH = "*** End Patch"
_UPDATE_PREFIX = "*** Update File: "
_ADD_PREFIX = "*** Add File: "
_DELETE_PREFIX = "*** Delete File: "
_EOF_MARK = "*** End of File"
_SECTION_STOPS = (_END_PATCH, "*** Update File:", "*** Delete File:", "*** Add File:", _EOF_MARK)

_FORMAT_HINT = (
    "*** Begin Patch\n"
    "*** Update File: game.js\n"
    "@@ function update()\n"
    " context line\n"
    "-old line\n"
    "+new line\n"
    "*** End Patch"
)


class _PatchError(ValueError):
    """解析/应用失败。消息原样回给模型，所以写成可执行的重试指引。"""


@dataclass
class _Chunk:
    orig_index: int = -1
    del_lines: list[str] = field(default_factory=list)
    ins_lines: list[str] = field(default_factory=list)


def _strip_patch_fence(patch: str) -> str:
    text = str(patch or "").strip()
    if text.startswith("```"):
        fenced = re.match(r"```[^\n]*\n(.*?)\n?```\s*$", text, re.S)
        if fenced:
            return fenced.group(1)
    return text


def _prepare_patch_lines(patch: str) -> list[str]:
    text = _strip_patch_fence(patch).replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not text.strip():
        raise _PatchError("empty patch; expected V4A format:\n" + _FORMAT_HINT)
    if _UPDATE_PREFIX not in text and re.search(r"^@@ -\d+(?:,\d+)? \+\d+", text, re.M):
        raise _PatchError("this is a unified diff; use the V4A patch format instead:\n" + _FORMAT_HINT)
    lines = text.split("\n")
    if not lines[0].startswith(_BEGIN_PATCH):
        if any(line.startswith(_UPDATE_PREFIX) for line in lines):
            lines.insert(0, _BEGIN_PATCH)  # 信封缺失但结构完整：补上，省一个重试回合
        else:
            raise _PatchError("not a V4A patch; start with '*** Begin Patch', e.g.:\n" + _FORMAT_HINT)
    return lines


def _resolve_bundle_path(raw: str, files: dict[str, str]) -> str:
    path = raw.strip().strip('"').replace("\\", "/")
    if path.startswith("./"):
        path = path[2:]
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if path not in files and os.path.basename(path) in files:
        path = os.path.basename(path)  # bundle 是平铺的，容忍模型多写目录前缀
    if path not in files:
        raise _PatchError(f"no such file {raw!r}; bundle has: {', '.join(files)}")
    return path


def _peek_section(lines: list[str], index: int) -> tuple[list[str], list[_Chunk], int, bool]:
    """读一个 @@ 小节的补丁行，产出（旧文上下文, chunks, 新游标, 是否 EOF 段）。"""
    old: list[str] = []
    del_lines: list[str] = []
    ins_lines: list[str] = []
    chunks: list[_Chunk] = []
    mode = "keep"
    start_index = index
    while index < len(lines):
        s = lines[index]
        if s.startswith(("@@",) + _SECTION_STOPS) or s == "***":
            break
        if s.startswith("***"):
            raise _PatchError(f"invalid patch line: {s[:60]!r}")
        index += 1
        last_mode = mode
        if s == "":
            s = " "
        if s[0] == "+":
            mode = "add"
        elif s[0] == "-":
            mode = "delete"
        elif s[0] == " ":
            mode = "keep"
        else:
            raise _PatchError(f"invalid patch line {s[:60]!r}; every line must start with ' ', '+' or '-'")
        s = s[1:]
        if mode == "keep" and last_mode != mode:
            if ins_lines or del_lines:
                chunks.append(_Chunk(orig_index=len(old) - len(del_lines), del_lines=del_lines, ins_lines=ins_lines))
            del_lines, ins_lines = [], []
        if mode == "delete":
            del_lines.append(s)
            old.append(s)
        elif mode == "add":
            ins_lines.append(s)
        else:
            old.append(s)
    if ins_lines or del_lines:
        chunks.append(_Chunk(orig_index=len(old) - len(del_lines), del_lines=del_lines, ins_lines=ins_lines))
    if index < len(lines) and lines[index] == _EOF_MARK:
        index += 1
        return old, chunks, index, True
    if index == start_index:
        raise _PatchError("empty '@@' section in patch")
    return old, chunks, index, False


def _find_context_core(lines: list[str], context: list[str], start: int) -> tuple[int, int]:
    if not context:
        return start, 0
    for i in range(start, len(lines)):
        if lines[i : i + len(context)] == context:
            return i, 0
    for i in range(start, len(lines)):
        if [s.rstrip() for s in lines[i : i + len(context)]] == [s.rstrip() for s in context]:
            return i, 1
    for i in range(start, len(lines)):
        if [s.strip() for s in lines[i : i + len(context)]] == [s.strip() for s in context]:
            return i, 100
    return -1, 0


def _find_context(lines: list[str], context: list[str], start: int, eof: bool) -> tuple[int, int]:
    if eof:
        new_index, fuzz = _find_context_core(lines, context, max(0, len(lines) - len(context)))
        if new_index != -1:
            return new_index, fuzz
        new_index, fuzz = _find_context_core(lines, context, start)
        return new_index, fuzz + 10_000
    return _find_context_core(lines, context, start)


@dataclass
class _V4AParser:
    patch_lines: list[str]
    files: dict[str, str]
    index: int = 0
    fuzz: int = 0
    updates: dict[str, list[_Chunk]] = field(default_factory=dict)
    adds: dict[str, str] = field(default_factory=dict)
    deletes: list[str] = field(default_factory=list)

    def _cur(self) -> str:
        if self.index >= len(self.patch_lines):
            raise _PatchError("patch ended without '*** End Patch' — if it was cut off, resend the complete patch")
        return self.patch_lines[self.index]

    def parse(self) -> None:
        while not self._cur().startswith(_END_PATCH):
            line = self._cur()
            if line.startswith(_ADD_PREFIX):
                self.index += 1
                path = self._new_path(line[len(_ADD_PREFIX):])
                self.adds[path] = self._parse_add_section(path)
                continue
            if line.startswith(_DELETE_PREFIX):
                self.index += 1
                path = _resolve_bundle_path(line[len(_DELETE_PREFIX):], self.files)
                if path in _PROTECTED_FILES:
                    raise _PatchError(f"cannot delete {path}; entry files {', '.join(_PROTECTED_FILES)} must stay")
                if path in self.deletes:
                    raise _PatchError(f"duplicate '*** Delete File: {path}'")
                if path in self.updates:
                    raise _PatchError(f"{path} is both updated and deleted in one patch; pick one")
                self.deletes.append(path)
                continue
            if line.startswith("*** Move to:"):
                raise _PatchError("'*** Move to:' is not supported; use '*** Add File:' plus '*** Delete File:'")
            if not line.startswith(_UPDATE_PREFIX):
                raise _PatchError(f"unexpected patch line {line[:60]!r}; expected '*** Update File: <path>'")
            self.index += 1
            path = _resolve_bundle_path(line[len(_UPDATE_PREFIX):], self.files)
            if path in self.updates:
                raise _PatchError(f"duplicate '*** Update File: {path}'; merge the sections into one block")
            if path in self.deletes:
                raise _PatchError(f"{path} is both updated and deleted in one patch; pick one")
            self.updates[path] = self._parse_update_section(path)
        self.index += 1

    def _new_path(self, raw: str) -> str:
        path = raw.strip().strip('"').replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        if path in self.files:
            raise _PatchError(f"{path!r} already exists; use '*** Update File: {path}'")
        if path in self.adds:
            raise _PatchError(f"duplicate '*** Add File: {path}'")
        if not _NEW_PATH_RE.match(path):
            raise _PatchError(
                f"invalid new file path {raw.strip()!r}; use a flat filename ([A-Za-z0-9._-]) ending in .js or .css"
            )
        return path

    def _parse_add_section(self, path: str) -> str:
        body: list[str] = []
        while self.index < len(self.patch_lines) and not self._cur().startswith(_SECTION_STOPS):
            s = self._cur()
            if not s.startswith("+"):
                raise _PatchError(
                    f"in '*** Add File: {path}' every content line must start with '+'; got {s[:60]!r}"
                )
            body.append(s[1:])
            self.index += 1
        if not body:
            raise _PatchError(f"'*** Add File: {path}' has no '+' content lines")
        return "\n".join(body)

    def _parse_update_section(self, path: str) -> list[_Chunk]:
        file_lines = self.files[path].split("\n")
        chunks: list[_Chunk] = []
        index = 0
        while self.index < len(self.patch_lines) and not self._cur().startswith(_SECTION_STOPS):
            cur = self._cur()
            anchor = ""
            bare_at = False
            if cur.startswith("@@ "):
                anchor = cur[3:]
                self.index += 1
            elif cur.strip() == "@@":
                bare_at = True
                self.index += 1
            if not (anchor or bare_at or index == 0):
                raise _PatchError(
                    f"invalid line in update section: {cur[:60]!r}; each block after the first needs an '@@' locator"
                )
            if anchor.strip():
                index = self._seek_anchor(file_lines, index, anchor)
            context, section_chunks, end_index, eof = _peek_section(self.patch_lines, self.index)
            new_index, fuzz = _find_context(file_lines, context, index, eof)
            if new_index == -1:
                shown = "\n".join(context[:8])
                raise _PatchError(
                    f"context not found in {path}{' at end of file' if eof else ''}:\n{shown}\n"
                    "-> read_file again, copy the context lines exactly, and keep sections in file order"
                )
            self.fuzz += fuzz
            for chunk in section_chunks:
                chunk.orig_index += new_index
                chunks.append(chunk)
            index = new_index + len(context)
            self.index = end_index
        return chunks

    def _seek_anchor(self, file_lines: list[str], index: int, anchor: str) -> int:
        if anchor not in file_lines[:index]:
            for i in range(index, len(file_lines)):
                if file_lines[i] == anchor:
                    return i + 1
        if anchor.strip() not in [s.strip() for s in file_lines[:index]]:
            for i in range(index, len(file_lines)):
                if file_lines[i].strip() == anchor.strip():
                    self.fuzz += 1
                    return i + 1
        return index  # 锚点找不到时与官方一致：不报错，退回靠上下文匹配


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
