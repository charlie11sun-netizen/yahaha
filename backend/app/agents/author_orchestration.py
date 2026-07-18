"""Budgeted author-team orchestration and lifecycle events."""

from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Iterable

from app.agents import tracing
from app.agents.repair_session import RepairOutcome, RepairSession
from .author_contract import (
    _ACCEPTANCE_EVIDENCE_PATH,
    _AUTHOR_CONTRACT_PATH,
    _CONTRACT_CAPTURE_LIMIT,
    _DesignContractOutput,
    _canonical_json,
    _compact_brief,
    _contract_input,
    _freeze_contract,
    _role_input,
    _retry_role_input,
    _snapshot_revision,
    _structured_contract_payload,
    _with_contract_file,
)
from .author_merge import (
    _acceptance_evidence_issues, _actual_changes, _candidate_changes,
    _merge_candidate_report,
    _runtime_wiring_path, _salvage_owner_files,
)
from .author_prompts import (
    _CODER_CONCURRENCY, _DEFAULT_TEAM_DEADLINE_SECONDS,
    _DESIGN_CONTRACT_INSTRUCTIONS,
    _INTEGRATION_INSTRUCTIONS, _INTEGRATION_POLICY, _IMPLEMENTATION_ROLES,
    _MIN_INTEGRATION_TURNS, _OWNER_RETRY_MAX_TURNS, _READ_ONLY_POLICY,
    _TOKENS_PER_TURN_BUDGET, _RoleCandidate, _RoleDefinition,
)

@dataclass(frozen=True)
class _TurnPlan:
    planner: int
    coders: tuple[int, int, int]
    retry_reserve: int
    integration: int


@dataclass
class _TeamBudget:
    max_turns: int
    max_tokens: int
    max_changed_files: int
    deadline_at: float
    turns_used: int = 0
    tokens_used: int = 0
    changed_paths: set[str] | None = None

    def __post_init__(self) -> None:
        if self.changed_paths is None:
            self.changed_paths = set()

    @property
    def remaining_turns(self) -> int:
        return max(0, self.max_turns - self.turns_used)

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.deadline_at

    def observe(
        self, outcome: RepairOutcome | None, *, changed: Iterable[str] = ()
    ) -> None:
        if outcome is not None:
            self.turns_used += max(0, int(outcome.turns or 0))
            self.tokens_used += max(0, int(outcome.tokens or 0))
            self.changed_paths.update(str(path) for path in outcome.changed)
        self.changed_paths.update(str(path) for path in changed)

    def exhausted_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.remaining_turns <= 0:
            reasons.append("turns")
        if self.tokens_used >= self.max_tokens:
            reasons.append("tokens")
        if len(self.changed_paths) > self.max_changed_files:
            reasons.append("changed_files")
        if self.expired:
            reasons.append("deadline")
        return reasons

    def can_start(self, *, turns: int = 1) -> bool:
        return self.remaining_turns >= turns and not self.exhausted_reasons()


