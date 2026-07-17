"""Candidate validation, dependency-aware merging, and evidence checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.agents.agent_tools import AgentToolPolicy
from app.agents.repair_session import RepairOutcome, RepairSession
from app.services.vite_projects import validate_vite_project
from .author_contract import (
    _ACCEPTANCE_EVIDENCE_PATH,
    _AUTHOR_CONTRACT_PATH,
    _FrozenContract,
    _TYPESCRIPT_IDENTIFIER,
    _snapshot_revision,
)
from .author_prompts import _IMPLEMENTATION_ROLES, _INTEGRATION_POLICY, _RoleCandidate

@dataclass
class _MergeResult:
    files: list[dict]
    accepted_paths: set[str]
    accepted_roles: set[str]
    candidate_errors: dict[str, str]
    blocked_roles: dict[str, tuple[str, ...]]
    logs: list[str]
    export_gaps: dict[str, tuple[str, ...]] | None = None


def _actual_changes(base_files: list[dict], candidate_files: list[dict]) -> set[str]:
    base = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in base_files
    }
    candidate = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in candidate_files
    }
    return {
        path
        for path in set(base) | set(candidate)
        if base.get(path) != candidate.get(path)
        or (path in base) != (path in candidate)
    }


def _candidate_changes(
    candidate: _RoleCandidate,
    base_files: list[dict],
    *,
    expected_base_revision: str,
    expected_contract_hash: str,
    contract: _FrozenContract | None = None,
) -> tuple[dict[str, str | None] | None, str | None, tuple[str, ...]]:
    role = candidate.role
    outcome = candidate.outcome
    if candidate.base_revision != expected_base_revision:
        return None, "candidate base revision is stale", ()
    if candidate.contract_hash != expected_contract_hash:
        return None, "candidate contract hash is stale", ()
    if outcome is None:
        return None, "agent unavailable", ()
    actual = _actual_changes(base_files, outcome.files)
    declared = {str(path) for path in outcome.changed}
    if actual != declared:
        return (
            None,
            f"declared changes do not match candidate diff ({sorted(actual ^ declared)})",
            (),
        )
    unowned = sorted(path for path in actual if not role.policy.allows_write(path))
    if unowned:
        return None, f"candidate crossed file ownership: {', '.join(unowned)}", ()
    role_acceptance = (
        [item for item in contract.acceptance if item.owner == role.name]
        if contract is not None
        else []
    )
    role_modules = (
        [item for item in contract.modules if item.owner == role.name]
        if contract is not None
        else []
    )
    if (role_acceptance or role_modules) and not actual:
        return None, "candidate made no owned changes for assigned requirements", ()
    if role_modules:
        candidate_contents = {
            str(item.get("path") or ""): str(item.get("content") or "")
            for item in outcome.files
            if str(item.get("path") or "") in actual
        }
        exported = set().union(
            *(
                _typescript_exports(content)
                for path, content in candidate_contents.items()
                if role.policy.allows_write(path)
            )
        )
        missing_exports = sorted(
            {
                identifier
                for module in role_modules
                for identifier in module.exports
                if identifier not in exported
            }
        )
        if missing_exports:
            # Keep valid partial work; IntegrationAgent receives the explicit gap.
            missing = tuple(missing_exports)
        else:
            missing = ()
    else:
        missing = ()
    static_errors = validate_vite_project(outcome.files)
    if static_errors:
        return None, "candidate source validation failed: " + "; ".join(static_errors[:3]), ()
    candidate = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in outcome.files
    }
    return {path: candidate.get(path) for path in actual}, None, missing


def _typescript_exports(source: str) -> set[str]:
    identifiers = set(
        re.findall(
            r"\bexport\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?"
            r"(?:class|function|const|let|var|interface|type|enum|namespace)\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*)",
            source,
        )
    )
    for block in re.findall(r"\bexport\s*\{([^}]*)\}", source, flags=re.DOTALL):
        for item in block.split(","):
            token = item.strip().removeprefix("type ").strip()
            if not token:
                continue
            parts = re.split(r"\s+as\s+", token)
            identifier = parts[-1].strip()
            if _TYPESCRIPT_IDENTIFIER.fullmatch(identifier):
                identifiers.add(identifier)
    return identifiers


def _salvage_owner_files(
    base_files: list[dict], candidate: _RoleCandidate
) -> list[dict]:
    """Keep only the failed candidate's owner-scoped edits for its one retry."""
    if candidate.outcome is None:
        return [dict(item) for item in base_files]
    base = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in base_files
    }
    order = [str(item.get("path") or "") for item in base_files]
    attempted = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in candidate.outcome.files
    }
    for path in _actual_changes(base_files, candidate.outcome.files):
        if not candidate.role.policy.allows_write(path):
            continue
        if path not in attempted:
            base.pop(path, None)
            if path in order:
                order.remove(path)
        else:
            base[path] = attempted[path]
            if path not in order:
                order.append(path)

    return [{"path": path, "content": base[path]} for path in order]


