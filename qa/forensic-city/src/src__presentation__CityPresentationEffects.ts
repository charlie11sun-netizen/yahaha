import Phaser from "phaser";
import { Backdrop } from "../systems/Backdrop";
import { Juice } from "../systems/Juice";
import { Sfx } from "../systems/Sfx";
import { gameConfig, sheetFrame } from "../config/gameConfig";

export type CityAnimationState = "idle" | "construction" | "upgrading" | "unpowered" | "damaged" | "celebrating";

export interface CityVisualAnimationManifest {
  idle?: readonly string[];
  construction?: readonly string[];
  upgrading?: readonly string[];
  unpowered?: readonly string[];
  damaged?: readonly string[];
  celebrating?: readonly string[];
}

export interface CityPresentationEffects {
  focusAt(x: number, y: number, durationMs?: number): void;
  buildAccepted(x: number, y: number, large?: boolean): void;
  buildRejected(x: number, y: number, reason?: string): void;
  monthSettled(net: number, scoreDelta: number): void;
  networksChanged(kind: "power" | "water", improved: boolean): void;
  disasterWarning(x: number, y: number): void;
  disasterActivated(x: number, y: number): void;
  disasterResolved(x: number, y: number, dispatched: boolean): void;
  scoreMilestone(score: 40 | 60 | 80): void;
  destroy(): void;
}

/** Registers content-provided frame groups without inventing replacement art.
 * Timings match the frozen presentation contract: roads .2s, 1x1 buildings
 * 1.2s, and 2x2 utilities 1.8s. */
export function registerCityAnimations(
  scene: Phaser.Scene,
  id: string,
  manifest: CityVisualAnimationManifest,
): Readonly<Partial<Record<CityAnimationState, string>>> {
  const result: Partial<Record<CityAnimationState, string>> = {};
  const durations: Record<CityAnimationState, number> = {
    idle: 1200, construction: 1200, upgrading: 1200, unpowered: 900, damaged: 500, celebrating: 600,
  };
  for (const state of Object.keys(durations) as CityAnimationState[]) {
    const names = manifest[state];
    if (!names?.length) continue;
    const resolved = names.map(sheetFrame).filter((frame): frame is { key: string; index: number } => frame !== null);
    if (!resolved.length || resolved.some((frame) => frame.key !== resolved[0].key)) continue;
    const key = `city:${id}:${state}`;
    if (!scene.anims.exists(key)) {
      scene.anims.create({
        key,
        frames: resolved.map((frame) => ({ key: frame.key, frame: frame.index })),
        duration: durations[state],
        repeat: state === "construction" || state === "upgrading" ? 0 : -1,
      });
    }
    result[state] = key;
  }
  return result;
}

export function selectStructureAnimation(
  animations: Readonly<Partial<Record<CityAnimationState, string>>>,
  state: CityAnimationState,
): string | null {
  return animations[state] ?? animations.idle ?? null;
}

/** Shared backdrop, camera and event feedback for IntegrationAgent wiring. */
export function createCityPresentationEffects(scene: Phaser.Scene): CityPresentationEffects {
  const juice = new Juice(scene);
  const backdrop = Backdrop.draw(scene);
  const camera = scene.cameras.main;
  camera.setBounds(0, 0, gameConfig.width, gameConfig.height).setRoundPixels(true);
  camera.setZoom(1).centerOn(gameConfig.width / 2, gameConfig.height / 2);

  const markerFrame = sheetFrame("flash") ?? sheetFrame("item_1");
  const burst = (x: number, y: number, count: number): void => {
    if (markerFrame) juice.burst(x, y, markerFrame.key, count, 95);
  };

  return {
    focusAt(x, y, durationMs = 260): void {
      // The designed map is a single screen; focus is a subtle pan that always returns
      // to center, preventing camera movement from hiding the 20x12 planning board.
      const clampedX = Phaser.Math.Clamp(x, 560, 720);
      const clampedY = Phaser.Math.Clamp(y, 320, 400);
      scene.tweens.add({
        targets: camera, scrollX: clampedX - gameConfig.width / 2, scrollY: clampedY - gameConfig.height / 2,
        duration: durationMs, yoyo: true, hold: 280, ease: "Sine.easeInOut",
      });
    },
    buildAccepted(x, y, large = false): void {
      Sfx.play("pickup", 0.55); burst(x, y, large ? 12 : 7);
      juice.floatText(x, y - 18, large ? "设施施工 1.8秒" : "施工 1.2秒", gameConfig.palette.accent, 14);
    },
    buildRejected(x, y, reason = "不可建设"): void {
      Sfx.play("hit", 0.35); juice.floatText(x, y - 14, `✕ ${reason}`, gameConfig.palette.danger, 14);
    },
    monthSettled(net, scoreDelta): void {
      Sfx.play(net >= 0 ? "pickup" : "hit", 0.35);
      if (Math.abs(scoreDelta) >= 5) juice.pulse(camera, 1.005, 100);
    },
    networksChanged(kind, improved): void {
      Sfx.play(improved ? "powerup" : "hit", 0.35);
      if (!improved) juice.flash(kind === "power" ? 255 : 70, kind === "power" ? 190 : 170, kind === "power" ? 50 : 255, 90);
    },
    disasterWarning(x, y): void {
      Sfx.playPitched("hit", 5, 0.45); juice.floatText(x, y - 24, "⚠ 灾害预警", gameConfig.palette.accent, 18);
    },
    disasterActivated(x, y): void {
      Sfx.play("explosion", 0.55); juice.shake(0.005, 160); juice.flash(255, 80, 60, 120); burst(x, y, 14);
    },
    disasterResolved(x, y, dispatched): void {
      Sfx.play(dispatched ? "powerup" : "select", 0.55); juice.floatText(x, y - 20, dispatched ? "✓ 应急处置成功" : "✓ 灾害恢复", "#baffca", 17);
    },
    scoreMilestone(score): void {
      Sfx.playPitched("powerup", score === 40 ? 0 : score === 60 ? 4 : 7, 0.65);
      juice.flash(255, 211, 78, 100);
    },
    destroy(): void { backdrop?.destroy(); },
  };
}
