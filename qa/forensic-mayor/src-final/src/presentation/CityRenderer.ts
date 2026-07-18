import Phaser from "phaser";
import { gameConfig, sheetFrame, tileFamily, tileVariant } from "../config/gameConfig";
import { Backdrop } from "../systems/Backdrop";
import type { BuildingVisual, Cell, OverlayKind, PlacementPreview } from "./types";

export interface OverlayCellVisual {
  cell: Cell;
  status: "ok" | "warning" | "danger" | "inactive";
  label?: string;
}

interface VisualEntry {
  sprite: Phaser.GameObjects.Sprite;
  issue?: Phaser.GameObjects.Text;
  data: BuildingVisual;
}

const semanticTerms: Record<BuildingVisual["kind"], readonly string[]> = {
  road: ["城市道路"],
  home: ["暖顶住宅"],
  commercial: ["蓝牌商业"],
  power: ["橙炉电厂"],
  water: ["青蓝水务"],
  tree: ["保留树木"],
};

function semanticFrame(terms: readonly string[]): { key: string; index: number; name: string } | null {
  for (const sheet of gameConfig.sheets) {
    for (const [name, meta] of Object.entries(sheet.frameMeta)) {
      if (terms.some(term => meta.includes(term))) {
        return { key: sheet.key, index: sheet.frames[name], name };
      }
    }
  }
  return null;
}

export class CityRenderer {
  private readonly buildings = new Map<string, VisualEntry>();
  private readonly roadCells = new Set<string>();
  private readonly roads = new Map<string, Phaser.GameObjects.Sprite>();
  private readonly previewGraphics: Phaser.GameObjects.Graphics;
  private readonly overlayGraphics: Phaser.GameObjects.Graphics;
  private readonly riskGraphics: Phaser.GameObjects.Graphics;
  private readonly overlayLabels: Phaser.GameObjects.Text[] = [];
  private readonly decorations: Phaser.GameObjects.GameObject[] = [];
  private readonly vehicles: Phaser.GameObjects.Sprite[] = [];
  private backdrop: Phaser.GameObjects.Image | null = null;
  private paused = true;
  private reducedMotion = false;
  readonly cellWidth: number;
  readonly cellHeight: number;

