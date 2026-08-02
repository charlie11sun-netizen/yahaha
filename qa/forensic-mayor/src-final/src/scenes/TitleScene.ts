import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { Backdrop } from "../systems/Backdrop";
import { Sfx } from "../systems/Sfx";

export class TitleScene extends Phaser.Scene {
  constructor() { super("TitleScene"); }

  create(): void {
    const { width, height } = this.scale;
    const { palette } = gameConfig;
    this.cameras.main.setBackgroundColor(palette.bg);
    Backdrop.draw(this, 0.55);
    const title = this.add.text(width / 2, height * 0.34, gameConfig.title, {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "52px",
      color: palette.primary,
      align: "center",
      wordWrap: { width: width * 0.8 },
    }).setOrigin(0.5).setScale(0.9);
    this.tweens.add({ targets: title, scale: 1, duration: 420, ease: "Back.easeOut" });
    this.add.text(width / 2, height * 0.55, "铺路并接通电力与供水，连续稳定执政60日\nSpace / Enter 或点击开始", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "21px",
      color: "#cbd5e1",
      align: "center",
      wordWrap: { width: width * 0.72 },
    }).setOrigin(0.5);
    const start = this.add.text(width / 2, height * 0.72, "开始市政规划", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "20px",
      color: palette.accent,
    }).setOrigin(0.5).setPadding(22, 12, 22, 12).setBackgroundColor("#132238")
      .setInteractive({ useHandCursor: true });
    this.tweens.add({ targets: start, alpha: 0.35, duration: 750, yoyo: true, repeat: -1 });
    const begin = (): void => {
      Sfx.play("select");
      this.scene.start("PlayScene");
    };
    start.once("pointerdown", begin);
    this.input.keyboard?.once("keydown-SPACE", begin);
    this.input.keyboard?.once("keydown-ENTER", begin);
  }
}
