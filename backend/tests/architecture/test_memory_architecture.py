"""Architecture constraints for the memory service package."""

from __future__ import annotations

import ast
from pathlib import Path


SERVICE_DIR = Path(__file__).parents[2] / "app" / "services"
MEMORY_MODULES = {
    path.stem: path
    for path in SERVICE_DIR.glob("memory*.py")
}
LOWER_LAYER_MODULES = {
    name
    for name in MEMORY_MODULES
    if name.startswith("memory_profile_")
    or name in {"memory_repository", "memory_retention", "memory_rules"}
}
APPLICATION_FACADES = {"app.services.memory", "app.services.memory_profiles"}


def _tree(module_name: str) -> ast.Module:
    return ast.parse(MEMORY_MODULES[module_name].read_text(encoding="utf-8"))


def _memory_dependencies(module_name: str) -> set[str]:
    dependencies: set[str] = set()
    for node in ast.walk(_tree(module_name)):
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.services":
                dependencies.update(alias.name for alias in node.names if alias.name in MEMORY_MODULES)
            elif node.module and node.module.startswith("app.services.memory"):
                dependency = node.module.rsplit(".", 1)[-1]
                if dependency in MEMORY_MODULES:
                    dependencies.add(dependency)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app.services.memory"):
                    dependency = alias.name.rsplit(".", 1)[-1]
                    if dependency in MEMORY_MODULES:
                        dependencies.add(dependency)
    dependencies.discard(module_name)
    return dependencies


def test_memory_services_use_explicit_public_imports() -> None:
    violations: list[str] = []
    for module_name, path in MEMORY_MODULES.items():
        for node in ast.walk(_tree(module_name)):
            if not isinstance(node, ast.ImportFrom):
                continue
            if any(alias.name == "*" for alias in node.names):
                violations.append(f"{path.name}:{node.lineno} uses import *")
            if node.module and node.module.startswith("app.services.memory"):
                private_names = [alias.name for alias in node.names if alias.name.startswith("_")]
                if private_names:
                    violations.append(
                        f"{path.name}:{node.lineno} imports private names {private_names} from {node.module}"
                    )
    assert not violations, "\n".join(violations)


def test_lower_memory_layers_do_not_import_application_facades() -> None:
    violations: list[str] = []
    for module_name in LOWER_LAYER_MODULES:
        path = MEMORY_MODULES[module_name]
        for node in ast.walk(_tree(module_name)):
            if isinstance(node, ast.ImportFrom):
                if node.module in APPLICATION_FACADES:
                    violations.append(f"{path.name}:{node.lineno} imports {node.module}")
                if node.module == "app.services":
                    for alias in node.names:
                        facade = f"app.services.{alias.name}"
                        if facade in APPLICATION_FACADES:
                            violations.append(f"{path.name}:{node.lineno} imports {facade}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in APPLICATION_FACADES:
                        violations.append(f"{path.name}:{node.lineno} imports {alias.name}")
    assert not violations, "\n".join(violations)


def test_memory_service_dependency_graph_is_acyclic() -> None:
    graph = {name: _memory_dependencies(name) for name in MEMORY_MODULES}
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(module_name: str) -> None:
        if module_name in visiting:
            start = visiting.index(module_name)
            cycle = visiting[start:] + [module_name]
            raise AssertionError("Memory service dependency cycle: " + " -> ".join(cycle))
        if module_name in visited:
            return
        visiting.append(module_name)
        for dependency in sorted(graph[module_name]):
            visit(dependency)
        visiting.pop()
        visited.add(module_name)

    for module_name in sorted(graph):
        visit(module_name)
