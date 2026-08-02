"""Deterministic WinScript interpreter for the win-path simulation.

The WinScript is an authored "how to win" artifact (src/contracts/WinScript.json
in the generated project). The sandbox executes it with NO model in the loop:
the same bundle and script must always produce the same verdict, so a failed
run is replayable evidence, not an opinion.

Pure functions only — no Playwright imports. The driver in ``main.py`` owns the
page; this module owns parsing and the per-tick decision:

* ``parse_script`` is the authoritative validator (the backend ships a mirror
  for gate-time checks; a parity test in backend/tests keeps them aligned).
* ``next_action`` fires the ordered ``setup`` actions one per tick, then the
  first ``rules`` entry whose condition, cooldown and max_times allow it.
* Conditions read the gauges published by ``Probe.stat`` (``__GW_STATS__``),
  the counters published by ``Probe.emit`` (``__GW_PROBES__.counts``), or the
  virtual clock.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_SETUP_STEPS = 40
MAX_RULES = 24
MIN_SIM_SECONDS = 30
MAX_SIM_SECONDS = 900
_ALLOWED_OPS = ("gte", "lte", "eq")
_KEY_PATTERN = re.compile(
    r"^([A-Za-z0-9]|ArrowUp|ArrowDown|ArrowLeft|ArrowRight|Space|Enter|Escape|Shift|Control|Alt|Tab|Backspace)$"
)


class WinScriptError(ValueError):
    """Raised when a WinScript payload fails validation."""


@dataclass
class SimProgress:
    """Mutable interpreter state carried across decision ticks."""

    setup_index: int = 0
    fired_counts: dict[int, int] = field(default_factory=dict)
    last_fired_s: dict[int, float] = field(default_factory=dict)


def _require_number(value: object, label: str, lo: float, hi: float, errors: list[str]) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{label} must be a number")
        return lo
    if value < lo or value > hi:
        errors.append(f"{label} must be within [{lo}, {hi}]")
        return min(max(float(value), lo), hi)
    return float(value)


def _parse_action(raw: object, label: str, errors: list[str]) -> dict:
    if not isinstance(raw, dict):
        errors.append(f"{label} must be an object")
        return {"action": "wait", "seconds": 1.0}
    kind = raw.get("action")
    action: dict = {"action": kind}
    if kind == "pointer":
        action["x"] = _require_number(raw.get("x"), f"{label}.x", 0, 4096, errors)
        action["y"] = _require_number(raw.get("y"), f"{label}.y", 0, 4096, errors)
    elif kind == "key":
        key = str(raw.get("key") or "")
        if not _KEY_PATTERN.match(key):
            errors.append(f"{label}.key '{key[:24]}' is not an allowed key name")
            key = "Space"
        action["key"] = key
        hold = raw.get("hold_ms", 0)
        action["hold_ms"] = int(_require_number(hold, f"{label}.hold_ms", 0, 2000, errors))
    elif kind == "wait":
        action["seconds"] = _require_number(raw.get("seconds", 1.0), f"{label}.seconds", 0.1, 60, errors)
    else:
        errors.append(f"{label}.action must be one of pointer/key/wait")
        return {"action": "wait", "seconds": 1.0}
    if raw.get("label") is not None:
        action["label"] = str(raw.get("label"))[:80]
    return action


def _parse_condition(raw: object, label: str, errors: list[str]) -> dict:
    if not isinstance(raw, dict):
        errors.append(f"{label} must be an object")
        return {"always": True}
    if raw.get("always") is True:
        return {"always": True}
    selectors = [key for key in ("stat", "probe", "time") if key in raw]
    if len(selectors) != 1:
        errors.append(f"{label} needs exactly one of stat/probe/time/always")
        return {"always": True}
    op = raw.get("op")
    if op not in _ALLOWED_OPS:
        errors.append(f"{label}.op must be one of {'/'.join(_ALLOWED_OPS)}")
        op = "gte"
    value = _require_number(raw.get("value"), f"{label}.value", -1e9, 1e9, errors)
    selector = selectors[0]
    condition: dict = {"op": op, "value": value}
    if selector == "time":
        condition["time"] = True
    else:
        subject = str(raw.get(selector) or "").strip()[:120]
        if not subject:
            errors.append(f"{label}.{selector} must be a non-empty name")
        condition[selector] = subject
    return condition


def parse_script(raw: object) -> tuple[dict, list[str]]:
    """Validate + normalize a WinScript payload. Returns (script, errors)."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return {}, ["WinScript must be a JSON object"]
    sim_seconds = _require_number(
        raw.get("sim_seconds", 300), "sim_seconds", MIN_SIM_SECONDS, MAX_SIM_SECONDS, errors
    )
    setup_raw = raw.get("setup") or []
    rules_raw = raw.get("rules") or []
    if not isinstance(setup_raw, list) or len(setup_raw) > MAX_SETUP_STEPS:
        errors.append(f"setup must be a list of at most {MAX_SETUP_STEPS} actions")
        setup_raw = setup_raw[:MAX_SETUP_STEPS] if isinstance(setup_raw, list) else []
    if not isinstance(rules_raw, list) or len(rules_raw) > MAX_RULES:
        errors.append(f"rules must be a list of at most {MAX_RULES} entries")
        rules_raw = rules_raw[:MAX_RULES] if isinstance(rules_raw, list) else []
    if not setup_raw and not rules_raw:
        errors.append("WinScript needs at least one setup action or rule")

    setup = [
        _parse_action(item, f"setup[{index}]", errors) for index, item in enumerate(setup_raw)
    ]
    rules = []
    for index, item in enumerate(rules_raw):
        if not isinstance(item, dict):
            errors.append(f"rules[{index}] must be an object")
            continue
        rule = {
            "when": _parse_condition(item.get("when"), f"rules[{index}].when", errors),
            "do": _parse_action(item.get("do"), f"rules[{index}].do", errors),
            "cooldown_s": _require_number(
                item.get("cooldown_s", 2.0), f"rules[{index}].cooldown_s", 0, 120, errors
            ),
            "max_times": int(
                _require_number(item.get("max_times", 40), f"rules[{index}].max_times", 1, 200, errors)
            ),
        }
        if item.get("label") is not None:
            rule["label"] = str(item.get("label"))[:80]
        rules.append(rule)

    script = {"version": 1, "sim_seconds": sim_seconds, "setup": setup, "rules": rules}
    return script, errors


