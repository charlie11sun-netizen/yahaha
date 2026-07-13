"""Formatting helpers for planning-agent progress logs."""

import re

from app.agents.nodes_common import _clip


def _controls_line(controls: dict) -> str:
    keys = controls.get("keyboard") if isinstance(controls.get("keyboard"), list) else []
    pointer = controls.get("pointer") if isinstance(controls.get("pointer"), list) else []
    parts = []
    if keys:
        parts.append("keyboard=" + ", ".join(str(key) for key in keys[:4]))
    if pointer:
        parts.append("pointer=" + ", ".join(str(item) for item in pointer[:3]))
    if controls.get("hint"):
        parts.append("hint=" + _clip(controls.get("hint"), 70))
    return "; ".join(parts) if parts else "default keyboard + pointer controls"


def _spec_log_lines(spec: dict, source: str) -> list[str]:
    controls = spec.get("controls") if isinstance(spec.get("controls"), dict) else {}
    tags = ", ".join(str(tag) for tag in (spec.get("tags") or [])[:5]) or "none"
    return [
        f"source: {source}",
        f"title: {_clip(spec.get('title'), 80)}",
        f"genre/theme/runtime: {spec.get('genre', 'arcade')} / {spec.get('theme', 'retro')} / {spec.get('target_runtime', 'phaser-vite')}",
        f"core loop: {_clip(spec.get('core_loop'), 120)}",
        f"win/lose: {spec.get('win_condition', 'reach_target_score')} / {spec.get('lose_condition', 'timer_or_lives_depleted')}",
        f"controls: {_controls_line(controls)}",
        f"tags: {tags}",
    ]


def _entity_line(entity: dict) -> str:
    name = entity.get("name", "?")
    entity_type = entity.get("type", "?")
    movement = entity.get("movement") or entity.get("spawn") or entity.get("behavior") or "static"
    return f"{name}({entity_type}, {movement})"


def _design_log_lines(design: dict) -> list[str]:
    screen = design.get("screen") if isinstance(design.get("screen"), dict) else {}
    entities = design.get("entities") if isinstance(design.get("entities"), list) else []
    rules = design.get("rules") if isinstance(design.get("rules"), dict) else {}
    balance = design.get("balance") if isinstance(design.get("balance"), dict) else {}
    entity_text = ", ".join(_entity_line(entity) for entity in entities[:8]) or "none"
    rule_bits = []
    for key in ("collision_player_hazard", "collision_player_star", "connect_left_to_right", "survive_seconds"):
        if key in rules:
            rule_bits.append(f"{key}={rules[key]}")
    lines = [
        f"archetype: {design.get('archetype', 'unknown')}",
        f"screen: {screen.get('width', 1152)}x{screen.get('height', 768)} Phaser",
        f"entities: {entity_text}",
        "rules: " + (", ".join(str(bit) for bit in rule_bits) or "default game loop"),
    ]
    if balance:
        lines.append(
            "balance: "
            f"duration={balance.get('round_seconds')}s, target={balance.get('target_score')}, "
            f"lives={balance.get('lives')}, hazard_spawn={balance.get('hazard_spawn_ms')}ms"
        )
    return lines


def _asset_log_lines(uploaded: list[dict], manifest: dict, spec: dict) -> list[str]:
    lines = [f"uploaded references loaded: {len(uploaded)}"]
    for asset in uploaded[:4]:
        lines.append(f"reference: {asset.get('key')} ({asset.get('type', 'file')})")
    if len(uploaded) > 4:
        lines.append(f"reference overflow: {len(uploaded) - 4} additional asset(s)")
    lines.append(f"cover strategy: theme={spec.get('theme', 'retro')} -> {manifest.get('cover')}")
    lines.append(f"asset manifest entries: cover + {len(uploaded)} uploaded reference(s)")
    return lines



def _brief_log_lines(brief: dict, source: str) -> list[str]:
    return [
        f"source: {source}",
        f"player fantasy: {_clip(brief.get('player_fantasy'), 120)}",
        f"objective: {_clip(brief.get('objective'), 120)}",
        "core verbs: " + ", ".join(brief.get("core_verbs") or []),
        "mechanic requirements: " + ", ".join(brief.get("mechanic_requirements") or []),
        "difficulty beats: " + " / ".join(brief.get("difficulty_beats") or []),
    ]



def _mechanic_log_lines(plan: dict, source: str) -> list[str]:
    enemies = ", ".join(str(item.get("name", "?")) for item in plan.get("enemy_behaviors") or [])
    rewards = ", ".join(str(item.get("name", "?")) for item in plan.get("reward_items") or [])
    powerups = ", ".join(str(item.get("name", "?")) for item in plan.get("powerups") or [])
    return [
        f"source: {source}",
        f"archetype hint: {plan.get('archetype_hint')}",
        f"primary/secondary: {plan.get('primary_action')} / {plan.get('secondary_action')}",
        f"risk model: {_clip(plan.get('risk_model'), 120)}",
        f"reward model: {_clip(plan.get('reward_model'), 120)}",
        f"enemy behaviors: {enemies}",
        f"rewards/powerups: {rewards} / {powerups}",
    ]



def _content_log_lines(plan: dict) -> list[str]:
    return [
        f"tutorial: {_clip(plan.get('tutorial'), 120)}",
        "waves: " + "; ".join(f"{w.get('time')}s {w.get('note')}" for w in plan.get("waves", [])[:5]),
        "hazards: " + ", ".join(plan.get("hazard_names") or []),
        "rewards: " + ", ".join(plan.get("reward_names") or []),
        "powerups: " + ", ".join(plan.get("powerups") or []),
        f"mechanic label: {plan.get('mechanic_label')}",
    ]



def _balance_log_lines(archetype: str, balance: dict) -> list[str]:
    qa = balance.get("qa") if isinstance(balance.get("qa"), dict) else {}
    return [
        f"selected playable archetype: {archetype}",
        f"round target: {balance.get('target_score')} points in {balance.get('round_seconds')}s",
        f"player/hazard: speed={balance.get('player_speed')} / {balance.get('hazard_speed')}, lives={balance.get('lives')}",
        f"spawn budget: hazard every {balance.get('hazard_spawn_ms')}ms, collectible every {balance.get('collectible_spawn_ms')}ms, max hazards={balance.get('max_hazards')}",
        "QA thresholds: " + (", ".join(f"{key}={value}" for key, value in qa.items()) or "default"),
    ]



__all__ = [
    "_controls_line",
    "_spec_log_lines",
    "_entity_line",
    "_design_log_lines",
    "_asset_log_lines",
    "_brief_log_lines",
    "_mechanic_log_lines",
    "_content_log_lines",
    "_balance_log_lines",
]
