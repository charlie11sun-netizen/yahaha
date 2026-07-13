"""OpenAI Agents SDK tool schema for the game bundle workspace."""
from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel

from app.agents.repair_session import RepairSession, available_skills


class PatchOperationInput(BaseModel):
    operation_type: Literal["create_file", "update_file", "delete_file"]
    path: str
    diff: str = ""
    move_to: str = ""


class _RepairSessionPatchEditor:
    """Send structured SDK operations directly to the verified in-memory workspace."""

    def __init__(self, session: RepairSession, result_factory: Callable[..., Any]):
        self.session = session
        self.result_factory = result_factory

    def _result(self, output: str):
        return self.result_factory(
            status="failed" if output.startswith("error:") else "completed",
            output=output,
        )

    def _apply(self, operation: Any, operation_type: str):
        path = str(operation.path or "").strip()
        diff = None if operation.diff is None else str(operation.diff)
        move_to = str(getattr(operation, "move_to", "") or "").strip() or None
        return self._result(
            self.session.apply_patch_operation(
                operation_type,
                path=path,
                diff=diff,
                move_to=move_to,
            )
        )

    def create_file(self, operation: Any):
        return self._apply(operation, "create_file")

    def update_file(self, operation: Any):
        return self._apply(operation, "update_file")

    def delete_file(self, operation: Any):
        return self._apply(operation, "delete_file")


def _make_tools(session: RepairSession, *, author: bool = False):
    """工具面固定顺序构建：工具 schema 是每轮请求前缀的一部分，顺序/文案稳定是
    prompt cache 命中的前提。author 额外拿 write_file（整文件写入，修复 agent 不给，
    保持"最小 patch"纪律）。"""
    from agents import function_tool

    @function_tool
    def list_files() -> str:
        """List the current generated bundle or Vite project files and their sizes."""
        return session.list_files()

    @function_tool
    def read_file(path: str) -> str:
        """Read one generated source file, for example game.js or src/scenes/PlayScene.ts."""
        return session.read_file(path)

    @function_tool
    def read_files(paths: list[str]) -> str:
        """Read up to 16 generated source files in one call.

        Pass every file implicated by the error or feature together instead of
        reading them one at a time.
        """
        return session.read_files(paths)

    @function_tool
    def search_files(query: str, file_pattern: str = "") -> str:
        """Search generated source files. file_pattern may be a glob such as src/**/*.ts."""
        return session.search_files(query, file_pattern)

    @function_tool
    def apply_patch(
        operation_type: Literal["create_file", "update_file", "delete_file"],
        path: str,
        diff: str = "",
        move_to: str = "",
    ) -> str:
        """Apply one verified project patch.

        For update_file, diff contains only V4A context and +/- lines, optionally
        with @@ locators; omit the Begin/Update/End patch envelope. For
        create_file, prefix every content line with +. delete_file ignores diff.
        move_to is only valid for update_file.
        """
        return session.apply_patch_operation(
            operation_type,
            path=path,
            diff=diff or None,
            move_to=move_to.strip() or None,
        )

    @function_tool
    def apply_patch_set(operations: list[PatchOperationInput]) -> str:
        """Atomically apply up to 16 coordinated patch operations across multiple files.

        Use one operation per file and send all related edits in the same call. Each
        update diff uses V4A context lines; create content lines start with +. If any
        operation fails validation, no files are changed.
        """
        return session.apply_patch_operations([operation.model_dump() for operation in operations])

    @function_tool
    def write_file(path: str, content: str) -> str:
        """Create a safe relative JS/TS/CSS/JSON project file or replace an existing file. Prefer apply_patch for small edits."""
        return session.write_file(path, content)

    @function_tool
    def run_checks() -> str:
        """Run bundle checks, or TypeScript validation plus the isolated Vite build for a source project."""
        return session.run_checks()

    tools = (
        [list_files, read_file, read_files, search_files, apply_patch, apply_patch_set, write_file, run_checks]
        if author
        else [list_files, read_file, read_files, search_files, apply_patch, apply_patch_set, run_checks]
    )
    if available_skills():

        @function_tool
        def read_skill(name: str) -> str:
            """Read a GameWeave reference skill document by name (names are listed in the task input)."""
            return session.read_skill(name)

        tools.append(read_skill)
    return tools
