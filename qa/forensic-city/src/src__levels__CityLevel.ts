export interface GridPoint {
  readonly x: number;
  readonly y: number;
}

export interface GridRect {
  readonly xMin: number;
  readonly yMin: number;
  readonly xMax: number;
  readonly yMax: number;
}

export type TerrainKind = "grass" | "river" | "bridge" | "rock" | "naturalObstacle";

export interface GridCellDefinition extends GridPoint {
  readonly index: number;
  readonly terrain: TerrainKind;
  readonly buildable: boolean;
  readonly regionIds: readonly string[];
}

export interface RegionDefinition {
  readonly id: "west_reserve" | "old_town_corridor" | "east_market" | "utility_basin";
  readonly name: string;
  readonly bounds: GridRect;
  readonly kind: string;
  readonly planningHint: string;
}

export interface LevelPathDefinition {
  readonly id: "starting_road" | "bridge_expansion_route" | "utility_branch_route";
  readonly points: readonly GridPoint[];
}

export interface LevelPointDefinition extends GridPoint {
  readonly id: string;
  readonly kind: "spawn" | "objective" | "item" | "hazard" | "exit";
}

export interface InitialStructureDefinition {
  readonly id: string;
  readonly kind: "road";
  readonly anchor: GridPoint;
  readonly built: true;
  readonly playerOwned: false;
}

export const REGION_DEFINITIONS: readonly RegionDefinition[] = Object.freeze([
  {
    id: "west_reserve",
    name: "河西新区",
    bounds: { xMin: 0, yMin: 0, xMax: 8, yMax: 11 },
    kind: "主要住宅与早期教学建设区",
    planningHint: "接近起始道路，适合紧凑住宅；注意为商业和设施预留路口。",
  },
  {
    id: "old_town_corridor",
    name: "旧城交通走廊",
    bounds: { xMin: 1, yMin: 5, xMax: 15, yMax: 7 },
    kind: "包含预铺道路与跨河桥的城市主轴",
    planningHint: "跨河唯一连续主轴，断路会同时影响两岸服务。",
  },
  {
    id: "east_market",
    name: "东岸商街",
    bounds: { xMin: 11, yMin: 2, xMax: 19, yMax: 7 },
    kind: "商业、就业与高税收发展区",
    planningHint: "适合商业集群，但需控制道路距离与双服务容量。",
  },
  {
    id: "utility_basin",
    name: "东南公用设施区",
    bounds: { xMin: 11, yMin: 8, xMax: 19, yMax: 11 },
    kind: "适合放置电厂和供水设施的工业岩地区",
    planningHint: "远离西岸住宅，可降低电厂污染暴露；东南角岩地不可建。",
  },
]);

const WALL_RECTS: readonly GridRect[] = Object.freeze([
  { xMin: 9, yMin: 0, xMax: 10, yMax: 4 },
  { xMin: 9, yMin: 7, xMax: 10, yMax: 11 },
  { xMin: 17, yMin: 0, xMax: 19, yMax: 1 },
  { xMin: 18, yMin: 10, xMax: 19, yMax: 11 },
]);

const COVER_CELLS: readonly GridPoint[] = Object.freeze([
  { x: 1, y: 1 },
  { x: 3, y: 2 },
  { x: 7, y: 1 },
  { x: 1, y: 10 },
  { x: 6, y: 9 },
  { x: 13, y: 1 },
  { x: 16, y: 3 },
  { x: 15, y: 10 },
]);

const BRIDGE_CELLS: readonly GridPoint[] = Object.freeze([
  { x: 9, y: 5 },
  { x: 10, y: 5 },
  { x: 9, y: 6 },
  { x: 10, y: 6 },
]);

const PATHS: readonly LevelPathDefinition[] = Object.freeze([
  {
    id: "starting_road",
    points: [
      { x: 2, y: 6 },
      { x: 3, y: 6 },
      { x: 4, y: 6 },
      { x: 5, y: 6 },
      { x: 6, y: 6 },
    ],
  },
  {
    id: "bridge_expansion_route",
    points: [
      { x: 6, y: 6 },
      { x: 7, y: 6 },
      { x: 8, y: 6 },
      { x: 9, y: 6 },
      { x: 10, y: 6 },
      { x: 11, y: 6 },
      { x: 12, y: 6 },
      { x: 13, y: 6 },
      { x: 14, y: 6 },
    ],
  },
  {
    id: "utility_branch_route",
    points: [
      { x: 12, y: 6 },
      { x: 12, y: 7 },
      { x: 12, y: 8 },
      { x: 12, y: 9 },
      { x: 13, y: 9 },
      { x: 14, y: 9 },
      { x: 15, y: 9 },
      { x: 16, y: 9 },
    ],
  },
]);

