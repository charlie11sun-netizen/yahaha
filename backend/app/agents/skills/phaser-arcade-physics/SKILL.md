---
name: phaser-arcade-physics
description: "Arcade Physics in Phaser 3.90: enabling physics, velocity/gravity/bounce, colliders vs overlaps, dynamic and static groups, world bounds, common pitfalls. Read this when fixing collision, movement, gravity, or physics-group bugs in a Phaser game."
---

# Arcade Physics (Phaser 3.90) - distilled

Condensed from the official `skills/physics-arcade` with GameWeave notes.

## Enable + basic bodies

```js
// in GameConfig
physics: { default: 'arcade', arcade: { gravity: { y: 300 }, debug: false } }

// dynamic body (moves, affected by gravity)
this.player = this.physics.add.sprite(100, 300, 'player');
this.player.setCollideWorldBounds(true);
this.player.setBounce(0.2);

// static platforms (immovable)
this.platforms = this.physics.add.staticGroup();
this.platforms.create(400, 568, 'ground').setScale(2).refreshBody();
```

Pitfall: after scaling/moving a STATIC body you MUST call `refreshBody()` or the
collision box stays at the old size/position.

## Movement

```js
update() {
    if (this.cursors.left.isDown) this.player.setVelocityX(-160);
    else if (this.cursors.right.isDown) this.player.setVelocityX(160);
    else this.player.setVelocityX(0);
    if (this.cursors.up.isDown && this.player.body.blocked.down) this.player.setVelocityY(-330); // jump only when grounded
}
```

- Prefer `setVelocity*` over mutating x/y directly — direct position writes skip
  collision resolution.
- Grounded check: `body.blocked.down` (vs world bounds/static) or `body.touching.down` (vs other bodies).
- Top-down games: set `gravity: { y: 0 }` and use `setVelocity` on both axes;
  normalize diagonals with `body.velocity.normalize().scale(speed)`.

## Collide vs overlap

```js
this.physics.add.collider(this.player, this.platforms);                      // physical blocking
this.physics.add.overlap(this.player, this.pickups, this.onPickup, null, this); // trigger only
```

- `collider` separates bodies (walls, floors); `overlap` only fires the callback
  (coins, bullets, sensors).
- Callback signature `(a, b)` — the order matches the collider arguments.
- Destroying a sprite inside the callback is safe; disable instead with
  `body.enable = false` if you plan to reuse it from a group.

## Groups

```js
this.bullets = this.physics.add.group({ maxSize: 40 });
const b = this.bullets.get(x, y, 'bullet');       // pooled; returns null when full
if (b) { b.setActive(true).setVisible(true); b.body.enable = true; b.setVelocityY(-400); }
```

Recycle off-screen members (`setActive(false).setVisible(false); body.enable=false`)
instead of creating new ones every shot — spawn storms are the top perf bug.

## World bounds & cleanup

- `this.physics.world.setBounds(0, 0, w, h)` to size the playfield.
- Spawn dynamic actors far enough inside those bounds that their entire body,
  including radius and offset, starts inside the playfield. Edge telegraphs should
  use an inset derived from body size, not the literal world-bound coordinate.
- Count delayed or telegraphed actors as pending when enforcing spawn caps. Permit
  at most one pending timer spawn so a background tab resuming cannot create a
  burst of actors on all four edges.
- `sprite.setCollideWorldBounds(true)` keeps it inside; listen for
  `body.onWorldBounds = true` + `this.physics.world.on('worldbounds', ...)` to
  despawn bullets at the edge.

GameWeave note: all textures referenced above must be generated procedurally in
`create()` (see ../phaser-runtime/SKILL.md) — never loaded from files or URLs.
