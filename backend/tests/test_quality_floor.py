"""质量底线与去趋同语义的回归测试。

覆盖:gameplay QA 的反馈特效硬底线与占位替换检测、规划层"只补缺不覆盖"、
archetype 降级为元数据、design 丰富键(palette/signature_twist/sfx_events)保留、
作者链路可读 game-quality-bar skill。
"""
import json

from app.agents import validation_nodes
from app.agents.codegen import code_generation_node
from app.agents.planning_brief import _coerce_mechanic_plan
from app.agents.planning_nodes import archetype_router_node, content_plan_node, gameplay_planning_node
from app.agents.planning_routing import _balance_plan, _merge_balance_into_design
from app.agents.planning_spec import _coerce_design, _coerce_spec, _simplify_design, _theme_cover
from app.agents.repair_session import RepairSession, available_skills
from app.services.vite_projects import phaser_input_binding_errors

_PAD = "// pad\n" * 80  # 让拼接源码超过 QA 的 400 字节下限


def _vite_state(play_content: str, code_source: str = "author") -> dict:
    project_files = [
        {"path": "package.json", "content": "{}"},
        {"path": "index.html", "content": "<html><main id='game-container'></main></html>"},
        {"path": "src/main.ts", "content": "import Phaser from 'phaser';\nnew Phaser.Game({});"},
        # 库文件里故意含特效 token:必须被剔除,否则底线检查永真
        {"path": "src/systems/Juice.ts", "content": "export class Juice { shake(){} } // tweens.add particles"},
        {"path": "src/scenes/PlayScene.ts", "content": play_content},
    ]
    return {
        "dimension": "2d",
        "artifact_format": "phaser-vite/v1",
        "code_source": code_source,
        "game_spec": {"archetype": "topdown_collect"},
        "game_design": {},
        "validation_result": {"valid": True},
        "generated_files": [],
        "project_files": project_files,
    }


def test_gameplay_qa_fails_when_no_feedback_effects_wired():
    play = _PAD + "createCursorKeys(); // restart hint, no effects at all"
    result = validation_nodes._gameplay_qa(_vite_state(play, code_source="template"))
    assert any("no gameplay feedback effects" in issue for issue in result["issues"])


def test_gameplay_qa_passes_with_juice_usage_and_flags_missing_audio():
    play = _PAD + "createCursorKeys();\nthis.juice.shake(0.01, 100); // restart"
    result = validation_nodes._gameplay_qa(_vite_state(play, code_source="template"))
    assert not any("no gameplay feedback effects" in issue for issue in result["issues"])
    assert any("no audio usage" in warning for warning in result["warnings"])
    assert result["passed"], result["issues"]


def test_gameplay_qa_rejects_unreplaced_placeholder_only_for_authored_projects():
    play = _PAD + "// GW_PLACEHOLDER_GAMEPLAY\ncreateCursorKeys();\nthis.juice.shake(0.01); // restart"
    authored = validation_nodes._gameplay_qa(_vite_state(play, code_source="author"))
    assert any("GW_PLACEHOLDER_GAMEPLAY" in issue for issue in authored["issues"])
    fallback = validation_nodes._gameplay_qa(_vite_state(play, code_source="template"))
    assert not any("GW_PLACEHOLDER_GAMEPLAY" in issue for issue in fallback["issues"])

    real_fallback = _vite_state(play, code_source="template")
    real_fallback["use_real"] = True
    assert any(
        "GW_PLACEHOLDER_GAMEPLAY" in issue
        for issue in validation_nodes._gameplay_qa(real_fallback)["issues"]
    )


def test_phaser_input_binding_lint_rejects_raw_dom_codes_and_accepts_normalization():
    bad = [{
        "path": "src/input/InputBindingService.ts",
        "content": """
const bindings = { moveUp: ['Keyboard:KeyW'], moveAlt: ['Keyboard:ArrowUp'] };
const code = binding.slice(9);
keyboard.addKey(code, false, false);
void bindings;
""",
    }]
    errors = phaser_input_binding_errors(bad)
    assert len(errors) == 1
    assert "KeyW/ArrowUp" in errors[0]

    good = [{
        "path": "src/input/InputBindingService.ts",
        "content": """
const bindings = { moveUp: ['Keyboard:KeyW'], moveAlt: ['Keyboard:ArrowUp'] };
const code = binding.slice(9);
const phaserName = toPhaserKeyName(code);
keyboard.addKey(phaserName, false, false);
void bindings;
""",
    }]
    assert phaser_input_binding_errors(good) == []


