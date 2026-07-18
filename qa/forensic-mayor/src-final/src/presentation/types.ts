export type BuildTool = "road" | "home" | "commercial" | "power" | "water" | "demolish";
export type OverlayKind = "road" | "power" | "water" | "pollution";
export type InputSource = "keyboard" | "pointer";
export type SimulationSpeed = 1 | 2 | 3;

export interface Cell {
  x: number;
  y: number;
}

export interface ToolState {
  selected: BuildTool | null;
  hoverCell: Cell | null;
  dragCells: Cell[];
  overlay: OverlayKind | null;
}

export interface PlacementPreview {
  cells: Cell[];
  legal: boolean;
  reason?: string;
  cost?: number;
}

export interface PresentationCommands {
  selectTool(tool: BuildTool | null, source: InputSource): void;
  setPaused(paused?: boolean): void;
  setSpeed(speed: SimulationSpeed): void;
  toggleOverlay(overlay: OverlayKind): void;
  cancel(): void;
  confirm(): void;
  restart(source: "Enter" | "button"): void;
  disasterAction(actionId: string): void;
}

export interface InputBindings {
  pause: string;
  speed1: string;
  speed2: string;
  speed3: string;
  road: string;
  home: string;
  commercial: string;
  power: string;
  water: string;
  demolish: string;
  cancel: string;
  overlay: string;
  confirm: string;
}

export interface CitySettings {
  masterVolume: number;
  musicVolume: number;
  sfxVolume: number;
  reducedMotion: boolean;
  highContrast: boolean;
}

export interface EconomyHudSnapshot {
  funds: number;
  dailyIncome: number;
  dailyMaintenance: number;
}

export interface CityMetricsHudSnapshot {
  population: number;
  pollution: number;
  satisfaction: number;
  score: number;
  powerDemand: number;
  powerCapacity: number;
  waterDemand: number;
  waterCapacity: number;
}

export interface CityHudSnapshot {
  day: number;
  stableDays: number;
  speed: SimulationSpeed;
  paused: boolean;
  economy: EconomyHudSnapshot;
  metrics: CityMetricsHudSnapshot;
  bankruptcyDays: number;
  abandonmentDays: number;
}

export type BuildingVisualKind = "road" | "home" | "commercial" | "power" | "water" | "tree";

export interface BuildingVisual {
  id: string;
  kind: BuildingVisualKind;
  cell: Cell;
  width: number;
  height: number;
  connected?: boolean;
  powered?: boolean;
  watered?: boolean;
  operating?: boolean;
  pollution?: "none" | "weak" | "strong";
  disaster?: string | null;
}

export interface DisasterNotice {
  id: string;
  title: string;
  detail: string;
  remainingDays: number;
  actions?: ReadonlyArray<{ id: string; label: string; enabled?: boolean }>;
}

export type FeedbackEventName =
  | "placement-ok" | "placement-rejected" | "network-connected" | "income"
  | "milestone" | "disaster-warning" | "disaster-start" | "disaster-resolved"
  | "score-threshold" | "stable-day" | "pause" | "speed" | "victory" | "defeat";
