import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "./Colors";
import { Probe } from "./Probe";

/** Show a generated background image when one exists (cover-fit at the
 * lowest depth, dimmed toward the palette bg so gameplay sprites stay
 * readable). Returns null when no background asset was generated — callers
 * fall back to a palette gradient.
 *
 * Several scene variants may exist (gameConfig.assetKeys.backgrounds: main
 * stage, high-intensity / boss phase, alternate zone). Switch stages with
 * Backdrop.swap: it crossfades from the current backdrop to the named one —
 * call it on phase changes (boss spawn, new wave tier, level change). */
export const Backdrop = {
  /** Omit `dim` to use the measured per-image strength (gameConfig.backdropDims):
   * generated dark art gets a light overlay, bright art a stronger one — never
   * double-darken an already moody scene. Pass an explicit dim only for special
   * screens (e.g. the title screen dims harder behind its text). */
  draw(scene: Phaser.Scene, dim?: number, key?: string): Phaser.GameObjects.Image | null {
    const textureKey = key ?? gameConfig.assetKeys.background;
    if (!textureKey || !scene.textures.exists(textureKey)) return null;
    Probe.emit("backdrop:draw", scene.scene.key);
    const { width, height } = scene.scale;
    const image = scene.add.image(width / 2, height / 2, textureKey).setDepth(-20);
    const scale = Math.max(width / image.width, height / image.height);
    image.setScale(scale);
    const applied = dim ?? gameConfig.backdropDims[textureKey] ?? 0.35;
    if (applied > 0) {
      scene.add
        .rectangle(width / 2, height / 2, width, height, colorNum(gameConfig.palette.bg), applied)
        .setDepth(-19);
    }
    return image;
  },

  /** Crossfade the stage to another generated scene variant. `current` is the
   * image returned by draw()/swap() (null-safe); returns the new backdrop (or
   * the old one when the target texture is missing). */
  swap(
    scene: Phaser.Scene,
    current: Phaser.GameObjects.Image | null,
    key: string,
    durationMs = 600,
  ): Phaser.GameObjects.Image | null {
    if (!key || !scene.textures.exists(key)) return current;
    const next = this.draw(scene, 0, key);
    if (!next) return current;
    // 在旧背景之上、暗化层(-19)之下淡入,交叉渐变全程可见。
    next.setDepth(-19.5).setAlpha(0);
    scene.tweens.add({
      targets: next,
      alpha: 1,
      duration: durationMs,
      onComplete: () => {
        next.setDepth(-20);
        current?.destroy();
      },
    });
    return next;
  },
};