def test_gameplay_qa_rejects_background_used_only_on_title_screen():
    play = _PAD + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart"
    state = _vite_state(play)
    state["project_files"].append(
        {"path": "src/scenes/TitleScene.ts", "content": "create(){ Backdrop.draw(this); }"}
    )
    state["asset_manifest"] = {"assets": [{"kind": "image", "key": "background"}]}
    result = validation_nodes._gameplay_qa(state)
    assert any("only outside PlayScene" in issue for issue in result["issues"])

    state["project_files"][4]["content"] = play + "\ncreate(){ Backdrop.draw(this); }"
    result = validation_nodes._gameplay_qa(state)
    assert not any("only outside PlayScene" in issue for issue in result["issues"])


def test_gameplay_qa_rejects_multiple_tiny_embedded_hud_fonts():
    tiny = (
        _PAD
        + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart\n"
        + "textStyle(10); textStyle(14); textStyle(15);"
    )
    result = validation_nodes._gameplay_qa(_vite_state(tiny))
    assert any("source fonts below 16px" in issue for issue in result["issues"])

    readable = tiny.replace("textStyle(10); textStyle(14); textStyle(15);", "textStyle(18); textStyle(18); textStyle(16);")
    result = validation_nodes._gameplay_qa(_vite_state(readable))
    assert not any("source fonts below 16px" in issue for issue in result["issues"])


def test_topdown_facing_lint_rejects_unconditional_player_spin():
    bad_sources = [
        "update(){ this.player.rotation += 0.04; }",
        "update(time: number, delta: number): void { this.hero.angle = this.hero.angle + delta * 0.01; }",
        "update(time: number){ this.avatar.setRotation(time * 0.001); }",
        "update(){ playerSprite.angle = performance.now() * 0.001; }",
    ]
    for source in bad_sources:
        issues = validation_nodes._topdown_uncontrolled_facing_issues(source)
        assert len(issues) == 1, source
        assert "latest non-zero movement/aim vector" in issues[0]


def test_topdown_facing_lint_allows_input_state_and_event_driven_rotation():
    good_sources = [
        "update(time, delta){ if (this.isSpinning) { this.hero.rotation += delta * 0.01; } }",
        "update(){ if (this.cursors.left.isDown) this.player.angle -= 0.04; }",
        "update(time, delta){ this.player.rotation += this.turnAxis * delta; }",
        "create(){ this.input.on('pointerdown', () => this.avatar.rotation += 0.1); }",
        "update(){ this.player.rotation = Phaser.Math.Angle.Between(px, py, aimX, aimY); }",
    ]
    for source in good_sources:
        assert validation_nodes._topdown_uncontrolled_facing_issues(source) == [], source


def test_generated_dungeon_avatar_lint_rejects_rotating_pose_sheet_body():
    bad_sources = [
        "class Player extends Sprite { update(){ const direction = movement(); if(direction.lengthSq()) this.setRotation(direction.angle()); } }",
        "update(){ this.player.setRotation(this.lastAim.angle()); }",
        "faceDirection(direction: Vector2){ this.setRotation(direction.angle()); } update(){ this.player.faceDirection(this.lastAim); }",
    ]
    for source in bad_sources:
        issues = validation_nodes._topdown_generated_avatar_rotation_issues(source)
        assert len(issues) == 1, source
        assert "pose-sheet" in issues[0]


def test_gameplay_qa_rejects_pose_sheet_body_rotation_only_for_authored_dungeon():
    play = _PAD + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart\n" \
        "class Player extends Sprite { update(){ const direction = movement(); this.setRotation(direction.angle()); } }"
    state = _vite_state(play)
    state["game_spec"] = {"archetype": "topdown_collect", "genre": "top-down action dungeon"}
    state["asset_manifest"] = {
        "assets": [{"kind": "spritesheet", "frames": [{"name": "player_idle"}]}]
    }
    authored = validation_nodes._gameplay_qa(state)
    assert any("pose-sheet" in issue for issue in authored["issues"])

    no_sheet = _vite_state(play)
    no_sheet["game_spec"] = state["game_spec"]
    assert not any("pose-sheet" in issue for issue in validation_nodes._gameplay_qa(no_sheet)["issues"])

    template = dict(state)
    template["code_source"] = "template"
    assert not any("pose-sheet" in issue for issue in validation_nodes._gameplay_qa(template)["issues"])

    revision = dict(state)
    revision["code_source"] = "revision"
    assert any("pose-sheet" in issue for issue in validation_nodes._gameplay_qa(revision)["issues"])


