export type StructureKind = "road" | "residential" | "commercial" | "powerPlant" | "waterTower";
export type BuildFootprint = Readonly<{ width: 1 | 2; height: 1 | 2 }>;
export type ServiceKind = "power" | "water";

export interface CityCatalogEntry {
  readonly id: StructureKind;
  readonly name: string;
  readonly category: "transport" | "zone" | "utility";
  readonly cost: number;
  readonly maintenance: number;
  readonly footprint: BuildFootprint;
  readonly requiresAdjacentRoad: boolean;
  readonly powerDemand: number;
  readonly waterDemand: number;
  readonly powerCapacity: number;
  readonly waterCapacity: number;
  readonly maxPopulation: number;
  readonly jobs: number;
  readonly pollutionRadius: number;
  readonly pollutionStrength: number;
  readonly description: string;
}

export const CITY_CATALOG: Readonly<Record<StructureKind, CityCatalogEntry>> = Object.freeze({
  road: {
    id: "road",
    name: "道路",
    category: "transport",
    cost: 8,
    maintenance: 1,
    footprint: { width: 1, height: 1 },
    requiresAdjacentRoad: false,
    powerDemand: 0,
    waterDemand: 0,
    powerCapacity: 0,
    waterCapacity: 0,
    maxPopulation: 0,
    jobs: 0,
    pollutionRadius: 0,
    pollutionStrength: 0,
    description: "正交连接城市；公用服务可沿同一道路网络传播。",
  },
  residential: {
    id: "residential",
    name: "住宅",
    category: "zone",
    cost: 50,
    maintenance: 2,
    footprint: { width: 1, height: 1 },
    requiresAdjacentRoad: true,
    powerDemand: 4,
    waterDemand: 4,
    powerCapacity: 0,
    waterCapacity: 0,
    maxPopulation: 4,
    jobs: 0,
    pollutionRadius: 0,
    pollutionStrength: 0,
    description: "在道路、电力和供水齐备时发展，每10游戏秒最多迁入1人。",
  },
  commercial: {
    id: "commercial",
    name: "商业",
    category: "zone",
    cost: 70,
    maintenance: 4,
    footprint: { width: 1, height: 1 },
    requiresAdjacentRoad: true,
    powerDemand: 6,
    waterDemand: 5,
    powerCapacity: 0,
    waterCapacity: 0,
    maxPopulation: 0,
    jobs: 4,
    pollutionRadius: 0,
    pollutionStrength: 0,
    description: "提供4个岗位并产生商业税，必须获得道路及双服务。",
  },
  powerPlant: {
    id: "powerPlant",
    name: "电厂",
    category: "utility",
    cost: 280,
    maintenance: 20,
    footprint: { width: 2, height: 2 },
    requiresAdjacentRoad: true,
    powerDemand: 0,
    waterDemand: 0,
    powerCapacity: 40,
    waterCapacity: 0,
    maxPopulation: 0,
    jobs: 0,
    pollutionRadius: 3,
    pollutionStrength: 1,
    description: "输出40电力；会污染曼哈顿距离3格内的住宅。",
  },
  waterTower: {
    id: "waterTower",
    name: "水塔",
    category: "utility",
    cost: 220,
    maintenance: 16,
    footprint: { width: 2, height: 2 },
    requiresAdjacentRoad: true,
    powerDemand: 0,
    waterDemand: 0,
    powerCapacity: 0,
    waterCapacity: 40,
    maxPopulation: 0,
    jobs: 0,
    pollutionRadius: 0,
    pollutionStrength: 0,
    description: "输出40供水，通过相邻道路向同一网络分配。",
  },
});

export type DisasterType = "fire" | "blackout" | "pipeBurst";

export interface DisasterDefinition {
  readonly id: DisasterType;
  readonly name: string;
  readonly warningSeconds: number;
  readonly durationSeconds: number;
  readonly emergencyCost: number;
  readonly dispatchDurationMultiplier: number;
  readonly targetKinds: readonly StructureKind[];
  readonly effect: "disableProduction" | "disablePower" | "disableWater";
  readonly maxAffectedRadius: 0 | 1;
  readonly warningText: string;
  readonly activeText: string;
}

export interface DisasterScheduleDefinition {
  readonly safeOpeningSeconds: number;
  readonly minimumPopulation: number;
  readonly firstEligibleDelaySeconds: number;
  readonly normalIntervalSeconds: readonly [number, number];
  readonly denseCityPopulation: number;
  readonly denseCityIntervalSeconds: readonly [number, number];
  readonly maxConcurrent: 1;
  readonly avoidConsecutiveRegion: true;
}