def condition_met(
    condition: dict, stats: dict, probes: dict, sim_seconds: float
) -> bool:
    if condition.get("always"):
        return True
    if condition.get("time"):
        observed: float | None = sim_seconds
    elif "stat" in condition:
        raw = stats.get(condition["stat"])
        observed = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    else:
        raw = probes.get(condition.get("probe", ""), 0)
        observed = float(raw) if isinstance(raw, (int, float)) else 0.0
    if observed is None:
        # An unpublished stat can never satisfy a condition; the driver surfaces
        # missing gauges separately so authors learn to wire Probe.stat.
        return False
    op = condition.get("op", "gte")
    value = float(condition.get("value", 0))
    if op == "gte":
        return observed >= value
    if op == "lte":
        return observed <= value
    return abs(observed - value) < 1e-9


def next_action(
    script: dict,
    stats: dict,
    probes: dict,
    sim_seconds: float,
    progress: SimProgress,
) -> tuple[dict | None, str]:
    """Pick at most one action per decision tick. Returns (action, source_label)."""
    setup = script.get("setup") or []
    if progress.setup_index < len(setup):
        action = setup[progress.setup_index]
        progress.setup_index += 1
        return action, f"setup[{progress.setup_index - 1}]"
    for index, rule in enumerate(script.get("rules") or []):
        if progress.fired_counts.get(index, 0) >= int(rule.get("max_times", 40)):
            continue
        last = progress.last_fired_s.get(index)
        if last is not None and sim_seconds - last < float(rule.get("cooldown_s", 2.0)):
            continue
        if not condition_met(rule.get("when") or {}, stats, probes, sim_seconds):
            continue
        progress.fired_counts[index] = progress.fired_counts.get(index, 0) + 1
        progress.last_fired_s[index] = sim_seconds
        return rule.get("do"), rule.get("label") or f"rule[{index}]"
    return None, ""


def missing_stats(script: dict, stats: dict) -> list[str]:
    """Stats referenced by conditions that the game never published."""
    referenced = {
        rule["when"]["stat"]
        for rule in script.get("rules") or []
        if isinstance(rule.get("when"), dict) and "stat" in rule["when"]
    }
    return sorted(name for name in referenced if name not in stats)


def terminal_verdict(probes: dict) -> str | None:
    if int(probes.get("game:status|won", 0) or 0) > 0:
        return "won"
    if int(probes.get("game:status|lost", 0) or 0) > 0:
        return "lost"
    return None