def test_gameplay_qa_requires_bridge_when_prompt_requests_persistence():
    base = _PAD + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart"
    missing = _vite_state(base)
    missing["prompt"] = "动作地牢，加入存档和设置"
    result = validation_nodes._gameplay_qa(missing)
    assert any("GameWeaveBridge" in issue for issue in result["issues"])

    wired = _vite_state(
        base
        + "\nGameWeaveBridge.load('settings', defaults);"
        + "\nvoid GameWeaveBridge.save('settings', settings);"
    )
    wired["prompt"] = missing["prompt"]
    result = validation_nodes._gameplay_qa(wired)
    assert not any("GameWeaveBridge" in issue for issue in result["issues"])


def test_gameplay_qa_rejects_disconnected_settings_bindings_and_volume():
    base = _PAD + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart"
    state = _vite_state(base)
    state["prompt"] = "动作地牢，加入存档、设置、按键修改和音量控制"
    state["project_files"] += [
        {
            "path": "src/presentation/SettingsService.ts",
            "content": (
                "export class SettingsService { async load(){ return GameWeaveBridge.load('settings', {}); } "
                "save(){ return GameWeaveBridge.save('settings', {}); } "
                "apply(){ Sfx.setMasterVolume(0.5); bindings.requestRebind('attack', 'KeyK'); } }"
            ),
        },
        {
            "path": "src/scenes/BootScene.ts",
            "content": "void new SettingsService().load();",
        },
        {
            "path": "src/ui/MenuControllers.ts",
            "content": "export const pauseItems = ['设置', '按键修改'];",
        },
        {
            "path": "src/presentation/index.ts",
            "content": "export * from './SettingsService';",
        },
        {
            "path": "src/scenes/GameOverScene.ts",
            "content": "void GameWeaveBridge.save('last-result', result); this.load.image('bg', 'bg.png');",
        },
    ]
    result = validation_nodes._gameplay_qa(state)
    assert any("reachable gameplay" in issue for issue in result["issues"])
    assert any("functional settings" in issue for issue in result["issues"])
    assert any("key rebinding" in issue for issue in result["issues"])
    assert any("volume controls" in issue for issue in result["issues"])


def test_gameplay_qa_accepts_reachable_settings_bindings_and_volume():
    play = (
        _PAD
        + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart\n"
        + "const settings = new SettingsService(); void settings.load(); "
        + "settings.bindings.requestRebind('attack', 'KeyK', 'swap'); "
        + "Sfx.setMasterVolume(0.5); "
        + "void GameWeaveBridge.load('run', defaults); void GameWeaveBridge.save('run', snapshot);"
    )
    state = _vite_state(play)
    state["prompt"] = "动作地牢，加入存档、设置、按键修改和音量控制"
    result = validation_nodes._gameplay_qa(state)
    assert not any("reachable gameplay" in issue for issue in result["issues"])
    assert not any("functional settings" in issue for issue in result["issues"])
    assert not any("key rebinding" in issue for issue in result["issues"])
    assert not any("volume controls" in issue for issue in result["issues"])


def test_gameplay_qa_accepts_delegated_settings_volume_and_generic_bridge_load():
    base = _PAD + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart"
    state = _vite_state(base)
    state["prompt"] = "动作地牢，加入存档、设置、按键修改和音量控制"
    state["project_files"] += [
        {
            "path": "src/composition/AppServices.ts",
            "content": "export const settings = new SettingsService(); settings.update({ masterVolume: 0.5 });",
        },
        {
            "path": "src/presentation/SettingsService.ts",
            "content": "class SettingsService { apply(){ Sfx.setMasterVolume(0.5); } }",
        },
        {
            "path": "src/ui/SettingsOverlay.ts",
            "content": "settings.bindings.requestRebind('attack', 'KeyK', 'swap'); settings.update({ effectsVolume: 0.4 });",
        },
        {
            "path": "src/systems/ProfileService.ts",
            "content": (
                "const data = await GameWeaveBridge.load<Profile>('profile', defaults); "
                "void GameWeaveBridge.save('profile', data);"
            ),
        },
    ]
    result = validation_nodes._gameplay_qa(state)
    assert not any("reachable gameplay" in issue for issue in result["issues"])
    assert not any("functional settings" in issue for issue in result["issues"])
    assert not any("key rebinding" in issue for issue in result["issues"])
    assert not any("volume controls" in issue for issue in result["issues"])


