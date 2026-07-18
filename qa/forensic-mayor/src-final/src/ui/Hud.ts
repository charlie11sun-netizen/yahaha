import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { GameState } from "../systems/GameState";

export class Hud {
  private readonly scoreText: Phaser.GameObjects.Text;
  private readonly livesText: Phaser.GameObjects.Text;

  constructor(scene: Phaser.Scene) {
    const style: Phaser.Types.GameObjects.Text.TextStyle = {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "22px",
      color: gameConfig.palette.primary,
      stroke: "#020617",
      strokeThickness: 5,
    };
    this.scoreText = scene.add.text(24, 18, "", style).setScrollFactor(0).setDepth(50);
    this.livesText = scene.add.text(scene.scale.width - 24, 18, "", style)
      .setOrigin(1, 0).setScrollFactor(0).setDepth(50);
  }

  update(state: GameState): void {
    this.scoreText.setText(`Score ${state.score}/${state.targetScore}`);
    this.livesText.setText(`Lives ${state.lives}`);
  }
}
