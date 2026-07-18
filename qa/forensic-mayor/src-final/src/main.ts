import Phaser from "phaser";
import "./styles.css";
import { gameConfig } from "./config/gameConfig";
import { BootScene } from "./scenes/BootScene";
import { TitleScene } from "./scenes/TitleScene";
import { PlayScene } from "./scenes/PlayScene";
import { GameOverScene } from "./scenes/GameOverScene";

export function createGameConfig(): Phaser.Types.Core.GameConfig {
  return {
  type: Phaser.AUTO,
  parent: "game-container",
  width: gameConfig.width,
  height: gameConfig.height,
  backgroundColor: gameConfig.palette.bg,
  scene: [BootScene, TitleScene, PlayScene, GameOverScene],
  physics: {
    default: "arcade",
    // Neutral default. Side-view / platformer designs should raise gravity.y here.
    arcade: { gravity: { x: 0, y: 0 }, debug: false },
  },
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  };
}

new Phaser.Game(createGameConfig());
