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

import os
import re
import time
from dataclasses import dataclass, field

from app.agents import llm, smoke, validation
from app.core.config import settings

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
_EDITABLE = ("index.html", "style.css", "game.js")
_MAX_ERRORS_SHOWN = 8

_INSTRUCTIONS = """You repair a small self-contained HTML5 game bundle (index.html, style.css, game.js) that just failed one of GameWeave's quality gates — static build validation or browser gameplay QA (the task input states which).

Hard sandbox contract (any violation fails validation again):
- Forbidden everywhere: eval(), new Function, fetch(), XMLHttpRequest, WebSocket, EventSource, navigator.sendBeacon, dynamic import(), localStorage, sessionStorage, document.cookie, window.parent/window.top access (postMessage is the only exception), and any external http(s) URL including <script src="http...">.
- Required files: exactly index.html, style.css, game.js; each <= 400KB; index.html must reference game.js.
- Graphics/sound must be procedural or data:/blob: URIs. Report score only via window.parent.postMessage({type:"gameweave:score", points:<int>}, "*").
- game.js top-level code also runs once in a stubbed V8 smoke test (no real DOM, requestAnimationFrame/setTimeout are no-ops): it must not throw at load time.

Method — work in small verified steps:
1. read_file the files implicated by the error (start with game.js).
2. Make the smallest edit that fixes the reported errors; keep gameplay and structure intact. Use apply_patch with a unified diff for the exact changed lines only. Never rewrite a whole file.
3. run_checks after every patch. Repeat until it reports ALL CHECKS PASSED.
4. Finish with exactly one line: "FIXED: <what you changed>". If genuinely impossible, finish with "GIVEUP: <why>".
Never rewrite the game from scratch; repair causes, not symptoms."""

_3D_NOTE = (
    'This is a 3D game: index.html loads the self-hosted engine via <script src="three.min.js"></script> '
    "before game.js, and game.js uses the global THREE. Keep that script tag and never switch to a CDN."
)

_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


@dataclass
class _PatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


def _strip_patch_fence(patch: str) -> str:
    text = str(patch or "").strip()
    fenced = re.search(r"```[ \t]*(?:diff|patch)?[^\n]*\n(.*?)```", text, re.S | re.I)
    if fenced and "@@" in fenced.group(1):
        return fenced.group(1).strip("\n")
    return text


def _declared_patch_paths(patch: str) -> set[str]:
    paths: set[str] = set()
    for line in _strip_patch_fence(patch).splitlines():
        if not line.startswith("+++ "):
            continue
        raw = line[4:].strip().split("\t", 1)[0].strip().strip('"')
        if raw == "/dev/null":
            continue
        if raw.startswith(("a/", "b/")):
            raw = raw[2:]
        paths.add(raw.replace("\\", "/"))
    return paths


def _parse_unified_patch(patch: str) -> tuple[list[_PatchHunk], str | None]:
    lines = _strip_patch_fence(patch).splitlines()
    hunks: list[_PatchHunk] = []
    i = 0
    while i < len(lines):
        match = _HUNK_RE.match(lines[i])
        if not match:
            i += 1
            continue
        old_count = int(match.group("old_count") or "1")
        new_count = int(match.group("new_count") or "1")
        hunk_lines: list[str] = []
        i += 1
        while i < len(lines):
            line = lines[i]
            if _HUNK_RE.match(line) or line.startswith("diff --git "):
                break
            if line.startswith("\\ No newline at end of file"):
                i += 1
                continue
            if not line or line[0] not in " +-":
                return [], f"invalid hunk line: {line[:80]!r}"
            hunk_lines.append(line)
            i += 1
        hunks.append(
            _PatchHunk(
                old_start=int(match.group("old_start")),
                old_count=old_count,
                new_start=int(match.group("new_start")),
                new_count=new_count,
                lines=hunk_lines,
            )
        )
    if not hunks:
        return [], "patch contains no unified diff hunks"
    return hunks, None


def _find_sequence(lines: list[str], needle: list[str], start: int) -> int:
    if not needle:
        return max(0, min(start, len(lines)))
    if 0 <= start <= len(lines) and lines[start : start + len(needle)] == needle:
        return start
    matches = [
        i
        for i in range(0, len(lines) - len(needle) + 1)
        if lines[i : i + len(needle)] == needle
    ]
    return matches[0] if len(matches) == 1 else -1


def _apply_unified_hunks(content: str, hunks: list[_PatchHunk]) -> tuple[str | None, str | None]:
    newline = "\r\n" if "\r\n" in content else "\n"
    had_final_newline = content.endswith(("\n", "\r"))
    lines = content.splitlines()
    offset = 0
    for hunk in hunks:
        old_lines = [line[1:] for line in hunk.lines if line and line[0] in " -"]
        new_lines = [line[1:] for line in hunk.lines if line and line[0] in " +"]
        hint = max(0, hunk.old_start - 1 + offset)
        pos = _find_sequence(lines, old_lines, hint)
        if pos < 0:
            return None, f"hunk starting at -{hunk.old_start} did not match current file"
        lines[pos : pos + len(old_lines)] = new_lines
        offset += len(new_lines) - len(old_lines)
    output = newline.join(lines)
    if had_final_newline and output:
        output += newline
    return output, None


def _path_matches_declared(path: str, declared: set[str]) -> bool:
    wanted = path.replace("\\", "/")
    return any(candidate == wanted or os.path.basename(candidate) == wanted for candidate in declared)


