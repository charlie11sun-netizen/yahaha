"""Legacy Phaser playback plus modular Phaser generation checks."""
from types import SimpleNamespace

from app.agents import author_runner, code_agent, nodes, smoke, validation
from app.services import packaging
from app.services.phaser_projects import create_modular_phaser_project

# 黄金样例：地道的 Phaser 4 产物 —— 没有字面 requestAnimationFrame/addEventListener，
# 输入、循环、纹理全走引擎 API。旧的 Canvas 规则会把它误杀，本文件证明现在不会。
_PHASER_JS = """
class PlayScene extends Phaser.Scene {
    create() {
        const g = this.add.graphics();
        g.fillStyle(0x67e8f9, 1); g.fillCircle(16, 16, 14);
        g.generateTexture('orb', 32, 32); g.destroy();
        this.player = this.physics.add.sprite(200, 300, 'orb').setCollideWorldBounds(true);
        this.cursors = this.input.keyboard.createCursorKeys();
        this.input.on('pointerdown', () => this.fire(), this);
        this.score = 0;
        this.hud = this.add.text(12, 10, 'SCORE 0', { fontFamily: 'system-ui', fontSize: '20px', color: '#e2e8f0' });
        this.time.addEvent({ delay: 900, loop: true, callback: () => this.spawn(), callbackScope: this });
    }
    fire() {
        this.tweens.add({ targets: this.player, scale: 1.2, yoyo: true, duration: 120 });
        this.score += 10;
        this.hud.setText('SCORE ' + this.score);
    }
    spawn() { this.add.particles(120, 80, 'orb', { speed: 80, lifespan: 400, quantity: 6 }); }
    gameOver() {
        window.parent.postMessage({ type: 'gameweave:score', points: Math.floor(this.score) }, '*');
        this.input.keyboard.on('keydown-SPACE', () => this.scene.restart(), this);
    }
    update(time, delta) {
        if (this.cursors.left.isDown) this.player.setVelocityX(-160);
        else if (this.cursors.right.isDown) this.player.setVelocityX(160);
        else this.player.setVelocityX(0);
    }
}
new Phaser.Game({
    type: Phaser.AUTO,
    backgroundColor: '#0b1026',
    scale: { mode: Phaser.Scale.RESIZE, autoCenter: Phaser.Scale.CENTER_BOTH },
    physics: { default: 'arcade', arcade: { gravity: { y: 0 } } },
    scene: [PlayScene],
});
"""

_PHASER_INDEX = (
    '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="style.css">'
    '<script src="phaser.min.js"></script></head><body><script src="game.js"></script></body></html>'
)


def _phaser_files():
    return [
        {"path": "index.html", "content": _PHASER_INDEX},
        {"path": "style.css", "content": "canvas{display:block}"},
        {"path": "game.js", "content": _PHASER_JS},
    ]


def _skipped_sandbox(*args, **kwargs):
    return SimpleNamespace(
        skipped=True, detail="sandbox skipped in test", ok=True, timed_out=False,
        page_errors=[], console_errors=[], requests_aborted=[],
        frames_observed=0, intervals_observed=0, load_ms=0,
    )


# ---- 组装：引擎标签注入 ----

def test_assemble_bundle_injects_phaser_tag_for_synthesized_index():
    files = nodes._assemble_bundle({"game.js": _PHASER_JS}, "T", runtime="phaser")
    index = files[0]["content"]
    assert index.index('src="phaser.min.js"') < index.index('src="game.js"')


def test_assemble_bundle_adds_missing_phaser_tag_to_model_index():
    bundle = {"game.js": _PHASER_JS, "index.html": "<html><head></head><body><script src=\"game.js\"></script></body></html>"}
    index = nodes._assemble_bundle(bundle, "T", runtime="phaser")[0]["content"]
    assert "phaser.min.js" in index


def test_assemble_bundle_canvas_gets_no_engine_tag():
    index = nodes._assemble_bundle({"game.js": "var x=1;"}, "T")[0]["content"]
    assert "phaser.min.js" not in index and "three.min.js" not in index


# ---- 校验与冒烟：Phaser 产物被放行 ----

