type GridCell = readonly [col: number, row: number];
type GridRect = readonly [left: number, top: number, right: number, bottom: number];
type ToolId = "road" | "residential" | "commercial" | "powerPlant" | "waterTower";
type BuildingKind = "network" | "zone" | "utility";
type FrameRef = Readonly<{ sheet: "sheet" | "sheet-2" | "sheet-3"; frame: string }>;

interface BuildingDefinition {
  readonly id: ToolId;
  readonly name: string;
  readonly kind: BuildingKind;
  readonly footprint: readonly [number, number];
  readonly buildCost: number;
  readonly dailyMaintenance: number;
  readonly maxHealth: number;
  readonly requiresRoad: boolean;
  readonly electricityDemand: number;
  readonly waterDemand: number;
  readonly electricityPerResident?: number;
  readonly waterPerResident?: number;
  readonly populationCapacity?: number;
  readonly taxPerResident?: number;
  readonly commercialIncomeAtFullSupport?: number;
  readonly residentsPerFullCommercial?: number;
  readonly electricityCapacity?: number;
  readonly waterCapacity?: number;
  readonly roadServiceRange?: number;
  readonly pollutionSource?: number;
  readonly pollutionFalloffPerCell?: number;
  readonly pollutionSampleRadius?: number;
  readonly trafficPollutionWhenOperating?: number;
  readonly pollutionCapacityCurve?: readonly Readonly<{ pollution: number; capacityFactor: number }>[];
  readonly visual: FrameRef;
}

/** Exact 24×14 authored city plan. Coordinates are zero-based grid cells and rects are inclusive. */
export const CITY_MAP = {
  id: "pixel_city_single_screen",
  name: "像素都市规划师",
  viewport: { width: 1280, height: 720 },
  grid: { cols: 24, rows: 14, cellWidth: 53.33, cellHeight: 51.43 },
  initialState: { funds: 5000, satisfaction: 60, day: 1 },
  regions: [
    { id: "west_residential_terrace", name: "西部住宅台地", cells: [0, 0, 9, 7] as GridRect, kind: "平坦低污染建设区，教学阶段推荐建立首个住宅街区" },
    { id: "central_planning_cross", name: "中央规划十字区", cells: [9, 0, 16, 8] as GridRect, kind: "道路网络汇合区，地块规整且靠近全图中心" },
    { id: "east_industrial_buffer", name: "东部工业缓冲区", cells: [16, 0, 23, 7] as GridRect, kind: "远离西侧住宅的设施用地，适合电厂和备用基础设施" },
    { id: "south_expansion_plain", name: "南部扩建平原", cells: [0, 7, 16, 13] as GridRect, kind: "中后期住宅与商业扩建区，面积大但需要延伸道路网络" },
    { id: "southeast_water_lowland", name: "东南蓄水低地", cells: [16, 7, 23, 13] as GridRect, kind: "低初始污染的供水设施候选区，靠近排水渠与风暴路径" },
  ],
  walls: [
    { id: "central_ridge", cells: [11, 6, 13, 7] as GridRect, scenery: "ridge" },
    { id: "lowland_canal_west", cells: [19, 10, 23, 11] as GridRect, scenery: "canal" },
    { id: "lowland_canal_east", cells: [22, 11, 23, 13] as GridRect, scenery: "canal" },
  ],
  cover: ([
    [1, 1], [4, 1], [7, 5], [2, 10], [5, 12], [9, 10],
    [14, 2], [15, 12], [18, 1], [21, 3], [17, 12],
  ] as GridCell[]).map((cell, index) => ({ id: `ancient_tree_${index + 1}`, cell, scenery: "ancientTree" as const })),
  paths: [
    { id: "tutorial_road_guide", closed: false, points: [[2, 3], [3, 3], [4, 3], [5, 3], [6, 3], [7, 3], [8, 3], [9, 3]] as GridCell[] },
    { id: "city_vehicle_loop", closed: true, points: [[3, 4], [8, 4], [10, 4], [10, 9], [6, 9], [3, 9], [3, 4]] as GridCell[] },
    { id: "major_storm_track", closed: false, points: [[23, 2], [19, 4], [15, 6], [10, 8], [5, 11], [1, 13]] as GridCell[] },
  ],
  points: [
    { id: "player_spawn", kind: "spawn", at: [2, 3] as GridCell },
    { id: "first_district_objective", kind: "objective", at: [6, 3] as GridCell },
    { id: "industrial_recommendation", kind: "objective", at: [19, 4] as GridCell },
    { id: "clean_water_recommendation", kind: "objective", at: [18, 9] as GridCell },
    { id: "storm_entry", kind: "hazard", at: [23, 2] as GridCell },
    { id: "planning_grant_marker", kind: "item", at: [10, 5] as GridCell },
  ],
  decorativeTraffic: {
    maxVehicles: 24,
    routeId: "city_vehicle_loop",
    variants: ["red", "blue", "white"] as const,
    affectsSimulation: false,
  },
} as const;