def _dependency_names(value: object) -> set[str]:
    text = (
        json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    )
    return {role.name for role in _IMPLEMENTATION_ROLES if role.name in text}


def _role_dependencies(contract: _FrozenContract | None) -> dict[str, set[str]]:
    dependencies = {role.name: set() for role in _IMPLEMENTATION_ROLES}
    if contract is None:
        return dependencies
    export_owners: dict[str, str] = {}
    ignored_exports = {"typed", "type", "api", "data", "module", "system", "exports"}
    for module in contract.modules:
        for token in re.findall(
            r"[A-Za-z][A-Za-z0-9_]{3,}", " ".join(module.exports)
        ):
            if token.lower() not in ignored_exports:
                export_owners[token.lower()] = module.owner
    for module in contract.modules:
        if module.owner in dependencies:
            dependencies[module.owner].update(_dependency_names(module.depends_on))
            dependency_tokens = {
                token.lower()
                for token in re.findall(
                    r"[A-Za-z][A-Za-z0-9_]{3,}", " ".join(module.depends_on)
                )
            }
            dependencies[module.owner].update(
                export_owners[token]
                for token in dependency_tokens
                if token in export_owners and export_owners[token] in dependencies
            )
    for event in contract.events:
        if event.producer not in dependencies:
            continue
        for consumer in event.consumers:
            if consumer in dependencies and consumer != event.producer:
                dependencies[consumer].add(event.producer)
    for role, owners in dependencies.items():
        owners.discard(role)
    return dependencies


