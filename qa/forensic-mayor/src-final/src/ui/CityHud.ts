import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import type {
  BuildTool, CityHudSnapshot, CitySettings, DisasterNotice, OverlayKind, PresentationCommands, SimulationSpeed,
} from "../presentation/types";

interface HudButton {
  container: Phaser.GameObjects.Container;
  background: Phaser.GameObjects.Rectangle;
  label: Phaser.GameObjects.Text;
  setEnabled(enabled: boolean): void;
  setSelected(selected: boolean): void;
  destroy(): void;
}

const DEPTH = 200;
const TEXT = "#f8fafc";
const PANEL = 0x132238;
const PRIMARY = Phaser.Display.Color.HexStringToColor(gameConfig.palette.primary).color;
const ACCENT = Phaser.Display.Color.HexStringToColor(gameConfig.palette.accent).color;
const DANGER = Phaser.Display.Color.HexStringToColor(gameConfig.palette.danger).color;

export class CityHud {
  private readonly topPanel: Phaser.GameObjects.Rectangle;
  private readonly statsText: Phaser.GameObjects.Text;
  private readonly utilityText: Phaser.GameObjects.Text;
  private readonly riskText: Phaser.GameObjects.Text;
  private readonly auditGraphics: Phaser.GameObjects.Graphics;
  private readonly auditText: Phaser.GameObjects.Text;
  private readonly buttons: HudButton[] = [];
  private readonly toolButtons = new Map<BuildTool, HudButton>();
  private readonly speedButtons = new Map<SimulationSpeed, HudButton>();
  private readonly overlayButtons = new Map<OverlayKind, HudButton>();
  private readonly transient: Phaser.GameObjects.GameObject[] = [];
  private pauseOverlay: Phaser.GameObjects.Container | null = null;
  private endOverlay: Phaser.GameObjects.Container | null = null;
  private settingsOverlay: Phaser.GameObjects.Container | null = null;
  private disasterPanel: Phaser.GameObjects.Container | null = null;
  private inspectorPanel: Phaser.GameObjects.Container | null = null;
  private highContrast = false;
  private reducedMotion = false;
  private snapshot: CityHudSnapshot | null = null;

