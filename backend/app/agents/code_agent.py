"""修复回环的内层工具循环 Agent（OpenAI Agents SDK）。

外层 LangGraph 拓扑不变（graph.py：顶层固定，安全/校验/发布不可跳过）。本模块
只替换 repair 类节点的内核：旧路径是"把错误塞回 prompt 整体重生成"，这里改成
模型在有界回合内 read_file / apply_patch / run_checks（静态校验 + V8 冒烟）做
最小修改并自测收敛。外层 build_validation 仍是独立门禁，agent 自称修好不算数。

SDK 惰性导入：CODE_AGENT_ENABLED=false（默认）或未安装 openai-agents 时本模块
照常 import，run_repair 返回 None，节点自动回落旧的整体重生成路径。
记账沿用统一通道：usage → llm.record_usage()（LLMCall 行 + task.cost_usd）；
回合数受 CODE_AGENT_MAX_TURNS 硬限，TASK_TOKEN_BUDGET 仍在下一个节点边界生效。
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from app.agents import llm, smoke, tracing, validation
from app.core.config import settings

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
_PROTECTED_FILES = ("index.html", "style.css", "game.js")  # 入口三件套：可改不可删
# 新建文件：平铺文件名（天然排除 / 与 ..），只允许 .js/.css 模块
_NEW_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(?:js|css)$")
_MAX_ERRORS_SHOWN = 8

_INSTRUCTIONS = """You repair a small self-contained HTML5 game bundle (index.html, style.css, game.js) that just failed one of GameWeave's quality gates — static build validation or browser gameplay QA (the task input states which).

Hard sandbox contract (any violation fails validation again):
- Forbidden everywhere: eval(), new Function, fetch(), XMLHttpRequest, WebSocket, EventSource, navigator.sendBeacon, dynamic import(), localStorage, sessionStorage, document.cookie, window.parent/window.top access (postMessage is the only exception), and any external http(s) URL including <script src="http...">.
- Entry files index.html, style.css, game.js always exist; a bundle may also carry flat .js/.css modules. Every .js must be referenced by a <script src> in index.html; each file <= 400KB.
- Graphics/sound must be procedural or data:/blob: URIs. Report score only via window.parent.postMessage({type:"gameweave:score", points:<int>}, "*").
- game.js top-level code also runs once in a stubbed V8 smoke test (no real DOM, requestAnimationFrame/setTimeout are no-ops): it must not throw at load time.

Method — work in small verified steps:
1. read_file the files implicated by the error (start with game.js).
2. Make the smallest edit that fixes the reported errors; keep gameplay and structure intact. Edit via apply_patch in V4A format (*** Update File: + @@ locators + context lines, no line numbers), touching only the lines that must change. Never rewrite a whole file.
3. run_checks after every patch. Repeat until it reports ALL CHECKS PASSED.
4. Finish with exactly one line: "FIXED: <what you changed>". If genuinely impossible, finish with "GIVEUP: <why>".
Never rewrite the game from scratch; repair causes, not symptoms."""

_3D_NOTE = (
    'This is a 3D game: index.html loads the self-hosted engine via <script src="three.min.js"></script> '
    "before game.js, and game.js uses the global THREE. Keep that script tag and never switch to a CDN."
)

# 作者模式 instructions。必须保持模块级静态常量（不做任何插值）：它与固定的工具
# schema 序构成每轮请求的稳定前缀，是多轮循环 prompt cache 命中率的根基。动态内容
# （spec/design/骨架清单）一律走 _build_author_input。
_AUTHOR_INSTRUCTIONS = """You are GameCodeAuthor, a senior HTML5 game developer. Starting from a skeleton bundle, BUILD the complete, polished browser game described by the task's GameSpec/GameDesign, growing the bundle with your tools until run_checks passes and every designed system exists.

You decide the file layout:
- The entry trio index.html, style.css, game.js always stays. Add one flat .js module per big system (e.g. shop.js, upgrades.js, waves.js, hud.js) with write_file; extra .css files are allowed too. Max 12 files, each <= 400KB.
- Wire every .js into index.html with a <script src> tag in dependency order (helpers before their users). An unreferenced .js fails validation.
- write_file creates or fully replaces one file; apply_patch (V4A) makes surgical edits and can also '*** Add File:' / '*** Delete File:'.

