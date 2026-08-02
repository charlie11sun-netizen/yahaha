export type BuildingKind = "road" | "home" | "commercial" | "power" | "water";
export type DisasterKind = "facility_failure" | "fire" | "storm" | "blackout" | "water_main_break";
export type PopulationTierId = "growth" | "pressure" | "metropolis";
export type GridBlockReason = "boundary" | "reserved_tree" | null;

export interface Cell {
  readonly x: number;
  readonly y: number;
}

export interface CellRect extends Cell {
  readonly width: number;
  readonly height: number;
}

export interface ContentFrameRef {
  readonly sheetKey: "sheet-2" | "sheet-3";
  readonly frameName: string;
  readonly frameIndex: number;
}

export interface BuildingDefinition {
  readonly kind: BuildingKind;
  readonly name: string;
  readonly description: string;
  readonly footprint: { readonly width: number; readonly height: number };
  readonly cost: number;
  readonly demolitionRefundRate: number;
  readonly dailyIncome: number;
  readonly dailyMaintenance: number;
  readonly populationCapacity: number;
  readonly minimumPopulationToOperate: number;
  readonly powerDemand: number;
  readonly waterDemand: number;
  readonly powerCapacity: number;
  readonly waterCapacity: number;
  readonly pollution: {
    readonly strongRadius: number;
    readonly weakRadius: number;
    readonly strongAmount: number;
    readonly weakAmount: number;
  } | null;
  readonly requiresRoad: boolean;
  readonly art: ContentFrameRef;
  readonly connectableTileFamily?: "entity_1";
}

export interface GridCell extends Cell {
  readonly terrain: "grass";
  blocked: boolean;
  blockReason: GridBlockReason;
  buildingId: string | null;
  damaged: boolean;
}

export interface BuildingServiceState {
  roadConnected: boolean;
  powered: boolean;
  watered: boolean;
  efficiency: number;
}

export interface BuildingDisasterState {
  disasterId: string | null;
  disabledDays: number;
  capacityMultiplier: number;
  incomeMultiplier: number;
}

export interface BuildingInstance {
  readonly id: string;
  readonly kind: BuildingKind;
  readonly origin: Cell;
  readonly cells: readonly Cell[];
  readonly originalCost: number;
  service: BuildingServiceState;
  disaster: BuildingDisasterState;
}

export interface CityRegionDefinition extends CellRect {
  readonly id: string;
  readonly name: string;
  readonly kind: string;
}

export interface CityPathDefinition {
  readonly id: string;
  readonly points: readonly Cell[];
}

export interface CityPointDefinition extends Cell {
  readonly id: string;
  readonly kind: "spawn" | "objective" | "hazard" | "item" | "exit";
}

export interface CityMapDefinition {
  readonly cols: 24;
  readonly rows: 14;
  readonly cellWidth: number;
  readonly cellHeight: number;
  readonly regions: readonly CityRegionDefinition[];
  readonly boundaryCells: readonly Cell[];
  readonly reservedTreeCells: readonly Cell[];
  readonly starterRoadCells: readonly Cell[];
  readonly paths: readonly CityPathDefinition[];
  readonly points: readonly CityPointDefinition[];
  readonly maxBuildings: 160;
}

export interface DisasterDefinition {
  readonly kind: DisasterKind;
  readonly name: string;
  readonly description: string;
  readonly unlockPopulation: 120 | 300;
  readonly warningDays: 3;
  readonly durationDays: { readonly min: number; readonly max: number };
  readonly validTargets: readonly BuildingKind[];
  readonly maximumTargets: number;
  readonly effect: Readonly<Record<string, number | string | boolean>>;
  readonly mitigation: {
    readonly label: string;
    readonly flatCost?: number;
    readonly costRate?: number;
    readonly result: Readonly<Record<string, number | string | boolean>>;
  };
}

export interface MilestoneDefinition {
  readonly population: 100 | 250 | 400;
  readonly amount: 1000 | 1500 | 2000;
  readonly name: string;
  readonly purpose: string;
  readonly art: ContentFrameRef;
}

export interface PopulationTierDefinition {
  readonly id: PopulationTierId;
  readonly minPopulation: number;
  readonly maxPopulation: number | null;
  readonly demandMultiplier: number;
  readonly commercialIncomeMultiplier: number;
  readonly pollutionImpactMultiplier: number;
  readonly maintenanceMultiplier: number;
  readonly unlockedDisasters: readonly DisasterKind[];
}

export interface TutorialStepDefinition {
  readonly id: "build_power" | "build_water" | "build_home" | "build_commercial";
  readonly order: 1 | 2 | 3 | 4;
  readonly title: string;
  readonly instruction: string;
  readonly tool: Exclude<BuildingKind, "road">;
  readonly objectivePointId: string;
  readonly suggestedOrigin: Cell;
  readonly suggestedRoadCells: readonly Cell[];
  readonly completion: {
    readonly buildingKind: Exclude<BuildingKind, "road">;
    readonly requiresRoadConnection: true;
  };
  readonly advice: string;
}

export interface TutorialState {
  step: number;
  completed: boolean;
  skipped: boolean;
}

export interface InitialWorldState {
  /** Column-major: grid[x][y], exactly 24 columns by 14 rows. */
  readonly grid: GridCell[][];
  readonly buildings: Map<string, BuildingInstance>;
  tutorialState: TutorialState;
}
