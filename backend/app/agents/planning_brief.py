"""Pure brief, mechanic, and content planning helpers."""

import re

from app.agents.nodes_common import _ARCHETYPES, _clip, _has_any, bundles


def _prompt_cues(prompt: str) -> list[str]:
    stop = {
        "make",
        "game",
        "with",
        "where",
        "that",
        "this",
        "into",
        "from",
        "using",
        "player",
        "players",
        "collect",
        "avoid",
        "survive",
        "seconds",
        "the",
        "and",
        "for",
        "you",
    }
    cues: list[str] = []
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", prompt.lower()):
        if token in stop or token in cues:
            continue
        cues.append(token)
        if len(cues) == 6:
            break
    return cues



def _brief_keywords(prompt: str, spec: dict) -> list[str]:
    cues = _prompt_cues(prompt)
    for tag in spec.get("tags") or []:
        tag = str(tag).lower()
        if tag and tag not in cues:
            cues.append(tag)
    for word in re.findall(r"[\u4e00-\u9fff]{2,6}", prompt):
        if word not in cues:
            cues.append(word)
    return cues[:8]


def _heuristic_brief(prompt: str, spec: dict) -> dict:
    genre = str(spec.get("genre") or "arcade").lower()
    title = spec.get("title") or bundles.title_from(prompt)
    keywords = _brief_keywords(prompt, spec)
    if genre == "puzzle":
        verbs = ["inspect", "rotate", "connect", "optimize"]
        mechanics = ["visible solution path", "move-efficient scoring", "timed pressure"]
        fantasy = f"repair a living circuit in {title}"
    elif genre == "runner":
        verbs = ["switch lanes", "read patterns", "collect boosts", "recover from hits"]
        mechanics = ["lane telegraphing", "bonus chains", "forgiving lives", "late-round pressure"]
        fantasy = f"pilot the hero through a fast readable course in {title}"
    else:
        verbs = ["navigate", "collect", "bait hazards", "chain rewards"]
        mechanics = ["combo collection", "soft homing hazards", "temporary powerups", "safe opening"]
        fantasy = f"guide the hero through a compact arena in {title}"
    return {
        "player_fantasy": fantasy,
        "objective": spec.get("win_condition") or "reach the score goal before the round ends",
        "core_verbs": verbs,
        "mechanic_requirements": mechanics,
        "reward_loop": "small rewards every few seconds, larger payoff for chaining clean play",
        "difficulty_beats": ["0-10s tutorial-safe opening", "10-35s readable pattern pressure", "35s+ mastery challenge"],
        "feedback": ["clear hit flash", "score pop", "life/timer HUD", "restart affordance"],
        "keywords": keywords,
        "minimum_content": {"hazards": 2, "rewards": 3, "powerups": 2, "waves": 4},
    }


def _coerce_brief(data: dict, prompt: str, spec: dict) -> dict:
    base = _heuristic_brief(prompt, spec)
    if isinstance(data, dict):
        for key in ("player_fantasy", "objective", "reward_loop"):
            if data.get(key):
                base[key] = str(data[key])[:240]
        for key in ("core_verbs", "mechanic_requirements", "difficulty_beats", "feedback", "keywords"):
            if isinstance(data.get(key), list) and data[key]:
                base[key] = [str(item)[:80] for item in data[key]][:8]
        if isinstance(data.get("minimum_content"), dict):
            base["minimum_content"].update({k: int(v) for k, v in data["minimum_content"].items() if str(v).isdigit()})
    return base