Hard sandbox contract (the outer gate re-checks all of it):
- Forbidden everywhere: eval(), new Function, fetch(), XMLHttpRequest, WebSocket, EventSource, navigator.sendBeacon, dynamic import(), localStorage, sessionStorage, document.cookie, window.parent/window.top access (postMessage is the only exception), and any external http(s) URL.
- Graphics/sound are procedural or data:/blob: URIs only. Report score only via window.parent.postMessage({type:"gameweave:score", points:<int>}, "*").
- Top-level code of every .js runs once in a stubbed V8 smoke test (no real DOM, rAF/timers are no-ops): it must not throw at load time; gameplay setup lives in init/scene callbacks.

Method — small verified increments:
1. Build the playable core loop in game.js first; run_checks until green before adding systems.
2. Then add ONE system per module file, wiring index.html immediately; run_checks after each file.
3. When the design includes progression/economy it is mandatory, not optional: in-run currency, a shop/upgrade screen reachable from play (buy weapons, ammo, gear), prices and effects tied to the design's balance numbers. Keep all persistence in memory — no storage APIs.
4. Polish is part of done: particle bursts, screen shake, hit-flash, score pops, smooth easing, a living background; WebAudio oscillator sound for key events.
5. Finish with exactly one line: "DONE: <files written + systems implemented>". If genuinely impossible, "GIVEUP: <why>".
Never finish while run_checks is failing or any .js is unreferenced."""

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


def enabled(state: dict) -> bool:
    """agent 路径开关：显式 flag + 真模型任务（demo/mock 流水线不进 agent）。"""
    return bool(settings.CODE_AGENT_ENABLED and state.get("use_real"))


def author_enabled(state: dict) -> bool:
    """作者模式开关：agent 从骨架起步自定文件结构写整局游戏，失败回落单次整包生成。"""
    return bool(settings.CODE_AGENT_AUTHOR_ENABLED and state.get("use_real"))


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

    def _log(self, line: str) -> None:
        self.log_lines.append(line)
        tracing.record_step_log(line, step_id=self.live_step_id)

    # ---- 工具实现（SDK 包装见 run_repair；保持纯函数便于离线单测）----
    def read_file(self, path: str) -> str:
        if path not in self.contents:
            return f"error: no such file {path!r}; bundle has: {', '.join(self.order)}"
        body = self.contents[path]
        self._log(f"agent read {path} ({len(body.encode('utf-8'))}B)")
        return body

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
        self.contents[name] = body
        if created:
            self.order.append(name)
        self.changed.add(name)
        self.checks_ok = False
        self._log(f"agent wrote {name} ({size}B{', new file' if created else ''})")
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
                staged[path] = (new_text, len(chunks), size)
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
        for path, (content, chunk_count, size) in staged.items():
            self.contents[path] = content
            self.changed.add(path)
            self._log(f"agent patched {path} ({chunk_count} chunk(s), {size}B)")
            summaries.append(f"{path} ({chunk_count} chunk(s), {size}B)")
        for path in parser.deletes:
            del self.contents[path]
            self.order.remove(path)
            self.changed.add(path)
            self._log(f"agent deleted {path}")
            summaries.append(f"deleted {path}")
        for path, (content, size) in added.items():
            self.contents[path] = content
            self.order.append(path)
            self.changed.add(path)
            self._log(f"agent added {path} ({size}B)")
            summaries.append(f"added {path} ({size}B)")
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
            + ("ok" if ok_smoke else "crashed")
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
        self._log(f"agent read skill {name}")
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


def _build_input(
    files: list[dict],
    error: str,
    dimension: str,
    task_note: str | None,
    failure_label: str = "Build validation",
) -> str:
    listing = "\n".join(
        f"- {f.get('path')} ({len(str(f.get('content') or '').encode('utf-8'))}B)" for f in files
    )
    parts = [f"{failure_label} failed with:\n{error}", f"Bundle files:\n{listing}"]
    if dimension == "3d":
        parts.append(_3D_NOTE)
    if task_note:
        parts.append(task_note)
    skills = available_skills()
    if skills:
        parts.append("Reference skills available via read_skill: " + ", ".join(skills))
    parts.append("Begin by reading the offending file(s), then fix with apply_patch and verify with run_checks.")
    return "\n\n".join(parts)


def _build_author_input(files: list[dict], spec: dict, design: dict, runtime: str, dimension: str) -> str:
    """作者任务的动态载荷（首条 user 消息）：spec/design/骨架清单 + 运行时注记。
    这里的内容进对话历史后同样被 cache 复用，跑内一次成本、跑间不共享。"""
    listing = "\n".join(
        f"- {f.get('path')} ({len(str(f.get('content') or '').encode('utf-8'))}B)" for f in files
    )
    parts = [
        "Author the complete game for this specification.",
        f"GameSpec:\n{json.dumps(spec, ensure_ascii=False)}",
        f"GameDesign to implement (entities, mechanics, balance):\n{json.dumps(design, ensure_ascii=False)}",
        f"Skeleton bundle already in place:\n{listing}",
    ]
    if dimension == "3d":
        parts.append(_3D_NOTE)
    elif runtime == "phaser":
        parts.append(
            "Runtime: Phaser 4 via the global `Phaser`; index.html already loads phaser.min.js before game.js — "
            "keep that order and never fetch the engine. Structure play as Phaser Scenes (menu / play / shop or "
            "upgrade screens as the design demands) and read the phaser runtime skill before writing code."
        )
    else:
        parts.append("Runtime: vanilla Canvas 2D — no engine script tag; render everything yourself.")
    skills = available_skills()
    if skills:
        parts.append("Reference skills available via read_skill: " + ", ".join(skills))
    parts.append(
        "Begin now: read index.html, write the core game.js, then grow one system per file with run_checks between steps."
    )
    return "\n\n".join(parts)


def _usage_of(result) -> dict:
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    details = getattr(usage, "input_tokens_details", None)
    return {
        "requests": int(getattr(usage, "requests", 0) or 0),
        "input": int(getattr(usage, "input_tokens", 0) or 0),
        "output": int(getattr(usage, "output_tokens", 0) or 0),
        "total": int(getattr(usage, "total_tokens", 0) or 0),
        "cached": int(getattr(details, "cached_tokens", 0) or 0),
    }


def _log_cache_hit(session: RepairSession, result) -> None:
    """多轮循环的成本命门是 prompt cache：稳定前缀（静态 instructions + 固定工具序）
    加 append-only 历史应让命中率随轮数上升。把整跑命中率写进日志，退化能被看见。"""
    if result is None:
        return
    u = _usage_of(result)
    if u["input"]:
        pct = u["cached"] * 100 // u["input"]
        session._log(
            f"agent prompt cache: {u['cached']}/{u['input']} input tokens cached ({pct}%) over {u['requests']} request(s)"
        )


def _record(result, model_name: str, latency_ms: int) -> int:
    if result is None:
        return 0
    u = _usage_of(result)
    total = u["total"] or (u["input"] + u["output"])
    if total:
        try:
            llm.record_usage(model_name, u["input"], u["output"], latency_ms)
        except Exception:  # noqa: BLE001 —— 记账失败不影响修复结果
            pass
    return total


def _close_client(client) -> None:
    try:
        import asyncio

        asyncio.run(client.close())
    except Exception:  # noqa: BLE001
        pass


def _make_tools(session: RepairSession, *, author: bool = False):
    """工具面固定顺序构建：工具 schema 是每轮请求前缀的一部分，顺序/文案稳定是
    prompt cache 命中的前提。author 额外拿 write_file（整文件写入，修复 agent 不给，
    保持"最小 patch"纪律）。"""
    from agents import function_tool

    @function_tool
    def read_file(path: str) -> str:
        """Read one file from the game bundle. path is a bundle file name, e.g. "game.js"."""
        return session.read_file(path)

    @function_tool
    def apply_patch(patch: str) -> str:
        """Edit bundle files with a V4A patch (no line numbers):
