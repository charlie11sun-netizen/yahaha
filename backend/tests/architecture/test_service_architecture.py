"""Architecture constraints for the generation service boundary."""

from __future__ import annotations

import ast
from pathlib import Path


APP_DIR = Path(__file__).parents[2] / "app"
SERVICE_DIR = APP_DIR / "services"
SHARED_DIRS = (
    APP_DIR / "generation",
    APP_DIR / "llm",
    APP_DIR / "observability",
)


def _agent_imports(path: Path) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "app.agents" or node.module.startswith("app.agents."):
                imports.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.agents" or alias.name.startswith("app.agents."):
                    imports.append((node.lineno, alias.name))
    return imports


def _violations(paths: list[Path]) -> list[str]:
    return [
        f"{path.relative_to(APP_DIR)}:{line} imports {module}"
        for path in paths
        for line, module in _agent_imports(path)
    ]


def test_services_do_not_depend_on_agent_orchestration() -> None:
    violations = _violations(sorted(SERVICE_DIR.glob("*.py")))
    assert not violations, "\n".join(violations)


def test_shared_generation_components_do_not_depend_on_agents() -> None:
    paths = sorted(path for directory in SHARED_DIRS for path in directory.glob("*.py"))
    violations = _violations(paths)
    assert not violations, "\n".join(violations)
