import type { MilestoneDefinition, PopulationTierDefinition, TutorialStepDefinition } from "./CityTypes";

export const MILESTONE_CATALOG: readonly MilestoneDefinition[] = Object.freeze([
  Object.freeze({
    population: 100,
    amount: 1000,
    name: "小镇发展补助",
    purpose: "为第一次容量扩建提供资金缓冲，不改变道路或服务规则。",
    art: Object.freeze({ sheetKey: "sheet-2", frameName: "item_1", frameIndex: 2 }),
  }),
  Object.freeze({
    population: 250,
    amount: 1500,
    name: "城区扩张补助",
    purpose: "用于调整污染布局或建设第二套公用设施。",
    art: Object.freeze({ sheetKey: "sheet-2", frameName: "item_2", frameIndex: 4 }),
  }),
  Object.freeze({
    population: 400,
    amount: 2000,
    name: "宜居城市补助",
    purpose: "用于终局前建立备用容量和应急资金。",
    art: Object.freeze({ sheetKey: "sheet-2", frameName: "item_3", frameIndex: 6 }),
  }),
]);

/** Population phase values are data only; the simulation decides when and how to apply them. */
export const POPULATION_TIERS: readonly PopulationTierDefinition[] = Object.freeze([
  Object.freeze({
    id: "growth",
    minPopulation: 0,
    maxPopulation: 119,
    demandMultiplier: 1,
    commercialIncomeMultiplier: 1,
    pollutionImpactMultiplier: 1,
    maintenanceMultiplier: 1,
    unlockedDisasters: Object.freeze([] as const),
  }),
  Object.freeze({
    id: "pressure",
    minPopulation: 120,
    maxPopulation: 299,
    demandMultiplier: 1.15,
    commercialIncomeMultiplier: 1.2,
    pollutionImpactMultiplier: 1.25,
    maintenanceMultiplier: 1,
    unlockedDisasters: Object.freeze(["facility_failure", "fire"] as const),
  }),
  Object.freeze({
    id: "metropolis",
    minPopulation: 300,
    maxPopulation: null,
    demandMultiplier: 1.25,
    commercialIncomeMultiplier: 1.3,
    pollutionImpactMultiplier: 1.4,
    maintenanceMultiplier: 1.2,
    unlockedDisasters: Object.freeze(["facility_failure", "fire", "storm", "blackout", "water_main_break"] as const),
  }),
]);

export const TUTORIAL_STEPS: readonly TutorialStepDefinition[] = Object.freeze([
  Object.freeze({
    id: "build_power",
    order: 1,
    title: "先准备电力",
    instruction: "暂停规划，在东部缓冲地放置电厂，并从中央道路接出支路。",
    tool: "power",
    objectivePointId: "first_power_hint",
    suggestedOrigin: Object.freeze({ x: 19, y: 5 }),
    suggestedRoadCells: Object.freeze([
      Object.freeze({ x: 16, y: 7 }), Object.freeze({ x: 17, y: 7 }), Object.freeze({ x: 18, y: 7 }),
      Object.freeze({ x: 18, y: 6 }), Object.freeze({ x: 18, y: 5 }),
    ]),
    completion: Object.freeze({ buildingKind: "power", requiresRoadConnection: true }),
    advice: "电厂有强弱两圈污染影响；为住宅留出至少六格距离，并预留备用容量。",
  }),
  Object.freeze({
    id: "build_water",
    order: 2,
    title: "接通供水",
    instruction: "在东南侧放置水务站，并让它与同一道路网络连接。",
    tool: "water",
    objectivePointId: "first_water_hint",
    suggestedOrigin: Object.freeze({ x: 19, y: 8 }),
    suggestedRoadCells: Object.freeze([
      Object.freeze({ x: 18, y: 8 }), Object.freeze({ x: 18, y: 9 }),
    ]),
    completion: Object.freeze({ buildingKind: "water", requiresRoadConnection: true }),
    advice: "供水不足会按覆盖比例降低建筑效率，扩建前先检查容量。",
  }),
  Object.freeze({
    id: "build_home",
    order: 3,
    title: "建设第一片住宅",
    instruction: "在西侧低污染草坪放置住宅，并把支路接到住宅一侧。",
    tool: "home",
    objectivePointId: "first_home_hint",
    suggestedOrigin: Object.freeze({ x: 4, y: 5 }),
    suggestedRoadCells: Object.freeze([
      Object.freeze({ x: 7, y: 7 }), Object.freeze({ x: 6, y: 7 }),
      Object.freeze({ x: 6, y: 6 }), Object.freeze({ x: 6, y: 5 }),
    ]),
    completion: Object.freeze({ buildingKind: "home", requiresRoadConnection: true }),
    advice: "住宅需要道路、电力和供水才会稳定入住；远离电厂可保护满意度。",
  }),
  Object.freeze({
    id: "build_commercial",
    order: 4,
    title: "建立商业收入",
    instruction: "在中央道路北侧放置商业区；人口达到30后会正式营业。",
    tool: "commercial",
    objectivePointId: "first_shop_hint",
    suggestedOrigin: Object.freeze({ x: 9, y: 5 }),
    suggestedRoadCells: Object.freeze([]),
    completion: Object.freeze({ buildingKind: "commercial", requiresRoadConnection: true }),
    advice: "商业收入更高但耗用更多电水；保持应急资金，不要只追求短期扩张。",
  }),
]);

export const TUTORIAL_WINDOW = Object.freeze({ firstDay: 1, lastDay: 20, skippable: true });