const POINTS: readonly LevelPointDefinition[] = Object.freeze([
  { id: "planner_spawn", kind: "spawn", x: 3, y: 5 },
  { id: "prosperity_goal", kind: "objective", x: 14, y: 5 },
  { id: "west_tutorial_lot", kind: "item", x: 4, y: 5 },
  { id: "east_market_marker", kind: "objective", x: 15, y: 6 },
  { id: "utility_recommendation", kind: "item", x: 16, y: 8 },
  { id: "river_warning", kind: "hazard", x: 9, y: 5 },
  { id: "planning_exit", kind: "exit", x: 19, y: 6 },
]);

const INITIAL_STRUCTURES: readonly InitialStructureDefinition[] = Object.freeze(
  PATHS[0].points.map((anchor, index) => ({
    id: `starting-road-${index + 1}`,
    kind: "road" as const,
    anchor,
    built: true as const,
    playerOwned: false as const,
  })),
);

function pointKey(x: number, y: number): string {
  return `${x},${y}`;
}

function inside(rect: GridRect, x: number, y: number): boolean {
  return x >= rect.xMin && x <= rect.xMax && y >= rect.yMin && y <= rect.yMax;
}

const coverKeys = new Set(COVER_CELLS.map((cell) => pointKey(cell.x, cell.y)));
const bridgeKeys = new Set(BRIDGE_CELLS.map((cell) => pointKey(cell.x, cell.y)));

const CELLS: readonly GridCellDefinition[] = Object.freeze(
  Array.from({ length: 12 }, (_, y) =>
    Array.from({ length: 20 }, (_, x): GridCellDefinition => {
      const key = pointKey(x, y);
      const isBridge = bridgeKeys.has(key);
      const wallIndex = WALL_RECTS.findIndex((rect) => inside(rect, x, y));
      const isCover = coverKeys.has(key);
      const terrain: TerrainKind = isBridge
        ? "bridge"
        : isCover
          ? "naturalObstacle"
          : wallIndex === 0 || wallIndex === 1
            ? "river"
            : wallIndex >= 2
              ? "rock"
              : "grass";
      return Object.freeze({
        x,
        y,
        index: y * 20 + x,
        terrain,
        buildable: terrain === "grass" || terrain === "bridge",
        regionIds: REGION_DEFINITIONS.filter((region) => inside(region.bounds, x, y)).map((region) => region.id),
      });
    }),
  ).flat(),
);

export interface CityLevelDefinition {
  readonly id: "prosperity_city";
  readonly name: string;
  readonly viewport: Readonly<{ width: 1280; height: 720 }>;
  readonly grid: Readonly<{
    cols: 20;
    rows: 12;
    cellWidth: 64;
    cellHeight: 60;
    totalCells: 240;
    maxStructures: 120;
  }>;
  readonly cells: readonly GridCellDefinition[];
  readonly wallRects: readonly GridRect[];
  readonly coverCells: readonly GridPoint[];
  readonly bridgeCells: readonly GridPoint[];
  readonly paths: readonly LevelPathDefinition[];
  readonly points: readonly LevelPointDefinition[];
  readonly initialStructures: readonly InitialStructureDefinition[];
  readonly regions: readonly RegionDefinition[];
}

export const LEVEL_LAYOUT: CityLevelDefinition = Object.freeze({
  id: "prosperity_city",
  name: "双岸繁荣规划区",
  viewport: { width: 1280, height: 720 },
  grid: {
    cols: 20,
    rows: 12,
    cellWidth: 64,
    cellHeight: 60,
    totalCells: 240,
    maxStructures: 120,
  },
  cells: CELLS,
  wallRects: WALL_RECTS,
  coverCells: COVER_CELLS,
  bridgeCells: BRIDGE_CELLS,
  paths: PATHS,
  points: POINTS,
  initialStructures: INITIAL_STRUCTURES,
  regions: REGION_DEFINITIONS,
});