*** Begin Patch
*** Update File: game.js
@@ function update()
 unchanged context line
-removed line
+added line
*** End Patch
Keep ~3 context lines around each change; use '@@ <copied source line>' to locate a block when context repeats; several @@ blocks per file and several files per patch are allowed. A patch may also '*** Add File: <name>.js' (every body line prefixed '+') or '*** Delete File: <name>' (the entry files index.html/style.css/game.js cannot be deleted). Patch only the changed lines — never rewrite a file."""
        return session.apply_patch(patch)

    @function_tool
    def write_file(path: str, content: str) -> str:
        """Create a new flat .js/.css module (wire it into index.html afterwards) or fully replace one existing file with `content`. Prefer apply_patch for small edits."""
        return session.write_file(path, content)

    @function_tool
    def run_checks() -> str:
        """Run GameWeave's static validation plus the V8 smoke test on the current bundle."""
        return session.run_checks()

    tools = [read_file, apply_patch, write_file, run_checks] if author else [read_file, apply_patch, run_checks]
    if available_skills():

        @function_tool
        def read_skill(name: str) -> str:
            """Read a GameWeave reference skill document by name (names are listed in the task input)."""
            return session.read_skill(name)

        tools.append(read_skill)
    return tools


def _execute_agent(
    session: RepairSession,
    *,
    agent_name: str,
    instructions: str,
    author_tools: bool,
    task_input: str,
    turns_limit: int,
    workflow_name: str,
) -> RepairOutcome | None:
    """共享的 SDK 工具循环执行器。返回 None 表示不可用/异常（调用方回落旧路径）。

    注意：openai-agents 的顶层包名就是 `agents`（与 app.agents 无冲突，绝对导入
    只会命中 site-packages）。所有 SDK 符号惰性导入，未安装不影响主流程。
    cache 纪律：instructions 必须是模块级常量、工具序固定、循环 append-only ——
    三者共同构成跨轮稳定的请求前缀；动态内容一律放 task_input（首条 user 消息，
    进历史后同样被缓存复用）。整跑命中率由 _log_cache_hit 落日志。
    """
    try:
        from agents import Agent, OpenAIChatCompletionsModel, RunConfig, Runner
        from agents.exceptions import AgentsException, MaxTurnsExceeded
        from openai import AsyncOpenAI
    except Exception:  # pragma: no cover —— SDK 未安装
        return None

    model_name = settings.CODE_AGENT_MODEL or settings.MODEL_NAME
    tools = _make_tools(session, author=author_tools)

    try:
        client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            timeout=settings.OPENAI_TIMEOUT,
            default_headers={"User-Agent": "GameWeave/1.0"},
        )
    except Exception:  # noqa: BLE001 —— 缺 key 等配置问题
        return None

    agent = Agent(
        name=agent_name,
        instructions=instructions,
        model=OpenAIChatCompletionsModel(model=model_name, openai_client=client),
        tools=tools,
    )

    start = time.perf_counter()
    result = None
    hit_limit = False
    try:
        result = Runner.run_sync(
            agent,
            task_input,
            max_turns=turns_limit,
            run_config=RunConfig(workflow_name=workflow_name, tracing_disabled=True),
        )
        note = str(result.final_output or "").strip()[:200]
    except MaxTurnsExceeded:
        hit_limit = True
        note = f"max turns ({turns_limit}) exhausted"
    except AgentsException as exc:
        _close_client(client)
        session._log(f"agent aborted: {str(exc)[:160]}")
        return None
    except Exception as exc:  # noqa: BLE001 —— 网络/供应商异常，一律回落旧路径
        _close_client(client)
        session._log(f"agent failed: {str(exc)[:160]}")
        return None
    _close_client(client)

    latency_ms = int((time.perf_counter() - start) * 1000)
    tokens = _record(result, model_name, latency_ms)
    _log_cache_hit(session, result)
    if hit_limit:
        session._log(f"agent stopped: {note}")
    return RepairOutcome(
        files=session.to_files(),
        changed=sorted(session.changed),
        tokens=tokens,
        logs=list(session.log_lines),
        note=note,
        checks_ok=session.checks_ok,
        turns=_usage_of(result)["requests"] if result is not None else turns_limit,
    )


