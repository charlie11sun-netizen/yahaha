import Phaser from "phaser";
import { Sfx } from "../systems/Sfx";
import type { CityPresentationCommands, CoverageOverlay, PlannerTool, SimulationSpeed } from "../presentation/CityPresentationTypes";

export type GameControlAction =
  | "pause" | "speed1" | "speed2" | "speed4"
  | "road" | "residential" | "commercial" | "powerPlant" | "waterTower" | "demolish"
  | "close" | "minimap" | "powerOverlay" | "waterOverlay" | "pollutionOverlay";

export interface RegisteredGameControls {
  readonly keys: Readonly<Record<GameControlAction, Phaser.Input.Keyboard.Key>>;
  trigger(action: GameControlAction): void;
  setPaused(paused: boolean): void;
  setOverlay(overlay: CoverageOverlay): void;
  selectTool(tool: PlannerTool): void;
  destroy(): void;
}

export interface GameControlOptions {
  isPaused: () => boolean;
  getOverlay: () => CoverageOverlay;
}

/** Registers the frozen keyboard map. UI buttons should call trigger/selectTool/
 * setOverlay on the returned object so keyboard and pointer share one command path. */
export function registerGameControls(
  scene: Phaser.Scene,
  commands: CityPresentationCommands,
  options: GameControlOptions,
): RegisteredGameControls {
  const keyboard = scene.input.keyboard;
  if (!keyboard) throw new Error("Keyboard input is unavailable");

  const codes: Record<GameControlAction, number> = {
    pause: Phaser.Input.Keyboard.KeyCodes.SPACE,
    speed1: Phaser.Input.Keyboard.KeyCodes.ONE,
    speed2: Phaser.Input.Keyboard.KeyCodes.TWO,
    speed4: Phaser.Input.Keyboard.KeyCodes.THREE,
    road: Phaser.Input.Keyboard.KeyCodes.R,
    residential: Phaser.Input.Keyboard.KeyCodes.H,
    commercial: Phaser.Input.Keyboard.KeyCodes.C,
    powerPlant: Phaser.Input.Keyboard.KeyCodes.E,
    waterTower: Phaser.Input.Keyboard.KeyCodes.W,
    demolish: Phaser.Input.Keyboard.KeyCodes.X,
    close: Phaser.Input.Keyboard.KeyCodes.ESC,
    minimap: Phaser.Input.Keyboard.KeyCodes.M,
    powerOverlay: Phaser.Input.Keyboard.KeyCodes.P,
    waterOverlay: Phaser.Input.Keyboard.KeyCodes.U,
    pollutionOverlay: Phaser.Input.Keyboard.KeyCodes.O,
  };

  const keys = {} as Record<GameControlAction, Phaser.Input.Keyboard.Key>;
  const select = (tool: PlannerTool): void => {
    commands.selectTool(tool);
    Sfx.play("select", 0.55);
  };
  const overlay = (next: Exclude<CoverageOverlay, "none">): void => {
    commands.setOverlay(options.getOverlay() === next ? "none" : next);
    Sfx.play("select", 0.5);
  };
  const speed = (value: SimulationSpeed): void => {
    commands.requestSimulation({ paused: false, speed: value });
    Sfx.play("select", 0.45);
  };

  const actions: Record<GameControlAction, () => void> = {
    pause: () => commands.requestSimulation({ paused: !options.isPaused() }),
    speed1: () => speed(1),
    speed2: () => speed(2),
    speed4: () => speed(4),
    road: () => select("road"),
    residential: () => select("residential"),
    commercial: () => select("commercial"),
    powerPlant: () => select("powerPlant"),
    waterTower: () => select("waterTower"),
    demolish: () => select("demolish"),
    close: () => commands.closeTopPanel(),
    minimap: () => commands.toggleMinimap(),
    powerOverlay: () => overlay("power"),
    waterOverlay: () => overlay("water"),
    pollutionOverlay: () => overlay("pollution"),
  };

  for (const action of Object.keys(codes) as GameControlAction[]) {
    const key = keyboard.addKey(codes[action], true);
    keys[action] = key;
    key.on("down", (_key: Phaser.Input.Keyboard.Key, event: KeyboardEvent) => {
      if (action === "pause") event?.preventDefault();
      actions[action]();
    });
  }

  return {
    keys,
    trigger(action): void { actions[action](); },
    setPaused(paused): void { commands.requestSimulation({ paused }); },
    setOverlay(next): void { commands.setOverlay(next); },
    selectTool(tool): void { select(tool); },
    destroy(): void {
      for (const key of Object.values(keys)) {
        key.removeAllListeners();
        keyboard.removeKey(key);
      }
    },
  };
}