/** Buildable catalog; values are tuning inputs for the rules layer, not rule implementations. */
export const BUILDING_DEFINITIONS = {
  road: {
    id: "road", name: "像素道路", kind: "network", footprint: [1, 1], buildCost: 40,
    dailyMaintenance: 1, maxHealth: 100, requiresRoad: false, electricityDemand: 0,
    waterDemand: 0, visual: { sheet: "sheet-2", frame: "entity_1" },
  },
  residential: {
    id: "residential", name: "青瓦住宅", kind: "zone", footprint: [1, 1], buildCost: 300,
    dailyMaintenance: 8, maxHealth: 100, requiresRoad: true, electricityDemand: 0,
    waterDemand: 0, populationCapacity: 50, taxPerResident: 2,
    electricityPerResident: 1, waterPerResident: 1,
    visual: { sheet: "sheet-2", frame: "entity_2" },
  },
  commercial: {
    id: "commercial", name: "金牌商业区", kind: "zone", footprint: [1, 1], buildCost: 450,
    dailyMaintenance: 18, maxHealth: 100, requiresRoad: true, electricityDemand: 35,
    waterDemand: 30, commercialIncomeAtFullSupport: 120, residentsPerFullCommercial: 60,
    trafficPollutionWhenOperating: 1.5,
    visual: { sheet: "sheet-2", frame: "entity_3" },
  },
  powerPlant: {
    id: "powerPlant", name: "赤焰电厂", kind: "utility", footprint: [1, 1], buildCost: 1200,
    dailyMaintenance: 95, maxHealth: 160, requiresRoad: true, electricityDemand: 0,
    waterDemand: 0, electricityCapacity: 300, roadServiceRange: 10, pollutionSource: 28,
    pollutionFalloffPerCell: 4, visual: { sheet: "sheet-2", frame: "entity_4" },
  },
  waterTower: {
    id: "waterTower", name: "蓝泉水塔", kind: "utility", footprint: [1, 1], buildCost: 900,
    dailyMaintenance: 70, maxHealth: 140, requiresRoad: true, electricityDemand: 0,
    waterDemand: 0, waterCapacity: 260, roadServiceRange: 10, pollutionSampleRadius: 3,
    pollutionCapacityCurve: [
      { pollution: 0, capacityFactor: 1 },
      { pollution: 10, capacityFactor: 1 },
      { pollution: 45, capacityFactor: 0.55 },
      { pollution: 64.444444, capacityFactor: 0.3 },
    ],
    visual: { sheet: "sheet-2", frame: "entity_5" },
  },
} as const satisfies Record<ToolId, BuildingDefinition>;

/** Disaster roster and authored targeting limits consumed by deterministic scheduling rules. */
export const DISASTER_DEFINITIONS = {
  fire: {
    id: "fire", name: "局部火灾", class: "normal", unlockDay: 40, warningDays: 2,
    durationDays: 1, target: "operatingBuilding", maxPrimaryTargets: 1, maxSpreadBuildings: 1,
    damage: { min: 28, max: 48 }, icon: "🔥", recoverable: true,
  },
  blackout: {
    id: "blackout", name: "短时停电", class: "normal", unlockDay: 40, warningDays: 2,
    durationDays: { min: 2, max: 4 }, target: "roadNetwork", maxPrimaryTargets: 1,
    damage: null, icon: "⚡", recoverable: true,
  },
  pollutionLeak: {
    id: "pollutionLeak", name: "供水污染", class: "normal", unlockDay: 40, warningDays: 2,
    durationDays: 3, target: "waterTower", maxPrimaryTargets: 1,
    temporaryPollution: 36, radius: 3, icon: "💧!", recoverable: true,
  },
  storm: {
    id: "storm", name: "风暴损坏", class: "normal", unlockDay: 40, warningDays: 2,
    durationDays: 1, target: "stormTrackVicinity", maxBuildingTargets: 3, maxRoadTargets: 6,
    damage: { min: 20, max: 45 }, icon: "🌪", recoverable: true,
  },
  majorStorm: {
    id: "majorStorm", name: "都市大型风暴", class: "climax", triggerPopulation: 400,
    triggerScore: 700, warningDays: 3, durationDays: 1, pathId: "major_storm_track",
    maxPotentialTargets: 4, postDisasterExemptionDays: 5, oncePerSession: true,
    preserveAtLeastOnePowerSource: true, preserveAtLeastOneWaterSource: true,
    damage: { min: 35, max: 65 }, icon: "🌩", recoverable: true,
  },
  scheduling: { maxConcurrent: 1, minimumNormalImpactGapDays: 12, tutorialSafeThroughDay: 10 },
} as const;

