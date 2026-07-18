import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { InputRouter } from "../systems/InputRouter";
import { Sfx } from "../systems/Sfx";

type Tool = "road" | "residential" | "commercial" | "powerPlant" | "waterTower" | "demolish" | null;
type Overlay = "power" | "water" | "pollution" | null;
type Speed = 1 | 2 | 4;
type SliceKey = "clock" | "economy" | "utilities" | "cityMetrics" | "disaster" | "progression" | string;
type HudSnapshot = {
  clock: { day: number; paused: boolean; speed: Speed };
  economy: { funds: number; netIncome: number; bankruptcyDays: number };
  utilities: { powerSupply: number; powerDemand: number; waterSupply: number; waterDemand: number; blockedCauses?: readonly string[] };
  cityMetrics: { population: number; pollution: number; happiness: number; score: number; stars: number; stabilityDays: number; abandonmentDays: number };
};
type DetailView = {
  title: string;
  roadConnected: boolean;
  power: string;
  water: string;
  pollution: number;
  capacity: string;
  maintenance: number;
  health: number;
  maxHealth: number;
  repairCost: number;
  waterBaseCapacity?: number;
  waterPollutionModifier?: number;
  waterActualCapacity?: number;
  actionableCause?: string;
  canRepair?: boolean;
};
type HudCallbacks = {
  onTool?: (tool: Tool) => void;
  onPause?: () => void;
  onSpeed?: (speed: Speed) => void;
  onOverlay?: (overlay: Overlay) => void;
  onRepair?: () => void;
  onAlertLocate?: () => void;
  onRestart?: () => void;
};
type Button = {
  bg: Phaser.GameObjects.Rectangle;
  label: Phaser.GameObjects.Text;
  enabled: boolean;
  selected: boolean;
  action: () => void;
};

const TOP_DEPTH = 200;
const PANEL = 0x17343a;
const PANEL_ALPHA = 0.96;
const WHITE = "#ffffff";

/** Persistent, signal-driven HUD and controls. All objects are built once and updated in place. */
export class HudController {
  private readonly scene: Phaser.Scene;
  private readonly callbacks: HudCallbacks;
  private readonly metrics = new Map<string, Phaser.GameObjects.Text>();
  private readonly buttons = new Map<string, Button>();
  private readonly detailPanel: Phaser.GameObjects.Container;
  private readonly detailTitle: Phaser.GameObjects.Text;
  private readonly detailBody: Phaser.GameObjects.Text;
  private readonly repairButton: Button;
  private readonly alertBar: Phaser.GameObjects.Container;
  private readonly alertText: Phaser.GameObjects.Text;
  private readonly outcomePanel: Phaser.GameObjects.Container;
  private readonly outcomeTitle: Phaser.GameObjects.Text;
  private readonly outcomeBody: Phaser.GameObjects.Text;
  private readonly causeText: Phaser.GameObjects.Text;
  private detailOpen = false;
  private alertOpen = false;
  private outcomeOpen = false;
  private cache = new Map<string, string>();

  constructor(scene: Phaser.Scene, callbacks: HudCallbacks = {}) {
    this.scene = scene;
    this.callbacks = callbacks;
    this.buildTopHud();
    this.buildToolbar();

    const detailBg = InputRouter.shield(scene.add.rectangle(scene.scale.width - 8, 105, 270, 430, PANEL, PANEL_ALPHA)
      .setOrigin(1, 0).setStrokeStyle(2, 0xffd447).setScrollFactor(0));
    this.detailTitle = scene.add.text(scene.scale.width - 258, 120, "建筑详情", this.textStyle(20, "#ffd447"));
    this.detailBody = scene.add.text(scene.scale.width - 258, 158, "", {
      ...this.textStyle(16), wordWrap: { width: 238 }, lineSpacing: 7,
    });
    const close = this.makeButton(scene.scale.width - 52, 129, 58, 38, "关闭", () => this.hideDetails(), 16);
    this.repairButton = this.makeButton(scene.scale.width - 143, 497, 220, 48, "🔧 修复", () => this.callbacks.onRepair?.());
    this.detailPanel = scene.add.container(0, 0, [detailBg, this.detailTitle, this.detailBody, close.bg, close.label, this.repairButton.bg, this.repairButton.label])
      .setDepth(TOP_DEPTH + 5).setScrollFactor(0).setVisible(false);

    const alertBg = InputRouter.shield(scene.add.rectangle(scene.scale.width / 2, 104, 660, 44, 0x8d2d26, 0.98)
      .setStrokeStyle(2, 0xffd447).setScrollFactor(0));
    this.alertText = scene.add.text(scene.scale.width / 2 - 305, 104, "", this.textStyle(17, WHITE)).setOrigin(0, 0.5);
    const locate = this.makeButton(scene.scale.width / 2 + 270, 104, 84, 34, "定位", () => this.callbacks.onAlertLocate?.(), 16);
    this.alertBar = scene.add.container(0, 0, [alertBg, this.alertText, locate.bg, locate.label])
      .setDepth(TOP_DEPTH + 8).setScrollFactor(0).setVisible(false);

    const modalBg = InputRouter.shield(scene.add.rectangle(scene.scale.width / 2, scene.scale.height / 2, 610, 400, 0x10272b, 0.99)
      .setStrokeStyle(4, 0xffd447).setScrollFactor(0));
    this.outcomeTitle = scene.add.text(scene.scale.width / 2, 235, "", this.textStyle(34, "#ffd447")).setOrigin(0.5);
    this.outcomeBody = scene.add.text(scene.scale.width / 2, 300, "", {
      ...this.textStyle(20), align: "center", lineSpacing: 10, wordWrap: { width: 520 },
    }).setOrigin(0.5, 0);
    const restart = this.makeButton(scene.scale.width / 2, 500, 280, 64, "重新开始", () => this.callbacks.onRestart?.(), 24);
    this.outcomePanel = scene.add.container(0, 0, [modalBg, this.outcomeTitle, this.outcomeBody, restart.bg, restart.label])
      .setDepth(TOP_DEPTH + 20).setScrollFactor(0).setVisible(false);

    this.causeText = scene.add.text(18, 102, "", {
      ...this.textStyle(16, "#fff4c2"), backgroundColor: "#8d2d26", padding: { x: 8, y: 5 },
    }).setDepth(TOP_DEPTH + 2).setScrollFactor(0).setVisible(false);
  }

