"""Genre-agnostic mechanic geometry, probing, and handoff regressions."""

import pytest

from app.agents import (
    author_contract,
    author_prompts,
    design_contract,
    prompts,
    validation_nodes,
)
from app.agents.planning_spec import _coerce_design
from app.agents.repair import _classify_gameplay_failure
from app.services.phaser_projects import create_modular_phaser_project


def _source(content: str) -> list[dict]:
    return [{"path": "src/scenes/PlayScene.ts", "content": content}]


def test_center_crossing_plus_action_labels_fails_geometry_gate():
    bad = """
class PlayScene {
  private resolveCrossings() {
    for (const actor of this.actors) {
      if (actor.sprite.x > this.player.x + 10) continue;
      if (actor.kind === "jumpObstacle") this.rules.collideObstacle("jump");
      else if (actor.kind === "slideObstacle") this.rules.collideObstacle("slide");
      actor.resolved = true;
    }
  }
}
"""

    issues = validation_nodes._spatial_interaction_fidelity_issues(_source(bad))

    assert len(issues) == 1
    assert "center-line crossing" in issues[0]
    assert "actor and target geometry" in issues[0]
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable == issues


def test_bounds_intersection_satisfies_geometry_gate():
    good = """
class PlayScene {
  private resolveCrossings() {
    for (const actor of this.actors) {
      if (actor.sprite.x > this.player.x + 10) continue;
      const touches = Phaser.Geom.Intersects.RectangleToRectangle(
        actor.sprite.getBounds(),
        this.player.getBounds(),
      );
      if (!touches) continue;
      if (actor.kind === "jumpObstacle") this.rules.collideObstacle("jump");
      else if (actor.kind === "slideObstacle") this.rules.collideObstacle("slide");
    }
  }
}
"""

    assert validation_nodes._spatial_interaction_fidelity_issues(_source(good)) == []


def test_interaction_profiles_survive_planning_and_scaffold_handoff():
    profile = {
        "id": "low_bar",
        "required_action": "jump",
        "visible_envelope": {"width": 48, "height": 42},
        "anchor": "floor",
        "interaction_envelope": {"width": 44, "height": 38},
        "clearance_or_timing_window": {"seconds": 0.45},
        "feasibility": "jump arc clears target height and width with 20% margin",
    }

    design = _coerce_design({"interaction_profiles": [profile]}, {})
    assert design["interaction_profiles"] == [profile]

    project = {
        str(item["path"]): str(item.get("content") or "")
        for item in create_modular_phaser_project({}, design)
    }
    config = project["src/config/gameConfig.ts"]
    assert '"interactionProfiles": [' in config
    assert '"required_action": "jump"' in config
    assert "interactionProfiles: Array<Record<string, unknown>>" in config
    probe = project["src/systems/Probe.ts"]
    assert "window(id: string" in probe
    assert "despawn(category: string" in probe

    frozen = design_contract.compile_design_contract(
        {"title": "Runner", "genre": "runner"},
        design,
    )
    assert any(system.id == "interaction-fidelity" for system in frozen.systems)
    assert any(
        requirement.id == "REQ-INTERACTION-001"
        for requirement in frozen.requirements
    )
    action_acceptance = next(
        item
        for item in frozen.acceptance_tests
        if item.id == "AT-INTERACTION-001"
    )
    assert "Probe.action" in action_acceptance.verification
    assert "outcome:low_bar:success" in action_acceptance.runtime_evidence


def test_contract_rejects_different_actions_with_identical_envelopes():
    shared = {
        "visible_envelope": {"width": 50, "height": 40},
        "anchor": "floor",
        "interaction_envelope": {"width": 46, "height": 36},
        "clearance_or_timing_window": {"seconds": 0.4},
        "feasibility": "subject clears target with 20% margin",
    }
    design = {
        "interaction_profiles": [
            {"id": "jump_target", "required_action": "jump", **shared},
            {"id": "slide_target", "required_action": "slide", **shared},
        ]
    }

    with pytest.raises(
        design_contract.ContractCompileError,
        match="mechanically distinct interaction profiles share",
    ):
        design_contract.compile_design_contract(
            {"title": "Bad Runner", "genre": "runner"},
            design,
        )


def test_author_and_planning_prompts_require_per_action_geometry_and_outcomes():
    assert "interaction profile" in prompts.PLANNING_SHARED_CACHE_PREFIX
    assert "input semantics" in prompts.PLANNING_SHARED_CACHE_PREFIX
    assert "same stable entity id" in prompts.PLANNING_SHARED_CACHE_PREFIX
    assert "production UI" in prompts.PLANNING_SHARED_CACHE_PREFIX
    assert "center-point crossing plus a posture/kind string" in (
        author_prompts._DESIGN_CONTRACT_INSTRUCTIONS
    )
    assert "Probe.action" in author_prompts._SCAFFOLD_KIT_CHEATSHEET
    assert "Probe.window" in author_prompts._SCAFFOLD_KIT_CHEATSHEET
    assert "Probe.despawn" in author_prompts._SCAFFOLD_KIT_CHEATSHEET
    assert "Probe.outcome" in author_prompts._INTEGRATION_INSTRUCTIONS
    assert "same logical tick" in author_prompts._INTEGRATION_INSTRUCTIONS
    assert "one generic \"primary action exercised\" row" in (
        author_prompts._INTEGRATION_INSTRUCTIONS
    )