def test_validate_files_accepts_phaser_bundle():
    result = validation.validate_files(_phaser_files())
    assert result["valid"], result["errors"]


def test_smoke_stub_survives_phaser_toplevel():
    ok, detail = smoke.run_smoke(_PHASER_JS)
    assert ok, detail


# ---- QA：Phaser 惯用法不再被 Canvas 规则误杀 ----

def test_gameplay_qa_passes_phaser_idioms(monkeypatch):
    monkeypatch.setattr(nodes.smoke, "run_smoke", lambda js: (True, "ok"))
    monkeypatch.setattr(nodes.sandbox_client, "run_bundle", _skipped_sandbox)
    result = nodes._gameplay_qa({
        "game_spec": {"archetype": "topdown_collect"},
        "validation_result": {"valid": True},
        "generated_files": _phaser_files(),
    })
    assert result["passed"], result["issues"]
    assert result["metrics"]["has_input"] is True
    assert result["metrics"]["uses_gradient_or_glow"] is True  # generateTexture/tweens 记为美术深度


def test_gameplay_qa_canvas_rules_unchanged(monkeypatch):
    monkeypatch.setattr(nodes.smoke, "run_smoke", lambda js: (True, "ok"))
    monkeypatch.setattr(nodes.sandbox_client, "run_bundle", _skipped_sandbox)
    result = nodes._gameplay_qa({
        "game_spec": {"archetype": "topdown_collect"},
        "validation_result": {"valid": True},
        "generated_files": [
            {"path": "index.html", "content": "<html><script src=\"game.js\"></script></html>"},
            {"path": "style.css", "content": "c{}"},
            {"path": "game.js", "content": "var x = 1;" * 60},
        ],
    })
    assert not result["passed"]
    assert any("no game loop" in issue for issue in result["issues"])
    assert any("no input handling" in issue for issue in result["issues"])


# ---- QA 沙箱与发布：引擎随包 ----

def test_phaser_player_overlap_lint_flags_group_vs_player_first_arg_callbacks():
    bad = """
class PlayScene extends Phaser.Scene {
  create(){
    this.physics.add.overlap(this.enemyBullets, this.player, this.enemyBulletHitsPlayer, null, this);
    this.physics.add.overlap(this.rockets, this.player, (r,p)=>this.explode(r.x,r.y,52,18,true,r), null, this);
    this.physics.add.overlap(this.enemies, this.player, this.enemyTouchPlayer, null, this);
  }
  enemyBulletHitsPlayer(b,p){ this.killObj(b); this.damagePlayer(b.getData('dmg')||8); }
  enemyTouchPlayer(e,p){ this.damagePlayer(ENEMY[e.getData('type')].touch); p.setVelocity(1,1); }
}
"""
    issues = nodes._phaser_player_overlap_issues(bad)
    assert len(issues) == 3
    assert any("enemyBullets" in issue for issue in issues)
    assert any("rockets" in issue for issue in issues)
    assert any("enemies" in issue for issue in issues)


def test_phaser_player_overlap_lint_accepts_registration_order():
    good = """
class PlayScene extends Phaser.Scene {
  create(){
    this.physics.add.overlap(this.enemyBullets, this.player, this.enemyBulletHitsPlayer, null, this);
    this.physics.add.overlap(this.rockets, this.player, (player,rocket)=>this.explode(rocket.x,rocket.y,52,18,true,rocket), null, this);
    this.physics.add.overlap(this.enemies, this.player, this.enemyTouchPlayer, null, this);
  }
  enemyBulletHitsPlayer(player,bullet){ this.killObj(bullet); this.damagePlayer(bullet.getData('dmg')||8); }
  enemyTouchPlayer(player,enemy){ this.damagePlayer(ENEMY[enemy.getData('type')].touch); player.setVelocity(1,1); }
}
"""
    assert nodes._phaser_player_overlap_issues(good) == []


def test_phaser_removed_api_lint_flags_set_tint_fill():
    issues = nodes._phaser_removed_api_issues("sprite.setTintFill(0xffffff);")
    assert issues == [
        "Phaser 4 removed setTintFill(); use setTint(color).setTintMode(Phaser.TintModes.FILL)."
    ]


