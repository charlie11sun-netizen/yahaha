import Phaser from "phaser";
import type {
  BuildTool, Cell, InputBindings, OverlayKind, PlacementPreview,
  PresentationCommands, ToolState,
} from "../presentation/types";
import { DEFAULT_INPUT_BINDINGS } from "../ui/AccessibilityController";

export interface RegisteredGameInput {
  readonly keys: ReadonlyMap<string, Phaser.Input.Keyboard.Key>;
  destroy(): void;
}

const REQUIRED_CODES = [
  "Space", "Digit1", "Digit2", "Digit3", "KeyR", "KeyH", "KeyC",
  "KeyE", "KeyW", "KeyD", "Escape", "KeyP", "Enter",
] as const;

function keyCodeFor(code: string): number {
  if (/^Key[A-Z]$/.test(code)) return Phaser.Input.Keyboard.KeyCodes[code.slice(3) as keyof typeof Phaser.Input.Keyboard.KeyCodes] as number;
  if (/^Digit[0-9]$/.test(code)) return Phaser.Input.Keyboard.KeyCodes[code.slice(5) as keyof typeof Phaser.Input.Keyboard.KeyCodes] as number;
  const named: Record<string, number> = {
    Space: Phaser.Input.Keyboard.KeyCodes.SPACE,
    Escape: Phaser.Input.Keyboard.KeyCodes.ESC,
    Enter: Phaser.Input.Keyboard.KeyCodes.ENTER,
    ArrowUp: Phaser.Input.Keyboard.KeyCodes.UP,
    ArrowDown: Phaser.Input.Keyboard.KeyCodes.DOWN,
    ArrowLeft: Phaser.Input.Keyboard.KeyCodes.LEFT,
    ArrowRight: Phaser.Input.Keyboard.KeyCodes.RIGHT,
  };
  return named[code] ?? Phaser.Input.Keyboard.KeyCodes.SPACE;
}

export function registerGameInput(
  scene: Phaser.Scene,
  commands: PresentationCommands,
  bindings: Readonly<InputBindings> = DEFAULT_INPUT_BINDINGS,
): RegisteredGameInput {
  const keyboard = scene.input.keyboard;
  const keys = new Map<string, Phaser.Input.Keyboard.Key>();
  if (!keyboard) return { keys, destroy: () => undefined };

  const actionByCode = new Map<string, () => void>();
  const bind = (code: string, action: () => void): void => { actionByCode.set(code, action); };
  bind(bindings.pause, () => commands.setPaused());
  bind(bindings.speed1, () => commands.setSpeed(1));
  bind(bindings.speed2, () => commands.setSpeed(2));
  bind(bindings.speed3, () => commands.setSpeed(3));
  bind(bindings.road, () => commands.selectTool("road", "keyboard"));
  bind(bindings.home, () => commands.selectTool("home", "keyboard"));
  bind(bindings.commercial, () => commands.selectTool("commercial", "keyboard"));
  bind(bindings.power, () => commands.selectTool("power", "keyboard"));
  bind(bindings.water, () => commands.selectTool("water", "keyboard"));
  bind(bindings.demolish, () => commands.selectTool("demolish", "keyboard"));
  bind(bindings.cancel, () => commands.cancel());
  bind(bindings.overlay, () => commands.toggleOverlay("power"));
  bind(bindings.confirm, () => commands.confirm());

  const allCodes = new Set<string>([...REQUIRED_CODES, ...Object.values(bindings)]);
  for (const code of allCodes) {
    const key = keyboard.addKey(keyCodeFor(code), false, false);
    const handler = (_key: Phaser.Input.Keyboard.Key, event: KeyboardEvent): void => {
      if (event.repeat || event.code !== code) return;
      actionByCode.get(code)?.();
    };
    key.on("down", handler);
    keys.set(code, key);
  }

  return {
    keys,
    destroy: () => {
      for (const key of keys.values()) {
        key.removeAllListeners();
        keyboard.removeKey(key.keyCode);
      }
      keys.clear();
    },
  };
}

export interface GridInteractionOptions {
  cols?: number;
  rows?: number;
  originX?: number;
  originY?: number;
  cellWidth: number;
  cellHeight: number;
  preview: (tool: BuildTool, cells: readonly Cell[]) => PlacementPreview;
  buildingAt: (cell: Cell) => string | null;
  onToolSelected?: (payload: { tool: BuildTool | null; source: "keyboard" | "pointer" }) => void;
  onPlacementRequested: (payload: { kind: Exclude<BuildTool, "demolish">; cells: Cell[]; drag: boolean }) => void;
  onDemolitionRequested: (payload: { buildingId: string }) => void;
  onPreviewChanged?: (preview: PlacementPreview | null) => void;
}

