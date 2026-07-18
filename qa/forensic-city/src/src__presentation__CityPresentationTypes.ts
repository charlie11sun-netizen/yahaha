export type BuildTool = "road" | "residential" | "commercial" | "powerPlant" | "waterTower";
export type PlannerTool = BuildTool | "inspect" | "demolish";
export type CoverageOverlay = "none" | "power" | "water" | "pollution";
export type SimulationSpeed = 1 | 2 | 4;

export interface GridPoint {
  x: number;
  y: number;
}

export interface BuildRequest {
  tool: BuildTool;
  anchor: GridPoint;
  dragId?: string;
}

export interface BuildValidation {
  legal: boolean;
  price: number;
  reason?: string;
  footprint?: readonly GridPoint[];
  connectionDirections?: readonly ("up" | "right" | "down" | "left")[];
}

export interface DemolitionPreview {
  structureId: string;
  name: string;
  refund: number;
  affectedBuildingCount: number;
  affectedLabels?: readonly string[];
}

export interface PlannerState {
  tool: PlannerTool;
  hover: GridPoint | null;
  dragPath: readonly GridPoint[];
  validation: BuildValidation | null;
  demolition: DemolitionPreview | null;
}

export interface CityHudSnapshot {
  funds: number;
  population: number;
  netIncome: number;
  satisfaction: number;
  pollution: number;
  score: number;
  speed: SimulationSpeed;
  paused: boolean;
  gameSeconds: number;
  month: number;
  scoreParts: readonly { label: string; value: number; max: number; icon: string }[];
  penaltyReasons: readonly string[];
  prosperitySeconds: number;
  prosperityConditions: readonly { label: string; met: boolean; current: string; target: string }[];
  danger?: { kind: "debt" | "satisfaction"; seconds: number; reason: string };
  disaster?: DisasterPresentation;
  voucherAvailable?: boolean;
}

export interface DisasterPresentation {
  id: string;
  type: "fire" | "blackout" | "pipeBurst";
  targetName: string;
  warning: boolean;
  remainingSeconds: number;
  totalSeconds: number;
  dispatchCost: number;
  affordable: boolean;
  direction?: "up" | "right" | "down" | "left";
}

export interface CapacityPresentation {
  used: number;
  capacity: number;
  covered: boolean;
  distance?: number;
}

export interface BuildingPresentation {
  id: string;
  name: string;
  kind: BuildTool;
  cost: number;
  maintenance: number;
  roadConnected: boolean;
  power: CapacityPresentation;
  water: CapacityPresentation;
  population?: number;
  populationCapacity?: number;
  jobs?: number;
  jobCapacity?: number;
  pollution: number;
  satisfactionImpact: number;
  statusText: string;
}

export interface OutcomeStatsPresentation {
  population: number;
  peakPopulation: number;
  totalTax: number;
  disastersHandled: number;
  peakScore: number;
  operatingSeconds: number;
}

export interface OutcomePresentation {
  kind: "victory" | "defeat";
  reason: string;
  stats: OutcomeStatsPresentation;
}

export interface CityPresentationCommands {
  requestBuild(request: BuildRequest): void;
  requestDemolish(structureId: string, confirmed: boolean): void;
  requestSimulation(control: { paused?: boolean; speed?: SimulationSpeed }): void;
  requestEmergency(disasterId: string): void;
  requestRestart(source: "hud" | "victory" | "defeat"): void;
  requestContinueAfterVictory(): void;
  selectTool(tool: PlannerTool): void;
  setOverlay(overlay: CoverageOverlay): void;
  toggleMinimap(): void;
  closeTopPanel(): void;
}

export const BUILD_TOOL_LABELS: Readonly<Record<BuildTool, string>> = {
  road: "道路",
  residential: "住宅",
  commercial: "商业",
  powerPlant: "电厂",
  waterTower: "水塔",
};
