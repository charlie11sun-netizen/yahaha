import Phaser from "phaser";
import { gameConfig, sheetFrame } from "../config/gameConfig";
import { Juice } from "../systems/Juice";
import { Sfx } from "../systems/Sfx";

type Point = { x: number; y: number };
type DisasterKind = "fire" | "blackout" | "pollutionLeak" | "storm" | "majorStorm";
type EndResult = "victory" | "bankruptcy" | "abandoned";

/** Central visual/audio event mapping. Effects are one-shot and never participate in rules. */
export class FeedbackController {
  private readonly scene: Phaser.Scene;
  private readonly juice: Juice;
  private reducedMotion = false;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    this.juice = new Juice(scene);
  }

  setReducedMotion(reduced: boolean): void { this.reducedMotion = reduced; }

  built(at: Point, target?: Phaser.GameObjects.GameObject): void {
    Sfx.play("pickup", 0.8);
    if (this.reducedMotion) return;
    if (target) {
      (target as Phaser.GameObjects.Sprite).setScale(0.72);
      this.scene.tweens.add({ targets: target, scaleX: 1, scaleY: 1, duration: 190, ease: "Back.easeOut" });
    }
    this.burst(at, 8, 100);
  }

  illegal(at: Point, reason: string, target?: Phaser.GameObjects.GameObject): void {
    Sfx.play("hit", 0.6);
    this.juice.floatText(at.x, at.y, `✕ ${reason}`, gameConfig.palette.danger, 16);
    if (this.reducedMotion) return;
    if (target) {
      const originalX = "x" in target && typeof target.x === "number" ? target.x : at.x;
      this.scene.tweens.add({ targets: target, x: { from: originalX - 4, to: originalX + 4 }, duration: 42, yoyo: true, repeat: 2 });
    } else this.juice.shake(0.003, 70);
  }

  connection(at: Point): void {
    Sfx.play("powerup", 0.55);
    this.juice.floatText(at.x, at.y, "⌁ 网络已连接", gameConfig.palette.accent, 16);
    if (!this.reducedMotion) this.burst(at, 10, 120);
  }

  residents(at: Point, amount: number): void {
    if (amount === 0) return;
    Sfx.play(amount > 0 ? "pickup" : "hit", 0.45);
    this.juice.floatText(at.x, at.y, `${amount > 0 ? "+" : ""}${Math.round(amount)} 人`, amount > 0 ? "#b8ffba" : "#ffd0c8", 18);
    if (!this.reducedMotion && amount > 0) this.windowLights(at);
  }

  settlement(at: Point, lines: readonly { label: string; amount: number }[]): void {
    lines.slice(0, 6).forEach((line, index) => {
      this.scene.time.delayedCall(index * (this.reducedMotion ? 10 : 90), () => {
        const sign = line.amount >= 0 ? "+" : "";
        this.juice.floatText(at.x, at.y + index * 4, `${line.label} ${sign}${Math.round(line.amount)}`, line.amount >= 0 ? "#b8ffba" : "#ffd0c8", 16);
        Sfx.playPitched(line.amount >= 0 ? "pickup" : "hit", Math.min(index, 4), 0.25);
      });
    });
  }

  pollutedWaterTower(at: Point, modifier: number, target?: { setTint: (color: number) => unknown }): void {
    const percent = Math.round(modifier * 100);
    target?.setTint(percent < 55 ? 0x8b6955 : percent < 80 ? 0xb99b69 : 0xffffff);
    this.juice.floatText(at.x, at.y, `💧 污染修正 ${percent}%`, percent < 70 ? "#fff4c2" : "#d5fbff", 16);
    if (percent < 70) Sfx.play("hit", 0.45);
  }

  milestone(kind: "tutorial" | "grant" | "star" | "stability", value: number, reward?: number): void {
    const text = kind === "star" ? `★ 城市达到 ${value} 星` : kind === "grant" ? `规划补助 +$${Math.round(reward ?? value)}` : kind === "stability" ? `稳定进度 ${value}/30` : `教学完成 ${value}`;
    const banner = this.scene.add.text(this.scene.scale.width / 2, 150, text, {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "26px", color: "#17343a",
      backgroundColor: gameConfig.palette.accent, padding: { x: 22, y: 10 }, stroke: "#ffffff", strokeThickness: 2,
    }).setOrigin(0.5).setDepth(260).setScrollFactor(0);
    Sfx.play("powerup");
    if (this.reducedMotion) {
      this.scene.time.delayedCall(900, () => banner.destroy());
    } else {
      banner.setScale(0.75);
      this.scene.tweens.add({ targets: banner, scale: 1, duration: 180, ease: "Back.easeOut" });
      this.scene.tweens.add({ targets: banner, alpha: 0, y: 125, delay: 1000, duration: 350, onComplete: () => banner.destroy() });
      this.burst({ x: this.scene.scale.width / 2, y: 150 }, 18, 170);
    }
  }

  disasterAlert(kind: DisasterKind, daysRemaining: number): void {
    Sfx.play(kind === "majorStorm" ? "explosion" : "hit", 0.65);
    if (!this.reducedMotion) this.juice.flash(217, 75, 61, 90);
    const label = kind === "fire" ? "火灾" : kind === "blackout" ? "停电" : kind === "pollutionLeak" ? "污染泄漏" : kind === "majorStorm" ? "大型风暴" : "风暴";
    this.juice.floatText(this.scene.scale.width / 2, 145, `⚠ ${label}：${daysRemaining}日后`, "#fff4c2", 20);
  }

  disasterImpact(kind: DisasterKind, points: readonly Point[]): void {
    Sfx.play(kind === "blackout" ? "hit" : "explosion", 0.75);
    if (!this.reducedMotion) {
      this.juice.shake(kind === "majorStorm" ? 0.009 : 0.005, kind === "majorStorm" ? 180 : 110);
      for (const point of points.slice(0, kind === "majorStorm" ? 12 : 6)) this.burst(point, kind === "fire" ? 13 : 9, kind === "majorStorm" ? 210 : 145);
    }
    for (const point of points.slice(0, 4)) this.juice.floatText(point.x, point.y, kind === "fire" ? "🔥 火灾" : kind.includes("storm") || kind === "majorStorm" ? "✦ 风暴损伤" : "⚠ 故障", "#ffd0c8", 16);
  }

  repaired(at: Point, target?: Phaser.GameObjects.GameObject): void {
    Sfx.play("powerup", 0.7);
    this.juice.floatText(at.x, at.y, "🔧 已修复", "#b8ffba", 18);
    if (!this.reducedMotion) {
      if (target) this.juice.pulse(target, 1.08, 100);
      this.burst(at, 10, 120);
    }
  }

  gameEnded(result: EndResult): void {
    if (result !== "victory") {
      Sfx.play("lose");
      if (!this.reducedMotion) this.juice.flash(120, 20, 20, 180);
      return;
    }
    Sfx.play("win");
    if (this.reducedMotion) return;
    this.juice.flash(255, 212, 71, 220);
    const flash = sheetFrame("flash");
    if (!flash) return;
    for (let i = 0; i < 18; i += 1) {
      const sprite = this.scene.add.sprite(
        Phaser.Math.Between(80, this.scene.scale.width - 80),
        Phaser.Math.Between(120, this.scene.scale.height - 100),
        flash.key,
        flash.index,
      ).setDepth(250).setScale(0.15).setAlpha(0);
      this.scene.tweens.add({
        targets: sprite, alpha: 1, scale: 0.45, angle: 90, yoyo: true,
        delay: i * 55, duration: 420, onComplete: () => sprite.destroy(),
      });
    }
  }

  private burst(at: Point, count: number, speed: number): void {
    const flash = sheetFrame("flash");
    if (flash) this.juice.burst(at.x, at.y, flash.key, count, speed);
  }

  private windowLights(at: Point): void {
    const flash = sheetFrame("flash");
    if (!flash) return;
    for (let i = 0; i < 4; i += 1) {
      const light = this.scene.add.sprite(at.x + (i % 2) * 12 - 6, at.y + Math.floor(i / 2) * 10 - 5, flash.key, flash.index)
        .setDepth(40).setDisplaySize(7, 7).setAlpha(0);
      this.scene.tweens.add({ targets: light, alpha: 1, yoyo: true, delay: i * 45, duration: 180, onComplete: () => light.destroy() });
    }
  }
}
