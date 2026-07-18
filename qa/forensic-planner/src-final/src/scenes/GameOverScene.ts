import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";

interface GameOverData {
  score?: number;
  won?: boolean;
}

export class GameOverScene extends Phaser.Scene {
  private score = 0;
  private won = false;

  constructor() { super("GameOverScene"); }

  init(data: GameOverData): void {
    this.score = Math.max(0, Math.floor(data.score ?? 0));
    this.won = Boolean(data.won);
  }

  create(): void {
    const { width, height } = this.scale;
    const { palette } = gameConfig;
    this.cameras.main.setBackgroundColor(palette.bg);
    const edge = this.won ? palette.accent : palette.danger;
    const panel = this.add.rectangle(width / 2, height / 2, 560, 250, colorNum(palette.surface), 0.94)
      .setStrokeStyle(2, colorNum(edge)).setScale(0.9);
    this.tweens.add({ targets: panel, scale: 1, duration: 300, ease: "Back.easeOut" });
    this.add.text(width / 2, height / 2 - 52, this.won ? "YOU WIN" : "GAME OVER", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "46px",
      color: this.won ? palette.accent : palette.danger,
    }).setOrigin(0.5);
    this.add.text(width / 2, height / 2 + 8, `Score ${this.score}`, {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "26px",
      color: palette.primary,
    }).setOrigin(0.5);
    this.add.text(width / 2, height / 2 + 60, "Press R or click to restart", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "20px",
      color: "#cbd5e1",
    }).setOrigin(0.5);
    const restart = (): void => { this.scene.start("PlayScene"); };
    this.input.once("pointerdown", restart);
    this.input.keyboard?.once("keydown-R", restart);
  }
}