  /** Update only slices named by SimulationChanged.changed. */
  updateSimulation(changed: readonly SliceKey[], snapshot: HudSnapshot): void {
    const changedSet = new Set(changed);
    if (changedSet.has("clock")) {
      this.setMetric("day", `日期 ${snapshot.clock.day}`);
      this.setMetric("speed", snapshot.clock.paused ? "⏸ 规划暂停" : `速度 ×${snapshot.clock.speed}`);
      this.setButtonSelected("pause", snapshot.clock.paused);
      this.setButtonSelected("speed1", !snapshot.clock.paused && snapshot.clock.speed === 1);
      this.setButtonSelected("speed2", !snapshot.clock.paused && snapshot.clock.speed === 2);
      this.setButtonSelected("speed4", !snapshot.clock.paused && snapshot.clock.speed === 4);
    }
    if (changedSet.has("economy")) {
      const sign = snapshot.economy.netIncome >= 0 ? "+" : "";
      this.setMetric("funds", `资金 $${Math.round(snapshot.economy.funds)}  日净 ${sign}${Math.round(snapshot.economy.netIncome)}`);
      this.setMetric("bankruptcy", `破产危险 ${snapshot.economy.bankruptcyDays}/20日`);
    }
    if (changedSet.has("utilities")) {
      this.setMetric("power", `⚡ 电 ${Math.round(snapshot.utilities.powerSupply)}/${Math.round(snapshot.utilities.powerDemand)}`);
      this.setMetric("water", `💧 水 ${Math.round(snapshot.utilities.waterSupply)}/${Math.round(snapshot.utilities.waterDemand)}`);
      const causes = snapshot.utilities.blockedCauses?.filter(Boolean) ?? [];
      this.causeText.setText(causes.length ? `需处理：${causes.join("；")}` : "").setVisible(causes.length > 0);
    }
    if (changedSet.has("cityMetrics")) {
      this.setMetric("population", `人口 ${Math.round(snapshot.cityMetrics.population)}/500`);
      this.setMetric("pollution", `污染 ${snapshot.cityMetrics.pollution.toFixed(1)}/<35`);
      this.setMetric("happiness", `满意 ${snapshot.cityMetrics.happiness.toFixed(1)}/75`);
      this.setMetric("score", `评分 ${Math.round(snapshot.cityMetrics.score)}/800`);
      this.setMetric("stars", `星级 ${"★".repeat(Math.max(0, snapshot.cityMetrics.stars))}${"☆".repeat(Math.max(0, 5 - snapshot.cityMetrics.stars))}`);
      this.setMetric("stability", `稳定 ${snapshot.cityMetrics.stabilityDays}/30日`);
      this.setMetric("abandonment", `废弃危险 ${snapshot.cityMetrics.abandonmentDays}/15日`);
    }
  }

  /** Compatibility with the original scaffold HUD while scenes are migrated by IntegrationAgent. */
  update(state: { score: number; targetScore: number; lives: number }): void {
    this.setMetric("funds", `评分 ${state.score}/${state.targetScore}`);
    this.setMetric("population", `机会 ${state.lives}`);
  }