def run_repair(
    files: list[dict],
    *,
    error: str,
    dimension: str = "2d",
    task_note: str | None = None,
    failure_label: str = "Build validation",
    max_turns: int | None = None,
) -> RepairOutcome | None:
    """跑一轮修复 agent。返回 None 表示 agent 路径不可用/异常（调用方回落旧路径）。"""
    if not files:
        return None
    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameCodeRepair",
        instructions=_INSTRUCTIONS,
        author_tools=False,
        task_input=_build_input(files, error, dimension, task_note, failure_label),
        turns_limit=max_turns or settings.CODE_AGENT_MAX_TURNS,
        workflow_name="gameweave-repair",
    )


def run_author(
    files: list[dict],
    *,
    spec: dict,
    design: dict,
    runtime: str = "canvas",
    dimension: str = "2d",
    max_turns: int | None = None,
) -> RepairOutcome | None:
    """作者模式：从骨架 bundle 起步，agent 自定文件结构逐文件写出完整游戏。

    每轮输出只是一个小 patch/文件，单请求远离网关超时墙；总代码量为各轮之和，
    不受单次响应解码预算限制。产物只是候选——外层 build_validation / gameplay QA
    门禁照常把关；返回 None 时调用方回落单次整包生成。
    """
    if not files:
        return None
    session = RepairSession.from_files(files, live_step_id=tracing.current_step_id())
    return _execute_agent(
        session,
        agent_name="GameCodeAuthor",
        instructions=_AUTHOR_INSTRUCTIONS,
        author_tools=True,
        task_input=_build_author_input(files, spec, design, runtime, dimension),
        turns_limit=max_turns or settings.CODE_AGENT_AUTHOR_MAX_TURNS,
        workflow_name="gameweave-author",
    )