def _dependency_components(dependencies: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Return strongly connected owner groups in deterministic role order.

    Contracts commonly describe bidirectional typed APIs (rules emit events to
    presentation while presentation input commands feed rules). Treating those
    edges as a strict one-role-at-a-time topological order deadlocks every valid
    candidate in the cycle. Cyclic owners must be validated and accepted as one
    atomic merge unit.
    """
    role_order = {role.name: index for index, role in enumerate(_IMPLEMENTATION_ROLES)}
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for dependency in sorted(
            dependencies.get(node, set()), key=lambda name: role_order.get(name, 999)
        ):
            if dependency not in indices:
                visit(dependency)
                lowlinks[node] = min(lowlinks[node], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[dependency])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        components.append(tuple(sorted(component, key=lambda name: role_order[name])))

    for role in _IMPLEMENTATION_ROLES:
        if role.name not in indices:
            visit(role.name)
    return components


def _merge_candidate_report(
    base_files: list[dict],
    candidates: list[_RoleCandidate],
    *,
    base_revision: str,
    contract_hash: str,
    contract: _FrozenContract | None = None,
) -> _MergeResult:
    merged = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in base_files
    }
    order = [str(item.get("path") or "") for item in base_files]
    accepted: set[str] = set()
    accepted_roles: set[str] = set()
    candidate_errors: dict[str, str] = {}
    export_gaps: dict[str, tuple[str, ...]] = {}
    valid_changes: dict[str, dict[str, str | None]] = {}
    logs: list[str] = []
    for candidate in candidates:
        role = candidate.role
        changes, error, missing_exports = _candidate_changes(
            candidate,
            base_files,
            expected_base_revision=base_revision,
            expected_contract_hash=contract_hash,
            contract=contract,
        )
        if error:
            candidate_errors[role.name] = error
            logs.append(f"author team rejected {role.name} candidate: {error}")
            continue
        if missing_exports:
            export_gaps[role.name] = missing_exports
            logs.append(
                f"author team accepted {role.name} candidate with missing exports "
                f"(integration must bridge): {', '.join(missing_exports)}"
            )
        valid_changes[role.name] = changes or {}

    dependencies = _role_dependencies(contract)
    role_order = {role.name: index for index, role in enumerate(_IMPLEMENTATION_ROLES)}
    components = _dependency_components(dependencies)
    pending = [
        component
        for component in components
        if any(role_name in valid_changes for role_name in component)
    ]
    while pending:
        progressed = False
        for component in list(pending):

            component_set = set(component)
            component_roles = [
                role_name for role_name in component if role_name in valid_changes
            ]
            missing_members = component_set - set(component_roles)
            missing_external = set().union(
                *(
                    dependencies.get(role_name, set()) - component_set
                    for role_name in component_roles
                )
            ) - accepted_roles
            missing = missing_members | missing_external
            if missing:
                continue
            trial = dict(merged)
            trial_order = list(order)
            component_paths: set[str] = set()
            conflict: str | None = None
            for role_name in sorted(component_roles, key=lambda name: role_order[name]):
                changes = valid_changes[role_name]
                overlap = (accepted | component_paths).intersection(changes)
                if overlap:
                    conflict = "ownership conflict on " + ", ".join(sorted(overlap))
                    break
                component_paths.update(changes)
                for path, content in changes.items():
                    if content is None:
                        trial.pop(path, None)
                        if path in trial_order:
                            trial_order.remove(path)
                    else:
                        trial[path] = content
                        if path not in trial_order:
                            trial_order.append(path)
            if conflict:
                for role_name in component_roles:
                    candidate_errors[role_name] = conflict
                    logs.append(
                        f"author team rejected {role_name} candidate: {conflict}"
                    )
                pending.remove(component)
                progressed = True
                continue
            trial_files = [
                {"path": path, "content": trial[path]} for path in trial_order
            ]
            errors = validate_vite_project(trial_files)
            if errors:
                error = "candidate merge validation failed: " + "; ".join(errors[:3])
                for role_name in component_roles:
                    candidate_errors[role_name] = error
                    logs.append(f"author team rejected {role_name} merge: {error}")
                pending.remove(component)
                progressed = True
                continue
            merged, order = trial, trial_order
            accepted.update(component_paths)
            accepted_roles.update(component_roles)
            pending.remove(component)
            progressed = True
            for role_name in component_roles:
                changes = valid_changes[role_name]
                suffix = " as atomic dependency group" if len(component_roles) > 1 else ""
                logs.append(
                    f"author team accepted {role_name} candidate ({len(changes)} file(s)){suffix}: "
                    + (
                        ", ".join(sorted(changes))
                        if changes
                        else "no owned changes needed"
                    )
                )
        if not progressed:
            break

    # Salvage statically valid candidates even when a declared dependency owner
    # is unavailable.  The missing dependency is recorded for IntegrationAgent,
    # while delivered files remain useful instead of being discarded.
    for component in list(pending):
        for role_name in component:
            if role_name not in valid_changes:
                continue
            changes = valid_changes[role_name]
            if accepted.intersection(changes):
                continue
            trial = dict(merged)
            trial_order = list(order)
            for path, content in changes.items():
                if content is None:
                    trial.pop(path, None)
                    if path in trial_order:
                        trial_order.remove(path)
                else:
                    trial[path] = content
                    if path not in trial_order:
                        trial_order.append(path)
            trial_files = [{"path": path, "content": trial[path]} for path in trial_order]
            if validate_vite_project(trial_files):
                continue
            merged, order = trial, trial_order
            accepted.update(changes)
            accepted_roles.add(role_name)
            unmet = sorted(dependencies.get(role_name, set()) - accepted_roles)
            logs.append(
                f"author team accepted {role_name} candidate ({len(changes)} file(s)) despite unmet dependencies {', '.join(unmet) or 'none'} (integration must bridge)"
            )
        pending.remove(component)

    blocked_roles = {
        role_name: tuple(sorted(dependencies.get(role_name, set()) - accepted_roles))
        for component in pending
        for role_name in component
        if role_name in valid_changes
    }
    for role, missing in blocked_roles.items():
        logs.append(
            f"author team deferred {role} candidate: missing dependencies {', '.join(missing)}"
        )
    return _MergeResult(
        files=[{"path": path, "content": merged[path]} for path in order],
        accepted_paths=accepted,
        accepted_roles=accepted_roles,
        candidate_errors=candidate_errors,
        blocked_roles=blocked_roles,
        logs=logs,
        export_gaps=export_gaps,
    )


def _merge_candidates(
    base_files: list[dict],
    candidates: list[_RoleCandidate],
    *,
    base_revision: str,
    contract_hash: str,
    contract: _FrozenContract | None = None,
) -> tuple[list[dict], set[str], list[str]]:
    """Compatibility wrapper around the dependency-aware merge report."""
    result = _merge_candidate_report(
        base_files,
        candidates,
        base_revision=base_revision,
        contract_hash=contract_hash,
        contract=contract,
    )
    return result.files, result.accepted_paths, result.logs


def _runtime_wiring_path(path: str) -> bool:
    return path == "src/main.ts" or path.startswith(
        ("src/scenes/", "src/composition/", "src/adapters/")
    )


def _owner_policy(owner: str) -> AgentToolPolicy | None:
    if owner == "IntegrationAgent":
        return _INTEGRATION_POLICY
    return next(
        (role.policy for role in _IMPLEMENTATION_ROLES if role.name == owner), None
    )


def _source_identifiers(source: str) -> str:
    without_comments = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    without_comments = re.sub(r"//[^\r\n]*", " ", without_comments)
    without_strings = re.sub(r'"(?:\\.|[^"\\])*"', " ", without_comments)
    without_strings = re.sub(r"'(?:\\.|[^'\\])*'", " ", without_strings)
    return re.sub(r"`(?:\\.|[^`\\])*`", " ", without_strings, flags=re.DOTALL)


def _usage_identifiers(source: str) -> str:
    """Remove imports, re-exports, and inert ``void`` references."""
    stripped = _source_identifiers(source)
    stripped = re.sub(r"\bimport\b[^;]*?;", " ", stripped)
    stripped = re.sub(
        r"\bexport\s+(?:\{[^}]*\}|\*(?:\s+as\s+[A-Za-z_$][\w$]*)?)\s*(?:from[^;]*)?;",
        " ",
        stripped,
    )
    return re.sub(r"\bvoid\s+[A-Za-z_$][\w$]*\s*(?=[;,)\]\r\n])", " ", stripped)


def _acceptance_evidence_issues(
    files: list[dict],
    contract: _FrozenContract,
    contract_hash: str,
    gap_acceptance_ids: frozenset[str] | set[str] = frozenset(),
) -> list[str]:

    contents = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in files
    }
    raw = contents.get(_ACCEPTANCE_EVIDENCE_PATH)
    if raw is None:
        return [f"missing {_ACCEPTANCE_EVIDENCE_PATH}"]
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"acceptance evidence is not valid JSON: {exc.msg}"]
    if not isinstance(manifest, dict):
        return ["acceptance evidence root must be an object"]

    issues: list[str] = []
    if manifest.get("contract_hash") != contract_hash:
        issues.append("acceptance evidence contract_hash does not match frozen contract")
    requirement_rows = manifest.get("requirements")
    if not isinstance(requirement_rows, list):
        return issues + ["acceptance evidence requirements must be an array"]
    rows_by_id: dict[str, list[dict]] = {}
    for index, row in enumerate(requirement_rows):
        if not isinstance(row, dict):
            issues.append(f"acceptance evidence requirement #{index + 1} is not an object")
            continue
        acceptance_id = str(row.get("id") or "")
        rows_by_id.setdefault(acceptance_id, []).append(row)

    expected_ids = {item.id for item in contract.acceptance}
    extra_ids = sorted(set(rows_by_id) - expected_ids)
    if extra_ids:
        issues.append("acceptance evidence has unknown ids: " + ", ".join(extra_ids))
    for acceptance in contract.acceptance:
        rows = rows_by_id.get(acceptance.id, [])
        if len(rows) != 1:
            issues.append(
                f"{acceptance.id} must appear exactly once (found {len(rows)})"
            )
            continue
        row = rows[0]
        if row.get("owner") != acceptance.owner:
            issues.append(f"{acceptance.id} owner does not match contract")
        if row.get("status") != "implemented":
            issues.append(f"{acceptance.id} status must be implemented")
        if row.get("verification") != acceptance.verification:
            issues.append(f"{acceptance.id} verification does not match contract")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            issues.append(f"{acceptance.id} evidence must be a non-empty array")
            continue

        assigned_exports = {
            identifier
            for module in contract.modules
            if module.owner == acceptance.owner
            and acceptance.id in module.acceptance_ids
            for identifier in module.exports
        }
        owner_export_evidence = False
        wiring_export_evidence = False
        owner_policy = _owner_policy(acceptance.owner)
        gap_bridged = acceptance.id in gap_acceptance_ids
        for evidence_index, item in enumerate(evidence):
            label = f"{acceptance.id} evidence #{evidence_index + 1}"
            if not isinstance(item, dict):
                issues.append(f"{label} is not an object")
                continue
            path = str(item.get("path") or "")
            symbols = item.get("symbols")
            if path not in contents:
                issues.append(f"{label} path does not exist: {path or '<empty>'}")
                continue
            filename = path.rsplit("/", 1)[-1].lower()
            if path.startswith("src/contracts/") or filename in {"index.ts", "index.tsx"}:
                issues.append(f"{label} uses contract or barrel file: {path}")
                continue
            if not isinstance(symbols, list) or not symbols:
                issues.append(f"{label} symbols must be a non-empty array")
                continue
            clean_source = _source_identifiers(contents[path])
            usage_source = _usage_identifiers(contents[path])
            cited_symbols: set[str] = set()
            symbol_occurrences: dict[str, int] = {}
            for symbol_value in symbols:
                symbol = str(symbol_value or "")
                if not _TYPESCRIPT_IDENTIFIER.fullmatch(symbol):
                    issues.append(f"{label} has invalid symbol: {symbol or '<empty>'}")
                    continue
                occurrences = len(
                    re.findall(rf"\b{re.escape(symbol)}\b", clean_source)
                )
                usage_occurrences = len(
                    re.findall(rf"\b{re.escape(symbol)}\b", usage_source)
                )
                if not occurrences:
                    issues.append(f"{label} symbol is absent from {path}: {symbol}")
                    continue
                if not usage_occurrences:
                    issues.append(
                        f"{label} symbol appears only in import/re-export statements or inert `void` references in {path}"
                    )
                    continue
                cited_symbols.add(symbol)
                symbol_occurrences[symbol] = usage_occurrences
            cites_assigned_export = bool(cited_symbols & assigned_exports)
            if (
                acceptance.owner != "IntegrationAgent"
                and (
                    (owner_policy is not None and owner_policy.allows_write(path))
                    or (gap_bridged and _INTEGRATION_POLICY.allows_write(path))
                )
                and cites_assigned_export
            ):
                owner_export_evidence = True
            runtime_consumes_export = any(
                symbol_occurrences.get(symbol, 0) >= 1
                for symbol in cited_symbols & assigned_exports
            )
            if _runtime_wiring_path(path) and (
                runtime_consumes_export
                or (
                    acceptance.owner == "IntegrationAgent"
                    and cites_assigned_export
                )
            ):
                wiring_export_evidence = True

        if acceptance.owner != "IntegrationAgent" and not owner_export_evidence:
            issues.append(
                f"{acceptance.id} lacks owner implementation evidence for assigned exports"
            )
        if not wiring_export_evidence:
            issues.append(
                f"{acceptance.id} lacks runtime wiring evidence for assigned exports"
            )
    for path in sorted(contents):
        if not _runtime_wiring_path(path):
            continue
        stripped = _source_identifiers(contents[path])
        for match in re.finditer(r"\bvoid\s+([A-Za-z_$][\w$]*)\s*;", stripped):
            issues.append(
                "inert reference laundering: "
                f"{path} silences {match.group(1)} with a no-op `void` statement"
            )
    return issues