def test_gameplay_qa_allows_set_tint_fill_in_phaser_390_vite(monkeypatch):
    monkeypatch.setattr(nodes.sandbox_client, "run_bundle", _skipped_sandbox)
    source = """
import Phaser from "phaser";
class PlayScene extends Phaser.Scene {
  private player!: Phaser.GameObjects.Sprite;
  create() {
    this.player = this.add.sprite(100, 100, "player").setTintFill(0xffffff);
    const cursors = this.input.keyboard!.createCursorKeys();
    this.input.on("pointerdown", () => this.player.setTint(0x00ffff));
    this.input.keyboard!.on("keydown-R", () => this.scene.restart());
    this.tweens.add({ targets: this.player, alpha: 0.8, yoyo: true, repeat: -1 });
    void cursors;
  }
  update() { this.player.rotation += 0.01; }
}
new Phaser.Game({ type: Phaser.AUTO, scene: [PlayScene] });
"""
    result = nodes._gameplay_qa(
        {
            "artifact_format": "phaser-vite/v1",
            "game_spec": {"archetype": "topdown_collect"},
            "validation_result": {"valid": True},
            "project_files": [
                {"path": "index.html", "content": '<div id="app"></div><script type="module" src="/src/main.ts"></script>'},
                {"path": "src/main.ts", "content": source},
            ],
            "generated_files": [{"path": "index.html", "content": "<html></html>"}],
        }
    )

    assert not any("setTintFill" in issue for issue in result["issues"])
    assert result["passed"], result["issues"]


def test_phaser_destroyed_body_lint_flags_knockback_after_kill():
    bad = """
class PlayScene extends Phaser.Scene {
  bulletHitsEnemy(b,e){
    this.damageEnemy(e,dmg,b.x,b.y);
    e.setVelocity(e.body.velocity.x+1,e.body.velocity.y+1);
    this.killObj(b);
  }
}
"""
    issues = nodes._phaser_destroyed_body_issues(bad)
    assert issues == [
        "Phaser code reads e.body.velocity after damageEnemy(e, ...); damageEnemy may destroy the enemy before knockback."
    ]


def test_phaser_destroyed_body_lint_accepts_active_body_guard():
    good = """
class PlayScene extends Phaser.Scene {
  bulletHitsEnemy(b,e){
    this.damageEnemy(e,dmg,b.x,b.y);
    if(e.active && e.body) e.setVelocity(e.body.velocity.x+1,e.body.velocity.y+1);
    this.killObj(b);
  }
}
"""
    assert nodes._phaser_destroyed_body_issues(good) == []


def test_sandbox_files_include_phaser_engine(monkeypatch):
    monkeypatch.setattr(packaging, "phaser_engine_bytes", lambda: b"//phaser-stub")
    payload = nodes._sandbox_files_for_qa(_phaser_files(), "2d")
    assert any(f["path"] == "phaser.min.js" for f in payload)


def test_sandbox_files_skip_engine_for_canvas():
    payload = nodes._sandbox_files_for_qa(
        [{"path": "index.html", "content": "<html><script src=\"game.js\"></script></html>"}], "2d"
    )
    assert not any(f["path"] == "phaser.min.js" for f in payload)


def test_publish_helpers_know_phaser():
    assert "phaser.min.js" in packaging._CONTENT_TYPE
    assert packaging._bundle_references(_phaser_files(), "phaser.min.js")
    assert not packaging._bundle_references(_phaser_files(), "three.min.js")
    assert packaging.phaser_engine_bytes(), "vendored phaser.min.js missing or empty"


# ---- 生成侧：新 2D 游戏只允许模块化 Phaser/Vite ----

def test_generate_code_always_returns_modular_typescript(monkeypatch):
    monkeypatch.setattr(nodes.code_agent, "author_enabled", lambda state: False)
    monkeypatch.setattr(
        nodes.llm,
        "chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("2D must not use legacy one-shot generation")),
    )
    files, tokens, mode, _agent_logs = nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})
    paths = {f["path"] for f in files}
    assert tokens == 0
    assert mode == "modular TypeScript template"
    assert {"src/main.ts", "src/scenes/PlayScene.ts", "src/entities/Player.ts"}.issubset(paths)
    assert "game.js" not in paths


