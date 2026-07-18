import Phaser from "phaser";
import { Backdrop } from "../systems/Backdrop";
import { gameConfig, sheetFrame, tileFamily, tileVariant } from "../config/gameConfig";

type Tool = "road" | "residential" | "commercial" | "powerPlant" | "waterTower" | "demolish" | null;
type Cell = { x: number; y: number };
type BuildingKind = Exclude<Tool, "demolish" | null>;
type BuildingView = {
  id: string;
  kind: BuildingKind;
  cell: Cell;
  health?: number;
  maxHealth?: number;
  occupancy?: number;
  powered?: boolean;
  watered?: boolean;
  roadConnected?: boolean;
  pollution?: number;
  waterModifier?: number;
};
type CityRenderState = {
  revision: number;
  roads: readonly Cell[];
  buildings: readonly BuildingView[];
};
type PreviewView = {
  tool: Tool;
  cells: readonly Cell[];
  legal: boolean;
  reason?: string;
  cost?: number;
};
type RendererOptions = {
  cols?: number;
  rows?: number;
  originX?: number;
  originY?: number;
  width?: number;
  height?: number;
  depth?: number;
  drawBackdrop?: boolean;
};

const KIND_WORDS: Record<BuildingKind, readonly string[]> = {
  road: ["像素道路"],
  residential: ["青瓦住宅"],
  commercial: ["金牌商业区"],
  powerPlant: ["赤焰电厂"],
  waterTower: ["蓝泉水塔"],
};

/** Signal-driven city map presentation. It consumes authoritative views and never judges placement. */
export class CityRenderer {
  readonly cols: number;
  readonly rows: number;
  readonly cellWidth: number;
  readonly cellHeight: number;
  readonly originX: number;
  readonly originY: number;

  private readonly scene: Phaser.Scene;
  private readonly root: Phaser.GameObjects.Container;
  private readonly grid: Phaser.GameObjects.Graphics;
  private readonly preview: Phaser.GameObjects.Graphics;
  private readonly previewLabel: Phaser.GameObjects.Text;
  private readonly selection: Phaser.GameObjects.Graphics;
  private readonly locator: Phaser.GameObjects.Graphics;
  private readonly roadSprites = new Map<string, Phaser.GameObjects.Sprite>();
  private readonly buildingSprites = new Map<string, Phaser.GameObjects.Sprite>();
  private readonly statusLabels = new Map<string, Phaser.GameObjects.Text>();
  private readonly kindFrames = new Map<BuildingKind, { key: string; index: number }>();
  private lastRevision = -1;
  private locatorTween?: Phaser.Tweens.Tween;

