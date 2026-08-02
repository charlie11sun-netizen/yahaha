import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";
import { Juice } from "../systems/Juice";
import { Sfx } from "../systems/Sfx";
import type {
  BuildTool, BuildValidation, CityPresentationCommands, DemolitionPreview, GridPoint,
  PlannerState, PlannerTool,
} from "./CityPresentationTypes";

export interface PlannerControllerOptions {
  originX: number;
  originY: number;
  cellWidth: number;
  cellHeight: number;
  cols?: number;
  rows?: number;
  validate(tool: BuildTool, anchor: GridPoint): BuildValidation;
  structureAt(cell: GridPoint): string | null;
  demolitionPreview(structureId: string): DemolitionPreview;
  onInspect(structureId: string): void;
  commands: CityPresentationCommands;
}

export interface PlannerController {
  readonly state: PlannerState;
  setTool(tool: PlannerTool): void;
  pointerMove(worldX: number, worldY: number, isDown?: boolean): void;
  pointerDown(worldX: number, worldY: number): void;
  pointerUp(worldX: number, worldY: number): void;
  confirmDemolition(): void;
  cancel(): void;
  destroy(): void;
}

const sameCell = (a: GridPoint, b: GridPoint): boolean => a.x === b.x && a.y === b.y;
const keyOf = (point: GridPoint): string => `${point.x},${point.y}`;