def _heuristic_mechanic_plan(spec: dict, brief: dict, prompt: str) -> dict:
    genre = str(spec.get("genre") or "").lower()
    text = " ".join([prompt, " ".join(brief.get("mechanic_requirements") or []), " ".join(brief.get("keywords") or [])]).lower()
    if genre == "shooter" or _has_any(text, ["shoot", "bullet", "shmup", "raiden", "战机", "雷霆", "射击", "弹幕", "飞机大战", "打飞机"]):
        archetype_hint = "vertical_shooter"
        secondary = "spread / laser power-ups and a screen-clearing bomb"
        enemies = [{"name": "swarm fighter", "behavior": "weaves downward firing aimed shots"}, {"name": "gunship", "behavior": "strafes the top and lays bullet spreads"}, {"name": "boss carrier", "behavior": "multi-phase, telegraphed barrages"}]
        rewards = [{"name": "power chip", "effect": "upgrades the main gun"}, {"name": "medal", "effect": "score chain"}]
        powerups = [{"name": "spread shot", "effect": "wider fire arc"}, {"name": "shield", "effect": "absorbs one hit"}, {"name": "wingman", "effect": "adds a side gun"}]
    elif genre == "puzzle" or _has_any(text, ["connect", "circuit", "puzzle", "logic"]):
        archetype_hint = "logic_grid"
        secondary = "route preview pulses"
        enemies = [{"name": "locked node", "behavior": "blocks inefficient routes"}, {"name": "timer drain", "behavior": "forces decisive rotations"}]
        rewards = [{"name": "clean link", "effect": "score bonus"}, {"name": "few moves", "effect": "efficiency bonus"}]
        powerups = [{"name": "hint pulse", "effect": "briefly shows connected tiles"}, {"name": "time crystal", "effect": "adds seconds"}]
    elif genre == "runner" or _has_any(text, ["runner", "lane", "dash", "dodge", "race"]):
        archetype_hint = "lane_runner"
        secondary = "one-lane dash recovery"
        enemies = [{"name": "drone gate", "behavior": "blocks one lane"}, {"name": "sweeper", "behavior": "encourages early lane change"}]
        rewards = [{"name": "energy orb", "effect": "score chain"}, {"name": "route badge", "effect": "lane streak bonus"}]
        powerups = [{"name": "phase dash", "effect": "forgive the next hit"}, {"name": "magnet trail", "effect": "pulls nearby bonuses"}]
    else:
        archetype_hint = "topdown_collect"
        secondary = "short shield after clean combo"
        enemies = [{"name": "drifter", "behavior": "soft-homes toward the player"}, {"name": "sentinel", "behavior": "crosses the arena slowly"}]
        rewards = [{"name": "glow shard", "effect": "combo score"}, {"name": "cache", "effect": "larger timed bonus"}]
        powerups = [{"name": "shield bloom", "effect": "temporary invulnerability"}, {"name": "slow field", "effect": "slows hazards"}, {"name": "spark dash", "effect": "quick reposition"}]
    return {
        "archetype_hint": archetype_hint,
        "primary_action": _clip((brief.get("core_verbs") or ["move"])[0], 60),
        "secondary_action": secondary,
        "risk_model": "mistakes cost lives, but the first seconds are safe and recovery is possible",
        "reward_model": brief.get("reward_loop") or "chain rewards for score",
        "enemy_behaviors": enemies,
        "reward_items": rewards,
        "powerups": powerups,
        "feedback": brief.get("feedback") or ["score pop", "hit flash", "restart"],
        "skill_tests": brief.get("difficulty_beats") or [],
    }


def _coerce_mechanic_plan(data: dict, spec: dict, brief: dict, prompt: str) -> dict:
    base = _heuristic_mechanic_plan(spec, brief, prompt)
    if isinstance(data, dict):
        for key in ("primary_action", "secondary_action", "signature_twist", "risk_model", "reward_model"):
            if data.get(key):
                base[key] = str(data[key])[:180]
        for key in ("enemy_behaviors", "reward_items", "powerups"):
            if isinstance(data.get(key), list) and data[key]:
                base[key] = [item if isinstance(item, dict) else {"name": str(item), "effect": "gameplay variation"} for item in data[key]][:5]
        if isinstance(data.get("feedback"), list) and data["feedback"]:
            base["feedback"] = [str(item)[:80] for item in data["feedback"]][:6]
    genre = str(spec.get("genre") or "").strip().lower()
    expected = {
        "shooter": "vertical_shooter",
        "puzzle": "logic_grid",
        "runner": "lane_runner",
        "collector": "topdown_collect",
    }.get(genre)
    candidate = str((data or {}).get("archetype_hint") or "")
    if genre and genre != "arcade" and expected is None:
        # Native genres (platformer, roguelite, tactics, rhythm, simulation...)
        # must never be squeezed into one of the four historical demo templates.
        base["archetype_hint"] = None
    elif expected is not None:
        base["archetype_hint"] = expected
    elif candidate in _ARCHETYPES:
        base["archetype_hint"] = candidate
    elif base.get("archetype_hint") not in _ARCHETYPES:
        base["archetype_hint"] = None
    return base