  constructor(private readonly scene: Phaser.Scene, private readonly commands: PresentationCommands) {
    const width = scene.scale.width;
    this.topPanel = scene.add.rectangle(width / 2, 48, width - 24, 84, PANEL, 0.96)
      .setStrokeStyle(3, PRIMARY).setScrollFactor(0).setDepth(DEPTH);
    this.statsText = this.text(28, 18, "", 18);
    this.utilityText = this.text(420, 18, "", 18);
    this.riskText = this.text(width - 28, 18, "", 16).setOrigin(1, 0);
    this.auditGraphics = scene.add.graphics().setScrollFactor(0).setDepth(DEPTH + 2);
    this.auditText = this.text(width / 2, 58, "市政稳定审计 0/60", 16).setOrigin(0.5, 0);
    this.createToolbar();
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, this.destroy, this);
  }

  update(snapshot: CityHudSnapshot): void {
    this.snapshot = snapshot;
    const net = snapshot.economy.dailyIncome - snapshot.economy.dailyMaintenance;
    const m = snapshot.metrics;
    this.statsText.setText([
      `资金 ¥${Math.round(snapshot.economy.funds).toLocaleString()}  人口 ${Math.round(m.population)}`,
      `日收入 ${this.signed(net)}  污染 ${Math.round(m.pollution)}  满意 ${Math.round(m.satisfaction)}  评分 ${Math.round(m.score)}`,
    ]);
    this.utilityText.setText([
      `⚡ 电力 ${Math.round(m.powerDemand)}/${Math.round(m.powerCapacity)}  ◆ 供水 ${Math.round(m.waterDemand)}/${Math.round(m.waterCapacity)}`,
      `第 ${snapshot.day} 日  ${snapshot.paused ? "Ⅱ 已暂停" : `▶ ${snapshot.speed}倍速`}`,
    ]);
    const risks: string[] = [];
    if (snapshot.bankruptcyDays > 0) risks.push(`⚠ 破产倒计时 ${30 - snapshot.bankruptcyDays}日`);
    if (snapshot.abandonmentDays > 0) risks.push(`⚠ 废弃倒计时 ${30 - snapshot.abandonmentDays}日`);
    if (m.powerDemand > m.powerCapacity) risks.push("⚡ 电力缺口");
    if (m.waterDemand > m.waterCapacity) risks.push("◆ 供水缺口");
    this.riskText.setText(risks.join("\n")).setColor(risks.length ? "#ffd166" : TEXT);
    this.drawAudit(snapshot);
    for (const [speed, button] of this.speedButtons) button.setSelected(!snapshot.paused && speed === snapshot.speed);
  }

  selectTool(tool: BuildTool | null): void {
    for (const [kind, button] of this.toolButtons) button.setSelected(kind === tool);
  }

  selectOverlay(overlay: OverlayKind | null): void {
    for (const [kind, button] of this.overlayButtons) button.setSelected(kind === overlay);
  }

  showToast(message: string, tone: "info" | "success" | "warning" | "danger" = "info", duration = 1800): void {
    const colors = { info: PRIMARY, success: 0x1f9d68, warning: ACCENT, danger: DANGER };
    const label = this.scene.add.text(this.scene.scale.width / 2, 112, message, {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "20px", color: TEXT,
      backgroundColor: "#101827", stroke: "#101827", strokeThickness: 8, align: "center",
    }).setOrigin(0.5).setScrollFactor(0).setDepth(DEPTH + 20);
    label.setShadow(0, 3, Phaser.Display.Color.IntegerToColor(colors[tone]).rgba, 5, true, true);
    this.transient.push(label);
    this.scene.time.delayedCall(duration, () => {
      const remove = (): void => { label.destroy(); this.transient.splice(this.transient.indexOf(label), 1); };
      if (this.reducedMotion) remove();
      else this.scene.tweens.add({ targets: label, alpha: 0, y: 96, duration: 180, onComplete: remove });
    });
  }

  showDisaster(notice: DisasterNotice | null): void {
    this.disasterPanel?.destroy();
    this.disasterPanel = null;
    if (!notice) return;
    const width = 390;
    const children: Phaser.GameObjects.GameObject[] = [];
    const bg = this.scene.add.rectangle(0, 0, width, 130, 0x471b26, 0.98).setStrokeStyle(3, DANGER);
    const title = this.scene.add.text(-width / 2 + 16, -52, `⚠ ${notice.title} · ${notice.remainingDays}日`, this.style(19, "#ffffff"));
    const detail = this.scene.add.text(-width / 2 + 16, -24, notice.detail, { ...this.style(16, "#ffe7e7"), wordWrap: { width: width - 32 } });
    children.push(bg, title, detail);
    let buttonX = -width / 2 + 16;
    for (const action of notice.actions ?? []) {
      const button = this.makeButton(buttonX, 38, action.label, 110, 30, () => this.commands.disasterAction(action.id), action.enabled !== false);
      button.container.setPosition(buttonX + 55, 38);
      children.push(button.container);
      buttonX += 120;
    }
    this.disasterPanel = this.scene.add.container(this.scene.scale.width - width / 2 - 18, 174, children)
      .setScrollFactor(0).setDepth(DEPTH + 10);
  }

  showInspector(title: string, lines: readonly string[], onDemolish?: () => void): void {
    this.inspectorPanel?.destroy();
    const width = 300;
    const height = Math.max(130, 68 + lines.length * 23 + (onDemolish ? 42 : 0));
    const bg = this.scene.add.rectangle(0, 0, width, height, PANEL, 0.98).setStrokeStyle(3, PRIMARY);
    const heading = this.scene.add.text(-width / 2 + 14, -height / 2 + 12, title, this.style(20, "#ffffff"));
    const body = this.scene.add.text(-width / 2 + 14, -height / 2 + 46, lines.join("\n"), { ...this.style(16, "#dbeafe"), lineSpacing: 5 });
    const children: Phaser.GameObjects.GameObject[] = [bg, heading, body];
    if (onDemolish) {
      const button = this.makeButton(0, height / 2 - 24, "拆除（返还40%）", 170, 32, onDemolish);
      children.push(button.container);
    }
    this.inspectorPanel = this.scene.add.container(width / 2 + 18, this.scene.scale.height / 2, children)
      .setScrollFactor(0).setDepth(DEPTH + 8);
  }

  closeInspector(): void { this.inspectorPanel?.destroy(); this.inspectorPanel = null; }

  showPauseMenu(visible: boolean): void {
    this.pauseOverlay?.destroy();
    this.pauseOverlay = null;
    if (!visible) return;
    this.pauseOverlay = this.modal("城市规划已暂停", "日期、经济与灾害计时冻结；仍可建设、拆除和检查。", [
      { label: "继续", action: () => this.commands.setPaused(false) },
    ]);
  }

  showEndOverlay(outcome: "victory" | "bankruptcy" | "abandonment", finalScore: number, detail: string): void {
    this.endOverlay?.destroy();
    const titles = { victory: "市政审计通过！", bankruptcy: "城市财政破产", abandonment: "居民离城，城市废弃" };
    this.endOverlay = this.modal(titles[outcome], `${detail}\n最终得分 ${Math.round(finalScore).toLocaleString()}`, [
      { label: "重新开始", action: () => this.commands.restart("button") },
    ]);
  }

  closeEndOverlay(): void { this.endOverlay?.destroy(); this.endOverlay = null; }

  showSettingsMenu(
    settings: Readonly<CitySettings>,
    onChange: (patch: Partial<CitySettings>) => void,
    visible = true,
  ): void {
    this.settingsOverlay?.destroy();
    this.settingsOverlay = null;
    if (!visible) return;
    const width = 560;
    const height = 330;
    const children: Phaser.GameObjects.GameObject[] = [];
    children.push(this.scene.add.rectangle(0, 0, width, height, this.highContrast ? 0x000000 : PANEL, 0.99)
      .setStrokeStyle(4, this.highContrast ? 0xffffff : ACCENT));
    children.push(this.scene.add.text(0, -132, "设置与无障碍", this.style(28, "#ffffff")).setOrigin(0.5));
    const rows: Array<[string, number, keyof Pick<CitySettings, "masterVolume" | "musicVolume" | "sfxVolume">]> = [
      ["总音量", -78, "masterVolume"], ["音乐", -32, "musicVolume"], ["音效", 14, "sfxVolume"],
    ];
    for (const [label, y, key] of rows) {
      children.push(this.scene.add.text(-220, y - 10, `${label} ${Math.round(settings[key] * 100)}%`, this.style(17, "#dbeafe")));
      const minus = this.makeButton(35, y, "−", 42, 32, () => onChange({ [key]: Math.max(0, settings[key] - 0.1) }));
      const plus = this.makeButton(145, y, "+", 42, 32, () => onChange({ [key]: Math.min(1, settings[key] + 0.1) }));
      minus.container.setPosition(56, y); plus.container.setPosition(166, y);
      children.push(minus.container, plus.container);
    }
    const motion = this.makeButton(-214, 76, `减少动态：${settings.reducedMotion ? "开" : "关"}`, 190, 38, () => onChange({ reducedMotion: !settings.reducedMotion }));
    const contrast = this.makeButton(20, 76, `高对比：${settings.highContrast ? "开" : "关"}`, 190, 38, () => onChange({ highContrast: !settings.highContrast }));
    motion.container.setPosition(-118, 76); contrast.container.setPosition(116, 76);
    const close = this.makeButton(-70, 132, "关闭", 140, 38, () => this.showSettingsMenu(settings, onChange, false));
    close.container.setPosition(0, 132);
    children.push(motion.container, contrast.container, close.container);
    this.settingsOverlay = this.scene.add.container(this.scene.scale.width / 2, this.scene.scale.height / 2, children)
      .setScrollFactor(0).setDepth(DEPTH + 60);
  }

  setAccessibility(settings: { highContrast: boolean; reducedMotion: boolean }): void {
    this.highContrast = settings.highContrast;
    this.reducedMotion = settings.reducedMotion;
    this.topPanel.setFillStyle(settings.highContrast ? 0x05080d : PANEL, settings.highContrast ? 1 : 0.96);
    this.topPanel.setStrokeStyle(settings.highContrast ? 4 : 3, settings.highContrast ? 0xffffff : PRIMARY);
  }

  destroy(): void {
    this.topPanel.destroy(); this.statsText.destroy(); this.utilityText.destroy(); this.riskText.destroy();
    this.auditGraphics.destroy(); this.auditText.destroy();
    for (const button of this.buttons) button.destroy();
    for (const object of this.transient) object.destroy();
    this.pauseOverlay?.destroy(); this.endOverlay?.destroy(); this.settingsOverlay?.destroy();
    this.disasterPanel?.destroy(); this.inspectorPanel?.destroy();
  }

  private createToolbar(): void {
    const y = this.scene.scale.height - 28;
    const tools: Array<[BuildTool, string]> = [
      ["road", "R 道路"], ["home", "H 住宅"], ["commercial", "C 商业"],
      ["power", "E 电厂"], ["water", "W 水务"], ["demolish", "D 拆除"],
    ];
    let x = 18;
    for (const [tool, label] of tools) {
      const button = this.makeButton(x, y, label, 94, 42, () => {
        this.commands.selectTool(tool, "pointer"); this.selectTool(tool);
      });
      this.toolButtons.set(tool, button); x += 100;
    }
    const pause = this.makeButton(x + 8, y, "Space 暂停", 116, 42, () => this.commands.setPaused());
    x += 134;
    for (const speed of [1, 2, 3] as const) {
      const button = this.makeButton(x, y, `${speed}×`, 48, 42, () => this.commands.setSpeed(speed));
      this.speedButtons.set(speed, button); x += 54;
    }
    const overlays: Array<[OverlayKind, string]> = [["power", "⚡"], ["water", "◆"], ["pollution", "☁"], ["road", "路"]];
    for (const [overlay, label] of overlays) {
      const button = this.makeButton(x, y, label, 45, 42, () => {
        this.commands.toggleOverlay(overlay); this.selectOverlay(overlay);
      });
      this.overlayButtons.set(overlay, button); x += 51;
    }
    void pause;
  }

  private drawAudit(snapshot: CityHudSnapshot): void {
    this.auditGraphics.clear();
    const width = 360;
    const gap = 1;
    const segment = (width - 59 * gap) / 60;
    const startX = this.scene.scale.width / 2 - width / 2;
    const y = 42;
    const m = snapshot.metrics;
    const danger = m.population < 500 || m.satisfaction < 70 || m.score < 80 || snapshot.economy.funds < -2000;
    for (let index = 0; index < 60; index += 1) {
      const filled = index < Math.min(60, snapshot.stableDays);
      const color = filled ? (danger ? ACCENT : 0x42d392) : 0x334155;
      this.auditGraphics.fillStyle(color, filled ? 1 : 0.7).fillRect(startX + index * (segment + gap), y, segment, 10);
    }
    this.auditText.setText(`◆ 市政稳定审计 ${Math.min(60, snapshot.stableDays)}/60${danger ? " · ⚠ 指标有风险" : ""}`)
      .setColor(danger ? "#ffd166" : "#ffffff");
  }

  private modal(title: string, detail: string, actions: ReadonlyArray<{ label: string; action: () => void }>): Phaser.GameObjects.Container {
    const width = 540;
    const bg = this.scene.add.rectangle(0, 0, width, 250, this.highContrast ? 0x000000 : PANEL, 0.99).setStrokeStyle(4, this.highContrast ? 0xffffff : ACCENT);
    const heading = this.scene.add.text(0, -82, title, this.style(30, "#ffffff")).setOrigin(0.5);
    const body = this.scene.add.text(0, -28, detail, { ...this.style(18, "#dbeafe"), align: "center", wordWrap: { width: width - 60 } }).setOrigin(0.5);
    const children: Phaser.GameObjects.GameObject[] = [bg, heading, body];
    let x = -(actions.length - 1) * 75;
    for (const action of actions) {
      const button = this.makeButton(x, 78, action.label, 140, 42, action.action);
      children.push(button.container); x += 150;
    }
    return this.scene.add.container(this.scene.scale.width / 2, this.scene.scale.height / 2, children).setScrollFactor(0).setDepth(DEPTH + 50);
  }

  private makeButton(x: number, y: number, label: string, width: number, height: number, action: () => void, enabled = true): HudButton {
    const background = this.scene.add.rectangle(0, 0, width, height, 0x203a5d, 0.98).setStrokeStyle(2, PRIMARY);
    const text = this.scene.add.text(0, 0, label, this.style(16, "#ffffff")).setOrigin(0.5);
    const container = this.scene.add.container(x + width / 2, y, [background, text]).setScrollFactor(0).setDepth(DEPTH + 5);
    const api: HudButton = {
      container, background, label: text,
      setEnabled: value => { container.setAlpha(value ? 1 : 0.45); if (value) background.setInteractive({ useHandCursor: true }); else background.disableInteractive(); },
      setSelected: selected => background.setFillStyle(selected ? ACCENT : 0x203a5d, 0.98),
      destroy: () => container.destroy(),
    };
    background.on("pointerdown", () => { if (background.input?.enabled) action(); });
    background.on("pointerover", () => { if (background.input?.enabled) background.setStrokeStyle(3, 0xffffff); });
    background.on("pointerout", () => background.setStrokeStyle(2, PRIMARY));
    api.setEnabled(enabled);
    this.buttons.push(api);
    return api;
  }

  private text(x: number, y: number, value: string, size: number): Phaser.GameObjects.Text {
    return this.scene.add.text(x, y, value, this.style(size, TEXT)).setScrollFactor(0).setDepth(DEPTH + 2);
  }
  private style(size: number, color: string): Phaser.Types.GameObjects.Text.TextStyle {
    return { fontFamily: "Inter, system-ui, sans-serif", fontSize: `${Math.max(16, size)}px`, color, stroke: "#07101f", strokeThickness: 4 };
  }
  private signed(value: number): string { return `${value >= 0 ? "+" : "-"}¥${Math.abs(Math.round(value)).toLocaleString()}`; }
}
