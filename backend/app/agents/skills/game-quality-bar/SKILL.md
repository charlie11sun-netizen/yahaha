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
- `src/systems/AreaHint.ts` — keyed in-world range/area affordances:
  `AreaHint.circle(scene, key, x, y, radius, style?)`,
  `AreaHint.rect(scene, key, x, y, w, h, style?)` (redrawing the same key just
  moves it — safe from hover/drag handlers), `AreaHint.hide(scene, key)`,
  `AreaHint.clear(scene)`. Palette-styled, reports `hint:area` probes to QA.
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
const DIGIT_NAMES = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"];
const phaserKeyName = (code: string): string => {
  if (code.startsWith("Key")) return code.slice(3).toUpperCase();
  // Digit keys resolve by NAME: KeyCodes.TWO exists, KeyCodes["2"] does NOT —
  // addKey("2") silently registers a key that can never fire.
  if (code.startsWith("Digit")) return DIGIT_NAMES[Number(code.slice(5))] ?? code;
  return ({
    ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT",
    Space: "SPACE", Escape: "ESC", Enter: "ENTER", Tab: "TAB",
  } as Record<string, string>)[code] ?? code.toUpperCase();
};

keyboard.addKey(phaserKeyName(savedDomCode), false, false);
```

After registering, sanity-check the resolved code: `Phaser.Input.Keyboard.KeyCodes[name]`
must be a number for every binding you registered. QA runs a runtime probe that
fails the build when any `addKey` resolved to no key code.

Keep capture/storage and runtime registration separate. Before declaring input
complete, exercise every advertised primary control and confirm it changes a
rules-owned state or visible actor, not just that `addKey` appears in source.

## UI panels & world input — build once, layer correctly

These interaction defects reliably reach players and are QA-gated at runtime:

1. **Never rebuild UI per frame.** A panel or button that is destroyed and
   recreated inside an update path renders normally but NEVER becomes
   clickable: `setInteractive` queues the object for input insertion on the
   next frame, and a per-tick rebuild kills it before that frame arrives (it
   also leaks objects). Build every toolbar/panel/modal once; update its
   text/visibility/fill in place; rebuild only when the content SET changes,
   keyed on a state change signal (day counter, version), never on raw tick.
   A fixed-timestep simulation that returns a fresh state object every call
   must expose a cheap `version`/`day` field so presentation can compare.
2. **Separate UI clicks from world input.** A raw
   `scene.input.on("pointerdown", ...)` world handler also fires when the
   player presses a HUD button — placing buildings or attacking underneath the
   UI (and behind opaque HUD bars where the result is invisible but still
   charged). Register stage handlers through `InputRouter.worldPointer(scene,
   {down, move, up})` (skips presses over ANY interactive object, keeps a drag
   that started on the stage alive across UI) and `InputRouter.shield(panel)`
   every opaque panel rectangle so it swallows presses in its area.
3. **Toggle visuals derive from state.** After a click handler toggles
   something (overlay, speed, pause), read the resulting state to set the
   button highlight; never hardcode "selected" in the handler. Keep one
   open/visible flag per panel and update it on EVERY close path (the panel's
   own close button included), or the opener dead-clicks on the next press.
4. **Thresholds are visible and actionable.** Show current/target on the HUD
   for every numeric win/lose threshold ("population 200/500"), and explain
   blocked progress with its cause (for example a building's road network has
   no power plant) instead of a bare warning icon. For placement/builder
   games: apply the valid cells of a multi-cell drag instead of rejecting the
   whole batch over one blocked cell, and preview per-cell legality.
5. **Range mechanics must match the taught layout, and failures must say so.**
   If services have a range limit (power within N road steps, tower radius),
   check the distances of the layout your tutorial/regions actually prescribe —
   a 10-step service radius with homes and utilities pinned to opposite corners
   makes the opening unwinnable while the aggregate supply/demand HUD still
   looks healthy. Give every non-operating building a badge naming the missing
   prerequisite ("no road" / "out of power range" / "no water"): income sits at
   zero forever exactly when players cannot see why.
6. **Spatial extents are visible, not guessed.** Every range/radius/area number
   a rule consults (attack/effect radius, aura, blast area, service coverage,
   aggro distance) gets an in-world affordance at the moment the player can act
   on it: selecting or hovering an entity draws `AreaHint.circle(scene,
   "sel-range", ent.x, ent.y, ent.range)`, a placement preview draws the
   coverage BEFORE the player commits money, an active aura shows its extent,
   and the inspect/tooltip panel states the number itself. Call it from the
   hover/selection handler (redrawing a key is cheap), `AreaHint.hide` on
   deselect. QA reconciles `hint:area` probes against designs with ranged
   mechanics — rules the player cannot see read as a broken game.
7. **Spending is a deal the player can read before taking it.** Every control
   that spends or refunds currency (build, upgrade, sell, unlock, craft) shows
   its exact price on or beside the control, updated live for the selected
   target, and the benefit it buys. For upgrades that means current→next of
   every stat that changes, sourced from the same rules/content data the
   simulation consults (never a hard-coded copy in UI):

   ```ts
   const next = towerData.levels[tower.level + 1];
   if (!next) {
     upgradeBtn.setLabel("MAX").disable();          // maxed: price replaced by MAX
   } else {
     upgradeBtn.setLabel(`升级 ${next.cost}G`);
     infoPanel.setText([
       `伤害 ${cur.damage} → ${next.damage}`,
       `射程 ${cur.range} → ${next.range}`,
     ]);
     if (gold < next.cost) upgradeBtn.dim(`还差 ${next.cost - gold}G`);
   }
   ```

   Sell shows its refund amount the same way. A bare "升级" button whose cost
   and effect only reveal themselves after clicking reads as an unfinished
   game — players refuse to spend into the unknown.

## Mechanic geometry is one shared truth

For every mechanically distinct spatial or timed interaction, create one
content-owned interaction profile. It must bind:

- the required player action;
- input semantics: edge/tap, hold, toggle, buffered, continuous, or automatic;
- the visible envelope and anchor used to render the target;
- the collision/interaction envelope used by rules;
- the clearance and activation window, including action duration/hold behavior,
  earliest/latest useful activation, target occupancy/transit at worst-case
  speed, recovery, and cue timing;
- the resolution lifecycle (persist, transform, disable, or despawn); and
- worst-case feasibility using both the subject and target extents.

Rendering, physics/rules, telegraphing, and feedback consume that same profile.
Do not hand-write a sprite size in the factory, a second hitbox in the scene,
and a third timing number in a rules class. Those copies drift.

Different required responses need visibly different envelopes. A low obstacle
to jump over belongs on the floor and must fit under the implemented jump arc;
an obstacle to duck under belongs overhead and must leave a visible passage.
The same principle applies across genres: melee versus ranged targets, click
versus drag affordances, placement footprints, rhythm timing bands, cover
versus passable terrain, and attack versus dodge telegraphs must look like the
actions they require.

Never resolve a spatial result from a center-line crossing plus a semantic
label:

```ts
// WRONG: visible bodies may still overlap, yet rules report success.
if (target.x <= player.x + 10) rules.resolve(player.posture, target.kind);
```

Use Phaser overlap/collider, bounds intersection, or a swept interaction window
that consumes both bodies' extents. Apply the current frame's action state
before resolving contact. An imperative cue ("jump now", "slide", "parry",
"tap") may appear only while the action can remain active through resolution;
an earlier cue says "prepare" or the input must support hold/buffering. Emit
`Probe.action` when input reaches rules, `Probe.window` when the actionable
interval opens/closes, and `Probe.outcome` only after geometry/legality
resolves success, failure, or blocked. Each distinct action needs its own
reachable success and failure acceptance evidence; "exercise primary action"
is not sufficient.

## Resolved entities leave play

Every transient entity uses one stable id across rules and integration. When a
pickup, consumable, projectile, defeated actor, spent card, destroyed object,
or one-shot trigger resolves, remove or deactivate its renderer and
collision/input body in the same logical tick, remove it from future
interaction queries, then call `Probe.despawn(category, id, reason)`. Updating
score, adding the id to a resolved set, or waiting for off-screen cleanup while
the entity remains visible/collidable is incomplete.

## Production UI contains no QA evidence

Normal HUD, prompt, pause, result, and button copy tells the player what
happened or what to do. Never show collision pixels, coordinates, hitbox/body
math, rule-layer/physics/state-machine notes, Probe/QA/debug labels, acceptance
arithmetic, or developer instructions. Keep diagnostics in probes or behind an
explicit debug-only surface that is false in the published build.

## Balance numbers have ONE home

Every mechanic-relevant stat table — movement and geometry, timing windows,
puzzle data, card or board values, tower/unit levels, enemy HP, wave
compositions, economy, prices, progression — is exported by exactly one
content-owned module. The rules simulation imports it to resolve game state;
the HUD imports it (or reads it through rules accessors) to display the same
numbers. The moment a second hand-written copy exists, the two drift (a real
shipped case: the panel advertised a 34-damage cannon while the simulation
dealt 30, and the sell dialog quoted a refund 4 gold off from what was paid).
If you find yourself typing a number that already exists in another module,
import it instead.

Treat every `rules.win_feasibility_ledger.checks` entry generically as
required capability versus available capability. Preserve its unit and
minimum ratio in content, simulation, acceptance evidence, and HUD where the
threshold is player-facing. A runner may prove available track distance and
jump reach; a puzzle may prove move or board capacity; a rhythm game may prove
timing windows; an economy game may prove bootstrap cash flow. Do not invent
combat quantities for a non-combat game, and never use zero as an "N/A"
placeholder. Omit a check when that quantitative mechanic does not apply.

When the game has authored combat waves or phases, their compositions are part
of the design's capacity ledger — the
arithmetic that proved the heaviest wave is beatable with ~30% headroom.
Implement exactly the declared composition. Adding "a few more elites", extra
healer stacking, or an extra spawn group feels like flavor but silently blows
past the proven budget: support units multiply effective HP (healing x
lifetime x targets), and the endgame loadout's real on-target uptime is well
under 100%, so the margin is thinner than it looks. If a wave feels too easy,
tune within the ledger (or update the ledger arithmetic first) — never pile on
units ad hoc.

The ledger's supply side is range GEOMETRY: an enemy is only under fire along
the chord its path cuts through an attacker's range circle —
`2*sqrt(range² − distance²)` of path, divided by enemy speed. A 120-range
tower 48px off the path covers 220px ≈ 5.8s per enemy at speed 38 — not the
enemy's 26s full walk (a shipped opening "held wave 1 on paper" and killed
3 of 10 in play). So when you tune enemy `speed`, tower `range`, spawn
`intervalSeconds`, or path layout, you are moving chord seconds — recheck the
opening-vs-wave-1 and heaviest-wave numbers before shipping the change.

## Design for the embedded play surface

The 1280x720 canvas is commonly displayed around 840x470 CSS pixels. Text and
sprites that look acceptable at source resolution shrink by roughly one third:

- essential HUD, objective, and control text: at least 18px source size;
- secondary labels and tooltips: at least 16px source size;
- verify the effective rendered size after canvas and container scaling: aim for
  at least 16 CSS pixels for primary repeated gameplay text and 14 CSS pixels
  for secondary labels; source size alone is not evidence;
- keep outlines proportional to the rendered glyphs. For dense CJK, Japanese,
  or Korean text at 16-24px, prefer no outline or 1px and never exceed 10% of
  the font size. For Latin text never exceed 16%. Fill and outline must have
  clearly opposite luminance; a dark fill with a dark outline turns glyphs
  into blobs. Prefer a solid or translucent contrast panel to a heavy outline;
- measure text after wrapping and grow, reflow, or paginate its panel. Merely
  increasing the font inside a fixed-height card creates clipping and overlap;
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
Gameplay QA fails authored games that preload the sheet without using it.

### Display size = logical footprint (the #1 scale trap)

Sheet frames are large SOURCE art (typically 256px); an actor's rendered size
must come from the logical footprint it occupies — the grid cell or placement
slot it sits on (`gameConfig.levelLayout.cellWidth/cellHeight` when a grid
exists), its collision body, or gameplay scale (~40-90px) — never from the raw
art resolution. Normalize once with `setDisplaySize`, and make every LATER
size change relative to that base:

```ts
tower.setDisplaySize(cell, cell);            // scale is now cell/256 ≈ 0.19
tower.setData("baseScale", tower.scaleX);    // remember the normalized base

