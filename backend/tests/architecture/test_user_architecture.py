"""Architecture constraints for user authentication and lifecycle modules."""

from __future__ import annotations

import ast
from pathlib import Path


APP_DIR = Path(__file__).parents[2] / "app"
CORE_USERS = APP_DIR / "core" / "users.py"
USER_ACCOUNTS = APP_DIR / "services" / "user_accounts.py"
USER_AUTH = APP_DIR / "api" / "user_auth.py"


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def test_core_users_does_not_depend_on_application_or_storage_layers() -> None:
    forbidden = ("app.api", "app.services", "app.storage")
    violations = sorted(name for name in _imports(CORE_USERS) if name.startswith(forbidden))
    assert not violations, f"core/users.py has upward dependencies: {violations}"


def test_user_dependency_direction_is_api_to_services_to_core() -> None:
    assert "app.core.users" in _imports(USER_ACCOUNTS)
    assert "app.services.user_accounts" in _imports(USER_AUTH)
