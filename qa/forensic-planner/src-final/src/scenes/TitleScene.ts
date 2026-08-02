import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { Backdrop } from "../systems/Backdrop";
import { InputRouter } from "../systems/InputRouter";
import { Sfx } from "../systems/Sfx";

export class TitleScene extends Phaser.Scene {
  constructor() { super("TitleScene"); }

  create(): void {
    const { width, height } = this.scale;
    this.cameras.main.setBackgroundColor(gameConfig.palette.bg);
    Backdrop.draw(this, 0.58);
    InputRouter.shield(this.add.rectangle(width / 2, height / 2, 760, 520, 0x10272b, 0.96)
      .setStrokeStyle(4, 0xffd447).setDepth(20));
    const title = this.add.text(width / 2, 150, "像素都市规划师", {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "52px", color: gameConfig.palette.accent,
      stroke: "#020617", strokeThickness: 5,
    }).setOrigin(0.5).setDepth(21).setScale(0.9);
    this.tweens.add({ targets: title, scale: 1, duration: 420, ease: "Back.easeOut" });
    this.add.text(width / 2, 245,
      "目标：人口500 · 满意度75 · 污染严格低于35 · 评分800\n并连续稳定30个游戏日，建设一座五星韧性都市。", {
        fontFamily: "Inter, system-ui, sans-serif", fontSize: "22px", color: "#ffffff", align: "center",
        lineSpacing: 10, wordWrap: { width: 680 }, stroke: "#020617", strokeThickness: 3,
      }).setOrigin(0.5).setDepth(21);
    this.add.text(width / 2, 352,
      "道路优先：住宅、商业、电厂和水塔必须邻接道路。\n污染敏感供水：水塔远离电厂，污染下降后容量会按日恢复。", {
        fontFamily: "Inter, system-ui, sans-serif", fontSize: "19px", color: "#d5fbff", align: "center",
        lineSpacing: 8, wordWrap: { width: 680 }, stroke: "#020617", strokeThickness: 3,
      }).setOrigin(0.5).setDepth(21);
    this.add.text(width / 2, 438, "Space 暂停规划   ·   1 / 2 / 3 切换 ×1 / ×2 / ×4 速度", {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "18px", color: "#fff4c2", stroke: "#020617", strokeThickness: 3,
    }).setOrigin(0.5).setDepth(21);

    const begin = (): void => {
      Sfx.play("select");
      this.scene.start("PlayScene");
    };
    const button = this.add.rectangle(width / 2, 535, 320, 68, 0x237f83, 1)
      .setStrokeStyle(3, 0xffffff).setDepth(22).setInteractive({ useHandCursor: true });
    this.add.text(width / 2, 535, "开始规划", {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "26px", color: "#ffffff", stroke: "#020617", strokeThickness: 3,
    }).setOrigin(0.5).setDepth(23);
    button.on(Phaser.Input.Events.POINTER_DOWN, begin);
    this.input.keyboard?.once("keydown-SPACE", begin);
  }
}
