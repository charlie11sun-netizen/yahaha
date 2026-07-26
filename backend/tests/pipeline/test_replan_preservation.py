"""Genre-neutral regression coverage for non-destructive recovery replans."""

from app.agents import prompts, repair, validation_nodes


def _rich_design() -> dict:
    return {
        "archetype": "model_authored_strategy",
        "background": {"theme": "three distinct regions"},
        "level_layout": {"maps": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
        "entities": [
            {"id": "player", "name": "Commander", "role": "player"},
            {"id": "rival", "name": "Rival", "role": "enemy"},
        ],
        "waves": [{"t": index, "spawn": f"encounter-{index}"} for index in range(1, 21)],
        "powerups": [{"name": "Overdrive"}, {"name": "Shield"}],
        "boss": {"name": "Final Rival", "phases": ["one", "two", "three"]},
        "juice": ["hit flash", "camera shake"],
        "rules": {"win": "clear all authored encounters"},
        "ui": {"show_score": True},
    }


def test_replan_overlay_preserves_omitted_sections_and_collection_sizes():
    previous = _rich_design()
    candidate = {
        "archetype": "generic_template",
        "entities": [
            {
                "id": "player",
                "name": "Commander",
                "role": "player",
                "pool_size": 8,
            }
        ],
        "rules": {"max_active_entities": 48},
        "ui": {"show_score": True, "compact_panels": True},
    }

    merged = repair._merge_replan_preserving_design(previous, candidate)

    assert merged["archetype"] == previous["archetype"]
    assert len(merged["entities"]) == len(previous["entities"])
    assert merged["entities"][0]["pool_size"] == 8
    assert len(merged["waves"]) == 20
    assert merged["level_layout"] == previous["level_layout"]
    assert merged["boss"] == previous["boss"]
    assert merged["powerups"] == previous["powerups"]
    assert merged["juice"] == previous["juice"]
    assert merged["rules"]["max_active_entities"] == 48


def test_replan_overlay_cannot_replace_same_length_unstructured_content():
    previous = {
        "endings": ["rescue the city", "join the rival"],
        "boss": {"phases": ["shield maze", "final duel"]},
    }
    candidate = {
        "endings": ["generic win", "generic loss"],
        "boss": {"phases": ["single easy phase", "credits"]},
    }

    merged = repair._merge_replan_preserving_design(previous, candidate)

    assert merged["endings"][:2] == previous["endings"]
    assert merged["boss"]["phases"][:2] == previous["boss"]["phases"]
    assert {"generic win", "generic loss"}.issubset(merged["endings"])


def test_offline_replan_preserves_full_authored_design_and_never_selects_template():
    design = _rich_design()
    out = repair.replan_game_design_node(
        {
            "use_real": False,
            "dimension": "2d",
            "game_design": design,
            # This deliberately lossy execution projection must not become the
            # authoring source for an upstream replan.
            "design_execution_view": {
                "archetype": design["archetype"],
                "entities": [],
            },
            "game_spec": {"genre": "strategy"},
            "last_error": "presentation failed",
            "replan_attempts": 0,
        }
    )

    assert out["game_design"] == design
    assert "use_template_code" not in out
    assert any("preserved the authored design" in line for line in out["_logs"])


def test_patchable_quality_failure_never_crosses_into_design_replan_after_budget():
    state = {
        "task_kind": "generation",
        "gameplay_repair_attempts": 2,
        "replan_attempts": 0,
        "gameplay_qa_result": {
            "passed": False,
            "issues": ["visual review: essential text is not reliably legible"],
        },
    }
    assert validation_nodes.should_continue_after_gameplay_qa(state) == "failed"

    state["gameplay_qa_result"]["issues"] = [
        "the authored economy is mathematically unwinnable"
    ]
    assert (
        validation_nodes.should_continue_after_gameplay_qa(state)
        == "replan_game_design"
    )


def test_replan_prompt_exposes_auditable_preservation_ledger():
    prompt = prompts.build_replan_prompt(
        {"genre": "strategy"},
        _rich_design(),
        "feasibility gate failed",
    )

    assert "Preservation ledger" in prompt
    assert '"waves": 20' in prompt
    assert '"powerups": 2' in prompt
    assert "non-destructive" in prompt
