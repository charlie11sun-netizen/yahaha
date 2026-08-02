import pytest

from app.agents.planning_routing import _balance_plan, _merge_balance_into_design


_ACTION_ONLY_FIELDS = {
    "round_seconds",
    "target_score",
    "lives",
    "player_speed",
    "hazard_speed",
    "hazard_spawn_ms",
    "collectible_speed",
    "collectible_spawn_ms",
    "max_hazards",
    "lanes",
}


@pytest.mark.parametrize(
    ("archetype", "spec", "prompt", "timing_model"),
    [
        ("logic_grid", {"genre": "puzzle"}, "connect the circuit", "discrete"),
        ("strategy", {"genre": "strategy"}, "manage a colony", "discrete"),
        (
            "turn_based_tactics",
            {"genre": "turn-based tactics"},
            "command a squad one turn at a time",
            "turn_based",
        ),
    ],
)
def test_decision_driven_genres_do_not_receive_action_balance_fields(
    archetype, spec, prompt, timing_model
):
    balance = _balance_plan(archetype, spec, prompt)
    merged = _merge_balance_into_design({"rules": {}}, archetype, balance)

    assert balance["timing_model"] == timing_model
    assert balance["decision_model"]
    assert _ACTION_ONLY_FIELDS.isdisjoint(balance)
    assert "survive_seconds" not in merged["rules"]


def test_topdown_action_balance_defaults_remain_unchanged():
    balance = _balance_plan("topdown_collect", {"genre": "collector"}, "collect gems")
    merged = _merge_balance_into_design({"rules": {}}, "topdown_collect", balance)

    assert balance == {
        "round_seconds": 65,
        "target_score": 170,
        "lives": 4,
        "player_speed": 330,
        "hazard_speed": 92,
        "hazard_spawn_ms": 1750,
        "collectible_speed": 80,
        "collectible_spawn_ms": 720,
        "max_hazards": 6,
        "lanes": 3,
        "qa": {
            "min_reaction_ms": 1200,
            "min_player_to_hazard_ratio": 2.6,
            "max_obstacle_density": 6.5,
        },
    }
    assert merged["rules"]["survive_seconds"] == 65
