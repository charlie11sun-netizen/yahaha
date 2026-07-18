import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";
import { Juice } from "../systems/Juice";
import { Sfx } from "../systems/Sfx";
import type {
  BuildTool, CityHudSnapshot, CityPresentationCommands, CoverageOverlay, PlannerTool, SimulationSpeed,
} from "../presentation/CityPresentationTypes";

export interface CityHudOptions {
  commands: CityPresentationCommands;
  onHelp?: () => void;
}

export interface CityHud {
  update(snapshot: CityHudSnapshot): void;
  setSelectedTool(tool: PlannerTool): void;
  setSelectedOverlay(overlay: CoverageOverlay): void;
  announce(message: string, tone?: "info" | "success" | "danger"): void;
  destroy(): void;
}

interface HudButton {
  root: Phaser.GameObjects.Container;
  bg: Phaser.GameObjects.Rectangle;
  label: Phaser.GameObjects.Text;
  setSelected(value: boolean): void;
  setEnabled(value: boolean, reason?: string): void;
}

const fmtMoney = (value: number): string => `${value < 0 ? "−" : ""}¥${Math.abs(Math.round(value)).toLocaleString()}`;
const fmtTime = (seconds: number): string => `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${Math.floor(seconds % 60).toString().padStart(2, "0")}`;

function makeButton(
  scene: Phaser.Scene, x: number, y: number, width: number, height: number, text: string, onPress: () => void,
): HudButton {
  const root = scene.add.container(x, y).setScrollFactor(0);
  const bg = scene.add.rectangle(0, 0, width, height, colorNum(gameConfig.palette.surface), 0.98)
    .setStrokeStyle(2, colorNum(gameConfig.palette.primary), 0.7).setInteractive({ useHandCursor: true });
  const label = scene.add.text(0, 0, text, {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "14px", color: "#17212b", align: "center", fontStyle: "bold",
  }).setOrigin(0.5);
  root.add([bg, label]);
  let enabled = true;
  bg.on("pointerover", () => { if (enabled) bg.setFillStyle(colorNum(gameConfig.palette.accent), 0.95); });
  bg.on("pointerout", () => { if (enabled) bg.setFillStyle(colorNum(gameConfig.palette.surface), 0.98); });
  bg.on("pointerdown", () => {
    if (!enabled) return;
    Sfx.play("select", 0.45); onPress();
  });
  return {
    root, bg, label,
    setSelected(value): void {
      bg.setFillStyle(value ? colorNum(gameConfig.palette.accent) : colorNum(gameConfig.palette.surface), value ? 1 : 0.98);
      bg.setStrokeStyle(value ? 3 : 2, value ? 0x17212b : colorNum(gameConfig.palette.primary), 0.9);
    },
    setEnabled(value, reason): void {
      enabled = value; root.setAlpha(value ? 1 : 0.48);
      label.setText(reason && !value ? `${text}\n${reason}` : text);
      bg.input!.cursor = value ? "pointer" : "not-allowed";
    },
  };
}

/** Dense single-screen HUD: primary metrics stay in the top bar, planning tools
 * stay at the bottom, and the score trade-offs remain visible at right. */
