import Phaser from "phaser";
import { gameConfig, sheetFrame } from "../config/gameConfig";
import { Juice } from "../systems/Juice";
import { Sfx, type SfxName } from "../systems/Sfx";
import type { FeedbackEventName } from "./types";

export interface FeedbackContext {
  x?: number;
  y?: number;
  message?: string;
  amount?: number;
  severe?: boolean;
}

const AUDIO: Record<FeedbackEventName, SfxName> = {
  "placement-ok": "select",
  "placement-rejected": "hit",
  "network-connected": "powerup",
  income: "pickup",
  milestone: "powerup",
  "disaster-warning": "jump",
  "disaster-start": "explosion",
  "disaster-resolved": "powerup",
  "score-threshold": "pickup",
  "stable-day": "select",
  pause: "select",
  speed: "shoot",
  victory: "win",
  defeat: "lose",
};

const LABELS: Record<FeedbackEventName, string> = {
  "placement-ok": "建设完成",
  "placement-rejected": "无法建设",
  "network-connected": "网络已接通",
  income: "今日结算",
  milestone: "人口补助已到账",
  "disaster-warning": "灾害预警",
  "disaster-start": "灾害发生",
  "disaster-resolved": "灾害已解决",
  "score-threshold": "城市评分提升",
  "stable-day": "稳定审计 +1日",
  pause: "模拟暂停",
  speed: "模拟速度已调整",
  victory: "连续六十日稳定执政",
  defeat: "本届市政结束",
};

export class FeedbackController {
  private readonly juice: Juice;
  private reducedMotion = false;
  private activeParticleBudget = 0;
  private readonly maxParticles = 80;

  constructor(private readonly scene: Phaser.Scene) {
    this.juice = new Juice(scene);
  }

  setReducedMotion(reduced: boolean): void { this.reducedMotion = reduced; }
  get particleCount(): number { return this.activeParticleBudget; }

  emit(event: FeedbackEventName, context: FeedbackContext = {}): void {
    const x = context.x ?? this.scene.scale.width / 2;
    const y = context.y ?? this.scene.scale.height / 2;
    const message = context.message ?? LABELS[event];
    Sfx.play(AUDIO[event], event === "stable-day" ? 0.45 : 0.8);
    this.scene.events.emit("sfx:event", { name: event, preset: AUDIO[event] });
    this.scene.events.emit("accessibility:announce", message);

    switch (event) {
      case "placement-ok":
        this.float(x, y, `✓ ${message}`, "#66f2a3");
        this.burst(x, y, 8);
        break;
      case "placement-rejected":
        this.float(x, y, `✕ ${message}`, "#ff7180");
        if (!this.reducedMotion) this.juice.shake(0.003, 80);
        break;
      case "network-connected":
        this.float(x, y, `⚡ ${message}`, "#62d9ff");
        this.burst(x, y, 10);
        break;
      case "income":
        this.float(x, y, `${(context.amount ?? 0) >= 0 ? "+" : ""}¥${Math.round(context.amount ?? 0)}`, (context.amount ?? 0) >= 0 ? "#66f2a3" : "#ffb35c");
        break;
      case "milestone":
      case "score-threshold":
        this.banner(message, "#ffd166");
        this.burst(x, y, 18);
        break;
      case "disaster-warning":
        this.banner(`⚠ ${message}`, "#ffd166");
        break;
      case "disaster-start":
        this.banner(`! ${message}`, "#ff7180");
        if (!this.reducedMotion) { this.juice.flash(217, 75, 85, 100); this.juice.shake(0.006, 150); }
        this.burst(x, y, 20);
        break;
      case "disaster-resolved":
        this.banner(`✓ ${message}`, "#66f2a3");
        this.burst(x, y, 14);
        break;
      case "stable-day":
        this.float(x, y, `◆ ${message}`, "#8fe8c1", 17);
        break;
      case "pause":
      case "speed":
        this.banner(message, "#dbeafe", 700);
        break;
      case "victory":
        this.banner(`◆ ${message}`, "#ffd166", 2600);
        this.burst(x, y, 30);
        if (!this.reducedMotion) this.juice.flash(255, 220, 110, 180);
        break;
      case "defeat":
        this.banner(message, "#ff7180", 2200);
        if (!this.reducedMotion) this.juice.shake(context.severe ? 0.01 : 0.006, 250);
        break;
    }
  }

  private float(x: number, y: number, message: string, color: string, size = 20): void {
    if (this.reducedMotion) {
      const label = this.scene.add.text(x, y, message, {
        fontFamily: "Inter, system-ui, sans-serif", fontSize: `${Math.max(16, size)}px`, color,
        backgroundColor: "#101827", stroke: "#07101f", strokeThickness: 4,
      }).setOrigin(0.5).setDepth(250);
      this.scene.time.delayedCall(650, () => label.destroy());
    } else this.juice.floatText(x, y, message, color, size);
  }

  private banner(message: string, color: string, duration = 1300): void {
    const label = this.scene.add.text(this.scene.scale.width / 2, 126, message, {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "22px", color,
      backgroundColor: "#101827", stroke: "#07101f", strokeThickness: 7,
    }).setOrigin(0.5).setScrollFactor(0).setDepth(260);
    if (!this.reducedMotion) label.setScale(0.85);
    if (!this.reducedMotion) this.juice.pulse(label, 1.05, 120);
    this.scene.time.delayedCall(duration, () => label.destroy());
  }

  private burst(x: number, y: number, requested: number): void {
    if (this.reducedMotion) return;
    const count = Math.max(0, Math.min(requested, this.maxParticles - this.activeParticleBudget));
    if (count <= 0) return;
    const texture = sheetFrame("flash")?.key ?? gameConfig.assetKeys.reward;
    if (!texture || !this.scene.textures.exists(texture)) return;
    this.activeParticleBudget += count;
    this.juice.burst(x, y, texture, count, 120);
    this.scene.time.delayedCall(700, () => { this.activeParticleBudget = Math.max(0, this.activeParticleBudget - count); });
  }
}