def test_gameplay_qa_rejects_fixed_room_sequence_for_random_dungeon():
    play = (
        _PAD
        + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart\n"
        + "class Dungeon { private generateRooms(): RoomPlan[] { "
        + "return ['start', 'combat', 'chest', 'shop', 'trap', 'boss'].map(type => ({ type })); } }"
    )
    state = _vite_state(play)
    state["prompt"] = "制作随机地牢，每局随机生成房间、宝箱、商店、陷阱和 Boss 房"
    result = validation_nodes._gameplay_qa(state)
    assert any("fixed room sequence" in issue for issue in result["issues"])

    randomized = _vite_state(play.replace("return ['start'", "this.random(); return ['start'"))
    randomized["prompt"] = state["prompt"]
    assert not any("fixed room sequence" in issue for issue in validation_nodes._gameplay_qa(randomized)["issues"])


def test_gameplay_qa_rejects_fake_corridor_map_with_linear_room_index():
    play = (
        _PAD
        + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart\n"
        + "class Dungeon { private generateRooms(){ this.random(); return rooms; } "
        + "advanceRoom(){ this.roomIndex = this.roomIndex + 1; } "
        + "map(){ return this.rooms.map((room, index) => ({ adjacent: index === this.roomIndex + 1 })); } }"
    )
    state = _vite_state(play)
    state["prompt"] = "每局随机生成房间、走廊、宝箱和 Boss 房的随机地牢"
    result = validation_nodes._gameplay_qa(state)
    assert any("linear roomIndex + 1" in issue for issue in result["issues"])

    graph = _vite_state(
        play.replace(
            "advanceRoom(){ this.roomIndex = this.roomIndex + 1; }",
            "connections: string[] = []; chooseExit(nextRoomId: string){ this.currentRoomId = nextRoomId; }",
        ).replace("this.roomIndex + 1", "room.connections.includes(currentRoomId)")
    )
    graph["prompt"] = state["prompt"]
    assert not any("linear roomIndex + 1" in issue for issue in validation_nodes._gameplay_qa(graph)["issues"])


def test_gameplay_qa_applies_facing_guard_only_to_authored_topdown_games():
    play = _PAD + "createCursorKeys(); this.juice.shake(0.01); Sfx.play('hit'); // restart\n" \
        "class PlayScene { update(time, delta){ this.avatar.rotation += delta * 0.01; } }"

    chinese_topdown = _vite_state(play)
    chinese_topdown["game_spec"] = {"archetype": "canvas_arcade", "genre": "俯视角动作地牢"}
    result = validation_nodes._gameplay_qa(chinese_topdown)
    assert any("rotation changes continuously" in issue for issue in result["issues"])

    template = _vite_state(play, code_source="template")
    assert not any("rotation changes continuously" in issue for issue in validation_nodes._gameplay_qa(template)["issues"])

    non_topdown = _vite_state(play)
    non_topdown["game_spec"] = {"archetype": "platformer", "genre": "side scrolling platformer"}
    assert not any("rotation changes continuously" in issue for issue in validation_nodes._gameplay_qa(non_topdown)["issues"])


def test_archetype_router_keeps_model_genre_and_core_loop():
    out = archetype_router_node(
        {
            "dimension": "2d",
            "prompt": "a rooftop platformer where you flip gravity",
            "game_spec": {
                "title": "Roof Flip",
                "genre": "platformer",
                "core_loop": "run, jump and flip gravity across rooftops",
            },
        }
    )
    spec = out["game_spec"]
    assert spec["genre"] == "platformer"
    assert spec["core_loop"] == "run, jump and flip gravity across rooftops"
    assert spec["archetype"] == "platformer"


def test_native_genre_ignores_incompatible_legacy_mechanic_hint():
    out = archetype_router_node(
        {
            "dimension": "2d",
            "prompt": "random rooms, melee combat, relic builds and a boss",
            "game_spec": {
                "title": "Deep Ruins",
                "genre": "action_roguelite",
                "core_loop": "explore rooms, fight, build a run, defeat the boss",
            },
            "mechanic_plan": {"archetype_hint": "vertical_shooter"},
        }
    )

    assert out["game_spec"]["archetype"] == "action_roguelite"
    assert out["archetype_result"]["legacy_family"] is False
    assert "no legacy template coercion" in out["archetype_result"]["reason"]