  constructor(scene: Phaser.Scene, options: RendererOptions = {}) {
    this.scene = scene;
    this.cols = options.cols ?? 24;
    this.rows = options.rows ?? 14;
    this.originX = options.originX ?? 0;
    this.originY = options.originY ?? 0;
    const width = options.width ?? scene.scale.width;
    const height = options.height ?? scene.scale.height;
    this.cellWidth = width / this.cols;
    this.cellHeight = height / this.rows;
    if (options.drawBackdrop !== false) Backdrop.draw(scene);

    this.root = scene.add.container(0, 0).setDepth(options.depth ?? 0);
    this.grid = scene.add.graphics();
    this.preview = scene.add.graphics().setDepth(35);
    this.selection = scene.add.graphics().setDepth(34);
    this.locator = scene.add.graphics().setDepth(36).setVisible(false);
    this.previewLabel = scene.add.text(0, 0, "", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "16px",
      color: "#ffffff",
      backgroundColor: "#17343a",
      padding: { x: 7, y: 4 },
      stroke: "#020617",
      strokeThickness: 3,
    }).setDepth(37).setVisible(false);
    this.root.add([this.grid, this.selection, this.preview, this.locator, this.previewLabel]);
    this.resolveFrames();
    this.drawGrid();
  }

  cellAtWorld(worldX: number, worldY: number): Cell | null {
    const x = Math.floor((worldX - this.originX) / this.cellWidth);
    const y = Math.floor((worldY - this.originY) / this.cellHeight);
    return x >= 0 && y >= 0 && x < this.cols && y < this.rows ? { x, y } : null;
  }

  cellCenter(cell: Cell): Phaser.Math.Vector2 {
    return new Phaser.Math.Vector2(
      this.originX + (cell.x + 0.5) * this.cellWidth,
      this.originY + (cell.y + 0.5) * this.cellHeight,
    );
  }

  /** Call only for a map/building slice revision. Unchanged revisions allocate nothing. */
  updateCity(state: CityRenderState): void {
    if (state.revision === this.lastRevision) return;
    this.lastRevision = state.revision;
    const roadKeys = new Set(state.roads.map((cell) => this.key(cell)));
    for (const [key, sprite] of this.roadSprites) {
      if (!roadKeys.has(key)) {
        sprite.destroy();
        this.roadSprites.delete(key);
      }
    }
    for (const cell of state.roads) this.upsertRoad(cell, roadKeys);

    const buildingIds = new Set(state.buildings.map((building) => building.id));
    for (const [id, sprite] of this.buildingSprites) {
      if (!buildingIds.has(id)) {
        sprite.destroy();
        this.buildingSprites.delete(id);
        this.statusLabels.get(id)?.destroy();
        this.statusLabels.delete(id);
      }
    }
    for (const building of state.buildings) this.upsertBuilding(building);
  }

  setPreview(view: PreviewView | null): void {
    this.preview.clear();
    this.previewLabel.setVisible(false);
    if (!view || view.cells.length === 0) return;
    const color = view.legal ? 0x39d353 : 0xd94b3d;
    for (const cell of view.cells) this.drawPatternCell(this.preview, cell, color, view.legal);
    const anchor = this.cellCenter(view.cells[view.cells.length - 1]);
    const parts = view.tool === "road" && view.cells.length > 1 ? [`${view.cells.length}格`] : [];
    if (typeof view.cost === "number") parts.push(`$${Math.max(0, Math.round(view.cost))}`);
    if (!view.legal && view.reason) parts.push(`✕ ${view.reason}`);
    if (parts.length > 0) {
      this.previewLabel.setText(parts.join(" · "));
      this.previewLabel.setPosition(anchor.x, anchor.y - this.cellHeight * 0.65).setOrigin(0.5, 1).setVisible(true);
    }
  }

  setSelection(cell: Cell | null): void {
    this.selection.clear();
    if (!cell) return;
    const x = this.originX + cell.x * this.cellWidth;
    const y = this.originY + cell.y * this.cellHeight;
    this.selection.lineStyle(3, 0xffffff, 1).strokeRect(x + 2, y + 2, this.cellWidth - 4, this.cellHeight - 4);
    this.selection.lineStyle(1, 0x17343a, 1).strokeRect(x + 5, y + 5, this.cellWidth - 10, this.cellHeight - 10);
  }

  /** Locate an alert without moving the single-screen camera away from HUD/map bounds. */
  focusCell(cell: Cell, label = "警报位置"): void {
    const center = this.cellCenter(cell);
    const radius = Math.min(this.cellWidth, this.cellHeight) * 0.48;
    this.locatorTween?.stop();
    this.locator.clear().lineStyle(4, 0xffd447, 1).strokeCircle(center.x, center.y, radius).setVisible(true).setAlpha(1);
    this.previewLabel.setText(`⚠ ${label}`).setPosition(center.x, center.y - radius - 6).setOrigin(0.5, 1).setVisible(true);
    this.locatorTween = this.scene.tweens.add({
      targets: this.locator,
      alpha: 0.2,
      duration: 260,
      yoyo: true,
      repeat: 3,
      onComplete: () => this.locator.setVisible(false).setAlpha(1),
    });
  }

  destroy(): void {
    this.locatorTween?.stop();
    this.root.destroy(true);
  }

  private resolveFrames(): void {
    for (const kind of Object.keys(KIND_WORDS) as BuildingKind[]) {
      for (const sheet of gameConfig.sheets) {
        const frameName = Object.keys(sheet.frameMeta).find((name) =>
          KIND_WORDS[kind].some((word) => sheet.frameMeta[name].includes(word)),
        );
        if (frameName) {
          const frame = sheetFrame(frameName);
          if (frame) this.kindFrames.set(kind, frame);
          break;
        }
      }
    }
  }

  private drawGrid(): void {
    const width = this.cellWidth * this.cols;
    const height = this.cellHeight * this.rows;
    this.grid.fillStyle(0x78b95a, 0.24).fillRect(this.originX, this.originY, width, height);
    this.grid.lineStyle(1, 0x17343a, 0.2);
    for (let x = 0; x <= this.cols; x += 1) {
      const px = this.originX + x * this.cellWidth;
      this.grid.lineBetween(px, this.originY, px, this.originY + height);
    }
    for (let y = 0; y <= this.rows; y += 1) {
      const py = this.originY + y * this.cellHeight;
      this.grid.lineBetween(this.originX, py, this.originX + width, py);
    }
  }

  private upsertRoad(cell: Cell, roads: ReadonlySet<string>): void {
    const key = this.key(cell);
    const center = this.cellCenter(cell);
    const family = tileFamily(this.frameNameForKind("road"));
    const variant = family ? tileVariant(
      family,
      roads.has(this.key({ x: cell.x, y: cell.y - 1 })),
      roads.has(this.key({ x: cell.x + 1, y: cell.y })),
      roads.has(this.key({ x: cell.x, y: cell.y + 1 })),
      roads.has(this.key({ x: cell.x - 1, y: cell.y })),
    ) : null;
    const frame = variant ? sheetFrame(variant.frame) : this.kindFrames.get("road");
    if (!frame) return;
    let sprite = this.roadSprites.get(key);
    if (!sprite) {
      sprite = this.scene.add.sprite(center.x, center.y, frame.key, frame.index).setDepth(4);
      this.root.add(sprite);
      this.roadSprites.set(key, sprite);
    }
    sprite.setTexture(frame.key, frame.index).setDisplaySize(this.cellWidth, this.cellHeight).setAngle(variant?.angle ?? 0);
  }

  private upsertBuilding(building: BuildingView): void {
    const frame = this.kindFrames.get(building.kind);
    if (!frame) return;
    const center = this.cellCenter(building.cell);
    let sprite = this.buildingSprites.get(building.id);
    if (!sprite) {
      sprite = this.scene.add.sprite(center.x, center.y, frame.key, frame.index).setDepth(10);
      this.root.add(sprite);
      this.buildingSprites.set(building.id, sprite);
    }
    sprite.setTexture(frame.key, frame.index).setPosition(center.x, center.y)
      .setDisplaySize(this.cellWidth * 0.94, this.cellHeight * 0.94).setAngle(0).setFlipX(false);
    const damaged = typeof building.health === "number" && typeof building.maxHealth === "number" && building.health < building.maxHealth;
    const utilityFault = building.roadConnected === false || building.powered === false || building.watered === false;
    if (damaged) sprite.setTint(0xe89b8f);
    else if (building.kind === "waterTower" && (building.waterModifier ?? 1) < 0.7) sprite.setTint(0x9b7f62);
    else if (utilityFault) sprite.setTint(0xaab2bd);
    else sprite.clearTint();

    const faults = [building.roadConnected === false ? "⌁" : "", building.powered === false ? "⚡" : "", building.watered === false ? "💧" : "", damaged ? "🔧" : ""].filter(Boolean).join(" ");
    let label = this.statusLabels.get(building.id);
    if (!label && faults) {
      label = this.scene.add.text(center.x, center.y - this.cellHeight * 0.43, faults, {
        fontFamily: "Inter, system-ui, sans-serif", fontSize: "14px", color: "#ffffff",
        backgroundColor: "#8d2d26", padding: { x: 3, y: 1 },
      }).setOrigin(0.5, 0).setDepth(15);
      this.root.add(label);
      this.statusLabels.set(building.id, label);
    }
    if (label) label.setText(faults).setPosition(center.x, center.y - this.cellHeight * 0.43).setVisible(Boolean(faults));
  }

  private drawPatternCell(graphics: Phaser.GameObjects.Graphics, cell: Cell, color: number, legal: boolean): void {
    const x = this.originX + cell.x * this.cellWidth;
    const y = this.originY + cell.y * this.cellHeight;
    graphics.fillStyle(color, 0.28).fillRect(x + 1, y + 1, this.cellWidth - 2, this.cellHeight - 2);
    graphics.lineStyle(2, color, 0.95).strokeRect(x + 2, y + 2, this.cellWidth - 4, this.cellHeight - 4);
    graphics.lineStyle(2, legal ? 0xffffff : 0x3a0b08, 0.7);
    const step = 10;
    for (let offset = -this.cellHeight; offset < this.cellWidth; offset += step) {
      if (legal) graphics.lineBetween(x + Math.max(0, offset), y + Math.max(0, -offset), x + Math.min(this.cellWidth, offset + this.cellHeight), y + Math.min(this.cellHeight, this.cellHeight + offset));
      else graphics.lineBetween(x + Math.max(0, offset), y + Math.min(this.cellHeight, this.cellHeight + offset), x + Math.min(this.cellWidth, offset + this.cellHeight), y + Math.max(0, -offset));
    }
  }

  private frameNameForKind(kind: BuildingKind): string {
    const resolved = this.kindFrames.get(kind);
    if (!resolved) return "";
    for (const sheet of gameConfig.sheets) {
      if (sheet.key !== resolved.key) continue;
      const entry = Object.entries(sheet.frames).find(([, index]) => index === resolved.index);
      if (entry) return entry[0];
    }
    return "";
  }

  private key(cell: Cell): string { return `${cell.x},${cell.y}`; }
}
