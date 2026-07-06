"""Phaser 2D 运行时试点：组装注入、QA 放行、发布挂载、提示词切换、skills 可读（全离线）。"""
from types import SimpleNamespace

from app.agents import code_agent, nodes, prompts, smoke, validation
from app.services import packaging

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

def test_phaser_player_overlap_lint_flags_reversed_callbacks():
    bad = """
class PlayScene extends Phaser.Scene {
  create(){
    this.physics.add.overlap(this.enemyBullets, this.player, this.enemyBulletHitsPlayer, null, this);
    this.physics.add.overlap(this.rockets, this.player, (p,r)=>this.explode(r.x,r.y,52,18,true,r), null, this);
    this.physics.add.overlap(this.enemies, this.player, this.enemyTouchPlayer, null, this);
  }
  enemyBulletHitsPlayer(p,b){ this.killObj(b); this.damagePlayer(b.getData('dmg')||8); }
  enemyTouchPlayer(p,e){ this.damagePlayer(ENEMY[e.getData('type')].touch); p.setVelocity(1,1); }
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
    this.physics.add.overlap(this.rockets, this.player, (rocket,player)=>this.explode(rocket.x,rocket.y,52,18,true,rocket), null, this);
    this.physics.add.overlap(this.enemies, this.player, this.enemyTouchPlayer, null, this);
  }
  enemyBulletHitsPlayer(bullet,player){ this.killObj(bullet); this.damagePlayer(bullet.getData('dmg')||8); }
  enemyTouchPlayer(enemy,player){ this.damagePlayer(ENEMY[enemy.getData('type')].touch); player.setVelocity(1,1); }
}
"""
    assert nodes._phaser_player_overlap_issues(good) == []


def test_phaser_removed_api_lint_flags_set_tint_fill():
    issues = nodes._phaser_removed_api_issues("sprite.setTintFill(0xffffff);")
    assert issues == [
        "Phaser 4 removed setTintFill(); use setTint(color).setTintMode(Phaser.TintModes.FILL)."
    ]


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


# ---- 生成侧：提示词与运行时切换 ----

def test_generate_code_switches_to_phaser_prompt(monkeypatch):
    monkeypatch.setattr(nodes.settings, "PHASER_2D_ENABLED", True)
    monkeypatch.setattr(nodes.templating, "select_template", lambda spec, design: "t")
    monkeypatch.setattr(nodes.templating, "build_config", lambda *a, **kw: {"title": "T"})
    monkeypatch.setattr(nodes.templating, "render_files", lambda *a, **kw: [])
    seen = {}

    def fake_chat(system, user, **kwargs):
        seen["system"] = system
        seen["user"] = user
        js = "// phaser game\n" + _PHASER_JS
        return (f"```html\n\n```\n```css\ncanvas{{}}\n```\n```js\n{js}\n```", 42)

    monkeypatch.setattr(nodes.llm, "chat", fake_chat)
    files, tokens, mode = nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})
    assert seen["system"] is prompts.CODE_SYSTEM_PROMPT_PHASER
    assert mode.startswith("model (phaser")
    index = next(f["content"] for f in files if f["path"] == "index.html")
    assert "phaser.min.js" in index


def test_generate_code_canvas_default_unchanged(monkeypatch):
    monkeypatch.setattr(nodes.settings, "PHASER_2D_ENABLED", False)
    monkeypatch.setattr(nodes.templating, "select_template", lambda spec, design: "t")
    monkeypatch.setattr(nodes.templating, "build_config", lambda *a, **kw: {"title": "T"})
    monkeypatch.setattr(nodes.templating, "render_files", lambda *a, **kw: [])
    seen = {}

    def fake_chat(system, user, **kwargs):
        seen["system"] = system
        return ("```html\n\n```\n```css\nc{}\n```\n```js\n" + "var x=1;" * 80 + "\n```", 7)

    monkeypatch.setattr(nodes.llm, "chat", fake_chat)
    files, tokens, mode = nodes._generate_code({"use_real": True, "game_spec": {}, "game_design": {}})
    assert seen["system"] is prompts.CODE_SYSTEM_PROMPT
    assert mode in {"model (full bundle)", "model (game.js)"}
    index = next(f["content"] for f in files if f["path"] == "index.html")
    assert "phaser.min.js" not in index


def test_build_code_prompt_reframes_reference_for_phaser():
    text = prompts.build_code_prompt({}, {}, reference="// ref game", runtime="phaser")
    assert "Phaser 4" in text and "raw-Canvas" in text


# ---- 修复 agent 侧：skills 真的可读、会被列进任务输入 ----

def test_phaser_skills_visible_to_repair_agent():
    names = code_agent.available_skills()
    assert "phaser-runtime" in names and "phaser-arcade-physics" in names
    body = code_agent.RepairSession.from_files(_phaser_files()).read_skill("phaser-runtime")
    assert "generateTexture" in body and "scene.restart" in body
    task_input = code_agent._build_input(_phaser_files(), "boom", "2d", None)
    assert "phaser-runtime" in task_input
