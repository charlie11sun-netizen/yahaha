import Phaser from "phaser";

export type Actor = Phaser.GameObjects.Sprite | Phaser.GameObjects.Image;

/** World-edge handling. EVERY moving actor must use exactly one of these —
 * bodies that ignore the world edge drift offscreen and linger forever:
 * - collideWorld: contained actors (players, bouncing hazards, arena enemies)
 * - clamp: steered actors you position manually each tick
 * - wrap: asteroids-style screen wrapping
 * - despawnOutside: projectiles and spawned waves (call it in a timer or update) */
export const Bounds = {
  /** Keep an Arcade body inside the world; bounce > 0 makes it ricochet. */
  collideWorld(actor: Actor, bounce = 0): void {
    const body = actor.body as Phaser.Physics.Arcade.Body | null;
    if (!body) return;
    body.setCollideWorldBounds(true);
    if (bounce > 0) body.setBounce(bounce, bounce);
  },

  /** Clamp a manually-steered actor inside the camera view. */
  clamp(scene: Phaser.Scene, actor: Actor, inset = 24): void {
    actor.x = Phaser.Math.Clamp(actor.x, inset, scene.scale.width - inset);
    actor.y = Phaser.Math.Clamp(actor.y, inset, scene.scale.height - inset);
  },

  /** Wrap an actor to the opposite edge once it fully leaves the screen. */
  wrap(scene: Phaser.Scene, actor: Actor, margin = 32): void {
    const w = scene.scale.width;
    const h = scene.scale.height;
    if (actor.x < -margin) actor.x = w + margin;
    else if (actor.x > w + margin) actor.x = -margin;
    if (actor.y < -margin) actor.y = h + margin;
    else if (actor.y > h + margin) actor.y = -margin;
  },

  /** Destroy group members that left the screen by more than margin. */
  despawnOutside(scene: Phaser.Scene, group: Phaser.GameObjects.Group, margin = 64): number {
    const w = scene.scale.width;
    const h = scene.scale.height;
    let removed = 0;
    for (const child of group.getChildren().slice()) {
      const actor = child as Actor;
      if (!actor.active) continue;
      if (actor.x < -margin || actor.x > w + margin || actor.y < -margin || actor.y > h + margin) {
        actor.destroy();
        removed += 1;
      }
    }
    return removed;
  },
};