  constructor(
    private readonly scene: Phaser.Scene,
    options: { cellWidth?: number; cellHeight?: number; originX?: number; originY?: number; backdrop?: boolean } = {},
  ) {
    this.cellWidth = options.cellWidth ?? gameConfig.levelLayout?.cellWidth ?? gameConfig.width / 24;
    this.cellHeight = options.cellHeight ?? gameConfig.levelLayout?.cellHeight ?? gameConfig.height / 14;
    this.originX = options.originX ?? 0;
    this.originY = options.originY ?? 0;
    if (options.backdrop !== false) this.backdrop = Backdrop.draw(scene);
    this.overlayGraphics = scene.add.graphics().setDepth(18);
    this.previewGraphics = scene.add.graphics().setDepth(40);
    this.riskGraphics = scene.add.graphics().setDepth(35);
    scene.cameras.main.setBounds(this.originX, this.originY, this.cellWidth * 24, this.cellHeight * 14);
    scene.cameras.main.setRoundPixels(true);
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, this.destroy, this);
  }

  private readonly originX: number;
  private readonly originY: number;

  upsertBuilding(visual: BuildingVisual): void {
    if (visual.kind === "road") {
      this.setRoad(visual.cell, true);
      return;
    }
    const existing = this.buildings.get(visual.id);
    if (existing) {
      existing.data = visual;
      this.positionBuilding(existing.sprite, visual);
      this.applyBuildingState(existing);
      return;
    }
    const frame = semanticFrame(semanticTerms[visual.kind]);
    if (!frame) return;
    const sprite = this.scene.add.sprite(0, 0, frame.key, frame.index).setDepth(12);
    const entry: VisualEntry = { sprite, data: visual };
    this.buildings.set(visual.id, entry);
    this.positionBuilding(sprite, visual);
    this.applyBuildingState(entry);
  }

  removeBuilding(id: string): void {
    const entry = this.buildings.get(id);
    if (!entry) return;
    entry.sprite.destroy();
    entry.issue?.destroy();
    this.buildings.delete(id);
  }

  setRoadCells(cells: readonly Cell[]): void {
    const next = new Set(cells.map(cell => this.cellKey(cell)));
    for (const key of [...this.roadCells]) {
      if (!next.has(key)) this.setRoad(this.parseCell(key), false);
    }
    for (const cell of cells) this.setRoad(cell, true);
    for (const cell of cells) this.refreshRoadAndNeighbors(cell);
  }

  setRoad(cell: Cell, present: boolean): void {
    const key = this.cellKey(cell);
    if (present) this.roadCells.add(key);
    else {
      this.roadCells.delete(key);
      this.roads.get(key)?.destroy();
      this.roads.delete(key);
    }
    this.refreshRoadAndNeighbors(cell);
  }

  showPreview(preview: PlacementPreview | null): void {
    this.previewGraphics.clear();
    if (!preview) return;
    const color = preview.legal ? 0x35d07f : 0xe44752;
    for (const cell of preview.cells) {
      const { x, y } = this.cellTopLeft(cell);
      this.previewGraphics.fillStyle(color, 0.28).fillRect(x, y, this.cellWidth, this.cellHeight);
      this.previewGraphics.lineStyle(3, color, 0.95).strokeRect(x + 1, y + 1, this.cellWidth - 2, this.cellHeight - 2);
      if (!preview.legal) {
        this.previewGraphics.lineBetween(x + 5, y + 5, x + this.cellWidth - 5, y + this.cellHeight - 5);
        this.previewGraphics.lineBetween(x + this.cellWidth - 5, y + 5, x + 5, y + this.cellHeight - 5);
      }
    }
  }

  setOverlay(kind: OverlayKind | null, cells: readonly OverlayCellVisual[] = []): void {
    this.overlayGraphics.clear();
    for (const label of this.overlayLabels) label.destroy();
    this.overlayLabels.length = 0;
    if (!kind) return;
    const colors = { ok: 0x2bd9a8, warning: 0xffc857, danger: 0xff5263, inactive: 0x6b7280 };
    for (const item of cells) {
      const { x, y } = this.cellTopLeft(item.cell);
      const color = colors[item.status];
      this.overlayGraphics.fillStyle(color, 0.25).fillRect(x, y, this.cellWidth, this.cellHeight);
      this.overlayGraphics.lineStyle(2, color, 0.9).strokeRect(x + 2, y + 2, this.cellWidth - 4, this.cellHeight - 4);
      if (item.label) {
        this.overlayLabels.push(this.scene.add.text(x + 4, y + 3, item.label, {
          fontFamily: "Inter, system-ui, sans-serif", fontSize: "16px", color: "#ffffff",
          backgroundColor: "#101827", stroke: "#101827", strokeThickness: 3,
        }).setDepth(19));
      }
    }
  }

  showRiskLinks(sourceCells: readonly Cell[], hudAnchor = { x: this.scene.scale.width / 2, y: 52 }): void {
    this.riskGraphics.clear();
    if (sourceCells.length === 0) return;
    this.riskGraphics.lineStyle(3, 0xffc857, 0.9);
    for (const cell of sourceCells.slice(0, 8)) {
      const center = this.cellCenter(cell);
      this.riskGraphics.lineBetween(hudAnchor.x, hudAnchor.y, center.x, center.y);
      this.riskGraphics.fillStyle(0xffc857, 0.95).fillCircle(center.x, center.y, 6);
      this.riskGraphics.lineStyle(2, 0x101827, 1).strokeCircle(center.x, center.y, 8);
      this.riskGraphics.lineStyle(3, 0xffc857, 0.9);
    }
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
    for (const object of this.decorations) {
      const sprite = object as Phaser.GameObjects.Sprite;
      if ("anims" in sprite) {
        if (paused) sprite.anims.pause();
        else sprite.anims.resume();
      }
    }
    for (const vehicle of this.vehicles) {
      if (paused) vehicle.anims.pause();
      else vehicle.anims.resume();
    }
    if (paused) this.scene.tweens.pauseAll();
    else this.scene.tweens.resumeAll();
  }

  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced;
    if (reduced) {
      for (const vehicle of this.vehicles) vehicle.setVisible(false);
    } else {
      for (const vehicle of this.vehicles) vehicle.setVisible(true);
    }
  }

  addVehicle(cell: Cell, angle = 0): Phaser.GameObjects.Sprite | null {
    if (this.vehicles.length >= 12) return null;
    const frame = semanticFrame(["通勤车辆"]);
    if (!frame) return null;
    const center = this.cellCenter(cell);
    const vehicle = this.scene.add.sprite(center.x, center.y, frame.key, frame.index)
      .setDisplaySize(Math.min(28, this.cellWidth * 0.55), Math.min(18, this.cellHeight * 0.35))
      .setAngle(angle).setDepth(16).setVisible(!this.reducedMotion);
    this.vehicles.push(vehicle);
    return vehicle;
  }

  clearVehicles(): void {
    for (const vehicle of this.vehicles) vehicle.destroy();
    this.vehicles.length = 0;
  }

  switchBackdrop(index: number): void {
    const key = gameConfig.assetKeys.backgrounds[index];
    if (key) this.backdrop = Backdrop.swap(this.scene, this.backdrop, key, this.reducedMotion ? 0 : 600);
  }

  destroy(): void {
    for (const entry of this.buildings.values()) { entry.sprite.destroy(); entry.issue?.destroy(); }
    for (const road of this.roads.values()) road.destroy();
    for (const label of this.overlayLabels) label.destroy();
    this.clearVehicles();
    this.previewGraphics.destroy();
    this.overlayGraphics.destroy();
    this.riskGraphics.destroy();
    this.buildings.clear();
    this.roads.clear();
  }

  private refreshRoadAndNeighbors(cell: Cell): void {
    const cells = [cell, { x: cell.x, y: cell.y - 1 }, { x: cell.x + 1, y: cell.y }, { x: cell.x, y: cell.y + 1 }, { x: cell.x - 1, y: cell.y }];
    for (const current of cells) if (this.roadCells.has(this.cellKey(current))) this.drawRoad(current);
  }

  private drawRoad(cell: Cell): void {
    const family = tileFamily("entity_1");
    if (!family) return;
    const has = (x: number, y: number): boolean => this.roadCells.has(`${x},${y}`);
    const variant = tileVariant(family, has(cell.x, cell.y - 1), has(cell.x + 1, cell.y), has(cell.x, cell.y + 1), has(cell.x - 1, cell.y));
    const frame = sheetFrame(variant.frame);
    if (!frame) return;
    const key = this.cellKey(cell);
    let sprite = this.roads.get(key);
    const center = this.cellCenter(cell);
    if (!sprite) {
      sprite = this.scene.add.sprite(center.x, center.y, frame.key, frame.index).setDepth(8);
      this.roads.set(key, sprite);
    } else sprite.setTexture(frame.key, frame.index);
    sprite.setPosition(center.x, center.y).setAngle(variant.angle).setDisplaySize(this.cellWidth, this.cellHeight);
  }

  private positionBuilding(sprite: Phaser.GameObjects.Sprite, visual: BuildingVisual): void {
    const x = this.originX + (visual.cell.x + visual.width / 2) * this.cellWidth;
    const y = this.originY + (visual.cell.y + visual.height / 2) * this.cellHeight;
    sprite.setPosition(x, y).setDisplaySize(visual.width * this.cellWidth, visual.height * this.cellHeight).setAngle(0).setFlipX(false);
  }

  private applyBuildingState(entry: VisualEntry): void {
    const data = entry.data;
    const issues: string[] = [];
    if (data.connected === false) issues.push("⚠ 断路");
    if (data.powered === false) issues.push("⚡ 缺电");
    if (data.watered === false) issues.push("◆ 缺水");
    if (data.pollution === "strong") issues.push("☁ 强污染");
    else if (data.pollution === "weak") issues.push("☁ 污染");
    if (data.disaster) issues.push(`! ${data.disaster}`);
    entry.sprite.clearTint();
    if (data.operating === false) entry.sprite.setTint(0x8b94a3);
    entry.issue?.destroy();
    entry.issue = undefined;
    if (issues.length > 0) {
      entry.issue = this.scene.add.text(entry.sprite.x, entry.sprite.y - entry.sprite.displayHeight / 2, issues.join("\n"), {
        fontFamily: "Inter, system-ui, sans-serif", fontSize: "16px", color: "#ffffff",
        backgroundColor: "#8b1e2d", stroke: "#10131a", strokeThickness: 4, align: "center",
      }).setOrigin(0.5, 1).setDepth(30);
    }
  }

  private cellKey(cell: Cell): string { return `${cell.x},${cell.y}`; }
  private parseCell(key: string): Cell { const [x, y] = key.split(",").map(Number); return { x, y }; }
  private cellTopLeft(cell: Cell): { x: number; y: number } {
    return { x: this.originX + cell.x * this.cellWidth, y: this.originY + cell.y * this.cellHeight };
  }
  private cellCenter(cell: Cell): { x: number; y: number } {
    const top = this.cellTopLeft(cell);
    return { x: top.x + this.cellWidth / 2, y: top.y + this.cellHeight / 2 };
  }
}
