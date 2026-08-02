import Phaser from "phaser";

type Tintable = { setTintFill: (color: number) => unknown; clearTint: () => unknown };

/** Layered gameplay feedback helpers. A satisfying hit combines several:
 * hitFlash + burst + shake (+ hitStop on big impacts) + an Sfx preset.
 * Score gains get floatText; UI reactions get pulse. Prefer these helpers
 * over reinventing effects so feedback stays consistent. */
export class Juice {
  private frozen = false;

  constructor(private readonly scene: Phaser.Scene) {}

  /** White hit-flash on a sprite/image, auto-restored. */
  hitFlash(target: Tintable, ms = 60): void {
    try {
      target.setTintFill(0xffffff);
      this.scene.time.delayedCall(ms, () => {
        try {
          target.clearTint();
        } catch {
          /* target may already be destroyed */
        }
      });
    } catch {
      /* non-tintable targets are fine to ignore */
    }
  }

  /** Camera shake; keep intensity small (0.004-0.01) for readability. */
  shake(intensity = 0.008, duration = 120): void {
    this.scene.cameras.main.shake(duration, intensity);
  }

  /** Full-screen flash, e.g. on player damage (danger color) or pickup. */
  flash(red = 255, green = 255, blue = 255, duration = 80): void {
    this.scene.cameras.main.flash(duration, red, green, blue, false);
  }

  /** Freeze physics for a beat on heavy impacts — imperceptible but felt. */
  hitStop(ms = 70): void {
    if (this.frozen) return;
    try {
      const world = this.scene.physics.world;
      this.frozen = true;
      world.pause();
      this.scene.time.delayedCall(ms, () => {
        world.resume();
        this.frozen = false;
      });
    } catch {
      this.frozen = false;
    }
  }

  /** One-shot particle burst at a point (uses an additive glow blend). */
  burst(x: number, y: number, texture: string, count = 12, speed = 170): void {
    try {
      const emitter = this.scene.add.particles(x, y, texture, {
        speed: { min: speed * 0.4, max: speed },
        lifespan: 450,
        scale: { start: 0.9, end: 0 },
        blendMode: Phaser.BlendModes.ADD,
        emitting: false,
      });
      emitter.setDepth(60);
      emitter.explode(count);
      this.scene.time.delayedCall(650, () => emitter.destroy());
    } catch {
      /* missing texture must not crash gameplay */
    }
  }

  /** Floating score/status text that drifts up and fades. */
  floatText(x: number, y: number, text: string, color = "#ffffff", size = 20): void {
    const label = this.scene.add
      .text(x, y, text, {
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: `${size}px`,
        color,
        stroke: "#020617",
        strokeThickness: 4,
      })
      .setOrigin(0.5)
      .setDepth(90);
    this.scene.tweens.add({
      targets: label,
      y: y - 46,
      alpha: 0,
      duration: 650,
      ease: "Quad.easeOut",
      onComplete: () => label.destroy(),
    });
  }

  /** Quick scale pulse for pickups, buttons, HUD reactions. */
  pulse(target: object, scale = 1.15, duration = 110): void {
    this.scene.tweens.add({
      targets: target,
      scale,
      yoyo: true,
      duration,
      ease: "Back.easeOut",
    });
  }
}