def enabled(state: dict) -> bool:
    """agent 路径开关：显式 flag + 真模型任务（demo/mock 流水线不进 agent）。"""
    return bool(settings.CODE_AGENT_ENABLED and state.get("use_real"))


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

    @classmethod
    def from_files(cls, files: list[dict]) -> "RepairSession":
        contents: dict[str, str] = {}
        order: list[str] = []
        for f in files or []:
            path = str(f.get("path"))
            contents[path] = str(f.get("content") or "")
            order.append(path)
        return cls(contents=contents, order=order)

    def to_files(self) -> list[dict]:
        return [{"path": p, "content": self.contents[p]} for p in self.order]

    def _log(self, line: str) -> None:
        self.log_lines.append(line)

    # ---- 工具实现（SDK 包装见 run_repair；保持纯函数便于离线单测）----
    def read_file(self, path: str) -> str:
        if path not in self.contents:
            return f"error: no such file {path!r}; bundle has: {', '.join(self.order)}"
        body = self.contents[path]
        self._log(f"agent read {path} ({len(body.encode('utf-8'))}B)")
        return body

    def apply_patch(self, path: str, patch: str) -> str:
        if path not in _EDITABLE:
            return f"error: {path!r} is not editable; only {', '.join(_EDITABLE)} are"
        if path not in self.contents:
            return f"error: no such file {path!r}; bundle has: {', '.join(self.order)}"
        declared = _declared_patch_paths(patch)
        if declared and not all(_path_matches_declared(path, {candidate}) for candidate in declared):
            return f"error: patch targets {sorted(declared)}, not {path!r}"
        hunks, parse_error = _parse_unified_patch(patch)
        if parse_error:
            return f"error: {parse_error}"
        content, apply_error = _apply_unified_hunks(self.contents[path], hunks)
        if apply_error:
            return f"error: patch did not apply: {apply_error}"
        if content == self.contents[path]:
            return "error: patch made no changes"
        size = len(content.encode("utf-8"))
        if size > validation.MAX_FILE_BYTES:
            return (
                f"error: content exceeds {validation.MAX_FILE_BYTES // 1000}KB limit ({size}B); "
                "apply a smaller patch"
            )
        self.contents[path] = content
        self.changed.add(path)
        self.checks_ok = False
        self._log(f"agent patched {path} ({len(hunks)} hunk(s), {size}B)")
        return f"patched {path} with {len(hunks)} hunk(s) ({size}B). Now call run_checks to verify."

    def run_checks(self) -> str:
        result = validation.validate_files(self.to_files())
        errors = [str(e)[:160] for e in (result.get("errors") or [])][:_MAX_ERRORS_SHOWN]
        ok_smoke, smoke_detail = smoke.run_smoke(self.contents.get("game.js", ""))
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


def _usage_of(result) -> dict:
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    return {
        "requests": int(getattr(usage, "requests", 0) or 0),
        "input": int(getattr(usage, "input_tokens", 0) or 0),
        "output": int(getattr(usage, "output_tokens", 0) or 0),
        "total": int(getattr(usage, "total_tokens", 0) or 0),
    }


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


def run_repair(
    files: list[dict],
    *,
    error: str,
    dimension: str = "2d",
    task_note: str | None = None,
    failure_label: str = "Build validation",
    max_turns: int | None = None,
) -> RepairOutcome | None:
    """跑一轮修复 agent。返回 None 表示 agent 路径不可用/异常（调用方回落旧路径）。

    注意：openai-agents 的顶层包名就是 `agents`（与 app.agents 无冲突，绝对导入
    只会命中 site-packages）。所有 SDK 符号惰性导入，未安装不影响主流程。
    """
    if not files:
        return None
    try:
        from agents import Agent, OpenAIChatCompletionsModel, RunConfig, Runner, function_tool
        from agents.exceptions import AgentsException, MaxTurnsExceeded
        from openai import AsyncOpenAI
    except Exception:  # pragma: no cover —— SDK 未安装
        return None

    session = RepairSession.from_files(files)
    model_name = settings.CODE_AGENT_MODEL or settings.MODEL_NAME
    turns_limit = max_turns or settings.CODE_AGENT_MAX_TURNS

    @function_tool
    def read_file(path: str) -> str:
        """Read one file from the game bundle. path is a bundle file name, e.g. "game.js"."""
        return session.read_file(path)

    @function_tool
    def apply_patch(path: str, patch: str) -> str:
        """Apply a unified diff patch to one editable bundle file. Use exact context and changed lines only."""
        return session.apply_patch(path, patch)

    @function_tool
    def run_checks() -> str:
        """Run GameWeave's static validation plus the V8 smoke test on the current bundle."""
        return session.run_checks()

    tools = [read_file, apply_patch, run_checks]
    if available_skills():

        @function_tool
        def read_skill(name: str) -> str:
            """Read a GameWeave reference skill document by name (names are listed in the task input)."""
            return session.read_skill(name)

        tools.append(read_skill)

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
        name="GameCodeRepair",
        instructions=_INSTRUCTIONS,
        model=OpenAIChatCompletionsModel(model=model_name, openai_client=client),
        tools=tools,
    )

    start = time.perf_counter()
    result = None
    hit_limit = False
    try:
        result = Runner.run_sync(
            agent,
            _build_input(files, error, dimension, task_note, failure_label),
            max_turns=turns_limit,
            run_config=RunConfig(workflow_name="gameweave-repair", tracing_disabled=True),
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
