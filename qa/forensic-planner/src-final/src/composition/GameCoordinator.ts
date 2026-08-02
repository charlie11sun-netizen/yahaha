import { CitySimulation } from "../domain/CitySimulation";

export type CityCell = Readonly<{ x: number; y: number }>;
export type CityBuildTool = "road" | "residential" | "commercial" | "powerPlant" | "waterTower";
export type CitySpeed = 1 | 2 | 4;

/** The sole command gateway between presentation requests and the rules API. */
export class GameCoordinator {
  constructor(readonly simulation: CitySimulation) {}

  place(tool: CityBuildTool, cells: readonly CityCell[]) {
    return this.simulation.place(tool, tool === "road" ? cells : cells[0]);
  }

  demolish(cell: CityCell) { return this.simulation.demolish(cell); }
  repair(buildingId: string) { return this.simulation.repair(buildingId); }
  setTimeControl(request: { paused?: boolean; speed?: CitySpeed }): void { this.simulation.setTimeControl(request); }
  update(deltaMs: number): void { this.simulation.update(deltaMs); }
}
