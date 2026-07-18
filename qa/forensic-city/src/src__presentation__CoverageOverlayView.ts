import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";
import type { CoverageOverlay, GridPoint } from "./CityPresentationTypes";

export interface CoverageCellPresentation extends GridPoint {
  strength: number;
  covered: boolean;
}

export interface CoverageOverlayViewOptions {
  originX: number;
  originY: number;
  cellWidth: number;
  cellHeight: number;
  cols?: number;
  rows?: number;
}

export interface CoverageOverlayView {
  readonly active: CoverageOverlay;
  readonly minimapVisible: boolean;
  setOverlay(overlay: CoverageOverlay, cells?: readonly CoverageCellPresentation[]): void;
  updateCells(cells: readonly CoverageCellPresentation[]): void;
  toggleMinimap(force?: boolean): boolean;
  close(): void;
  destroy(): void;
}

const OVERLAY_STYLE: Record<Exclude<CoverageOverlay, "none">, { color: number; icon: string; label: string }> = {
  power: { color: 0xffd34e, icon: "⚡", label: "电力覆盖" },
  water: { color: 0x35cfe0, icon: "◆", label: "水务覆盖" },
  pollution: { color: 0xa85bb7, icon: "▧", label: "污染暴露" },
};

/** Mutually-exclusive coverage rendering. Every layer combines tint, hatch and
 * a repeated symbol so it remains readable in grayscale. */
export function createCoverageOverlayView(scene: Phaser.Scene, options: CoverageOverlayViewOptions): CoverageOverlayView {
  const graphics = scene.add.graphics().setDepth(30).setVisible(false);
  const icons = scene.add.group();
  const legend = scene.add.text(options.originX + 8, options.originY + 8, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "16px", color: "#ffffff",
    backgroundColor: "#17212b", padding: { x: 9, y: 6 }, stroke: "#000000", strokeThickness: 2,
  }).setDepth(32).setVisible(false);
  const minimap = scene.add.container(scene.scale.width - 268, 76).setDepth(70).setScrollFactor(0).setVisible(false);
  const miniBg = scene.add.rectangle(0, 0, 250, 166, colorNum(gameConfig.palette.surface), 0.96)
    .setOrigin(0).setStrokeStyle(3, colorNum(gameConfig.palette.primary));
  const miniTitle = scene.add.text(12, 8, "区域小地图  [M关闭]", { fontFamily: "Inter, system-ui, sans-serif", fontSize: "15px", color: "#17212b", fontStyle: "bold" });
  minimap.add([miniBg, miniTitle]);
  const regionSpecs = [
    { name: "河西新区", x: 12, y: 38, w: 92, h: 108, mark: "住" },
    { name: "旧城走廊", x: 24, y: 91, w: 164, h: 28, mark: "路" },
    { name: "东岸商街", x: 126, y: 42, w: 108, h: 66, mark: "商" },
    { name: "东南设施区", x: 126, y: 116, w: 108, h: 34, mark: "⚙" },
  ];
  for (const region of regionSpecs) {
    const box = scene.add.rectangle(region.x, region.y, region.w, region.h, colorNum(gameConfig.palette.primary), 0.13)
      .setOrigin(0).setStrokeStyle(1, colorNum(gameConfig.palette.primary), 0.7);
    const text = scene.add.text(region.x + 4, region.y + 3, `${region.mark} ${region.name}`, { fontFamily: "Inter, system-ui, sans-serif", fontSize: "11px", color: "#17212b" });
    minimap.add([box, text]);
  }

  let active: CoverageOverlay = "none";
  let currentCells: readonly CoverageCellPresentation[] = [];
  let minimapVisible = false;
  const clearIcons = (): void => { icons.clear(true, true); };
  const redraw = (): void => {
    graphics.clear(); clearIcons();
    if (active === "none") { graphics.setVisible(false); legend.setVisible(false); return; }
    graphics.setVisible(true); legend.setVisible(true);
    const style = OVERLAY_STYLE[active];
    legend.setText(`${style.icon} ${style.label} · 图标/纹理辅助辨识`);
    for (const cell of currentCells) {
      const x = options.originX + cell.x * options.cellWidth;
      const y = options.originY + cell.y * options.cellHeight;
      const alpha = cell.covered ? 0.12 + Math.max(0, Math.min(1, cell.strength)) * 0.28 : 0.08;
      graphics.fillStyle(cell.covered ? style.color : colorNum(gameConfig.palette.danger), alpha)
        .fillRect(x, y, options.cellWidth, options.cellHeight);
      graphics.lineStyle(1, style.color, cell.covered ? 0.5 : 0.25);
      const stripeStep = active === "power" ? 10 : active === "water" ? 14 : 8;
      for (let d = -options.cellHeight; d < options.cellWidth; d += stripeStep) {
        graphics.lineBetween(x + Math.max(0, d), y + Math.max(0, -d), x + Math.min(options.cellWidth, d + options.cellHeight), y + Math.min(options.cellHeight, options.cellHeight + d));
      }
      if ((cell.x + cell.y) % 2 === 0) {
        const icon = scene.add.text(x + options.cellWidth / 2, y + options.cellHeight / 2, cell.covered ? style.icon : "×", {
          fontFamily: "Inter, system-ui, sans-serif", fontSize: "16px", color: cell.covered ? "#ffffff" : gameConfig.palette.danger,
          stroke: "#17212b", strokeThickness: 3,
        }).setOrigin(0.5).setDepth(31);
        icons.add(icon);
      }
    }
  };

  const view: CoverageOverlayView = {
    get active(): CoverageOverlay { return active; },
    get minimapVisible(): boolean { return minimapVisible; },
    setOverlay(overlay, cells): void { active = overlay; if (cells) currentCells = cells; redraw(); },
    updateCells(cells): void { currentCells = cells; redraw(); },
    toggleMinimap(force): boolean {
      minimapVisible = force ?? !minimapVisible; minimap.setVisible(minimapVisible); return minimapVisible;
    },
    close(): void { active = "none"; minimapVisible = false; minimap.setVisible(false); redraw(); },
    destroy(): void { clearIcons(); icons.destroy(true); graphics.destroy(); legend.destroy(); minimap.destroy(true); },
  };
  return view;
}