def test_gameplay_planning_combines_brief_and_mechanics_in_one_model_call(monkeypatch):
    calls = []

    def fake_chat(system_prompt, user_prompt, **kwargs):
        calls.append((system_prompt, user_prompt, kwargs))
        return json.dumps(
            {
                "expanded_brief": {
                    "player_fantasy": "command a storm fighter",
                    "core_verbs": ["fly", "shoot", "dodge"],
                },
                "mechanic_plan": {
                    "archetype_hint": "vertical_shooter",
                    "primary_action": "shoot",
                    "signature_twist": "lightning chains through marked enemies",
                },
            }
        ), 37

    monkeypatch.setattr("app.agents.planning_nodes.llm.chat", fake_chat)
    out = gameplay_planning_node(
        {
            "use_real": True,
            "prompt": "a storm fighter vertical shooter",
            "game_spec": {"title": "Storm Wing", "genre": "shooter"},
        }
    )

    assert len(calls) == 1
    assert calls[0][2]["recover_partial_json"] is True
    assert calls[0][2]["timeout"] == 180
    assert "archetype_hint" not in calls[0][1]
    assert out["_agent"] == "GameplayPlanningAgent"
    assert out["_tokens_delta"] == 37
    assert out["expanded_brief"]["player_fantasy"] == "command a storm fighter"
    assert out["mechanic_plan"]["signature_twist"] == "lightning chains through marked enemies"


def test_generation_graph_has_one_combined_gameplay_planning_node():
    from app.agents.graph import build_graph

    graph = build_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert "gameplay_planning" in graph.nodes
    assert "brief_expansion" not in graph.nodes
    assert "mechanic_planner" not in graph.nodes
    assert ("intent_spec", "gameplay_planning") in edges
    assert ("gameplay_planning", "archetype_router") in edges


def test_content_plan_only_fills_gap_when_design_lacks_waves():
    base = {
        "prompt": "collect gems",
        "game_spec": {"title": "Gems", "genre": "arcade", "archetype": "topdown_collect"},
    }
    with_waves = content_plan_node({**base, "game_design": {"waves": [{"t": 0, "spawn": "few"}]}})
    assert "content_plan" not in with_waves["game_design"]
    without_waves = content_plan_node({**base, "game_design": {}})
    assert without_waves["game_design"].get("content_plan")


def test_balance_merge_does_not_override_model_pacing():
    merged = _merge_balance_into_design(
        {"rules": {"survive_seconds": 95}},
        "topdown_collect",
        {"round_seconds": 65, "target_score": 170},
    )
    assert merged["rules"]["survive_seconds"] == 95
    assert merged["balance"]["target_score"] == 170


def test_native_genre_balance_withholds_legacy_spawn_and_survival_defaults():
    balance = _balance_plan(
        "turn_based_tactics",
        {"genre": "turn_based_tactics"},
        "a tactical campaign",
    )
    merged = _merge_balance_into_design(
        {"rules": {"win": "complete the objective", "lose": "party defeated"}},
        "turn_based_tactics",
        balance,
    )

    assert balance["mode"] == "design_driven"
    assert "hazard_spawn_ms" not in balance
    assert "round_seconds" not in balance
    assert "survive_seconds" not in merged["rules"]


def test_native_genre_content_and_replan_stay_genre_neutral():
    planned = content_plan_node(
        {
            "prompt": "a side-scrolling platform adventure",
            "game_spec": {"title": "Clocktower", "genre": "platformer", "archetype": "platformer"},
            "expanded_brief": {
                "core_verbs": ["run", "jump", "grapple"],
                "difficulty_beats": ["safe tutorial", "combined traversal", "mastery test"],
            },
            "mechanic_plan": {"enemy_behaviors": [], "reward_items": [], "powerups": []},
            "game_design": {},
        }
    )
    content = planned["game_design"]["content_plan"]
    assert content["mode"] == "design_driven"
    assert all("hazards" not in beat for beat in content["waves"])
    assert "run, jump, grapple" in content["tutorial"]

    simplified = _simplify_design(
        {
            "archetype": "platformer",
            "rules": {"win": "reach the summit", "lose": "health depleted"},
            "entities": [{"name": f"enemy-{index}"} for index in range(9)],
            "waves": [{"room": index} for index in range(5)],
        }
    )
    assert simplified["archetype"] == "platformer"
    assert simplified["rules"]["win"] == "reach the summit"
    assert len(simplified["entities"]) == 6
    assert len(simplified["waves"]) == 3


