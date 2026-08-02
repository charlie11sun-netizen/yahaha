import Phaser from "phaser";
import { InputRouter } from "../systems/InputRouter";

type AccessibilityPreferences = {
  reducedMotion: boolean;
  highContrast: boolean;
  soundCues: boolean;
};
type CitySummary = {
  funds: number;
  population: number;
  powerSupply: number;
  powerDemand: number;
  waterSupply: number;
  waterDemand: number;
  pollution: number;
  happiness: number;
  score: number;
  stabilityDays: number;
};

/** Canvas/assistive-technology bridge plus color-independent status guidance. */
export class AccessibilityController {
  private readonly scene: Phaser.Scene;
  private readonly messageBg: Phaser.GameObjects.Rectangle;
  private readonly message: Phaser.GameObjects.Text;
  private liveRegion: HTMLElement | null = null;
  private preferences: AccessibilityPreferences = { reducedMotion: false, highContrast: true, soundCues: true };
  private hideTimer?: Phaser.Time.TimerEvent;
  private lastAnnouncement = "";

  constructor(scene: Phaser.Scene, initial: Partial<AccessibilityPreferences> = {}) {
    this.scene = scene;
    this.preferences = { ...this.preferences, ...initial };
    this.messageBg = InputRouter.shield(scene.add.rectangle(scene.scale.width / 2, scene.scale.height - 126, 760, 38, 0x10272b, 0.97)
      .setStrokeStyle(2, 0xffffff).setDepth(290).setScrollFactor(0).setVisible(false));
    this.message = scene.add.text(scene.scale.width / 2, scene.scale.height - 126, "", {
      fontFamily: "Inter, system-ui, sans-serif", fontSize: "17px", color: "#ffffff",
      stroke: "#020617", strokeThickness: 3, align: "center", wordWrap: { width: 730 },
    }).setOrigin(0.5).setDepth(291).setScrollFactor(0).setVisible(false);
    this.createLiveRegion();
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.destroy());
  }

  get currentPreferences(): Readonly<AccessibilityPreferences> { return this.preferences; }

  setPreferences(next: Partial<AccessibilityPreferences>): Readonly<AccessibilityPreferences> {
    this.preferences = { ...this.preferences, ...next };
    const canvas = this.scene.game.canvas;
    canvas.classList.toggle("game-high-contrast", this.preferences.highContrast);
    canvas.dataset.reducedMotion = String(this.preferences.reducedMotion);
    return this.preferences;
  }

  announce(message: string, priority: "polite" | "assertive" = "polite", visibleMs = 2800): void {
    const normalized = message.trim();
    if (!normalized || normalized === this.lastAnnouncement) return;
    this.lastAnnouncement = normalized;
    if (this.liveRegion) {
      this.liveRegion.setAttribute("aria-live", priority);
      this.liveRegion.textContent = "";
      // A separate task lets screen readers observe repeated region changes reliably.
      this.scene.time.delayedCall(10, () => { if (this.liveRegion) this.liveRegion.textContent = normalized; });
    }
    this.message.setText(normalized).setVisible(true);
    this.messageBg.setVisible(true);
    this.hideTimer?.remove(false);
    this.hideTimer = this.scene.time.delayedCall(visibleMs, () => {
      this.message.setVisible(false);
      this.messageBg.setVisible(false);
      this.lastAnnouncement = "";
    });
  }

  describeBlocked(action: string, causes: readonly string[]): void {
    const actionable = causes.filter(Boolean);
    this.announce(actionable.length > 0 ? `${action}不可用：${actionable.join("；")}` : `${action}目前不可用，请检查道路、资金和公共服务。`, "assertive", 3600);
  }

  announceOverlay(overlay: "power" | "water" | "pollution" | null): void {
    const text = overlay === "power" ? "已开启供电覆盖层。斜线表示覆盖，叉号表示断开。" :
      overlay === "water" ? "已开启供水覆盖层。波纹表示覆盖，叉号表示断开。" :
      overlay === "pollution" ? "已开启污染覆盖层。点阵密度表示污染强度，云朵表示污染源，水塔显示基础容量乘污染修正等于实际容量。" :
      "覆盖层已关闭。";
    this.announce(text);
  }

  announceSummary(summary: CitySummary): void {
    this.announce(
      `城市状态：资金${Math.round(summary.funds)}，人口${Math.round(summary.population)}/500，` +
      `电力${Math.round(summary.powerSupply)}/${Math.round(summary.powerDemand)}，供水${Math.round(summary.waterSupply)}/${Math.round(summary.waterDemand)}，` +
      `污染${summary.pollution.toFixed(1)}，目标严格低于35；满意度${summary.happiness.toFixed(1)}/75，` +
      `评分${Math.round(summary.score)}/800，稳定${summary.stabilityDays}/30日。`,
    );
  }

  destroy(): void {
    this.hideTimer?.remove(false);
    this.message.destroy();
    this.messageBg.destroy();
    this.liveRegion?.remove();
    this.liveRegion = null;
  }

  private createLiveRegion(): void {
    if (typeof document === "undefined") return;
    const region = document.createElement("div");
    region.className = "game-accessibility-live";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    region.setAttribute("aria-atomic", "true");
    document.body.appendChild(region);
    this.liveRegion = region;

    const canvas = this.scene.game.canvas;
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "application");
    canvas.setAttribute("aria-label", "像素都市规划师。使用R、H、C、E、W、X选择工具，空格暂停，数字1、2、3调速，Escape取消；所有功能也可点击。城市目标为人口500、满意度75、污染严格低于35、评分800并稳定30日。");
    canvas.classList.toggle("game-high-contrast", this.preferences.highContrast);
  }
}