def _turn_allocation(total: int) -> _TurnPlan:
    budget = max(5, int(total or 0))
    planner = 1
    retry_reserve = 0 if budget < 16 else min(6, max(3, budget // 8))
    integration = max(1, budget // 4)
    remaining = budget - planner - retry_reserve - integration
    if remaining < 3:
        integration = max(1, integration - (3 - remaining))
        remaining = budget - planner - retry_reserve - integration
    if remaining < 3:
        retry_reserve = 0
        remaining = budget - planner - integration
    base, extra = divmod(remaining, 3)
    coders = tuple(max(1, base + (1 if index < extra else 0)) for index in range(3))
    return _TurnPlan(planner, coders, retry_reserve, integration)


def _emit(step_id: str | None, event_type: str, line: str, **payload) -> None:
    tracing.record_step_log(
        line,
        step_id=step_id,
        payload={"type": "author_team", "event": event_type, **payload},
    )


def _is_budget_exhausted(outcome: RepairOutcome | None) -> bool:
    return bool(
        outcome
        and (
            outcome.stop_reason == "max_turns"
            or str(outcome.note).lower().startswith("max turns")
        )
    )


def _is_partial_outcome(outcome: RepairOutcome | None) -> bool:
    return bool(outcome and outcome.stop_reason != "completed")


def _emit_role_result(
    step_id: str | None,
    role: str,
    outcome: RepairOutcome | None,
    *,
    retry: bool = False,
) -> None:
    if outcome is None:
        _emit(
            step_id,
            "role_failed",
            f"author team role unavailable: {role}",
            role=role,
            retry=retry,
            status="failed",
        )
    elif _is_partial_outcome(outcome):
        budget_exhausted = _is_budget_exhausted(outcome)
        _emit(
            step_id,
            "role_budget_exhausted" if budget_exhausted else "role_partial",
            (
                f"author team role budget exhausted with candidate preserved: {role}"
                if budget_exhausted
                else f"author team role stopped with candidate preserved: {role}"
            ),
            role=role,
            retry=retry,
            changed=sorted(outcome.changed),
            checks_ok=outcome.checks_ok,
            quality_state=outcome.quality_state,
            stop_reason=outcome.stop_reason,
            status="partial",
        )
    else:
        _emit(
            step_id,
            "role_completed",
            f"author team role completed: {role}",
            role=role,
            retry=retry,
            changed=sorted(outcome.changed),
            checks_ok=outcome.checks_ok,
            status="done",
        )


def run_project_author_team(
    files: list[dict],
    *,
    spec: dict,
    design: dict,
    runtime: str,
    dimension: str,
    qa_feedback: list | None,
    max_turns: int,
    live_step_id: str | None,
    team_deadline_seconds: float | None = None,
    team_token_budget: int | None = None,
    team_changed_file_budget: int | None = None,
    deadline_at: float | None = None,
    planning_context: dict | None = None,
    _execute_agent_fn=None,
    _tracing=None,
) -> RepairOutcome | None:
    """Run the bounded internal team and return one integrated project candidate."""
    if _execute_agent_fn is None:
        # Keep the implementation module usable on its own while depending on
        # the runner's public entry point rather than its private worker.
        from app.agents.author_runner import execute_agent
    else:
        execute_agent = _execute_agent_fn
    if _tracing is not None:
        globals()["tracing"] = _tracing
    if not files:
        return None

    effective_turns = max(5, int(max_turns or 0))
    plan = _turn_allocation(effective_turns)
    deadline_seconds = (
        _DEFAULT_TEAM_DEADLINE_SECONDS
        if team_deadline_seconds is None
        else max(0.0, float(team_deadline_seconds))
    )
    now = time.monotonic()
    configured_deadline = now + deadline_seconds
    effective_deadline = (
        min(configured_deadline, float(deadline_at))
        if deadline_at is not None
        else configured_deadline
    )
    budget = _TeamBudget(
        max_turns=effective_turns,
        max_tokens=(
            max(1, int(team_token_budget))
            if team_token_budget is not None
            else effective_turns * _TOKENS_PER_TURN_BUDGET
        ),
        max_changed_files=(
            max(1, int(team_changed_file_budget))
            if team_changed_file_budget is not None
            else max(24, effective_turns * 2)
        ),
        deadline_at=effective_deadline,
    )
    original_revision = _snapshot_revision(files)
    team_logs = [f"author team started from frozen base {original_revision[:12]}"]
    _emit(
        live_step_id,
        "team_started",
        team_logs[-1],
        phase="start",

        base_revision=original_revision,
        max_turns=budget.max_turns,
        max_tokens=budget.max_tokens,
        max_changed_files=budget.max_changed_files,
        deadline_seconds=max(0.0, effective_deadline - now),
        status="running",
    )

    architect_session = RepairSession.from_files(files, live_step_id=live_step_id)
    _emit(
        live_step_id,
        "role_started",
        "author team role started: DesignContractAgent",
        role="DesignContractAgent",
        turns_limit=plan.planner,
        status="running",
    )
    planning_items = list((planning_context or {}).get("items") or [])
    architect_kwargs = {
        "agent_name": "DesignContractAgent",
        "instructions": _DESIGN_CONTRACT_INSTRUCTIONS,
        "author_tools": False,
        "tool_policy": _READ_ONLY_POLICY,
        "task_input": _contract_input(
            spec, design, runtime, dimension, qa_feedback,
            chained=bool(planning_items),
        ),
        "turns_limit": plan.planner,
        "workflow_name": "gameweave-author-design-contract",
        "final_output_limit": _CONTRACT_CAPTURE_LIMIT,
        "operation": "authoring",
        "output_type": _DesignContractOutput,
        "deadline_at": budget.deadline_at,
        "terminal_completion": False,
        "safe_partial_stream_retry": True,
        "workspace_tools": False,
    }
    if planning_items:
        # Replay the planning conversation ahead of the contract prompt so the
        # architect inherits the brief/mechanic/design rationale verbatim.
        architect_kwargs["context_items"] = planning_items
        architect_kwargs["chained_from_response_id"] = (
            planning_context or {}
        ).get("response_id")
    architect = execute_agent(architect_session, **architect_kwargs)
    budget.observe(architect)
    if architect is None:
        budget.turns_used += plan.planner
    _emit_role_result(live_step_id, "DesignContractAgent", architect)
    if architect:
        team_logs.extend(architect.logs)
    raw_contract = (
        _structured_contract_payload(architect.raw_output) if architect else None
    )
    contract_error: str | None = None
    try:
        contract = _freeze_contract(raw_contract, spec, design)
    except ValueError as exc:
        contract_error = str(exc)
        raw_contract = None
        contract = _freeze_contract(None, spec, design)
    contract_payload = contract.as_dict()
    contract_hash = hashlib.sha256(
        _canonical_json(contract_payload).encode("utf-8")
    ).hexdigest()
    contract_source = "model" if raw_contract else "deterministic fallback"
    contract_files = _with_contract_file(files, contract, contract_hash)
    base_revision = _snapshot_revision(contract_files)
    orchestrator_changes = _actual_changes(files, contract_files)
    budget.observe(None, changed=orchestrator_changes)
    contract_line = f"author team froze {contract_source} contract {contract_hash[:12]}"
    team_logs.append(contract_line)
    if contract_error:
        team_logs.append(
            "author team rejected invalid model contract: " + contract_error
        )
    _emit(
        live_step_id,
        "contract_frozen" if raw_contract else "contract_fallback",
        contract_line,
        phase="contract_frozen",
        contract_hash=contract_hash,
        contract_source=contract_source,
        contract_path=_AUTHOR_CONTRACT_PATH,
        base_revision=base_revision,
        status="done" if raw_contract else "degraded",
        contract_error=contract_error,
    )

    if budget.exhausted_reasons():
        reasons = budget.exhausted_reasons()
        _emit(
            live_step_id,
            "team_budget_exhausted",
            "author team budget exhausted before implementation roles: "
            + ", ".join(reasons),
            reasons=reasons,
            status="stopped",
        )
        return None

    def execute_role(role: _RoleDefinition, turns: int) -> RepairOutcome | None:
        role_session = RepairSession.from_files(
            contract_files, live_step_id=live_step_id
        )
        return execute_agent(
            role_session,
            agent_name=role.name,
            instructions=role.instructions,
            author_tools=True,
            tool_policy=role.policy,
            task_input=_role_input(
                role,
                spec,
                design,
                contract_hash,
                base_revision,
                qa_feedback,
                (item.get("path") for item in contract_files),
            ),
            turns_limit=turns,
            workflow_name=role.workflow_name,
            operation="authoring",
            deadline_at=budget.deadline_at,
            preserve_partial_on_error=True,
        )

    role_outcomes: dict[str, RepairOutcome | None] = {}
    allocated_turns = dict(
        zip(
            (role.name for role in _IMPLEMENTATION_ROLES),
            plan.coders,
            strict=True,
        )
    )
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(_CODER_CONCURRENCY, len(_IMPLEMENTATION_ROLES)),
        thread_name_prefix="GameAuthorRole",
    ) as executor:
        future_roles: dict[concurrent.futures.Future, _RoleDefinition] = {}
        for role in _IMPLEMENTATION_ROLES:
            turns = allocated_turns[role.name]
            _emit(
                live_step_id,
                "role_started",
                f"author team role started: {role.name}",
                role=role.name,
                turns_limit=turns,
                status="running",
            )
            context = contextvars.copy_context()
            future_roles[executor.submit(context.run, execute_role, role, turns)] = role
        for future in concurrent.futures.as_completed(future_roles):

            role = future_roles[future]
            try:
                role_outcomes[role.name] = future.result()
            except Exception as exc:  # noqa: BLE001 - isolate one role failure
                role_outcomes[role.name] = None
                team_logs.append(
                    f"author team role crashed {role.name}: {type(exc).__name__}: {str(exc)[:160]}"
                )

    role_candidates: list[_RoleCandidate] = []
    for role in _IMPLEMENTATION_ROLES:
        outcome = role_outcomes.get(role.name)
        budget.observe(outcome)
        if outcome is None:
            budget.turns_used += allocated_turns[role.name]
        _emit_role_result(live_step_id, role.name, outcome)
        role_candidates.append(
            _RoleCandidate(
                role=role,
                outcome=outcome,
                base_revision=base_revision,
                contract_hash=contract_hash,
            )
        )
        if outcome:
            team_logs.extend(outcome.logs)

    merge = _merge_candidate_report(
        contract_files,
        role_candidates,
        base_revision=base_revision,
        contract_hash=contract_hash,
        contract=contract,
    )
    team_logs.extend(merge.logs)
    for line in merge.logs:
        _emit(
            live_step_id,
            "candidate_merge",
            line,
            phase="candidate_merge",
            status="done",
        )

    # Retry only invalid owner candidates. Dependency-blocked valid candidates are
    # salvaged automatically when their missing owner succeeds.
    candidate_by_role = {item.role.name: item for item in role_candidates}
    retry_roles = [
        role
        for role in _IMPLEMENTATION_ROLES
        if role.name in merge.candidate_errors
        or role.name in (merge.export_gaps or {})
    ]
    integration_reserve = max(min(_MIN_INTEGRATION_TURNS, plan.integration), plan.integration)
    retry_turn_cap = min(
        _OWNER_RETRY_MAX_TURNS,
        max(1, plan.retry_reserve // max(1, len(retry_roles))),
    )
    for index, role in enumerate(retry_roles):
        retries_left = len(retry_roles) - index - 1
        available = budget.remaining_turns - integration_reserve - retries_left * retry_turn_cap
        retry_turns = min(retry_turn_cap, max(0, available))
        if retry_turns < 1 or budget.expired:
            break
        previous = candidate_by_role[role.name]
        retry_files = _salvage_owner_files(contract_files, previous)
        retry_session = RepairSession.from_files(retry_files, live_step_id=live_step_id)
        retry_session.changed = _actual_changes(contract_files, retry_files)
        error = merge.candidate_errors.get(role.name) or (
            "candidate is missing assigned TypeScript exports: "
            + ", ".join((merge.export_gaps or {}).get(role.name, ()))
        )
        _emit(
            live_step_id,
            "role_retry_started",
            f"author team targeted retry started: {role.name}",
            role=role.name,
            error=error,
            turns_limit=retry_turns,
            status="running",
        )
        retried = execute_agent(
            retry_session,
            agent_name=role.name,
            instructions=role.instructions,
            author_tools=True,
            tool_policy=role.policy,
            task_input=_retry_role_input(
                role,
                contract_hash=contract_hash,
                base_revision=base_revision,
                error=error,
            ),
            turns_limit=retry_turns,
            workflow_name=f"{role.workflow_name}-targeted-retry",
            operation="authoring",
            deadline_at=budget.deadline_at,
            preserve_partial_on_error=True,
        )
        budget.observe(retried)
        if retried is None:
            budget.turns_used += retry_turns
        _emit_role_result(live_step_id, role.name, retried, retry=True)
        if retried:
            team_logs.extend(retried.logs)
        candidate_by_role[role.name] = _RoleCandidate(
            role=role,
            outcome=retried,
            base_revision=base_revision,
            contract_hash=contract_hash,
        )

    role_candidates = [candidate_by_role[role.name] for role in _IMPLEMENTATION_ROLES]
    merge = _merge_candidate_report(
        contract_files,
        role_candidates,
        base_revision=base_revision,
        contract_hash=contract_hash,
        contract=contract,
    )
    team_logs.extend(merge.logs)
    for role in _IMPLEMENTATION_ROLES:
        if role.name in merge.accepted_roles:
            _emit(
                live_step_id,
                "role_candidate_accepted",
                f"author team accepted candidate: {role.name}",
                role=role.name,
                status="done",
            )
        elif role.name in merge.candidate_errors:
            _emit(
                live_step_id,
                "role_candidate_rejected",
                f"author team rejected candidate: {role.name}",
                role=role.name,
                error=merge.candidate_errors[role.name],
                status="failed",
            )
        else:
            _emit(
                live_step_id,
                "role_candidate_deferred",
                f"author team deferred candidate: {role.name}",
                role=role.name,
                missing_dependencies=list(merge.blocked_roles.get(role.name, ())),
                status="blocked",
            )

    required_roles = {role.name for role in _IMPLEMENTATION_ROLES}

    missing_roles = sorted(required_roles - merge.accepted_roles)
    if missing_roles:
        _emit(
            live_step_id,
            "team_degraded",
            "author team proceeding to integration without accepted owners: "
            + ", ".join(missing_roles),
            reason="missing_required_roles",
            missing_roles=missing_roles,
            status="degraded",
        )
        team_logs.append(
            "author team degraded: integration must bridge missing owners "
            + ", ".join(missing_roles)
        )

    exhausted_before_integration = budget.exhausted_reasons()
    if exhausted_before_integration or budget.remaining_turns < 1:
        reasons = exhausted_before_integration or ["turns"]
        _emit(
            live_step_id,
            "team_budget_exhausted",
            "author team budget exhausted before integration: " + ", ".join(reasons),
            reasons=reasons,
            status="stopped",
        )
        return None

    integration_session = RepairSession.from_files(
        merge.files, live_step_id=live_step_id
    )
    seeded_changes = set(merge.accepted_paths) | orchestrator_changes
    integration_session.changed = set(seeded_changes)
    integration_session.log_lines = list(team_logs)
    integration_input = "\n\n".join(
        [
            "Integrate the accepted role candidates into the final playable project.",
            f"Base revision: {base_revision}",
            f"Contract hash: {contract_hash}",
            f"Immutable contract file: {_AUTHOR_CONTRACT_PATH}",
            f"Required evidence file: {_ACCEPTANCE_EVIDENCE_PATH}",
            "Accepted candidate files:\n"
            + "\n".join(f"- {path}" for path in sorted(merge.accepted_paths)),
            f"Compact brief:\n{json.dumps(_compact_brief(spec, design), ensure_ascii=False)}",
            "Evidence JSON schema: {\"contract_hash\":\"exact hash above\",\"requirements\":[{\"id\":\"exact contract id\",\"owner\":\"exact contract owner\",\"status\":\"implemented\",\"verification\":\"exact contract verification\",\"evidence\":[{\"path\":\"real source path\",\"symbols\":[\"assigned contract export used in this file\"]}]}]}. Each non-Integration requirement needs both its owner file and a runtime wiring file citing an assigned export.",
            "Begin by reading the immutable contract, PlayScene, main.ts, gameConfig.ts, and accepted candidate files in bounded batches. Wire through scenes/contracts/adapters only, write the evidence file, then run_checks.",
        ]
    )
    if missing_roles:
        gap_lines = []
        for role_name in missing_roles:
            assigned = [
                module
                for module in contract.modules
                if module.owner == role_name
            ]
            gap_lines.append(
                f"- {role_name} delivered nothing usable. Implement compact equivalents in src/composition/ or src/adapters/ and export: "
                + ", ".join(export for module in assigned for export in module.exports)
            )
        integration_input += (
            "\n\nROLE GAPS you must bridge yourself (mandatory):\n"
            + "\n".join(gap_lines)
        )
    if qa_feedback:
        integration_input += (
            "\n\nGameplay QA findings that must be resolved:\n"
            + "\n".join(f"- {item}" for item in qa_feedback)
        )
    integration_turns = budget.remaining_turns
    _emit(
        live_step_id,
        "role_started",
        "author team role started: IntegrationAgent",
        role="IntegrationAgent",
        turns_limit=integration_turns,
        status="running",
    )
    integrated = execute_agent(
        integration_session,
        agent_name="IntegrationAgent",
        instructions=_INTEGRATION_INSTRUCTIONS,
        author_tools=True,
        tool_policy=_INTEGRATION_POLICY,
        task_input=integration_input,
        turns_limit=integration_turns,
        workflow_name="gameweave-author-integration",
        operation="authoring",
        deadline_at=budget.deadline_at,
        preserve_partial_on_error=True,
    )
    budget.observe(integrated)
    if integrated is None:
        budget.turns_used += integration_turns
    _emit_role_result(live_step_id, "IntegrationAgent", integrated)
    # 集成是把作者产出接进玩法的唯一环节,又恰好是网关抖动的单点(c28261d1:
    # 流重试 3/3 耗尽后 21 个已接受的作者文件全部没接线,树摇丢弃,发布了兜底
    # 玩法)。传输层死亡时用全新会话整体重试一次——种子工作区重建自干净的
    # 合并结果,重放安全;预算/截止时间照常约束重试。
    if (
        (integrated is None or integrated.stop_reason == "stream_error")
        and budget.remaining_turns >= 2
        and not budget.expired
    ):
        retry_turns = budget.remaining_turns
        _emit(
            live_step_id,
            "role_retry",
            "integration agent hit a transport failure; retrying once with a fresh session",
            role="IntegrationAgent",
            turns_limit=retry_turns,
            status="running",
        )
        retry_session = RepairSession.from_files(merge.files, live_step_id=live_step_id)
        retry_session.changed = set(seeded_changes)
        retry_session.log_lines = list(team_logs)
        retried = execute_agent(
            retry_session,
            agent_name="IntegrationAgent",
            instructions=_INTEGRATION_INSTRUCTIONS,
            author_tools=True,
            tool_policy=_INTEGRATION_POLICY,
            task_input=integration_input,
            turns_limit=retry_turns,
            workflow_name="gameweave-author-integration",
            operation="authoring",
            deadline_at=budget.deadline_at,
            preserve_partial_on_error=True,
        )
        budget.observe(retried)
        if retried is None:
            budget.turns_used += retry_turns
        _emit_role_result(live_step_id, "IntegrationAgent", retried)

        def _wired_composition(outcome) -> bool:
            return bool(
                outcome
                and any(
                    _runtime_wiring_path(path)
                    for path in set(outcome.changed) - seeded_changes
                )
            )

        if retried is not None and (
            integrated is None
            or _wired_composition(retried)
            or not _wired_composition(integrated)
        ):
            integrated = retried
    if integrated is None:
        _emit(
            live_step_id,
            "team_failed",
            "author team integration agent unavailable; owner candidates were not published",
            reason="integration_unavailable",
            status="failed",
        )
        return None

    if not integrated.changed:
        return None
    integration_delta = set(integrated.changed) - seeded_changes
    composition_delta = {
        path for path in integration_delta if _runtime_wiring_path(path)
    }
    play_scene = next(
        (
            str(item.get("content") or "")
            for item in integrated.files
            if item.get("path") == "src/scenes/PlayScene.ts"
        ),
        "",
    )
    if not composition_delta or "GW_PLACEHOLDER_GAMEPLAY" in play_scene:
        integrated.checks_ok = False
        reason = (
            "integration did not modify any composition file"
            if not composition_delta
            else "integration left GW_PLACEHOLDER_GAMEPLAY in PlayScene"
        )
        line = f"author team incomplete: {reason}; outer build/gameplay repair remains required"
        integrated.logs.append(line)
        _emit(
            live_step_id,
            "integration_incomplete",
            line,
            phase="integration_incomplete",
            status="partial",
        )
    evidence_issues = _acceptance_evidence_issues(
        integrated.files, contract, contract_hash
    )
    if evidence_issues:
        integrated.checks_ok = False
        line = "author team acceptance evidence invalid: " + "; ".join(
            evidence_issues[:8]
        )
        integrated.logs.append(line)
        _emit(
            live_step_id,
            "integration_evidence_invalid",
            line,
            phase="integration_evidence",
            issues=evidence_issues[:20],
            status="partial",
        )
    integration_budget_exhausted = _is_budget_exhausted(integrated)
    team_done = bool(integrated.checks_ok and composition_delta and not evidence_issues)
    integrated.tokens = budget.tokens_used
    integrated.turns = budget.turns_used
    integrated.quality_state = "valid" if team_done else "unchecked"
    integrated.note = (
        (

            f"TEAM DONE: contract {contract_hash[:12]}, {len(merge.accepted_paths)} role file(s); "
            if team_done
            else f"TEAM PARTIAL: contract {contract_hash[:12]}; "
        )
        + integrated.note
    )[:500]
    _emit(
        live_step_id,
        "team_completed",
        (
            "author team completed"
            if team_done
            else "author team completed with outer repair required"
        ),
        contract_hash=contract_hash,
        accepted_roles=sorted(merge.accepted_roles),
        checks_ok=integrated.checks_ok,
        budget_exhausted=integration_budget_exhausted,
        turns_used=budget.turns_used,
        tokens_used=budget.tokens_used,
        changed_files=len(budget.changed_paths),
        status="done" if team_done else "partial",
    )
    return integrated