export function createPlannerController(scene: Phaser.Scene, options: PlannerControllerOptions): PlannerController {
  const graphics = scene.add.graphics().setDepth(42);
  const label = scene.add.text(0, 0, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "15px", color: "#ffffff",
    backgroundColor: "#16202a", padding: { x: 7, y: 5 }, stroke: "#000000", strokeThickness: 2,
  }).setDepth(43).setVisible(false);
  const juice = new Juice(scene);
  const state: { tool: PlannerTool; hover: GridPoint | null; dragPath: GridPoint[]; validation: BuildValidation | null; demolition: DemolitionPreview | null } = {
    tool: "inspect", hover: null, dragPath: [], validation: null, demolition: null,
  };
  let dragging = false;
  let dragSequence = 0;

  const toCell = (worldX: number, worldY: number): GridPoint | null => {
    const x = Math.floor((worldX - options.originX) / options.cellWidth);
    const y = Math.floor((worldY - options.originY) / options.cellHeight);
    if (x < 0 || y < 0 || x >= (options.cols ?? 20) || y >= (options.rows ?? 12)) return null;
    return { x, y };
  };
  const cellRect = (point: GridPoint): Phaser.Geom.Rectangle => new Phaser.Geom.Rectangle(
    options.originX + point.x * options.cellWidth,
    options.originY + point.y * options.cellHeight,
    options.cellWidth,
    options.cellHeight,
  );

  const appendOrthogonal = (target: GridPoint): void => {
    if (!state.dragPath.length) { state.dragPath.push(target); return; }
    const revisited = state.dragPath.findIndex((cell) => sameCell(cell, target));
    if (revisited >= 0) { state.dragPath.splice(revisited + 1); return; }
    let cursor = { ...state.dragPath[state.dragPath.length - 1] };
    while (!sameCell(cursor, target)) {
      const dx = target.x - cursor.x;
      const dy = target.y - cursor.y;
      if (Math.abs(dx) >= Math.abs(dy) && dx !== 0) cursor = { x: cursor.x + Math.sign(dx), y: cursor.y };
      else cursor = { x: cursor.x, y: cursor.y + Math.sign(dy) };
      if (!state.dragPath.some((cell) => sameCell(cell, cursor))) state.dragPath.push(cursor);
    }
  };

  const drawCrossPattern = (rect: Phaser.Geom.Rectangle): void => {
    graphics.lineStyle(2, colorNum(gameConfig.palette.danger), 0.75);
    for (let offset = -rect.height; offset < rect.width; offset += 12) {
      graphics.lineBetween(rect.x + Math.max(0, offset), rect.bottom - Math.max(0, -offset), rect.x + Math.min(rect.width, offset + rect.height), rect.y + Math.max(0, rect.height - offset - rect.width));
    }
    graphics.lineBetween(rect.x + 6, rect.y + 6, rect.right - 6, rect.bottom - 6);
    graphics.lineBetween(rect.right - 6, rect.y + 6, rect.x + 6, rect.bottom - 6);
  };

  const redraw = (): void => {
    graphics.clear();
    label.setVisible(false);
    if (!state.hover) return;
    const buildTool = state.tool === "inspect" || state.tool === "demolish" ? null : state.tool;
    if (buildTool) state.validation = options.validate(buildTool, state.hover);
    else state.validation = null;

    const previewCells = state.tool === "road" && state.dragPath.length
      ? state.dragPath
      : state.validation?.footprint?.length
        ? [...state.validation.footprint]
        : buildTool && (buildTool === "powerPlant" || buildTool === "waterTower")
          ? [state.hover, { x: state.hover.x + 1, y: state.hover.y }, { x: state.hover.x, y: state.hover.y + 1 }, { x: state.hover.x + 1, y: state.hover.y + 1 }]
          : [state.hover];
    const valid = state.validation?.legal ?? state.tool !== "demolish";
    const color = valid ? 0x39d98a : colorNum(gameConfig.palette.danger);
    for (const cell of previewCells) {
      const rect = cellRect(cell);
      graphics.fillStyle(color, 0.2).fillRectShape(rect);
      graphics.lineStyle(3, color, 1).strokeRectShape(rect);
      if (!valid) drawCrossPattern(rect);
    }
    if (state.validation?.connectionDirections?.length) {
      const arrows = { up: "↑", right: "→", down: "↓", left: "←" } as const;
      const rect = cellRect(state.hover);
      label.setText(`${state.validation.connectionDirections.map((d) => arrows[d]).join("")}  ¥${state.validation.price}${valid ? " 可建设" : ` 不可建设：${state.validation.reason ?? "规则拒绝"}`}`)
        .setPosition(rect.centerX, rect.y - 4).setOrigin(0.5, 1).setVisible(true);
    } else if (state.validation) {
      const text = valid ? `✓ ¥${state.validation.price} 可建设` : `✕ ¥${state.validation.price} ${state.validation.reason ?? "不可建设"}`;
      const rect = cellRect(state.hover);
      label.setText(text).setPosition(rect.centerX, rect.y - 4).setOrigin(0.5, 1).setVisible(true);
    } else if (state.demolition) {
      const d = state.demolition;
      const rect = cellRect(state.hover);
      label.setText(`⚠ 拆除 ${d.name} · 退款 ¥${d.refund}\n影响 ${d.affectedBuildingCount} 座建筑 · 再确认执行`)
        .setPosition(rect.centerX, rect.y - 4).setOrigin(0.5, 1).setVisible(true);
    }
  };

  const controller: PlannerController = {
    state,
    setTool(tool): void {
      state.tool = tool; state.dragPath.length = 0; state.demolition = null; dragging = false;
      redraw();
    },
    pointerMove(worldX, worldY, isDown = false): void {
      const cell = toCell(worldX, worldY);
      state.hover = cell;
      if (cell && state.tool === "road" && (dragging || isDown)) appendOrthogonal(cell);
      redraw();
    },
    pointerDown(worldX, worldY): void {
      const cell = toCell(worldX, worldY);
      state.hover = cell;
      if (!cell) return;
      if (state.tool === "road") { dragging = true; state.dragPath.length = 0; appendOrthogonal(cell); }
      redraw();
    },
    pointerUp(worldX, worldY): void {
      const cell = toCell(worldX, worldY);
      state.hover = cell;
      if (!cell) { dragging = false; return; }
      if (state.tool === "road") {
        appendOrthogonal(cell);
        const dragId = `road-${++dragSequence}`;
        const unique = new Map(state.dragPath.map((point) => [keyOf(point), point]));
        for (const point of unique.values()) options.commands.requestBuild({ tool: "road", anchor: point, dragId });
        dragging = false; state.dragPath.length = 0; Sfx.play("select");
      } else if (state.tool === "inspect") {
        const id = options.structureAt(cell); if (id) { options.onInspect(id); Sfx.play("select"); }
      } else if (state.tool === "demolish") {
        const id = options.structureAt(cell);
        state.demolition = id ? options.demolitionPreview(id) : null;
        if (!id) Sfx.play("hit", 0.35);
      } else {
        const validation = options.validate(state.tool, cell);
        state.validation = validation;
        options.commands.requestBuild({ tool: state.tool, anchor: cell });
        if (validation.legal) { Sfx.play("pickup", 0.6); juice.floatText(cellRect(cell).centerX, cellRect(cell).y, `−¥${validation.price}`, gameConfig.palette.accent, 16); }
        else Sfx.play("hit", 0.4);
      }
      redraw();
    },
    confirmDemolition(): void {
      if (!state.demolition) return;
      options.commands.requestDemolish(state.demolition.structureId, true);
      Sfx.play("explosion", 0.35); juice.shake(0.003, 90); state.demolition = null; redraw();
    },
    cancel(): void { state.dragPath.length = 0; state.demolition = null; dragging = false; redraw(); },
    destroy(): void { graphics.destroy(); label.destroy(); },
  };
  return controller;
}
