"""OpenAI Agents SDK tool schema for the game bundle workspace."""
from __future__ import annotations

from app.agents.repair_session import RepairSession, available_skills

def _make_tools(session: RepairSession, *, author: bool = False):
    """工具面固定顺序构建：工具 schema 是每轮请求前缀的一部分，顺序/文案稳定是
    prompt cache 命中的前提。author 额外拿 write_file（整文件写入，修复 agent 不给，
    保持"最小 patch"纪律）。"""
    from agents import function_tool

    @function_tool
    def list_files() -> str:
        """List the current game bundle files, file sizes, script order, and whether each module is referenced."""
        return session.list_files()

    @function_tool
    def read_file(path: str) -> str:
        """Read one file from the game bundle. path is a bundle file name, e.g. "game.js"."""
        return session.read_file(path)

    @function_tool
    def search_files(query: str, file_pattern: str = "") -> str:
        """Search current game bundle files for a literal text query. Optional file_pattern is a glob like "*.js"."""
        return session.search_files(query, file_pattern)

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

    tools = (
        [list_files, read_file, search_files, apply_patch, write_file, run_checks]
        if author
        else [list_files, read_file, search_files, apply_patch, run_checks]
    )
    if available_skills():

        @function_tool
        def read_skill(name: str) -> str:
            """Read a GameWeave reference skill document by name (names are listed in the task input)."""
            return session.read_skill(name)

        tools.append(read_skill)
    return tools