def test_coerce_spec_flattens_nested_model_prose_for_downstream_prompts():
    spec = _coerce_spec(
        {
            "title": {"name": "Citadel Tactics"},
            "genre": {"type": "tactical_card_game"},
            "theme": {
                "setting": "a neon fortress above a storm sea",
                "tone": "tense but heroic",
                "playable_classes": ["warden", "arcanist", "ranger"],
            },
            "core_loop": {
                "campaign": "choose a route and upgrade the squad",
                "combat": {
                    "turn": "spend actions to move and play cards",
                    "positioning": "use cover, height, and hazards",
                },
            },
            "win_condition": {"primary": "defeat the phase-changing boss"},
        },
        "a tactical card game",
    )

    assert spec["title"] == "name: Citadel Tactics"
    assert spec["genre"] == "type: tactical_card_game"
    assert "setting: a neon fortress" in spec["theme"]
    assert "tone: tense but heroic" in spec["theme"]
    assert "campaign: choose a route" in spec["core_loop"]
    assert "combat: turn: spend actions" in spec["core_loop"]
    assert "positioning: use cover" in spec["core_loop"]
    assert "{" not in spec["theme"] and "'setting'" not in spec["theme"]
    assert "{" not in spec["core_loop"] and "'combat'" not in spec["core_loop"]
    assert _theme_cover(spec["theme"]) == _theme_cover("neon")


def test_coerce_design_preserves_identity_keys():
    design = _coerce_design(
        {
            "palette": {"bg": "#101820", "primary": "#f2aa4c"},
            "signature_twist": "the floor is lava every 10 seconds",
            "sfx_events": ["pickup", "lava_rise"],
        },
        {"genre": "arcade"},
    )
    assert design["palette"]["primary"] == "#f2aa4c"
    assert design["signature_twist"].startswith("the floor is lava")
    assert design["sfx_events"] == ["pickup", "lava_rise"]


def test_coerce_mechanic_plan_keeps_signature_twist():
    plan = _coerce_mechanic_plan({"signature_twist": "gravity flips on every pickup"}, {}, {}, "prompt")
    assert plan["signature_twist"] == "gravity flips on every pickup"


def test_codegen_reports_template_code_source_offline():
    out = code_generation_node(
        {
            "dimension": "2d",
            "use_real": False,
            "game_spec": {"title": "Sourced", "archetype": "topdown_collect"},
            "game_design": {},
        }
    )
    assert out["code_source"] == "template"


def test_quality_bar_skill_available_to_agents():
    assert "game-quality-bar" in available_skills()
    body = RepairSession.from_files(
        [{"path": "index.html", "content": "<html></html>"}]
    ).read_skill("game-quality-bar")
    assert "hitStop" in body and "risk-reward" in body and "GW_PLACEHOLDER_GAMEPLAY" in body
    assert "KeyboardEvent.code" in body and "embedded play surface" in body


# ---------- 运行时对账（Probe）与死导出报告 ----------

def _probe_state(play_extra: str = "", probes: dict | None = None, extra_files: list | None = None,
                 design: dict | None = None, manifest: dict | None = None) -> dict:
    play = _PAD + "createCursorKeys();\nthis.juice.shake(0.01); // restart\nconst f = sheetFrame('player_idle'); void 0;\n" + play_extra
    state = _vite_state(play, code_source="author")
    state["generated_files"] = [{"path": "index.html", "content": "<html><canvas></canvas></html>"}]
    state["game_design"] = design or {}
    state["asset_manifest"] = manifest or {
        "assets": [
            {"kind": "image", "key": "background"},
            {
                "kind": "spritesheet",
                "key": "sheet",
                "frames": {"player_idle": 0, "player_move_a": 1},
                "animations": {"player_idle": ["player_idle", "player_move_a"]},
            },
        ]
    }
    if extra_files:
        state["project_files"] = state["project_files"] + extra_files
    state["_test_probes"] = probes if probes is not None else {}
    return state


