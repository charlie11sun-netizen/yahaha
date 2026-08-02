import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";

export class BootScene extends Phaser.Scene {
  constructor() { super("BootScene"); }

  preload(): void {
    for (const asset of gameConfig.assets) {
      if (asset.kind === "image") this.load.image(asset.key, asset.path);
      else if (asset.kind === "spritesheet")
        this.load.spritesheet(asset.key, asset.path, {
          frameWidth: asset.frameWidth ?? 256,
          frameHeight: asset.frameHeight ?? 256,
        });
      else if (asset.kind === "audio") this.load.audio(asset.key, asset.path);
      else if (asset.kind === "video") this.load.video(asset.key, asset.path, true);
      else if (asset.kind === "tilemap") this.load.tilemapTiledJSON(asset.key, asset.path);
    }
  }

  create(): void {
    const { palette } = gameConfig;
    this.createFallbackTexture("player-fallback", colorNum(palette.primary), 16);
    this.createFallbackTexture("enemy-fallback", colorNum(palette.danger), 16);
    this.createFallbackTexture("reward-fallback", colorNum(palette.accent), 10);
    this.createGlowTexture("spark", 0xffffff, 6);
    this.scene.start("TitleScene");
  }

  private createFallbackTexture(key: string, color: number, radius: number): void {
    if (this.textures.exists(key)) return;
    const graphics = this.make.graphics({ x: 0, y: 0 }, false);
    graphics.fillStyle(color, 1);
    graphics.fillCircle(radius + 2, radius + 2, radius);
    graphics.lineStyle(3, 0xffffff, 0.85);
    graphics.strokeCircle(radius + 2, radius + 2, radius);
    graphics.generateTexture(key, radius * 2 + 4, radius * 2 + 4);
    graphics.destroy();
  }

  /** Soft radial dot for particle bursts and glows. */
  private createGlowTexture(key: string, color: number, radius: number): void {
    if (this.textures.exists(key)) return;
    const graphics = this.make.graphics({ x: 0, y: 0 }, false);
    for (let i = 3; i >= 1; i -= 1) {
      graphics.fillStyle(color, 0.25 * (4 - i));
      graphics.fillCircle(radius + 2, radius + 2, (radius * i) / 3);
    }
    graphics.generateTexture(key, radius * 2 + 4, radius * 2 + 4);
    graphics.destroy();
  }
}