/** Five rewarded tutorial beats; conditions are declarative facts interpreted by integration/rules. */
export const TUTORIAL_STEPS = [
  {
    id: "build_tutorial_road", order: 1, availableDays: [1, 2], title: "先铺道路",
    instruction: "沿白色规划线从起点连续铺设道路。", focusPathId: "tutorial_road_guide",
    completion: { kind: "roadPathBuilt", pathId: "tutorial_road_guide", minimumCells: 5 }, reward: 50,
  },
  {
    id: "connect_power_plant", order: 2, availableDays: [3, 4], title: "接入电力",
    instruction: "在东侧缓冲区放置电厂，并让它邻接道路。", focusPointId: "industrial_recommendation",
    completion: { kind: "operatingBuildingCount", building: "powerPlant", minimum: 1 }, reward: 50,
  },
  {
    id: "protect_clean_water", order: 3, availableDays: [5, 6], title: "远离污染取水",
    instruction: "在东南低地放置水塔，观察半径3格污染修正。", focusPointId: "clean_water_recommendation",
    completion: { kind: "operatingBuildingCount", building: "waterTower", minimum: 1 }, reward: 50,
  },
  {
    id: "open_first_home", order: 4, availableDays: [7, 8], title: "建设住宅",
    instruction: "在西部台地建造邻路住宅，并确保电力与供水可达。", focusPointId: "first_district_objective",
    completion: { kind: "fullyServedBuildingCount", building: "residential", minimum: 1 }, reward: 50,
  },
  {
    id: "open_first_shop", order: 5, availableDays: [9, 10], title: "引入商业",
    instruction: "建造一座邻路商业区，完成首个可运行街区。", focusPointId: "planning_grant_marker",
    completion: { kind: "fullyServedBuildingCount", building: "commercial", minimum: 1 }, reward: 50,
  },
] as const;

/** Day-gated content switches plus a feasible uncapped victory composition. */
export const PHASE_SCHEDULE = {
  phases: [
    { id: "guided_planning", startsDay: 1, endsDay: 10, enabled: ["tutorial", "building", "utilities"], disabled: ["disasters", "fullSettlement", "commercialTrafficPollution"] },
    { id: "city_settlement", startsDay: 11, enabled: ["fullSettlement"] },
    { id: "growing_city", startsDay: 25, enabled: ["commercialTrafficPollution", "fullMigrationRates"] },
    { id: "resilient_city", startsDay: 40, enabled: ["normalDisasters"] },
    { id: "capacity_pressure", startsDay: 65, enabled: ["capacityPressureHint"] },
    { id: "aging_infrastructure", startsDay: 90, enabled: ["utilityMaintenanceAging"] },
  ],
  tutorialRewardCap: 250,
  utilityMaintenanceMultiplierFromDay90: 1.25,
  recommendedVictoryMix: {
    residential: 14, commercial: 8, powerPlant: 4, waterTower: 4, road: 58,
    populationCapacity: 700, targetPopulation: 500, electricitySupply: 1200,
    electricityDemandAtTarget: 780, waterSupplyBeforePollution: 1040,
    waterDemandAtTarget: 740, approximateDailyNetAfterAging: 821,
  },
  milestones: [
    { score: 400, reward: 300, itemFrame: "item_1", name: "二星规划补助" },
    { score: 600, reward: 500, itemFrame: "item_2", name: "三星基础设施补助" },
    { score: 800, reward: 700, itemFrame: "item_3", name: "四星韧性基金" },
  ],
} as const;

/** Generated-art bindings are named from frameMeta, never inferred from frame order. */
export const VISUAL_CATALOG = {
  grid: { cols: 24, rows: 14, drawRoadAtExactCellSize: true, refreshOrthogonalNeighbors: true },
  ground: { palette: "#78b95a", backdropKeys: ["background", "background-2", "background-3"] },
  planningCursor: { sheet: "sheet", idleFrame: "player_idle", validFrame: "player_move_a", invalidFrame: "player_hurt", actionFrame: "player_action" },
  road: {
    sheet: "sheet-2", tileFamily: "entity_1",
    frames: { straight: "entity_1", end: "entity_1_end", corner: "entity_1_corner", tee: "entity_1_tee", cross: "entity_1_cross" },
  },
  buildings: {
    residential: { sheet: "sheet-2", frame: "entity_2" },
    commercial: { sheet: "sheet-2", frame: "entity_3" },
    powerPlant: { sheet: "sheet-2", frame: "entity_4" },
    waterTower: { sheet: "sheet-2", frame: "entity_5" },
  },
  scenery: {
    ancientTree: { sheet: "sheet", frame: "obstacle_1" },
    ridge: { sheet: "sheet", frame: "obstacle_2" },
    canal: { sheet: "sheet", frame: "obstacle_3" },
  },
  vehicle: { sheet: "sheet-2", frame: "entity_6", maxInstances: 24, routeId: "city_vehicle_loop" },
  grants: {
    score400: { sheet: "sheet", frames: ["item_1", "item_1_b"] },
    score600: { sheet: "sheet-2", frames: ["item_2", "item_2_b"] },
    score800: { sheet: "sheet-2", frames: ["item_3", "item_3_b"] },
  },
  effects: { flash: { sheet: "sheet-3", frame: "flash" }, impact: { sheet: "sheet-2", frame: "explosion" } },
} as const;
