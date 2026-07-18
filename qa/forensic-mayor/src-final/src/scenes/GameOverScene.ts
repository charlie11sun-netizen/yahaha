import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";

interface GameOverData {
  score?: number;
  outcome?: "victory" | "bankruptcy" | "abandonment";
  day?: number;
  population?: number;
  satisfaction?: number;
  cityScore?: number;
}

export class GameOverScene extends Phaser.Scene {
  private score = 0;
  private outcome: NonNullable<GameOverData["outcome"]> = "bankruptcy";
  private detail = "";

  constructor() { super("GameOverScene"); }

  init(data: GameOverData): void {
    this.score = Math.max(0, Math.floor(data.score ?? 0));
    this.outcome = data.outcome ?? "bankruptcy";
    this.detail = `第 ${data.day ?? 1} 日 · 人口 ${Math.round(data.population ?? 0)} · 满意 ${Math.round(data.satisfaction ?? 0)} · 城市评分 ${Math.round(data.cityScore ?? 0)}`;
  }

  create(): void {
    const { width, height } = this.scale;
    const { palette } = gameConfig;
    this.cameras.main.setBackgroundColor(palette.bg);
    const won = this.outcome === "victory";
    const edge = won ? palette.accent : palette.danger;
    const panel = this.add.rectangle(width / 2, height / 2, 680, 310, colorNum(palette.surface), 0.96)
      .setStrokeStyle(2, colorNum(edge)).setScale(0.9);
    this.tweens.add({ targets: panel, scale: 1, duration: 300, ease: "Back.easeOut" });
    const titles = { victory: "市政审计通过！", bankruptcy: "城市财政破产", abandonment: "居民离城，城市废弃" };
    this.add.text(width / 2, height / 2 - 92, titles[this.outcome], {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "46px",
      color: won ? palette.accent : palette.danger,
    }).setOrigin(0.5);
    this.add.text(width / 2, height / 2 - 28, `最终得分 ${this.score.toLocaleString()}`, {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "26px",
      color: palette.primary,
    }).setOrigin(0.5);
    this.add.text(width / 2, height / 2 + 18, this.detail, {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "18px",
      color: "#cbd5e1",
    }).setOrigin(0.5);
    const button = this.add.text(width / 2, height / 2 + 92, "重新开始（Enter / R）", {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "20px", color: "#ffffff",
      backgroundColor: palette.primary, padding: { x: 22, y: 12 },
    }).setOrigin(0.5).setInteractive({ useHandCursor: true });
    const restart = (): void => { this.scene.start("PlayScene"); };
    button.once("pointerdown", restart);
    this.input.keyboard?.once("keydown-R", restart);
    this.input.keyboard?.once("keydown-ENTER", restart);
  }
}

export { GameOverScene as EndScene };