  updateInteraction(tool: Tool, overlay: Overlay): void {
    for (const name of ["road", "residential", "commercial", "powerPlant", "waterTower", "demolish"]) {
      this.setButtonSelected(name, name === tool);
    }
    for (const name of ["power", "water", "pollution"]) this.setButtonSelected(`overlay-${name}`, name === overlay);
  }

  setToolAvailability(tool: Exclude<Tool, null>, enabled: boolean, reason = ""): void {
    this.setButtonEnabled(tool, enabled, reason);
  }

  showDetails(view: DetailView): void {
    this.detailOpen = true;
    this.detailTitle.setText(view.title);
    const damage = Math.max(0, view.maxHealth - view.health);
    const waterCapacity = view.waterBaseCapacity === undefined ? "" :
      `\n水塔基础 ${Math.round(view.waterBaseCapacity)}\n污染修正 ${Math.round((view.waterPollutionModifier ?? 1) * 100)}%\n实际容量 ${Math.round(view.waterActualCapacity ?? 0)}`;
    const cause = view.actionableCause ? `\n\n需处理：${view.actionableCause}` : "";
    this.detailBody.setText([
      `道路 ${view.roadConnected ? "✓ 已连接" : "✕ 未连接"}`,
      `供电 ${view.power}`,
      `供水 ${view.water}`,
      `本格污染 ${view.pollution.toFixed(1)}`,
      `产能/入住 ${view.capacity}`,
      `维护 $${Math.round(view.maintenance)}/日`,
      `损伤 ${Math.round(damage)}/${Math.round(view.maxHealth)}`,
      `修复费 $${Math.round(view.repairCost)}${waterCapacity}${cause}`,
    ].join("\n"));
    this.setButtonEnabledObject(this.repairButton, view.canRepair !== false && damage > 0, damage <= 0 ? "无需修复" : "");
    this.detailPanel.setVisible(true);
  }

  hideDetails(): void {
    this.detailOpen = false;
    this.detailPanel.setVisible(false);
  }

  isDetailsOpen(): boolean { return this.detailOpen; }

  showAlert(message: string): void {
    this.alertOpen = true;
    this.alertText.setText(`⚠ ${message}`);
    this.alertBar.setVisible(true);
  }

  hideAlert(): void {
    this.alertOpen = false;
    this.alertBar.setVisible(false);
  }

  isAlertOpen(): boolean { return this.alertOpen; }

  showOutcome(result: "victory" | "bankruptcy" | "abandoned", summary: { population: number; highestScore: number; days: number }): void {
    this.outcomeOpen = true;
    const victory = result === "victory";
    this.outcomeTitle.setText(victory ? "★★★★★ 城市典范" : result === "bankruptcy" ? "城市破产" : "城市被废弃");
    this.outcomeBody.setText(`${victory ? "目标稳定达成！" : "仍可重新规划并再次挑战。"}\n最终人口 ${Math.round(summary.population)}\n最高评分 ${Math.round(summary.highestScore)}\n运营 ${Math.round(summary.days)} 日`);
    this.outcomePanel.setVisible(true);
    Sfx.play(victory ? "win" : "lose");
  }

  hideOutcome(): void {
    this.outcomeOpen = false;
    this.outcomePanel.setVisible(false);
  }

  isOutcomeOpen(): boolean { return this.outcomeOpen; }

  destroy(): void {
    for (const text of this.metrics.values()) text.destroy();
    for (const button of this.buttons.values()) { button.bg.destroy(); button.label.destroy(); }
    this.metrics.clear();
    this.buttons.clear();
    this.detailPanel.destroy(true);
    this.alertBar.destroy(true);
    this.outcomePanel.destroy(true);
    this.causeText.destroy();
  }

  private buildTopHud(): void {
    const bg = InputRouter.shield(this.scene.add.rectangle(0, 0, this.scene.scale.width, 96, PANEL, PANEL_ALPHA)
      .setOrigin(0).setDepth(TOP_DEPTH).setScrollFactor(0));
    bg.setStrokeStyle(0);
    const specs = [
      ["funds", 16, 10], ["population", 318, 10], ["power", 478, 10], ["water", 630, 10],
      ["pollution", 780, 10], ["happiness", 930, 10], ["day", 1090, 10],
      ["score", 16, 53], ["stars", 196, 53], ["stability", 398, 53], ["bankruptcy", 600, 53],
      ["abandonment", 840, 53], ["speed", 1080, 53],
    ] as const;
    for (const [key, x, y] of specs) {
      const text = this.scene.add.text(x, y, "—", this.textStyle(18)).setDepth(TOP_DEPTH + 1).setScrollFactor(0);
      this.metrics.set(key, text);
    }
  }