def _content_plan(archetype: str, spec: dict, brief: dict, mechanics: dict) -> dict:
    enemy_names = [str(item.get("name", "hazard"))[:28] for item in mechanics.get("enemy_behaviors") or []] or ["hazard", "blocker"]
    reward_names = [str(item.get("name", "reward"))[:28] for item in mechanics.get("reward_items") or []] or ["reward", "bonus"]
    powerups = [str(item.get("name", "boost"))[:28] for item in mechanics.get("powerups") or []] or ["shield", "slow field"]
    beats = brief.get("difficulty_beats") or ["opening", "pressure", "mastery"]
    if archetype not in _ARCHETYPES:
        waves = [
            {"time": 0, "note": beats[0]},
            {"time": 1, "note": beats[min(1, len(beats) - 1)]},
            {"time": 2, "note": beats[-1]},
        ]
        verbs = [str(item) for item in (brief.get("core_verbs") or [])[:4]]
        tutorial = "teach the authored core verbs in a safe opening: " + (", ".join(verbs) or "move, act, and recover")
        mode = "design_driven"
    elif archetype == "logic_grid":
        waves = [
            {"time": 0, "pressure": "learn", "note": beats[0]},
            {"time": 18, "pressure": "optimize", "note": beats[min(1, len(beats) - 1)]},
            {"time": 40, "pressure": "rush", "note": beats[-1]},
        ]
        tutorial = "click tiles to rotate the live route from IN to OUT"
        mode = "legacy_family"
    elif archetype == "lane_runner":
        waves = [
            {"time": 0, "hazards": 1, "reward": 1, "note": beats[0]},
            {"time": 12, "hazards": 2, "reward": 1, "note": beats[min(1, len(beats) - 1)]},
            {"time": 28, "hazards": 3, "reward": 2, "note": "introduce paired lane reads"},
            {"time": 45, "hazards": 4, "reward": 2, "note": beats[-1]},
        ]
        tutorial = "tap left or right to switch lanes; chase bonuses, not every gap"
        mode = "legacy_family"
    else:
        waves = [
            {"time": 0, "hazards": 1, "reward": 2, "note": beats[0]},
            {"time": 14, "hazards": 2, "reward": 2, "note": beats[min(1, len(beats) - 1)]},
            {"time": 32, "hazards": 3, "reward": 3, "note": "use powerups to reset danger"},
            {"time": 50, "hazards": 4, "reward": 3, "note": beats[-1]},
        ]
        tutorial = "move smoothly, collect chains, use powerups when the arena tightens"
        mode = "legacy_family"
    return {
        "mode": mode,
        "tutorial": tutorial,
        "waves": waves,
        "hazard_names": enemy_names[:4],
        "reward_names": reward_names[:4],
        "powerups": powerups[:4],
        "pacing": beats,
        "mechanic_label": mechanics.get("secondary_action") or mechanics.get("primary_action") or "core loop",
    }




__all__ = [
    "_prompt_cues",
    "_brief_keywords",
    "_heuristic_brief",
    "_coerce_brief",
    "_heuristic_mechanic_plan",
    "_coerce_mechanic_plan",
    "_content_plan",
]
