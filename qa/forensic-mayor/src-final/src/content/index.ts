import { BUILDING_CATALOG } from "./BuildingCatalog";
import type { BuildingInstance, Cell, GridCell, InitialWorldState } from "./CityTypes";
import { DISASTER_CATALOG, DISASTER_SCHEDULING } from "./DisasterCatalog";
import { MILESTONE_CATALOG, POPULATION_TIERS, TUTORIAL_STEPS, TUTORIAL_WINDOW } from "./ProgressionContent";
import { CITY_MAP } from "../levels/CityMap";

export * from "./CityTypes";
export { BUILDING_CATALOG } from "./BuildingCatalog";
export { DISASTER_CATALOG, DISASTER_SCHEDULING } from "./DisasterCatalog";
export { MILESTONE_CATALOG, POPULATION_TIERS, TUTORIAL_STEPS, TUTORIAL_WINDOW } from "./ProgressionContent";
export { CITY_MAP } from "../levels/CityMap";

export const INITIAL_CITY_SETTINGS = Object.freeze({
  startingFunds: 12000,
  initialRunPhase: "paused" as const,
  initialDay: 1,
  maximumBuildings: 160,
});

function cellKey(cell: Cell): string {
  return `${cell.x},${cell.y}`;
}

function makeGrid(): GridCell[][] {
  const boundary = new Set(CITY_MAP.boundaryCells.map(cellKey));
  const trees = new Set(CITY_MAP.reservedTreeCells.map(cellKey));
  const grid: GridCell[][] = [];

  for (let x = 0; x < CITY_MAP.cols; x += 1) {
    const column: GridCell[] = [];
    for (let y = 0; y < CITY_MAP.rows; y += 1) {
      const key = `${x},${y}`;
      const isBoundary = boundary.has(key);
      const isTree = trees.has(key);
      column.push({
        x,
        y,
        terrain: "grass",
        blocked: isBoundary || isTree,
        blockReason: isBoundary ? "boundary" : isTree ? "reserved_tree" : null,
        buildingId: null,
        damaged: false,
      });
    }
    grid.push(column);
  }
  return grid;
}

function makeStarterRoad(id: string, origin: Cell): BuildingInstance {
  const placedCell = Object.freeze({ x: origin.x, y: origin.y });
  return {
    id,
    kind: "road",
    origin: placedCell,
    cells: Object.freeze([placedCell]),
    originalCost: BUILDING_CATALOG.road.cost,
    service: {
      roadConnected: true,
      powered: true,
      watered: true,
      efficiency: 1,
    },
    disaster: {
      disasterId: null,
      disabledDays: 0,
      capacityMultiplier: 1,
      incomeMultiplier: 1,
    },
  };
}

/** Produces a fresh mutable runtime snapshot from immutable city content. */
export function createInitialWorldState(): InitialWorldState {
  const grid = makeGrid();
  const buildings = new Map<string, BuildingInstance>();

  CITY_MAP.starterRoadCells.forEach((cell, index) => {
    const id = `starter-road-${String(index + 1).padStart(2, "0")}`;
    const road = makeStarterRoad(id, cell);
    buildings.set(id, road);
    grid[cell.x][cell.y].buildingId = id;
  });

  return {
    grid,
    buildings,
    tutorialState: {
      step: 0,
      completed: false,
      skipped: false,
    },
  };
}

/** Compact aggregate for adapters that prefer one import without duplicating content. */
export const CITY_CONTENT = Object.freeze({
  map: CITY_MAP,
  buildings: BUILDING_CATALOG,
  disasters: DISASTER_CATALOG,
  disasterScheduling: DISASTER_SCHEDULING,
  milestones: MILESTONE_CATALOG,
  populationTiers: POPULATION_TIERS,
  tutorialSteps: TUTORIAL_STEPS,
  tutorialWindow: TUTORIAL_WINDOW,
  initialSettings: INITIAL_CITY_SETTINGS,
});