  private buildToolbar(): void {
    const y = this.scene.scale.height - 54;
    InputRouter.shield(this.scene.add.rectangle(0, this.scene.scale.height - 108, this.scene.scale.width, 108, PANEL, PANEL_ALPHA)
      .setOrigin(0).setDepth(TOP_DEPTH).setScrollFactor(0));
    const tools: Array<[string, string, number, Tool]> = [
      ["road", "R 道路 $40", 58, "road"], ["residential", "H 住宅 $300", 174, "residential"],
      ["commercial", "C 商业 $450", 290, "commercial"], ["powerPlant", "E 电厂 $1200", 406, "powerPlant"],
      ["waterTower", "W 水塔 $900", 522, "waterTower"], ["demolish", "X 拆除", 638, "demolish"],
    ];
    for (const [key, label, x, tool] of tools) this.buttons.set(key, this.makeButton(x, y, 108, 48, label, () => this.callbacks.onTool?.(tool), 15));
    this.buttons.set("overlay-power", this.makeButton(770, y - 27, 96, 42, "⚡ 电网", () => this.callbacks.onOverlay?.("power"), 15));
    this.buttons.set("overlay-water", this.makeButton(872, y - 27, 96, 42, "💧 水网", () => this.callbacks.onOverlay?.("water"), 15));
    this.buttons.set("overlay-pollution", this.makeButton(974, y - 27, 112, 42, "▧ 污染", () => this.callbacks.onOverlay?.("pollution"), 15));
    this.buttons.set("pause", this.makeButton(770, y + 26, 96, 42, "Space 暂停", () => this.callbacks.onPause?.(), 14));
    this.buttons.set("speed1", this.makeButton(872, y + 26, 62, 42, "1 ×1", () => this.callbacks.onSpeed?.(1), 15));
    this.buttons.set("speed2", this.makeButton(940, y + 26, 62, 42, "2 ×2", () => this.callbacks.onSpeed?.(2), 15));
    this.buttons.set("speed4", this.makeButton(1008, y + 26, 62, 42, "3 ×4", () => this.callbacks.onSpeed?.(4), 15));
    this.buttons.set("cancel", this.makeButton(1148, y, 142, 48, "Esc 取消", () => this.callbacks.onTool?.(null), 16));
  }

  private makeButton(x: number, y: number, width: number, height: number, label: string, action: () => void, size = 16): Button {
    const bg = this.scene.add.rectangle(x, y, width, height, 0x237f83, 1).setStrokeStyle(2, 0xffffff, 0.8)
      .setDepth(TOP_DEPTH + 3).setScrollFactor(0).setInteractive({ useHandCursor: true });
    const text = this.scene.add.text(x, y, label, this.textStyle(size)).setOrigin(0.5).setDepth(TOP_DEPTH + 4).setScrollFactor(0);
    const button: Button = { bg, label: text, enabled: true, selected: false, action };
    bg.on(Phaser.Input.Events.POINTER_DOWN, () => {
      if (!button.enabled) return;
      button.action();
      Sfx.play("select");
    });
    bg.on(Phaser.Input.Events.POINTER_OVER, () => { if (button.enabled && !button.selected) bg.setFillStyle(0x2e9ca1); });
    bg.on(Phaser.Input.Events.POINTER_OUT, () => this.paintButton(button));
    return button;
  }

  private setMetric(key: string, value: string): void {
    if (this.cache.get(key) === value) return;
    this.cache.set(key, value);
    this.metrics.get(key)?.setText(value);
  }

  private setButtonSelected(key: string, selected: boolean): void {
    const button = this.buttons.get(key);
    if (!button || button.selected === selected) return;
    button.selected = selected;
    this.paintButton(button);
  }

  private setButtonEnabled(key: string, enabled: boolean, reason: string): void {
    const button = this.buttons.get(key);
    if (!button) return;
    this.setButtonEnabledObject(button, enabled, reason);
  }

  private setButtonEnabledObject(button: Button, enabled: boolean, reason: string): void {
    button.enabled = enabled;
    button.bg.input!.enabled = enabled;
    button.label.setAlpha(enabled ? 1 : 0.58);
    if (reason) button.bg.setData("disabledReason", reason);
    this.paintButton(button);
  }

  private paintButton(button: Button): void {
    button.bg.setFillStyle(!button.enabled ? 0x59656a : button.selected ? 0xffb000 : 0x237f83, 1);
    button.bg.setStrokeStyle(button.selected ? 3 : 2, button.selected ? 0xffffff : 0xb7e7e8, 0.9);
  }

  private textStyle(size: number, color = WHITE): Phaser.Types.GameObjects.Text.TextStyle {
    return { fontFamily: "Inter, system-ui, sans-serif", fontSize: `${size}px`, color, stroke: "#020617", strokeThickness: 3 };
  }
}

// Temporary source-compatible name for the scaffold PlayScene; IntegrationAgent should use HudController.
export { HudController as Hud };
