import Phaser from "phaser";
import { InputRouter } from "../systems/InputRouter";
import { Sfx } from "../systems/Sfx";

type Tool = "road" | "residential" | "commercial" | "powerPlant" | "waterTower" | "demolish" | null;
type Cell = { x: number; y: number };
type TimeSpeed = 1 | 2 | 4;
type InputCallbacks = {
  worldToCell: (worldX: number, worldY: number) => Cell | null;
  onToolSelected: (tool: Tool) => void;
  onPlacementRequested: (request: { tool: Exclude<Tool, "demolish" | null>; cell: Cell; dragCells?: Cell[] }) => void;
  onDemolitionRequested: (request: { cell: Cell }) => void;
  onSelectionRequested: (selection: { buildingId: null; cell: Cell | null }) => void;
  onTimeControlRequested: (request: { paused?: boolean; speed?: TimeSpeed }) => void;
  onHoverChanged?: (hover: { cell: Cell | null; tool: Tool; dragCells?: Cell[] }) => void;
  onCancel?: () => void;
};

/** Maps real Phaser keyboard/pointer input to commands; it never reads or mutates simulation state. */
export class InputController {
  private readonly scene: Phaser.Scene;
  private readonly callbacks: InputCallbacks;
  private readonly keys: Phaser.Input.Keyboard.Key[] = [];
  private readonly disposeWorldPointer: () => void;
  private activeTool: Tool = null;
  private paused = false;
  private speed: TimeSpeed = 1;
  private dragCells: Cell[] = [];
  private draggingRoad = false;
  private disposed = false;