export class GridInteractionController {
  readonly state: ToolState = { selected: null, hoverCell: null, dragCells: [], overlay: null };
  private dragging = false;
  private readonly cols: number;
  private readonly rows: number;
  private readonly originX: number;
  private readonly originY: number;

  constructor(private readonly scene: Phaser.Scene, private readonly options: GridInteractionOptions) {
    this.cols = options.cols ?? 24;
    this.rows = options.rows ?? 14;
    this.originX = options.originX ?? 0;
    this.originY = options.originY ?? 0;
    scene.input.on("pointerdown", this.handleDown, this);
    scene.input.on("pointermove", this.handleMove, this);
    scene.input.on("pointerup", this.handleUp, this);
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, this.destroy, this);
  }

  selectTool(tool: BuildTool | null, source: "keyboard" | "pointer" = "pointer"): void {
    this.state.selected = tool;
    this.state.dragCells = [];
    this.dragging = false;
    this.options.onToolSelected?.({ tool, source });
    this.refreshPreview();
  }

  setOverlay(overlay: OverlayKind | null): void {
    this.state.overlay = overlay;
  }

  cancel(): void {
    if (this.dragging) {
      this.dragging = false;
      this.state.dragCells = [];
      this.refreshPreview();
    } else {
      this.selectTool(null, "pointer");
    }
  }

  pointerToCell(pointer: Phaser.Input.Pointer): Cell | null {
    const world = this.scene.cameras.main.getWorldPoint(pointer.x, pointer.y);
    const x = Math.floor((world.x - this.originX) / this.options.cellWidth);
    const y = Math.floor((world.y - this.originY) / this.options.cellHeight);
    return x >= 0 && y >= 0 && x < this.cols && y < this.rows ? { x, y } : null;
  }

  pointerDown(cell: Cell | null): void {
    if (!cell || !this.state.selected) return;
    this.state.hoverCell = cell;
    if (this.state.selected === "road") {
      this.dragging = true;
      this.state.dragCells = [cell];
      this.refreshPreview();
      return;
    }
    if (this.state.selected === "demolish") {
      const buildingId = this.options.buildingAt(cell);
      if (buildingId) this.options.onDemolitionRequested({ buildingId });
      return;
    }
    const preview = this.options.preview(this.state.selected, [cell]);
    this.options.onPreviewChanged?.(preview);
    this.options.onPlacementRequested({ kind: this.state.selected, cells: [...preview.cells], drag: false });
  }

  pointerMove(cell: Cell | null): void {
    this.state.hoverCell = cell;
    if (this.dragging && cell) this.appendRoadCells(cell);
    this.refreshPreview();
  }

  pointerUp(cell: Cell | null): void {
    if (!this.dragging || this.state.selected !== "road") return;
    if (cell) this.appendRoadCells(cell);
    this.dragging = false;
    const preview = this.options.preview("road", this.state.dragCells);
    this.options.onPreviewChanged?.(preview);
    this.options.onPlacementRequested({ kind: "road", cells: [...preview.cells], drag: true });
    this.state.dragCells = [];
  }

  destroy(): void {
    this.scene.input.off("pointerdown", this.handleDown, this);
    this.scene.input.off("pointermove", this.handleMove, this);
    this.scene.input.off("pointerup", this.handleUp, this);
  }

  private handleDown(pointer: Phaser.Input.Pointer): void { this.pointerDown(this.pointerToCell(pointer)); }
  private handleMove(pointer: Phaser.Input.Pointer): void { this.pointerMove(this.pointerToCell(pointer)); }
  private handleUp(pointer: Phaser.Input.Pointer): void { this.pointerUp(this.pointerToCell(pointer)); }

  private appendRoadCells(target: Cell): void {
    const last = this.state.dragCells[this.state.dragCells.length - 1];
    if (!last) { this.state.dragCells.push(target); return; }
    let x = last.x;
    let y = last.y;
    while (x !== target.x) { x += Math.sign(target.x - x); this.pushUnique({ x, y }); }
    while (y !== target.y) { y += Math.sign(target.y - y); this.pushUnique({ x, y }); }
  }

  private pushUnique(cell: Cell): void {
    if (!this.state.dragCells.some(existing => existing.x === cell.x && existing.y === cell.y)) {
      this.state.dragCells.push(cell);
    }
  }

  private refreshPreview(): void {
    const tool = this.state.selected;
    if (!tool || tool === "demolish" || !this.state.hoverCell) {
      this.options.onPreviewChanged?.(null);
      return;
    }
    const cells = tool === "road" && this.state.dragCells.length > 0 ? this.state.dragCells : [this.state.hoverCell];
    this.options.onPreviewChanged?.(this.options.preview(tool, cells));
  }
}
