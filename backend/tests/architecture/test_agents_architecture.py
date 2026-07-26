"""Architecture constraints for the agents package facades."""

from __future__ import annotations

import ast
from pathlib import Path


AGENTS_DIR = Path(__file__).parents[2] / "app" / "agents"
FACADE_MODULES = {
    name: AGENTS_DIR / f"{name}.py"
    for name in ("author_team", "code_agent")
}
IMPLEMENTATION_MODULES = {
    name: AGENTS_DIR / f"{name}.py"
    for name in (
        "author_contract",
        "author_merge",
        "author_orchestration",
        "author_prompts",
        "author_runner",
    )
}
APPLICATION_FACADES = {
    "app.agents.author_team",
    "app.agents.code_agent",
}


def _tree(module_name: str) -> ast.Module:
    return ast.parse(FACADE_MODULES[module_name].read_text(encoding="utf-8"))


def _is_agents_import(node: ast.ImportFrom) -> bool:
    if node.level:
        return True
    module = node.module or ""
    return module == "app.agents" or module.startswith("app.agents.")


def test_agent_facades_use_explicit_public_imports() -> None:
    """Facades must not make private implementation names part of a boundary."""
    violations: list[str] = []
    for module_name, path in FACADE_MODULES.items():
        for node in ast.walk(_tree(module_name)):
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == "*" for alias in node.names):
                    violations.append(f"{path.name}:{node.lineno} uses import *")
                if _is_agents_import(node):
                    private_names = [
                        alias.name for alias in node.names if alias.name.startswith("_")
                    ]
                    if private_names:
                        source = node.module or "." * node.level
                        violations.append(
                            f"{path.name}:{node.lineno} imports private names "
                            f"{private_names} from {source}"
                        )
            elif isinstance(node, ast.Import):
                private_modules = [
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("app.agents._")
                ]
                if private_modules:
                    violations.append(
                        f"{path.name}:{node.lineno} imports private modules {private_modules}"
                    )
    assert not violations, "\n".join(violations)


def test_agent_facades_publish_only_public_names() -> None:
    violations: list[str] = []
    for module_name, path in FACADE_MODULES.items():
        tree = _tree(module_name)
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                continue
            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                private_names = [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                    and element.value.startswith("_")
                ]
                if private_names:
                    violations.append(
                        f"{path.name}:{node.lineno} publishes private names {private_names}"
                    )
    assert not violations, "\n".join(violations)


def test_agent_implementations_do_not_import_application_facades() -> None:
    violations: list[str] = []
    for module_name, path in IMPLEMENTATION_MODULES.items():
        for node in ast.walk(
            ast.parse(path.read_text(encoding="utf-8"))
        ):
            if isinstance(node, ast.ImportFrom):
                if node.module in APPLICATION_FACADES:
                    violations.append(f"{path.name}:{node.lineno} imports {node.module}")
                if node.module == "app.agents":
                    for alias in node.names:
                        facade = f"app.agents.{alias.name}"
                        if facade in APPLICATION_FACADES:
                            violations.append(f"{path.name}:{node.lineno} imports {facade}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in APPLICATION_FACADES:
                        violations.append(f"{path.name}:{node.lineno} imports {alias.name}")
    assert not violations, "\n".join(violations)
