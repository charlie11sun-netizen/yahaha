---
name: game-quality-bar
description: "The GameWeave quality floor for generated 2D games: layered feedback (juice) recipes mapped to the scaffold's Juice/Sfx systems, risk-reward scoring, difficulty curves, genre physics, and what gameplay QA checks. Read this BEFORE writing gameplay code, and when QA reports missing feedback or placeholder gameplay."
---

# Game Quality Bar (Phaser 3.90 + TS scaffold)

A generated game that merely compiles is not done. This is the floor between
"runs" and "feels like a game". The scaffold already ships the tools — your job
is to wire them into every meaningful event.

## The kit you already have

- `src/systems/Juice.ts` — `hitFlash(target)`, `shake(intensity?, duration?)`,
  `hitStop(ms?)`, `burst(x, y, texture, count?, speed?)`,
  `floatText(x, y, text, color?, size?)`, `pulse(target, scale?, duration?)`.
  Create once per scene: `this.juice = new Juice(this)`.
- `src/systems/Sfx.ts` — `Sfx.play("pickup"|"hit"|"shoot"|"explosion"|"powerup"|"jump"|"select"|"win"|"lose")`,
  `Sfx.playPitched(name, semitoneSteps)` for rising combo tones. Procedural
  WebAudio, no files, never throws.
- `src/systems/Bounds.ts` — world-edge handling: `Bounds.collideWorld(actor, bounce?)`,
  `Bounds.clamp(scene, actor)`, `Bounds.wrap(scene, actor)`,
  `Bounds.despawnOutside(scene, group, margin?)`.