def _run_probe_qa(monkeypatch, state: dict):
    from app.services.sandbox_client import SandboxResult

    probes = state.pop("_test_probes")
    monkeypatch.setattr(
        validation_nodes.sandbox_client,
        "run_bundle",
        lambda *args, **kwargs: SandboxResult(
            ok=True, frames_observed=30, load_ms=500, probes=probes
        ),
    )
    return validation_nodes._gameplay_qa(state)


def test_probe_confirmed_backdrop_overrides_token_check(monkeypatch):
    result = _run_probe_qa(
        monkeypatch,
        _probe_state(
            probes={
                "probe:ready": 1,
                "scene:start|PlayScene": 1,
                "backdrop:draw|PlayScene": 1,
                "anims:play|player-run": 12,
            },
        ),
    )
    assert not any("background" in issue for issue in result["issues"]), result["issues"]
    assert not any("backdrop" in issue for issue in result["issues"])


def test_probe_refuted_backdrop_fails_even_with_tokens_present(monkeypatch):
    from app.agents import repair

    result = _run_probe_qa(
        monkeypatch,
        _probe_state(
            play_extra="Backdrop.draw(this); // dead branch in reality\n",
            probes={
                "probe:ready": 1,
                "scene:start|PlayScene": 1,
                "backdrop:draw|TitleScene": 1,
                "anims:play|player-run": 3,
            },
        ),
    )
    backdrop_issues = [i for i in result["issues"] if i.startswith("generated backdrop never rendered")]
    assert backdrop_issues, result["issues"]
    kind, patchable = repair._classify_gameplay_failure({"issues": backdrop_issues})
    assert kind == "quality"
    assert patchable == backdrop_issues


def test_probe_missing_falls_back_to_token_checks(monkeypatch):
    result = _run_probe_qa(
        monkeypatch,
        _probe_state(
            play_extra="Backdrop.draw(this);\n",
            probes={},
        ),
    )
    assert not any("backdrop" in issue.lower() for issue in result["issues"]), result["issues"]


def test_probe_reports_unplayed_animation_groups_and_missing_spawns(monkeypatch):
    result = _run_probe_qa(
        monkeypatch,
        _probe_state(
            probes={
                "probe:ready": 1,
                "scene:start|PlayScene": 1,
                "backdrop:draw|PlayScene": 1,
            },
            design={
                "entities": [
                    {"role": "enemy 近战追击", "name": "裂刃"},
                    {"role": "enemy ranged", "name": "弩手"},
                    {"role": "player", "name": "主角"},
                ]
            },
        ),
    )
    assert any(w.startswith("generated animation groups never played") for w in result["warnings"]), result["warnings"]
    assert any(w.startswith("declared enemy roster never spawned") for w in result["warnings"])


def test_probe_gameplay_not_reached_warns_and_skips_backdrop_gate(monkeypatch):
    result = _run_probe_qa(
        monkeypatch,
        _probe_state(
            play_extra="Backdrop.draw(this);\n",
            probes={"probe:ready": 1, "scene:start|TitleScene": 1},
        ),
    )
    assert any(w.startswith("simulated input never reached a gameplay scene") for w in result["warnings"])
    assert not any(i.startswith("generated backdrop never rendered") for i in result["issues"])


def test_dead_runtime_exports_reported_and_void_does_not_count_as_usage(monkeypatch):
    extra = [
        {"path": "src/systems/Combat.ts", "content": "export class CombatSystem { hit(): number { return 1; } }"},
        {"path": "src/content/enemies.ts", "content": "export const ENEMY_DEFS = [{ id: 'grunt' }];"},
        {"path": "src/ui/HudExtra.ts", "content": "export function drawHudExtra(): void {}"},
    ]
    state = _probe_state(
        play_extra="import { CombatSystem } from '../systems/Combat';\nvoid CombatSystem;\n",
        probes={"probe:ready": 1, "scene:start|PlayScene": 1, "backdrop:draw|PlayScene": 1, "anims:play|a": 1},
        extra_files=extra,
    )
    result = _run_probe_qa(monkeypatch, state)
    dead = [w for w in result["warnings"] if w.startswith("dead runtime exports:")]
    assert dead, result["warnings"]
    assert "CombatSystem" in dead[0] and "ENEMY_DEFS" in dead[0] and "drawHudExtra" in dead[0]

    from app.agents import repair

    advisory = repair._advisory_qa_feedback({"warnings": result["warnings"]})
    assert any(item.startswith("dead runtime exports:") for item in advisory)
