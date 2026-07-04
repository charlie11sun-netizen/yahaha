---
name: phaser-runtime
description: "Phaser 4 inside the GameWeave sandbox: boot config, scene lifecycle, procedural textures (no loader!), input idioms, restart, score reporting, smoke-test constraints. Read this when fixing a Phaser game that fails validation, crashes on load, or shows a black screen."
---

# Phaser 4 in the GameWeave Sandbox

Distilled from the official phaser repo `skills/` (game-setup-and-config, scenes,
input, graphics-and-shapes) and REWRITTEN for this sandbox: no network, no asset
files, engine served same-origin.

## Boot (index.html + top level of game.js)

```html
<script src="phaser.min.js"></script>   <!-- relative, BEFORE game.js; never a CDN URL -->
<script src="game.js"></script>
```

```js
class PlayScene extends Phaser.Scene {
    create() { /* build textures, sprites, input, HUD here */ }
    update(time, delta) { /* per-frame logic, scale motion by delta */ }
}
new Phaser.Game({
    type: Phaser.AUTO,
    backgroundColor: '#0b1026',
    scale: { mode: Phaser.Scale.RESIZE, autoCenter: Phaser.Scale.CENTER_BOTH },
    physics: { default: 'arcade', arcade: { gravity: { y: 0 } } },
    scene: [PlayScene],
});
```

TOP-LEVEL SAFETY: only class/const/config declarations and `new Phaser.Game(...)`
may run at top level. The V8 smoke test executes game.js top-level once with a
stubbed `Phaser`; touching scene systems (`this.add`, `this.physics`) outside
scene methods, or reading a variable before its initializer, fails the build.

## Textures: procedural ONLY — the loader is forbidden here

`this.load.image('x', 'assets/x.png')` and every file/URL load VIOLATES the
sandbox (no network; external URLs fail validation). Build textures instead:

```js
const g = this.add.graphics();
g.fillStyle(0x67e8f9, 1); g.fillCircle(16, 16, 14);
g.lineStyle(2, 0xffffff, 0.8); g.strokeCircle(16, 16, 14);
g.generateTexture('orb', 32, 32); g.destroy();
this.physics.add.sprite(200, 300, 'orb');
```

Layer fillRect/fillCircle/fillTriangle/strokePath per texture; generate one
texture per entity variant. `data:` URIs are also acceptable. Glow = a blurred
halo texture underneath or `setBlendMode(Phaser.BlendModes.ADD)`.

## Input idioms (engine-level; no addEventListener needed)

```js
this.cursors = this.input.keyboard.createCursorKeys();
this.keys = this.input.keyboard.addKeys('W,A,S,D');
this.input.on('pointerdown', (p) => this.fire(p), this);
this.input.keyboard.on('keydown-SPACE', () => this.fire(), this);
```

## Flow, restart, score

- Timers: `this.time.addEvent({ delay: 900, loop: true, callback: this.spawn, callbackScope: this })`.
- Restart: `this.scene.restart()` — NEVER `location.reload()` (QA checks restart works without reloading).
- Report score exactly once at game over:
  `window.parent.postMessage({ type: 'gameweave:score', points: Math.floor(score) }, '*');`
  This postMessage is the ONLY allowed parent access.
- Juice: `this.tweens.add({...})`, `this.add.particles(x, y, 'orb', {...})`,
  `this.cameras.main.shake(120, 0.008)`, `setTint/clearTint`.

## Frequent failure → fix map

| Symptom | Fix |
| --- | --- |
| validation: external URL / forbidden API | remove loader paths & CDN tags; procedural textures; engine via relative `phaser.min.js` |
| smoke crash: `Phaser is not defined` order issue | index.html must load `phaser.min.js` before `game.js` |
| smoke crash at load | move logic from top level into `create()`; declare data before first use |
| black screen in browser QA | scene never added to config, or all drawing waits on a loader that never runs — build textures in `create()` directly |
| QA: no input handling | use the input idioms above (they are recognized) |
