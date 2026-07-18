import Phaser from "phaser";

type Overlay = "power" | "water" | "pollution" | null;
type Cell = { x: number; y: number };
type OverlayCell = Cell & {
  value: number;
  covered?: boolean;
  disconnected?: boolean;
  source?: "power" | "water" | "pollution";
};
type TowerOverlay = {
  id: string;
  cell: Cell;
  baseCapacity: number;
  pollutionModifier: number;
  actualCapacity: number;
};
type OverlaySnapshot = {
  revision: number;
  power: readonly OverlayCell[];
  water: readonly OverlayCell[];
  pollution: readonly OverlayCell[];
  towers?: readonly TowerOverlay[];
};
type OverlayOptions = {
  cols?: number;
  rows?: number;
  originX?: number;
  originY?: number;
  width?: number;
  height?: number;
  depth?: number;
};

/** Mutually-exclusive, pattern-coded utility overlays driven only by state revisions. */
export class OverlayRenderer {
  private readonly scene: Phaser.Scene;
  private readonly graphics: Phaser.GameObjects.Graphics;
  private readonly labels = new Map<string, Phaser.GameObjects.Text>();
  private readonly cellWidth: number;
  private readonly cellHeight: number;
  private readonly originX: number;
  private readonly originY: number;
  private active: Overlay = null;
  private snapshot: OverlaySnapshot | null = null;
  private renderedRevision = -1;
  private renderedOverlay: Overlay = null;

  constructor(scene: Phaser.Scene, options: OverlayOptions = {}) {
    this.scene = scene;
    const cols = options.cols ?? 24;
    const rows = options.rows ?? 14;
    this.originX = options.originX ?? 0;
    this.originY = options.originY ?? 0;
    this.cellWidth = (options.width ?? scene.scale.width) / cols;
    this.cellHeight = (options.height ?? scene.scale.height) / rows;
    this.graphics = scene.add.graphics().setDepth(options.depth ?? 30).setVisible(false);
  }

  get overlay(): Overlay { return this.active; }

  setOverlay(overlay: Overlay): void {
    if (overlay === this.active) return;
    this.active = overlay;
    this.render(true);
  }

  update(snapshot: OverlaySnapshot): void {
    if (snapshot.revision === this.snapshot?.revision) return;
    this.snapshot = snapshot;
    this.render(false);
  }

  destroy(): void {
    this.graphics.destroy();
    for (const label of this.labels.values()) label.destroy();
    this.labels.clear();
  }

  private render(force: boolean): void {
    if (!force && this.snapshot && this.renderedRevision === this.snapshot.revision && this.renderedOverlay === this.active) return;
    this.graphics.clear();
    for (const label of this.labels.values()) label.setVisible(false);
    this.renderedRevision = this.snapshot?.revision ?? -1;
    this.renderedOverlay = this.active;
    this.graphics.setVisible(this.active !== null);
    if (!this.active || !this.snapshot) return;

    const cells = this.snapshot[this.active];
    for (const cell of cells) this.drawCell(cell, this.active);
    if (this.active === "pollution") {
      for (const tower of this.snapshot.towers ?? []) this.drawTower(tower);
    }
    this.upsertLabel("legend", this.originX + 12, this.originY + 106,
      this.active === "power" ? "⚡ 电力覆盖  ·  /// 未连接" : this.active === "water" ? "💧 供水覆盖  ·  ≋ 未连接" : "▧ 污染强度  ·  ☁ 污染源  ·  水塔显示 基础×修正=实际",
      "#ffffff", 16, 0, 0);
  }

  private drawCell(cell: OverlayCell, overlay: Exclude<Overlay, null>): void {
    const x = this.originX + cell.x * this.cellWidth;
    const y = this.originY + cell.y * this.cellHeight;
    const normalized = Phaser.Math.Clamp(cell.value, 0, 100) / 100;
    const color = overlay === "power" ? 0xffd447 : overlay === "water" ? 0x42c8f5 : 0xd94b3d;
    this.graphics.fillStyle(color, 0.12 + normalized * 0.42).fillRect(x, y, this.cellWidth, this.cellHeight);
    this.graphics.lineStyle(1, color, 0.5).strokeRect(x + 1, y + 1, this.cellWidth - 2, this.cellHeight - 2);

    if (overlay === "power") {
      this.graphics.lineStyle(2, cell.disconnected ? 0xffffff : 0x5b4a00, 0.75);
      for (let offset = -this.cellHeight; offset < this.cellWidth; offset += 12) {
        this.graphics.lineBetween(x + Math.max(0, offset), y + Math.max(0, -offset), x + Math.min(this.cellWidth, offset + this.cellHeight), y + Math.min(this.cellHeight, this.cellHeight + offset));
      }
    } else if (overlay === "water") {
      this.graphics.lineStyle(2, cell.disconnected ? 0xffffff : 0x075c78, 0.8);
      for (let row = 8; row < this.cellHeight; row += 12) {
        this.graphics.beginPath().moveTo(x + 4, y + row).lineTo(x + this.cellWidth * 0.35, y + row - 3)
          .lineTo(x + this.cellWidth * 0.68, y + row + 3).lineTo(x + this.cellWidth - 4, y + row).strokePath();
      }
    } else {
      this.graphics.lineStyle(2, 0xffffff, 0.65);
      const step = normalized > 0.5 ? 8 : 14;
      for (let px = 5; px < this.cellWidth; px += step) {
        for (let py = 5; py < this.cellHeight; py += step) this.graphics.strokeCircle(x + px, y + py, 1.5 + normalized * 2);
      }
    }

    if (cell.disconnected) this.upsertLabel(`fault:${cell.x},${cell.y}`, x + this.cellWidth / 2, y + this.cellHeight / 2, "✕", "#ffffff", 18);
    if (cell.source) {
      const icon = cell.source === "power" ? "⚡" : cell.source === "water" ? "💧" : "☁";
      this.upsertLabel(`source:${cell.x},${cell.y}`, x + this.cellWidth / 2, y + this.cellHeight / 2, icon, "#ffffff", 18);
    }
  }

  private drawTower(tower: TowerOverlay): void {
    const x = this.originX + (tower.cell.x + 0.5) * this.cellWidth;
    const y = this.originY + tower.cell.y * this.cellHeight;
    const percent = Math.round(tower.pollutionModifier * 100);
    this.upsertLabel(
      `tower:${tower.id}`,
      x,
      y,
      `💧 ${Math.round(tower.baseCapacity)}×${percent}%=${Math.round(tower.actualCapacity)}`,
      percent < 70 ? "#fff4c2" : "#ffffff",
      14,
      0.5,
      1,
    );
  }

  private upsertLabel(key: string, x: number, y: number, text: string, color: string, size: number, originX = 0.5, originY = 0.5): void {
    let label = this.labels.get(key);
    if (!label) {
      label = this.scene.add.text(x, y, text, {
        fontFamily: "Inter, system-ui, sans-serif", fontSize: `${size}px`, color,
        backgroundColor: "#17343a", padding: { x: 4, y: 2 }, stroke: "#020617", strokeThickness: 2,
      }).setDepth(this.graphics.depth + 1);
      this.labels.set(key, label);
    }
    label.setPosition(x, y).setText(text).setColor(color).setOrigin(originX, originY).setVisible(true);
  }
}