  constructor(scene: Phaser.Scene, callbacks: InputCallbacks) {
    this.scene = scene;
    this.callbacks = callbacks;
    this.disposeWorldPointer = InputRouter.worldPointer(scene, {
      down: (pointer) => this.pointerDown(pointer),
      move: (pointer) => this.pointerMove(pointer),
      up: (pointer) => this.pointerUp(pointer),
    });
    this.registerKeyboard();
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.destroy());
  }

  get tool(): Tool { return this.activeTool; }
  get currentSpeed(): TimeSpeed { return this.speed; }
  get isPaused(): boolean { return this.paused; }

  /** Integration feeds authoritative clock state back so toggles derive from current state. */
  setTimeState(paused: boolean, speed: TimeSpeed): void {
    this.paused = paused;
    this.speed = speed;
  }

  selectTool(tool: Tool): void {
    this.activeTool = tool;
    this.dragCells = [];
    this.draggingRoad = false;
    this.callbacks.onToolSelected(tool);
    this.callbacks.onHoverChanged?.({ cell: null, tool });
    Sfx.play("select");
  }

  togglePause(): void {
    const next = !this.paused;
    this.callbacks.onTimeControlRequested({ paused: next });
    Sfx.play("select");
  }

  requestSpeed(speed: TimeSpeed): void {
    this.callbacks.onTimeControlRequested({ speed });
    Sfx.play("select");
  }

  cancel(): void {
    this.activeTool = null;
    this.dragCells = [];
    this.draggingRoad = false;
    this.callbacks.onToolSelected(null);
    this.callbacks.onSelectionRequested({ buildingId: null, cell: null });
    this.callbacks.onHoverChanged?.({ cell: null, tool: null });
    this.callbacks.onCancel?.();
    Sfx.play("select", 0.65);
  }

  destroy(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.disposeWorldPointer();
    for (const key of this.keys) {
      key.removeAllListeners();
      this.scene.input.keyboard?.removeKey(key);
    }
    this.keys.length = 0;
  }

  private registerKeyboard(): void {
    const keyboard = this.scene.input.keyboard;
    if (!keyboard) return;
    const bind = (code: number, action: () => void): void => {
      const key = keyboard.addKey(code);
      key.on(Phaser.Input.Keyboard.Events.DOWN, action);
      this.keys.push(key);
    };
    bind(Phaser.Input.Keyboard.KeyCodes.SPACE, () => this.togglePause());
    bind(Phaser.Input.Keyboard.KeyCodes.ONE, () => this.requestSpeed(1));
    bind(Phaser.Input.Keyboard.KeyCodes.TWO, () => this.requestSpeed(2));
    bind(Phaser.Input.Keyboard.KeyCodes.THREE, () => this.requestSpeed(4));
    bind(Phaser.Input.Keyboard.KeyCodes.R, () => this.selectTool("road"));
    bind(Phaser.Input.Keyboard.KeyCodes.H, () => this.selectTool("residential"));
    bind(Phaser.Input.Keyboard.KeyCodes.C, () => this.selectTool("commercial"));
    bind(Phaser.Input.Keyboard.KeyCodes.E, () => this.selectTool("powerPlant"));
    bind(Phaser.Input.Keyboard.KeyCodes.W, () => this.selectTool("waterTower"));
    bind(Phaser.Input.Keyboard.KeyCodes.X, () => this.selectTool("demolish"));
    bind(Phaser.Input.Keyboard.KeyCodes.ESC, () => this.cancel());
  }

  private pointerDown(pointer: Phaser.Input.Pointer): void {
    const cell = this.callbacks.worldToCell(pointer.worldX, pointer.worldY);
    if (!cell) return;
    if (this.activeTool === "road") {
      this.draggingRoad = true;
      this.dragCells = [cell];
      this.callbacks.onHoverChanged?.({ cell, tool: this.activeTool, dragCells: [...this.dragCells] });
    }
  }

  private pointerMove(pointer: Phaser.Input.Pointer): void {
    const cell = this.callbacks.worldToCell(pointer.worldX, pointer.worldY);
    if (!cell) {
      this.callbacks.onHoverChanged?.({ cell: null, tool: this.activeTool, dragCells: this.draggingRoad ? [...this.dragCells] : undefined });
      return;
    }
    if (this.draggingRoad && this.activeTool === "road") this.extendOrthogonalPath(cell);
    this.callbacks.onHoverChanged?.({
      cell,
      tool: this.activeTool,
      dragCells: this.draggingRoad ? [...this.dragCells] : undefined,
    });
  }

  private pointerUp(pointer: Phaser.Input.Pointer): void {
    const cell = this.callbacks.worldToCell(pointer.worldX, pointer.worldY);
    if (!cell) {
      this.draggingRoad = false;
      this.dragCells = [];
      return;
    }
    if (this.activeTool === "road") {
      if (this.dragCells.length === 0) this.dragCells = [cell];
      else this.extendOrthogonalPath(cell);
      const cells = [...this.dragCells];
      this.draggingRoad = false;
      this.dragCells = [];
      this.callbacks.onPlacementRequested({ tool: "road", cell: cells[0], dragCells: cells });
      return;
    }
    if (this.activeTool === "demolish") {
      this.callbacks.onDemolitionRequested({ cell });
      return;
    }
    if (this.activeTool) {
      this.callbacks.onPlacementRequested({ tool: this.activeTool, cell });
      return;
    }
    this.callbacks.onSelectionRequested({ buildingId: null, cell });
  }

  /** Pointer geometry only: rules still decide whether any generated cell may be built. */
  private extendOrthogonalPath(target: Cell): void {
    const last = this.dragCells[this.dragCells.length - 1];
    if (!last) {
      this.dragCells.push(target);
      return;
    }
    let x = last.x;
    let y = last.y;
    while (x !== target.x) {
      x += Math.sign(target.x - x);
      this.pushUniqueTail({ x, y });
    }
    while (y !== target.y) {
      y += Math.sign(target.y - y);
      this.pushUniqueTail({ x, y });
    }
  }

  private pushUniqueTail(cell: Cell): void {
    const tail = this.dragCells[this.dragCells.length - 1];
    if (!tail || tail.x !== cell.x || tail.y !== cell.y) this.dragCells.push(cell);
  }
}