// upgrade level bump — RELATIVE to the base:
tower.setScale(tower.getData("baseScale") * (1 + (level - 1) * 0.1));

// WRONG: tower.setScale(1 + (level - 1) * 0.1)
// setScale is ABSOLUTE (relative to the NATIVE 256px frame, not to the
// normalized display size): the tower snaps back to raw art resolution and
// covers several grid cells while still occupying one logical slot.
```

`Juice.pulse` is already relative — safe on normalized sprites. QA probes both
failure modes at runtime: `scale:conflict` (setDisplaySize later wiped by an
absolute setScale) and `scale:native` (large frames rendering at scale ≈ 1).

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
transitions, `anims.play`, and `Backdrop.draw` report automatically. Add these
bounded calls at the real lifecycle points:

- `Probe.spawn("enemy", definition.id)` (or `"boss"`) whenever an actor enters
  play — put it in the content factory or the scene spawn helper, once per
  spawn.
- `Probe.emit("projectile:spawn", projectileId)` when a projectile is fired.
- `Probe.action(actionId, "attempt"|"start"|"triggered"|"end")` when a mapped
  input reaches rules-owned action handling.
- `Probe.window(interactionId, "open"|"close")` around a duration-bound useful
  activation interval.
- `Probe.outcome(interactionId, "success"|"failure"|"blocked")` only after the
  rules resolve the interaction from geometry, timing, or legality.
- `Probe.despawn(category, stableEntityId, reason)` only after the matching
  renderer and collision/input body have left play.

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
- Hard fail (runtime input probes): pointer presses reach the page but no scene
  processes them; interactive objects re-registered every frame during the quiet
  observation window (UI rebuilt per tick = unclickable buttons); any `addKey`
  call that resolved to no key code; a normalized display size wiped by a later
  absolute `setScale` (`scale:conflict` — actors ballooning to raw art size).
- Hard fail (mechanic fidelity): spatial outcomes dispatched from semantic
  labels or a center-line crossing without consuming both visible bodies'
  geometry. Use overlap/bounds or a swept interaction window from the shared
  interaction profile.
- Hard fail (interaction evidence): repeated authored actions resolve only as
  blocked; a pickup/consumable success has no matching despawn; or integration
  acknowledges a terminal entity but leaves it visible/collidable.
- Hard fail (production UI): player-visible strings expose debug, collision,
  QA, acceptance, or implementation prose.
- Warnings that reviewers read: no audio usage, flat art (no glow/gradient/tint),
  shooters without projectiles or a boss climax, a canvas measuring 0x0 after
  load (stylesheet race), animation groups that never play, dead exports, large
  art frames rendered at near-native scale (`scale:native`), rule-consulted
  range/radius data with no visible affordance (no AreaHint, no ring drawing,
  zero `hint:area` probes), and spend/upgrade/sell controls with no visible
  price or benefit preview (the screenshot review flags commerce buttons that
  carry no cost label).
