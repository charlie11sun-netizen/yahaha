"""WinScript: the authored, machine-executable "how to win" contract artifact.

The Integration author derives ``src/contracts/WinScript.json`` from the frozen
design contract (tutorial steps + win_feasibility ledger): an ordered ``setup``
sequence plus condition→action ``rules`` in design-space canvas coordinates.
The QA sandbox replays it deterministically — no model in the loop — and the
game only passes the win-path check when its own rules layer emits
``Probe.status("won")``.

This module is the backend-side validator used at gate time. The sandbox owns
the authoritative parser (``sandbox/app/winscript.py``); a parity test in
``backend/tests/pipeline/test_win_simulation.py`` keeps the two aligned, so any
schema change must land in both.

Example artifact::

    {
      "sim_seconds": 300,
      "setup": [
        {"action": "pointer", "x": 240, "y": 520, "label": "place opening tower"},
        {"action": "wait", "seconds": 2}
      ],
      "rules": [
        {"label": "build when affordable",
         "when": {"stat": "gold", "op": "gte", "value": 120},
         "do": {"action": "pointer", "x": 300, "y": 520},
         "cooldown_s": 3, "max_times": 6},
        {"label": "start next wave",
         "when": {"probe": "window:open|wave-ready", "op": "gte", "value": 1},
         "do": {"action": "key", "key": "Space"}, "cooldown_s": 5}
      ]
    }
"""
from __future__ import annotations

import json
import re

WIN_SCRIPT_PATH = "src/contracts/WinScript.json"

MAX_SETUP_STEPS = 40
MAX_RULES = 24
MIN_SIM_SECONDS = 30
MAX_SIM_SECONDS = 900
_ALLOWED_OPS = ("gte", "lte", "eq")
_KEY_PATTERN = re.compile(
    r"^([A-Za-z0-9]|ArrowUp|ArrowDown|ArrowLeft|ArrowRight|Space|Enter|Escape|Shift|Control|Alt|Tab|Backspace)$"
)


def _check_number(value: object, label: str, lo: float, hi: float, errors: list[str]) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{label} must be a number")
    elif value < lo or value > hi:
        errors.append(f"{label} must be within [{lo}, {hi}]")


def _check_action(raw: object, label: str, errors: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append(f"{label} must be an object")
        return
    kind = raw.get("action")
    if kind == "pointer":
        _check_number(raw.get("x"), f"{label}.x", 0, 4096, errors)
        _check_number(raw.get("y"), f"{label}.y", 0, 4096, errors)
    elif kind == "key":
        if not _KEY_PATTERN.match(str(raw.get("key") or "")):
            errors.append(f"{label}.key is not an allowed key name")
        if raw.get("hold_ms") is not None:
            _check_number(raw.get("hold_ms"), f"{label}.hold_ms", 0, 2000, errors)
    elif kind == "wait":
        _check_number(raw.get("seconds", 1.0), f"{label}.seconds", 0.1, 60, errors)
    else:
        errors.append(f"{label}.action must be one of pointer/key/wait")


def _check_condition(raw: object, label: str, errors: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append(f"{label} must be an object")
        return
    if raw.get("always") is True:
        return
    selectors = [key for key in ("stat", "probe", "time") if key in raw]
    if len(selectors) != 1:
        errors.append(f"{label} needs exactly one of stat/probe/time/always")
        return
    if raw.get("op") not in _ALLOWED_OPS:
        errors.append(f"{label}.op must be one of {'/'.join(_ALLOWED_OPS)}")
    _check_number(raw.get("value"), f"{label}.value", -1e9, 1e9, errors)
    if selectors[0] != "time" and not str(raw.get(selectors[0]) or "").strip():
        errors.append(f"{label}.{selectors[0]} must be a non-empty name")


def validate_win_script(raw: object) -> list[str]:
    """Return validation errors for a decoded WinScript payload (empty = valid)."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return ["WinScript must be a JSON object"]
    if raw.get("sim_seconds") is not None:
        _check_number(raw.get("sim_seconds"), "sim_seconds", MIN_SIM_SECONDS, MAX_SIM_SECONDS, errors)
    setup = raw.get("setup") or []
    rules = raw.get("rules") or []
    if not isinstance(setup, list) or len(setup) > MAX_SETUP_STEPS:
        errors.append(f"setup must be a list of at most {MAX_SETUP_STEPS} actions")
        setup = []
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        errors.append(f"rules must be a list of at most {MAX_RULES} entries")
        rules = []
    if not setup and not rules:
        errors.append("WinScript needs at least one setup action or rule")
    for index, item in enumerate(setup):
        _check_action(item, f"setup[{index}]", errors)
    for index, item in enumerate(rules):
        if not isinstance(item, dict):
            errors.append(f"rules[{index}] must be an object")
            continue
        _check_condition(item.get("when"), f"rules[{index}].when", errors)
        _check_action(item.get("do"), f"rules[{index}].do", errors)
        if item.get("cooldown_s") is not None:
            _check_number(item.get("cooldown_s"), f"rules[{index}].cooldown_s", 0, 120, errors)
        if item.get("max_times") is not None:
            _check_number(item.get("max_times"), f"rules[{index}].max_times", 1, 200, errors)
    return errors


def extract_win_script(source_files: list[dict]) -> tuple[dict | None, list[str]]:
    """Find and decode WinScript.json from project source files.

    Returns (payload, errors). (None, []) means the artifact simply is not
    there — adoption is prompt-driven and old tasks stay silent.
    """
    raw = next(
        (
            item.get("content")
            for item in source_files
            if str(item.get("path") or "") == WIN_SCRIPT_PATH
        ),
        None,
    )
    if raw is None:
        return None, []
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        return None, [f"WinScript.json is not valid JSON: {str(exc)[:120]}"]
    errors = validate_win_script(payload)
    return (payload if not errors else None), errors