export const DISASTER_DEFINITIONS = Object.freeze({
  schedule: {
    safeOpeningSeconds: 60,
    minimumPopulation: 20,
    firstEligibleDelaySeconds: 30,
    normalIntervalSeconds: [90, 150],
    denseCityPopulation: 35,
    denseCityIntervalSeconds: [70, 110],
    maxConcurrent: 1,
    avoidConsecutiveRegion: true,
  } as DisasterScheduleDefinition,
  types: {
    fire: {
      id: "fire",
      name: "火灾",
      warningSeconds: 5,
      durationSeconds: 30,
      emergencyCost: 80,
      dispatchDurationMultiplier: 0.4,
      targetKinds: ["residential", "commercial"],
      effect: "disableProduction",
      maxAffectedRadius: 1,
      warningText: "高温预警：目标建筑即将起火",
      activeText: "火灾中：人口迁入与税收暂停",
    },
    blackout: {
      id: "blackout",
      name: "停电",
      warningSeconds: 5,
      durationSeconds: 25,
      emergencyCost: 70,
      dispatchDurationMultiplier: 0.4,
      targetKinds: ["powerPlant"],
      effect: "disablePower",
      maxAffectedRadius: 0,
      warningText: "电网波动：电厂可能停机",
      activeText: "停电中：目标电厂停止供电",
    },
    pipeBurst: {
      id: "pipeBurst",
      name: "管裂",
      warningSeconds: 5,
      durationSeconds: 25,
      emergencyCost: 60,
      dispatchDurationMultiplier: 0.4,
      targetKinds: ["waterTower"],
      effect: "disableWater",
      maxAffectedRadius: 1,
      warningText: "水压异常：管网即将破裂",
      activeText: "管裂中：目标水塔停止供水",
    },
  } as Readonly<Record<DisasterType, DisasterDefinition>>,
});

export type TutorialTrigger =
  | "sessionStarted"
  | "residentialSelected"
  | "residentialPlaced"
  | "roadConnected"
  | "powerPlantPlaced"
  | "waterTowerPlaced"
  | "dualCoverageObserved";

export interface TutorialStepDefinition {
  readonly id: string;
  readonly title: string;
  readonly body: string;
  readonly trigger: TutorialTrigger;
  readonly suggestedTool?: StructureKind | "powerOverlay" | "waterOverlay";
  readonly focusPointId?: string;
  readonly completionHint: string;
}

export interface TutorialSequenceDefinition {
  readonly startsPaused: true;
  readonly skippable: true;
  readonly safeSeconds: 60;
  readonly grantsFreeStructures: false;
  readonly steps: readonly TutorialStepDefinition[];
}

export const TUTORIAL_SEQUENCE: TutorialSequenceDefinition = Object.freeze({
  startsPaused: true,
  skippable: true,
  safeSeconds: 60,
  grantsFreeStructures: false,
  steps: [
    {
      id: "welcome_home",
      title: "先规划住宅",
      body: "选择住宅，在河西新区的教学地块放置第一栋住房。放置会正常扣款。",
      trigger: "sessionStarted",
      suggestedTool: "residential",
      focusPointId: "west_tutorial_lot",
      completionHint: "选择住宅工具继续",
    },
    {
      id: "connect_road",
      title: "接入道路",
      body: "住宅必须紧邻连通道路。把住宅接到旧城走廊的5格起始道路。",
      trigger: "residentialPlaced",
      suggestedTool: "road",
      focusPointId: "west_tutorial_lot",
      completionHint: "铺设一条正交相连的道路",
    },
    {
      id: "build_power",
      title: "提供电力",
      body: "在远离住宅的位置建造2×2电厂，并让它邻接同一道路网络。",
      trigger: "roadConnected",
      suggestedTool: "powerPlant",
      focusPointId: "utility_recommendation",
      completionHint: "建造一座已接路的电厂",
    },
    {
      id: "build_water",
      title: "提供供水",
      body: "再建造2×2水塔。设施服务沿道路最多传播10格。",
      trigger: "powerPlantPlaced",
      suggestedTool: "waterTower",
      focusPointId: "utility_recommendation",
      completionHint: "建造一座已接路的水塔",
    },
    {
      id: "inspect_coverage",
      title: "检查双覆盖",
      body: "切换电力与供水覆盖图，确认住宅同时显示电力和水滴图标。",
      trigger: "waterTowerPlaced",
      suggestedTool: "powerOverlay",
      completionHint: "查看覆盖并确认住宅获得双服务",
    },
    {
      id: "resume_time",
      title: "恢复时间",
      body: "按空格或速度按钮恢复时间。住宅每10游戏秒最多迁入1人；前60游戏秒不会发生灾害。",
      trigger: "dualCoverageObserved",
      completionHint: "恢复模拟并观察首位居民迁入",
    },
  ],
});