def test_fallback_author_contract_keeps_per_action_acceptance():
    design = {
        "interaction_profiles": [
            {"id": "low_bar", "required_action": "jump"},
            {"id": "high_bar", "required_action": "slide"},
        ]
    }

    contract = author_contract._fallback_contract({"genre": "runner"}, design)
    interactions = [
        item
        for item in contract["acceptance"]
        if item["id"].startswith("REQ-INTERACTION-")
    ]

    assert [item["id"] for item in interactions] == [
        "REQ-INTERACTION-01",
        "REQ-INTERACTION-02",
    ]
    assert "jump" in interactions[0]["verification"]
    assert "Probe.action" in interactions[0]["verification"]
    assert "slide" in interactions[1]["observable"]

    model_contract_without_profiles = author_contract._fallback_contract(
        {"genre": "runner"}, {}
    )
    repaired, fixes = author_contract._repair_contract(
        model_contract_without_profiles,
        {"genre": "runner"},
        design,
    )
    repaired_ids = {item["id"] for item in repaired["acceptance"]}
    assert {"REQ-INTERACTION-01", "REQ-INTERACTION-02"} <= repaired_ids
    assert any("injected mandatory acceptance REQ-INTERACTION" in item for item in fixes)


def test_runtime_debug_like_player_copy_is_release_blocking():
    issues = validation_nodes._runtime_debug_ui_issues(
        _source(
            """
class PlayScene {
  private showWarning() {
    const label = "⇩ 滑铲｜梁底34px · 净空4px";
    this.warningText.setText(label);
  }
}
"""
        )
    )

    assert len(issues) == 1
    assert "player-visible runtime copy" in issues[0]
    assert "净空4px" in issues[0]
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable == issues


def test_player_facing_runtime_copy_passes_production_ui_gate():
    assert (
        validation_nodes._runtime_debug_ui_issues(
            _source(
                """
class PlayScene {
  private showWarning() {
    this.warningText.setText("前方低梁：按住下滑");
  }
}
"""
            )
        )
        == []
    )


def test_feedback_handler_must_remove_resolved_transient_entity():
    bad = _source(
        """
class PlayScene {
  private consumeFeedback() {
    for (const cue of this.rules.drainFeedback()) {
      if (cue.kind === "coin") {
        this.hud.feedback("coin");
        this.juice.burst(10, 10);
      }
    }
  }
}
"""
    )
    issues = validation_nodes._resolved_entity_lifecycle_issues(bad)
    assert issues
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable == issues

    good = _source(
        """
class PlayScene {
  private consumeFeedback() {
    for (const cue of this.rules.drainFeedback()) {
      if (cue.kind !== "coin") continue;
      const actor = this.actors.find((item) => item.id === cue.id);
      actor?.sprite.destroy();
      actor?.body?.disableBody(true, true);
      this.actors = this.actors.filter((item) => item.id !== cue.id);
      Probe.despawn("pickup", cue.id, "collected");
    }
  }
}
"""
    )
    assert validation_nodes._resolved_entity_lifecycle_issues(good) == []


def test_blocked_only_runtime_interactions_cannot_pass_authored_qa():
    issues = validation_nodes._runtime_interaction_probe_issues(
        {
            "probe:ready": 1,
            "action:attempt|slide": 2,
            "action:start|jump": 2,
            "outcome:blocked|slide_under_beam": 2,
            "outcome:blocked|jump_barrier": 3,
        },
        authored_code=True,
    )

    assert len(issues) == 1
    assert "every resolved result was blocked" in issues[0]
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable == issues


def test_collectible_success_requires_matching_despawn_probe():
    missing = validation_nodes._runtime_interaction_probe_issues(
        {
            "probe:ready": 1,
            "action:triggered|collect": 1,
            "outcome:success|collect_neon_coin": 2,
            "despawn:pickup|coin-1:collected": 1,
        },
        authored_code=True,
    )
    assert any("without matching entity removal" in item for item in missing)

    complete = validation_nodes._runtime_interaction_probe_issues(
        {
            "probe:ready": 1,
            "action:triggered|collect": 1,
            "outcome:success|collect_neon_coin": 2,
            "despawn:pickup|coin-1:collected": 1,
            "despawn:pickup|coin-2:collected": 1,
        },
        authored_code=True,
    )
    assert complete == []