def test_modular_phaser_scaffold_is_neutral_stage_with_quality_kit():
    files = create_modular_phaser_project({"title": "Boundary test"}, {})
    by_path = {item["path"]: item["content"] for item in files}

    # 中性舞台：不再自带"追踪敌人+收集"成品玩法（那是产出趋同的母版）。
    assert "src/entities/Enemy.ts" not in by_path
    assert "src/systems/SpawnSystem.ts" not in by_path
    # 品质基建齐备，占位玩法带显式标记且演示 Juice/Sfx 用法。
    assert "hitStop" in by_path["src/systems/Juice.ts"]
    assert "floatText" in by_path["src/systems/Juice.ts"]
    assert "playPitched" in by_path["src/systems/Sfx.ts"]
    assert "setMasterVolume" in by_path["src/systems/Sfx.ts"]
    bridge = by_path["src/systems/GameWeaveBridge.ts"]
    assert "gameweave:storage:set" in bridge and "gameweave:storage:get" in bridge
    assert "window.setTimeout(() => finish(false)" in bridge
    assert "localStorage" not in bridge
    assert "static save(slot: string, value: StoredValue, timeoutMs = 250): Promise<boolean>" in bridge
    assert 'value: cloned.value, requestId' in bridge
    assert "event.source !== window.parent" in bridge
    assert "JSON.parse(encoded)" in bridge
    play = by_path["src/scenes/PlayScene.ts"]
    assert "GW_PLACEHOLDER_GAMEPLAY" in play
    assert "this.juice" in play and "Sfx.play" in play
    assert "GameOverScene" in by_path["src/main.ts"]
    config = by_path["src/config/gameConfig.ts"]
    assert '"palette"' in config and '"params"' in config
    # dodge-collect 专用字段不再出现在类型契约里。
    assert "enemySpeed" not in config and "spawnMs" not in config


def test_scaffold_palette_prefers_design_and_varies_by_title():
    from app.services.phaser_projects import _PALETTES, _palette_for

    designed = _palette_for(
        {"title": "Any", "theme": "any"},
        {"palette": {"bg": "#123456", "primary": "#abcdef", "accent": "bad", "danger": "#FF0000"}},
    )
    assert designed["bg"] == "#123456"
    assert designed["primary"] == "#abcdef"
    assert designed["danger"] == "#ff0000"
    # 非法值回落到确定性调色板
    assert designed["accent"] in {p["accent"] for p in _PALETTES}

    fallbacks = {_palette_for({"title": f"Game {i}", "theme": "retro"}, {})["bg"] for i in range(12)}
    assert len(fallbacks) > 1, "fallback palettes must rotate so games look different"


def test_project_author_prompt_prevents_edge_spawn_bursts():
    instructions = author_runner._PROJECT_AUTHOR_INSTRUCTIONS
    assert "fully inside the configured world bounds" in instructions
    assert "include pending entities in wave caps" in instructions
    assert "background-tab catch-up" in instructions


def test_project_author_prompt_demands_quality_and_placeholder_replacement():
    instructions = author_runner._PROJECT_AUTHOR_INSTRUCTIONS
    assert "GW_PLACEHOLDER_GAMEPLAY" in instructions
    assert "signature_twist" in instructions
    assert "game-quality-bar" in instructions
    assert "hitFlash" in instructions and "floatText" in instructions
    assert "gameConfig.palette" in instructions
    assert "risk-reward" in instructions


# ---- 修复 agent 侧：skills 真的可读、会被列进任务输入 ----

def test_phaser_skills_visible_to_repair_agent():
    names = code_agent.available_skills()
    assert "phaser-runtime" in names and "phaser-arcade-physics" in names
    body = code_agent.RepairSession.from_files(_phaser_files()).read_skill("phaser-runtime")
    assert "generateTexture" in body and "scene.restart" in body
    task_input = code_agent._build_input(_phaser_files(), "boom", "2d", None)
    assert "phaser-runtime" in task_input