export interface SpriteFrameRef {
  readonly texture: "sheet" | "sheet-2" | "sheet-3";
  readonly frame: number;
  readonly frameName: string;
}

export interface StructureVisualDefinition {
  readonly idle: SpriteFrameRef;
  readonly active?: SpriteFrameRef;
  readonly displayCells: BuildFootprint;
  readonly buildAnimationSeconds: 0.2 | 1.2 | 1.8;
  readonly icon: string;
  readonly colorIdentity: string;
  readonly statusPattern: string;
}

export const CITY_VISUAL_MANIFEST = Object.freeze({
  palette: {
    background: "#8fd3a8",
    panel: "#f4e7c5",
    civicBlue: "#2878b8",
    warningGold: "#ffd34e",
    dangerRed: "#e84a3c",
  },
  backgrounds: {
    planning: "background",
    disaster: "background-2",
    prosperity: "background-3",
  },
  structures: {
    road: {
      idle: { texture: "sheet-2", frame: 7, frameName: "entity_1" },
      active: { texture: "sheet-2", frame: 8, frameName: "entity_2" },
      displayCells: { width: 1, height: 1 },
      buildAnimationSeconds: 0.2,
      icon: "路",
      colorIdentity: "灰白路面与黄色中心线",
      statusPattern: "按正交邻接掩码选择端点、直线、转角、三叉或十字图块",
    },
    residential: {
      idle: { texture: "sheet-2", frame: 9, frameName: "entity_3" },
      active: { texture: "sheet-3", frame: 1, frameName: "bonus_1" },
      displayCells: { width: 1, height: 1 },
      buildAnimationSeconds: 1.2,
      icon: "住",
      colorIdentity: "绿色屋顶",
      statusPattern: "窗灯表示入住，斜线纹表示缺少服务",
    },
    commercial: {
      idle: { texture: "sheet-2", frame: 10, frameName: "entity_4" },
      active: { texture: "sheet-3", frame: 2, frameName: "bonus_2" },
      displayCells: { width: 1, height: 1 },
      buildAnimationSeconds: 1.2,
      icon: "商",
      colorIdentity: "蓝色招牌",
      statusPattern: "闪烁招牌表示营业，百叶纹表示停业",
    },
    powerPlant: {
      idle: { texture: "sheet-2", frame: 11, frameName: "entity_5" },
      active: { texture: "sheet-2", frame: 14, frameName: "explosion" },
      displayCells: { width: 2, height: 2 },
      buildAnimationSeconds: 1.8,
      icon: "电",
      colorIdentity: "橙黑机组",
      statusPattern: "烟雾脉冲表示运行，闪电叉表示停电",
    },
    waterTower: {
      idle: { texture: "sheet-2", frame: 12, frameName: "entity_6" },
      active: { texture: "sheet-2", frame: 6, frameName: "item_2_b" },
      displayCells: { width: 2, height: 2 },
      buildAnimationSeconds: 1.8,
      icon: "水",
      colorIdentity: "青色水罐",
      statusPattern: "水波脉冲表示运行，裂纹表示管裂",
    },
  } as Readonly<Record<StructureKind, StructureVisualDefinition>>,
  overlays: {
    power: { icon: "⚡", texturePattern: "diagonal-bolts" },
    water: { icon: "●", texturePattern: "wave-drops" },
    pollution: { icon: "!", texturePattern: "stipple-smoke" },
  },
  effects: {
    construction: { texture: "sheet-2", frame: 15, frameName: "flash" },
    smoke: { texture: "sheet-2", frame: 14, frameName: "explosion" },
    warning: { texture: "sheet-3", frame: 3, frameName: "bonus_3" },
    prosperity: { texture: "sheet-3", frame: 4, frameName: "bonus_4" },
  },
});