export function createCityHud(scene: Phaser.Scene, options: CityHudOptions): CityHud {
  const depth = 80;
  const root = scene.add.container(0, 0).setDepth(depth).setScrollFactor(0);
  const topBg = scene.add.rectangle(0, 0, scene.scale.width, 66, 0x17212b, 0.94).setOrigin(0);
  const bottomBg = scene.add.rectangle(0, scene.scale.height - 104, scene.scale.width, 104, 0x17212b, 0.94).setOrigin(0);
  root.add([topBg, bottomBg]);
  const metricStyle: Phaser.Types.GameObjects.Text.TextStyle = {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "16px", color: "#ffffff", stroke: "#000000", strokeThickness: 2,
  };
  const funds = scene.add.text(18, 10, "", metricStyle);
  const population = scene.add.text(18, 36, "", metricStyle);
  const income = scene.add.text(190, 10, "", metricStyle);
  const satisfaction = scene.add.text(190, 36, "", metricStyle);
  const pollution = scene.add.text(370, 10, "", metricStyle);
  const score = scene.add.text(370, 36, "", { ...metricStyle, color: gameConfig.palette.accent, fontStyle: "bold" });
  const clock = scene.add.text(568, 10, "", metricStyle);
  const month = scene.add.text(568, 36, "", metricStyle);
  root.add([funds, population, income, satisfaction, pollution, score, clock, month]);

  let latest: CityHudSnapshot | null = null;
  const speedButtons = new Map<string, HudButton>();
  const makeSpeed = (x: number, text: string, speedValue?: SimulationSpeed): void => {
    const button = makeButton(scene, x, 33, 52, 42, text, () => {
      if (speedValue) options.commands.requestSimulation({ paused: false, speed: speedValue });
      else options.commands.requestSimulation({ paused: !(latest?.paused ?? true) });
    });
    button.root.setDepth(depth + 1); root.add(button.root); speedButtons.set(speedValue ? String(speedValue) : "pause", button);
  };
  makeSpeed(760, "Ⅱ\nSpace"); makeSpeed(820, "▶ 1×\n[1]", 1); makeSpeed(880, "▶▶ 2×\n[2]", 2); makeSpeed(940, "» 4×\n[3]", 4);
  const miniButton = makeButton(scene, 1012, 33, 72, 42, "地图 [M]", () => options.commands.toggleMinimap());
  const restartButton = makeButton(scene, 1094, 33, 72, 42, "重开", () => options.commands.requestRestart("hud"));
  const helpButton = makeButton(scene, 1176, 33, 72, 42, "帮助 [?]", () => options.onHelp?.());
  root.add([miniButton.root, restartButton.root, helpButton.root]);

  const scorePanel = scene.add.container(scene.scale.width - 278, 76).setDepth(depth).setScrollFactor(0);
  const scoreBg = scene.add.rectangle(0, 0, 266, 286, 0x17212b, 0.9).setOrigin(0).setStrokeStyle(2, colorNum(gameConfig.palette.accent), 0.8);
  const scoreTitle = scene.add.text(12, 9, "城市评分约束", { ...metricStyle, fontSize: "17px", color: gameConfig.palette.accent, fontStyle: "bold" });
  const partText = scene.add.text(12, 38, "", { ...metricStyle, fontSize: "14px", lineSpacing: 4 });
  const reasonText = scene.add.text(12, 158, "", { ...metricStyle, fontSize: "13px", color: "#ffd6d2", wordWrap: { width: 240 } });
  const prosperityText = scene.add.text(12, 220, "", { ...metricStyle, fontSize: "12px", color: "#ffffff", wordWrap: { width: 240 } });
  const prosperityBarBg = scene.add.rectangle(12, 270, 240, 8, 0x000000, 0.55).setOrigin(0);
  const prosperityBar = scene.add.rectangle(12, 270, 0, 8, colorNum(gameConfig.palette.accent), 1).setOrigin(0);
  scorePanel.add([scoreBg, scoreTitle, partText, reasonText, prosperityText, prosperityBarBg, prosperityBar]);

  const toolButtons = new Map<PlannerTool, HudButton>();
  const toolSpecs: readonly [PlannerTool, string, string, number][] = [
    ["road", "▦ 道路", "R", 8], ["residential", "⌂ 住宅", "H", 50], ["commercial", "▤ 商业", "C", 70],
    ["powerPlant", "⚡ 电厂 2×2", "E", 280], ["waterTower", "◆ 水塔 2×2", "W", 220],
    ["inspect", "ⓘ 检查", "I", 0], ["demolish", "⚒ 拆除 40%", "X", 0],
  ];
  toolSpecs.forEach(([tool, labelText, key, price], index) => {
    const button = makeButton(scene, 74 + index * 142, scene.scale.height - 52, 132, 78, `${labelText}\n${price ? fmtMoney(price) + " · " : ""}[${key}]`, () => options.commands.selectTool(tool));
    button.root.setDepth(depth + 1); root.add(button.root); toolButtons.set(tool, button);
  });

  const overlayButtons = new Map<CoverageOverlay, HudButton>();
  const overlays: readonly [Exclude<CoverageOverlay, "none">, string][] = [["power", "⚡电力 P"], ["water", "◆水务 U"], ["pollution", "▧污染 O"]];
  overlays.forEach(([overlay, text], index) => {
    const button = makeButton(scene, 1056 + index * 72, scene.scale.height - 76, 66, 34, text, () => options.commands.setOverlay(overlay));
    button.root.setDepth(depth + 2); root.add(button.root); overlayButtons.set(overlay, button);
  });
  const closeOverlay = makeButton(scene, 1128, scene.scale.height - 32, 138, 30, "关闭面板 [Esc]", () => options.commands.closeTopPanel());
  closeOverlay.root.setDepth(depth + 2); root.add(closeOverlay.root);

  const alertPanel = scene.add.container(scene.scale.width / 2, 92).setDepth(depth + 5).setScrollFactor(0).setVisible(false);
  const alertBg = scene.add.rectangle(0, 0, 490, 76, colorNum(gameConfig.palette.danger), 0.96).setStrokeStyle(3, 0xffffff, 0.9);
  const alertText = scene.add.text(-230, -27, "", { ...metricStyle, fontSize: "15px", wordWrap: { width: 340 } });
  const emergencyButton = makeButton(scene, 178, 0, 112, 52, "立即调度", () => { if (latest?.disaster) options.commands.requestEmergency(latest.disaster.id); });
  alertPanel.add([alertBg, alertText, emergencyButton.root]); root.add(alertPanel);

  const toast = scene.add.text(scene.scale.width / 2, scene.scale.height - 124, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "18px", color: "#ffffff", backgroundColor: "#17212b",
    padding: { x: 14, y: 9 }, stroke: "#000000", strokeThickness: 2,
  }).setOrigin(0.5).setDepth(depth + 10).setScrollFactor(0).setAlpha(0);
  const juice = new Juice(scene);

  const hud: CityHud = {
    update(snapshot): void {
      latest = snapshot;
      funds.setText(`💰 资金 ${fmtMoney(snapshot.funds)}`);
      population.setText(`♟ 人口 ${snapshot.population}`);
      income.setText(`${snapshot.netIncome >= 0 ? "▲" : "▼"} 净收入 ${fmtMoney(snapshot.netIncome)}`).setColor(snapshot.netIncome >= 0 ? "#8ff0a4" : "#ff9b91");
      satisfaction.setText(`☺ 满意度 ${Math.round(snapshot.satisfaction)}%`);
      pollution.setText(`▧ 污染住宅 ${Math.round(snapshot.pollution)}%`);
      score.setText(`★ 评分 ${Math.round(snapshot.score)}/100`);
      clock.setText(`${snapshot.paused ? "Ⅱ 已暂停" : `▶ ${snapshot.speed}×`} · ${fmtTime(snapshot.gameSeconds)}`);
      month.setText(`月度 ${snapshot.month} · 每10游戏秒结算`);
      speedButtons.get("pause")?.setSelected(snapshot.paused);
      for (const value of [1, 2, 4] as const) speedButtons.get(String(value))?.setSelected(!snapshot.paused && snapshot.speed === value);
      partText.setText(snapshot.scoreParts.slice(0, 5).map((part) => `${part.icon} ${part.label.padEnd(5, "　")} ${Math.round(part.value)}/${part.max}`).join("\n"));
      reasonText.setText(`前三项扣分原因\n${snapshot.penaltyReasons.slice(0, 3).map((reason, i) => `${i + 1}. ${reason}`).join("\n") || "✓ 暂无显著扣分"}`);
      prosperityText.setText(`繁荣稳定 ${Math.min(60, Math.floor(snapshot.prosperitySeconds))}/60秒\n${snapshot.prosperityConditions.map((c) => `${c.met ? "✓" : "○"}${c.label} ${c.current}/${c.target}`).join("  ")}`);
      prosperityBar.width = 240 * Math.max(0, Math.min(1, snapshot.prosperitySeconds / 60));
      if (snapshot.disaster) {
        const d = snapshot.disaster;
        const icon = d.type === "fire" ? "🔥" : d.type === "blackout" ? "⚡" : "◆";
        const edge = d.direction === "up" ? "↑" : d.direction === "right" ? "→" : d.direction === "down" ? "↓" : d.direction === "left" ? "←" : "";
        alertPanel.setVisible(true);
        alertBg.setFillStyle(d.warning ? colorNum(gameConfig.palette.accent) : colorNum(gameConfig.palette.danger), 0.96);
        alertText.setColor(d.warning ? "#17212b" : "#ffffff").setText(`${edge} ${icon} ${d.warning ? "灾害预警" : "灾害处理中"}：${d.targetName}\n${d.remainingSeconds.toFixed(1)}秒 · 调度 ${fmtMoney(d.dispatchCost)}${snapshot.voucherAvailable ? " · 韧性凭证半价" : ""}`);
        emergencyButton.setEnabled(d.affordable, d.affordable ? undefined : "资金不足");
      } else if (snapshot.danger) {
        alertPanel.setVisible(true); emergencyButton.root.setVisible(false);
        const danger = snapshot.danger;
        alertBg.setFillStyle(danger.kind === "debt" ? 0x8f3040 : 0x7a3fa0, 0.96);
        alertText.setColor("#ffffff").setText(`${danger.kind === "debt" ? "💸 债务危机" : "☹ 民意危机"}\n${danger.reason} · ${danger.seconds.toFixed(1)}/30秒`);
      } else {
        alertPanel.setVisible(false); emergencyButton.root.setVisible(true);
      }
    },
    setSelectedTool(tool): void { for (const [key, button] of toolButtons) button.setSelected(key === tool); },
    setSelectedOverlay(overlay): void { for (const [key, button] of overlayButtons) button.setSelected(key === overlay); },
    announce(message, tone = "info"): void {
      toast.setText(message).setColor(tone === "danger" ? "#ffd6d2" : tone === "success" ? "#baffca" : "#ffffff").setAlpha(1);
      scene.tweens.killTweensOf(toast);
      scene.tweens.add({ targets: toast, alpha: 0, delay: 1700, duration: 350 });
      if (tone === "success") { Sfx.play("powerup", 0.6); juice.pulse(score); }
      else if (tone === "danger") Sfx.play("hit", 0.5);
      else Sfx.play("select", 0.35);
    },
    destroy(): void { root.destroy(true); scorePanel.destroy(true); toast.destroy(); },
  };
  hud.setSelectedTool("inspect");
  return hud;
}