- `src/config/gameConfig.ts` — `gameConfig.palette` (bg/surface/primary/accent/danger,
  the game's visual identity — use it for EVERY color), `param(name, fallback)`
  for free-form tuning numbers, and `gameConfig.sheet` (generated sprite sheet, see below).
- `BootScene.createFallbackTexture`-style procedural textures and the soft
  `"spark"` glow texture for particle bursts.

## Controls must work, not merely exist in source

Phaser key names are not DOM `KeyboardEvent.code` names. A rebinding service may
persist `KeyW`, `ArrowUp`, `Space`, and `Escape`, but `keyboard.addKey()` expects
`W`, `UP`, `SPACE`, and `ESC` (or numeric `Phaser.Input.Keyboard.KeyCodes`).
Passing the DOM string through unchanged compiles and animates normally while
all keyboard controls remain inert.

```ts
const phaserKeyName = (code: string): string => {
  if (code.startsWith("Key")) return code.slice(3).toUpperCase();
  if (code.startsWith("Digit")) return code.slice(5);
  return ({
    ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT",
    Space: "SPACE", Escape: "ESC", Enter: "ENTER", Tab: "TAB",
  } as Record<string, string>)[code] ?? code.toUpperCase();
};

keyboard.addKey(phaserKeyName(savedDomCode), false, false);
```

Keep capture/storage and runtime registration separate. Before declaring input
complete, exercise every advertised primary control and confirm it changes a
rules-owned state or visible actor, not just that `addKey` appears in source.

## Design for the embedded play surface

The 1280x720 canvas is commonly displayed around 840x470 CSS pixels. Text and
sprites that look acceptable at source resolution shrink by roughly one third:

- essential HUD, objective, and control text: at least 18px source size;
- secondary labels and tooltips: at least 16px source size;
- generated player/threat art: size by the visible opaque silhouette, not the
  padded sprite-sheet cell; aim for a clearly readable ~28-36 CSS-pixel actor;
- keep instructions short and progressive instead of one dense line of controls.

Generated backdrop art belongs in the primary gameplay scene, not only the
title screen. Call `Backdrop.draw(this)` from `PlayScene.create()` and keep large
arena panels translucent enough that the image, palette, and phase changes stay
visible behind gameplay. A near-opaque full-screen rectangle technically uses
the asset but still looks like a flat debug arena.

## Generated sprite sheet — use it when present

When assets were generated, `gameConfig.sheet` holds a preloaded spritesheet with
NAMED frame indices (player poses as animation frames, enemies, items, effects):

```ts
const sheet = gameConfig.sheet;
if (sheet) {
  this.player = this.physics.add.sprite(x, y, sheet.key, sheet.frames["player_idle"]);
  this.anims.create({
    key: "player-run",
    frames: this.anims.generateFrameNumbers(sheet.key, {
      frames: [sheet.frames["player_move_a"], sheet.frames["player_move_b"]],
    }),
    frameRate: 8,
    repeat: -1,
  });
  this.player.play("player-run");
} else {
  // fall back to procedural textures ("player-fallback" etc.)
}
```

Each sheet also carries `sheet.animations`: the frames of every multi-frame actor,
keyed by its first frame name and guaranteed to live on the SAME texture. Use every
group you were given — actors that never change frame read as unfinished:

- Player pose set (`"player_idle" -> [idle, move_a, move_b, action, skill_2..5,
  hurt, jump, death, victory]`, whichever were generated): walk cycle from the
  move pair, `player_action`/`player_skill_N` while the matching ability fires,
  `player_hurt` during the invulnerability blink, `player_jump` while airborne,
  `player_death` before the game-over transition, `player_victory` on the win
  screen. Every designed ability with a pose frame should SHOW that frame.
- Enemy groups (`"grunt" -> ["grunt", "grunt_b", "grunt_move"]`): run base+`_move`
  as the walk/patrol animation, flash `_b` (or a 2-frame anim) while
  attacking/charging; snap back to the walk anim after.
- Boss groups (`[boss, boss_b, boss_c, boss_move]`): `_move` cycles while roaming,
  `_b` for attacks, `_c` telegraphs the special-skill phase — pair it with a
  warning tween before the hit lands.
- Item pairs (`"medkit" -> ["medkit", "medkit_b"]`): pulse the activated `_b` frame
  when the player is close, on spawn, or while the effect is running.

Rules: real sprites beat procedural circles — use the sheet for player, enemies,
pickups and the `explosion`/`flash`/`projectile` frames for effects (they also
work as particle textures). Frames from ONE animations group always share a
texture; for anything else use `sheetFrame("name")` which searches every sheet.
`setDisplaySize` sprites down to gameplay scale (~40-64px). Gameplay QA fails
authored games that preload the sheet without using it.

## Scene variants — the stage must evolve

`gameConfig.assetKeys.backgrounds` lists every generated backdrop in order: main
stage, high-intensity/boss phase, alternate zone. Draw the first with
`Backdrop.draw(this)` in create(), keep the returned image, and crossfade on
phase changes with `Backdrop.swap(this, current, gameConfig.assetKeys.backgrounds[1])`
— boss spawn, late-game wave tier, or a level/zone change are all natural
switch points. Pair the swap with `juice.flash` + an Sfx cue so the transition
reads as an event, not a glitch. A game that reaches its boss on the same
backdrop it started on is leaving generated art unused. For the generated background, call `Backdrop.draw(this)` (from
`src/systems/Backdrop.ts`) in your scene's create(): it cover-fits the image at
the lowest depth with a contrast dim, and falls back to a palette gradient when
no background was generated — never replace it with a flat fill.

## Runtime probes — QA replays the game and checks content actually happens

`src/systems/Probe.ts` reports runtime behavior to the QA sandbox. Scene
transitions, `anims.play`, and `Backdrop.draw` report automatically. You add
exactly two kinds of calls:

- `Probe.spawn("enemy", definition.id)` (or `"boss"`) whenever an actor enters
  play — put it in the content factory or the scene spawn helper, once per
  spawn.
- `Probe.emit("projectile:spawn", projectileId)` when a projectile is fired.

QA drives the built game for a few seconds and reconciles probes against the
design roster: a backdrop that never draws in the gameplay scene, animation
groups that never play, or an enemy roster with zero spawn reports all read as
"content generated but never wired". Probes are no-ops in production terms
(bounded counters on `window`), so never gate gameplay on them — just call
them at the real spawn points. Faking probes without the behavior is useless:
QA also sees screenshots, input response, and the static wiring checks.

## World edges — nothing drifts offscreen

Every moving actor uses exactly ONE of (gameplay QA flags violations):
- `Bounds.collideWorld(actor, bounce?)` — players, arena enemies, bouncing hazards.
- `Bounds.clamp(scene, actor)` in update() — manually steered actors.
- `Bounds.wrap(scene, actor)` — asteroids-style wrapping.
- `Bounds.despawnOutside(scene, group)` on a timer or in update() — bullets,
  falling/scrolling waves (recycling also keeps entity counts sane).
Enemies that "chase" the player still need collideWorld or clamp — steering
overshoot at high speed pushes them through the edge otherwise.

## Every hit needs five layers

Animation + sound + VFX + camera + a scoreboard reaction. Concretely:

```ts
// enemy damaged
this.juice.hitFlash(enemy);
this.juice.burst(enemy.x, enemy.y, "spark", 10);
Sfx.play("hit");
// enemy killed (bigger beat)
this.juice.shake(0.008, 120);
this.juice.hitStop(60);            // 1-2 frames of freeze sells impact
this.juice.floatText(enemy.x, enemy.y, `+${points}`, gameConfig.palette.accent);
Sfx.play("explosion");
// player damaged
this.juice.hitFlash(player);
this.juice.shake(0.012, 160);
this.juice.flash(255, 60, 60, 90);  // danger-tinted screen flash
Sfx.play("hit");
```

Rules of thumb:
- Feedback lands within ~100ms of the input that caused it.
- Spawn = scale-in tween (`Back.easeOut`); death = burst + flash, never a silent
  `destroy()`. Nothing pops in or vanishes.
- Ease everything: `ease: "Back.easeOut" | "Quad.easeOut" | "Elastic.easeOut"`.
  Linear-only motion reads as unfinished.
- Combos raise pitch: `Sfx.playPitched("pickup", Math.min(12, streak))`.
- Keep shake small (0.004–0.012) — effects must raise readability, not bury it.

## Scoring must encode risk-reward

Flat "+10 per pickup" is boring by construction. Pick at least one:
- Combo multiplier that resets on damage or on playing too safe.
- Proximity/graze bonus (score for near-misses, e.g. dodging close to a bullet).
- Risky verbs pay more (kill by ram vs by ranged shot; catch falling item low).
- Banked-vs-carried points: dying loses unbanked score.
Show the multiplier in the HUD and celebrate milestones with `floatText` + `pulse`.

## Difficulty is a curve, not a constant

- ~8s safe opening; then escalate one axis at a time (speed, density, new enemy
  behavior, tighter timing) every 15–25s or per wave.
- Speed is the fairest master knob — scale player AND threats together slightly.
- Always solvable: cap simultaneous hazards, never spawn on top of the player,
  telegraph dangers (tween a warning marker before a hazard becomes lethal).
- Damage overlaps fire EVERY frame: gate player damage behind an invulnerability
  window (~1s) with a visible blink, and knock the threat away — otherwise one
  hazard pass drains every life in a few frames (an unavoidable death).
- Win AND loss must both be reachable in a normal session.

## Genre physics — implement the design's actual genre

- Platformer / side-view: set `gravity.y` (800–1200), jump with grounded check
  (`body.blocked.down`), coyote time (~80ms) and jump buffering feel dramatically
  better; squash/stretch on land via `pulse`.
- Top-down: zero gravity, `setVelocity` every tick, normalized diagonals.
- Grid / puzzle: discrete tweened steps between cells; no physics drift.
- Shooter: pooled bullet groups (`maxSize`), muzzle flash + recoil nudge,
  distinct enemy movement patterns, boss with phases and a visible HP bar.
- Waves / defense: scripted escalating spawns along paths; pending spawns count
  toward wave caps.

## Flow & identity

- Keep Boot -> Title -> Play -> GameOver scene flow and scene keys. GameOver
  shows the score and restarts via `scene.start("PlayScene")` — never reload.
- Replace the GW_PLACEHOLDER_GAMEPLAY loop entirely; the placeholder exists only
  to demonstrate this kit.
- The design's `signature_twist` is the game's identity — implement it as a real
  rule the player experiences, and make the HUD/feedback acknowledge it.
- All colors come from `gameConfig.palette`; contrast gameplay-critical objects
  (player/primary, threats/danger, rewards/accent).

## What gameplay QA will flag

- Hard fail: no feedback effects anywhere in gameplay code (no Juice usage, no
  tweens/particles/shake), or authored games that still contain
  GW_PLACEHOLDER_GAMEPLAY.
- Warnings that reviewers read: no audio usage, flat art (no glow/gradient/tint),
  shooters without projectiles or a boss climax.
