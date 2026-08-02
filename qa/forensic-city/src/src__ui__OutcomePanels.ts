import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";
import { Juice } from "../systems/Juice";
import { Sfx } from "../systems/Sfx";
import type { CityPresentationCommands, OutcomePresentation } from "../presentation/CityPresentationTypes";

export interface OutcomePanelsOptions {
  commands: CityPresentationCommands;
  onVictoryLights?: () => void;
}

export interface OutcomePanels {
  readonly visible: boolean;
  show(outcome: OutcomePresentation): void;
  hide(): void;
  destroy(): void;
}

const durationText = (seconds: number): string => `${Math.floor(seconds / 60)}分${Math.floor(seconds % 60)}秒`;

export function createOutcomePanels(scene: Phaser.Scene, options: OutcomePanelsOptions): OutcomePanels {
  const root = scene.add.container(scene.scale.width / 2, scene.scale.height / 2).setDepth(120).setScrollFactor(0).setVisible(false);
  const veil = scene.add.rectangle(0, 0, scene.scale.width, scene.scale.height, 0x071018, 0.48);
  const panel = scene.add.rectangle(0, 0, 620, 480, 0x17212b, 0.97).setStrokeStyle(5, colorNum(gameConfig.palette.accent));
  const title = scene.add.text(0, -198, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "42px", color: gameConfig.palette.accent,
    fontStyle: "bold", stroke: "#000000", strokeThickness: 5,
  }).setOrigin(0.5);
  const reason = scene.add.text(0, -148, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "17px", color: "#ffffff", align: "center",
    wordWrap: { width: 540 }, stroke: "#000000", strokeThickness: 3,
  }).setOrigin(0.5);
  const stats = scene.add.text(0, -42, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "20px", color: "#ffffff", lineSpacing: 11,
    align: "left", stroke: "#000000", strokeThickness: 3,
  }).setOrigin(0.5);
  const continueBg = scene.add.rectangle(-145, 180, 250, 58, colorNum(gameConfig.palette.accent), 1).setInteractive({ useHandCursor: true });
  const continueText = scene.add.text(-145, 180, "继续建设", { fontFamily: "Inter, sans-serif", fontSize: "20px", color: "#17212b", fontStyle: "bold" }).setOrigin(0.5);
  const restartBg = scene.add.rectangle(145, 180, 250, 58, colorNum(gameConfig.palette.primary), 1).setInteractive({ useHandCursor: true });
  const restartText = scene.add.text(145, 180, "完整重开", { fontFamily: "Inter, sans-serif", fontSize: "20px", color: "#ffffff", fontStyle: "bold" }).setOrigin(0.5);
  root.add([veil, panel, title, reason, stats, continueBg, continueText, restartBg, restartText]);
  const confetti: Phaser.GameObjects.Rectangle[] = [];
  const juice = new Juice(scene);
  let current: OutcomePresentation | null = null;

  const clearConfetti = (): void => { while (confetti.length) confetti.pop()?.destroy(); };
  const celebrate = (): void => {
    options.onVictoryLights?.();
    clearConfetti();
    const colors = [colorNum(gameConfig.palette.accent), colorNum(gameConfig.palette.primary), 0xffffff, 0x55d88a];
    for (let i = 0; i < 22; i += 1) {
      const piece = scene.add.rectangle(scene.scale.width / 2 - 270 + (i * 79) % 540, scene.scale.height / 2 - 230, 7, 12, colors[i % colors.length]).setDepth(121);
      confetti.push(piece);
      scene.tweens.add({ targets: piece, y: piece.y + 300 + (i % 4) * 28, x: piece.x + ((i % 3) - 1) * 55, angle: 240 + i * 17, alpha: 0, duration: 1500 + (i % 5) * 150, ease: "Quad.easeIn" });
    }
    juice.flash(255, 211, 78, 180);
  };

  continueBg.on("pointerdown", () => {
    if (current?.kind !== "victory") return;
    Sfx.play("select"); root.setVisible(false); clearConfetti(); options.commands.requestContinueAfterVictory();
  });
  restartBg.on("pointerdown", () => {
    if (!current) return;
    Sfx.play("select"); options.commands.requestRestart(current.kind === "victory" ? "victory" : "defeat");
  });

  const panels: OutcomePanels = {
    get visible(): boolean { return root.visible; },
    show(outcome): void {
      current = outcome; root.setVisible(true);
      const won = outcome.kind === "victory";
      panel.setStrokeStyle(5, won ? colorNum(gameConfig.palette.accent) : colorNum(gameConfig.palette.danger));
      title.setColor(won ? gameConfig.palette.accent : gameConfig.palette.danger).setText(won ? "★ 都市繁荣达成 ★" : "城市经营失败");
      reason.setText(won ? `五项关键条件已连续稳定60秒\n${outcome.reason}` : `主因：${outcome.reason}`);
      stats.setText([
        `♟ 最终人口       ${outcome.stats.population}`,
        `▲ 最高人口       ${outcome.stats.peakPopulation}`,
        `¥ 累计税收       ${Math.round(outcome.stats.totalTax).toLocaleString()}`,
        `⚠ 已处理灾害     ${outcome.stats.disastersHandled}`,
        `★ 最高评分       ${Math.round(outcome.stats.peakScore)}/100`,
        `◷ 经营时长       ${durationText(outcome.stats.operatingSeconds)}`,
      ].join("\n"));
      continueBg.setVisible(won); continueText.setVisible(won);
      restartBg.setPosition(won ? 145 : 0, 180); restartText.setPosition(won ? 145 : 0, 180);
      if (won) { Sfx.play("win", 0.75); celebrate(); } else { Sfx.play("lose", 0.75); juice.shake(0.006, 220); }
    },
    hide(): void { root.setVisible(false); current = null; clearConfetti(); },
    destroy(): void { clearConfetti(); root.destroy(true); },
  };
  return panels;
}
