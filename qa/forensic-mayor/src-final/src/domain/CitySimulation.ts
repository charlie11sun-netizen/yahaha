export type RunPhase = "start" | "tutorial" | "running" | "paused" | "victory" | "defeat";
export type BuildingKind = "road" | "home" | "commercial" | "power" | "water";
export type DisasterKind = "facilityFailure" | "fire" | "storm" | "blackout" | "pipeBreak";
export type PlacementError = "unknownKind" | "invalidCells" | "outOfBounds" | "blocked" | "overlap" | "insufficientFunds" | "buildingLimit";
export type DisasterAction = "pay" | "rebuild" | "ignore";

export interface Cell { x: number; y: number }
export interface BuildingDefinition {
  kind: BuildingKind;
  width: number;
  height: number;
  cost: number;
  dailyIncome: number;
  dailyMaintenance: number;
  powerDemand?: number;
  waterDemand?: number;
  powerCapacity?: number;
  waterCapacity?: number;
}
export interface MilestoneDefinition { population: 100 | 250 | 400; amount: 1000 | 1500 | 2000 }
export interface CityMapDefinition { cols: number; rows: number; blockedCells: readonly Cell[]; starterRoad?: readonly Cell[] }
export interface SimulationContent {
  cityMap: CityMapDefinition;
  buildingCatalog: Readonly<Record<BuildingKind, BuildingDefinition>>;
  milestones: readonly MilestoneDefinition[];
}
export interface BuildingInstance {
  id: string;
  kind: BuildingKind;
  cells: Cell[];
  cost: number;
  networkId: string | null;
  connectedToRoad: boolean;
  powered: boolean;
  watered: boolean;
  efficiency: number;
  population: number;
  operating: boolean;
  damaged: boolean;
}
export interface RoadNetwork {
  id: string;
  roadIds: string[];
  buildingIds: string[];
  powerCapacity: number;
  powerDemand: number;
  waterCapacity: number;
  waterDemand: number;
  powerCoverage: number;
  waterCoverage: number;
}
export interface DisasterInstance {
  id: string;
  kind: DisasterKind;
  phase: "warning" | "active";
  targetIds: string[];
  affectedIds: string[];
  warningDays: number;
  remainingDays: number;
  originalDuration: number;
  mitigated: boolean;
  actionCost: number;
}
export interface EconomySnapshot {
  funds: number;
  dailyIncome: number;
  dailyMaintenance: number;
  milestones: Set<number>;
  quickRecoveryCount: number;
}
export interface CityMetrics {
  population: number;
  pollution: number;
  satisfaction: number;
  score: number;
  powerDemand: number;
  powerCapacity: number;
  waterDemand: number;
  waterCapacity: number;
  scoreParts: { population: number; economy: number; satisfaction: number; utilities: number; resilience: number };
}
export interface FailureClocks { bankruptcyDays: number; abandonmentDays: number }
export interface SimulationState {
  runPhase: RunPhase;
  calendar: { day: number; stableDays: number; speed: 1 | 2 | 3; dayAccumulatorMs: number };
  economy: EconomySnapshot;
  cityMetrics: CityMetrics;
  failureClocks: FailureClocks;
  roadNetworks: RoadNetwork[];
  activeDisasters: DisasterInstance[];
  disasterSchedule: { nextEligibleDay: number; safeUntilDay: number };
  buildings: Map<string, BuildingInstance>;
  content: SimulationContent;
  nextBuildingId: number;
  nextDisasterId: number;
  randomSeed: number;
  outcome: "victory" | "bankruptcy" | "abandonment" | null;
  finalScore: number | null;
}
export interface PlacementRequest { kind: BuildingKind; cells: readonly Cell[] }
export interface PlacementValidation { ok: boolean; reason?: PlacementError; cells: Cell[]; cost: number }
export interface PlacementResult extends PlacementValidation { state: SimulationState; buildingIds: string[]; changedNetworks: string[] }
export interface DemolitionResult { ok: boolean; state: SimulationState; buildingId: string; refund: number; disconnectedBuildingIds: string[]; changedNetworks: string[] }
export interface DayResult {
  state: SimulationState;
  milestonesAwarded: MilestoneDefinition[];
  disasterWarnings: DisasterInstance[];
  disasterChanges: { id: string; phase: "started" | "resolved"; affectedIds: string[] }[];
  runEnded: SimulationState["outcome"];
}
export interface DisasterActionResult { ok: boolean; state: SimulationState; cost: number; remainingDays: number; reason?: "notFound" | "notActive" | "insufficientFunds" | "unsupported" }

const MAX_BUILDINGS = 160;
const DAY_MS = 1000;
const key = (c: Cell): string => `${c.x},${c.y}`;
const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, v));
const copyBuilding = (b: BuildingInstance): BuildingInstance => ({ ...b, cells: b.cells.map(c => ({ ...c })) });

function cloneState(state: SimulationState): SimulationState {
  return {
    ...state,
    calendar: { ...state.calendar }, economy: { ...state.economy, milestones: new Set(state.economy.milestones) },
    cityMetrics: { ...state.cityMetrics, scoreParts: { ...state.cityMetrics.scoreParts } }, failureClocks: { ...state.failureClocks },
    disasterSchedule: { ...state.disasterSchedule }, buildings: new Map([...state.buildings].map(([id, b]) => [id, copyBuilding(b)])),
    roadNetworks: state.roadNetworks.map(n => ({ ...n, roadIds: [...n.roadIds], buildingIds: [...n.buildingIds] })),
    activeDisasters: state.activeDisasters.map(d => ({ ...d, targetIds: [...d.targetIds], affectedIds: [...d.affectedIds] })),
  };
}
function random(state: SimulationState): number {
  state.randomSeed = (Math.imul(state.randomSeed, 1664525) + 1013904223) >>> 0;
  return state.randomSeed / 0x100000000;
}
function randomInt(state: SimulationState, min: number, max: number): number { return min + Math.floor(random(state) * (max - min + 1)); }
function orthogonal(a: Cell, b: Cell): boolean { return Math.abs(a.x - b.x) + Math.abs(a.y - b.y) === 1; }
function uniqueCells(cells: readonly Cell[]): Cell[] {
  const seen = new Set<string>(); const result: Cell[] = [];
  for (const c of cells) if (Number.isInteger(c.x) && Number.isInteger(c.y) && !seen.has(key(c))) { seen.add(key(c)); result.push({ x: c.x, y: c.y }); }
  return result;
}
function occupied(state: SimulationState, ignoredId?: string): Map<string, string> {
  const result = new Map<string, string>();
  for (const [id, b] of state.buildings) if (id !== ignoredId) for (const c of b.cells) result.set(key(c), id);
  return result;
}
function footprint(origin: Cell, def: BuildingDefinition): Cell[] {
  const cells: Cell[] = [];
  for (let y = 0; y < def.height; y++) for (let x = 0; x < def.width; x++) cells.push({ x: origin.x + x, y: origin.y + y });
  return cells;
}
function normalizedPlacement(state: SimulationState, request: PlacementRequest): { cells: Cell[]; cost: number; validShape: boolean } | null {
  const def = state.content.buildingCatalog[request.kind]; if (!def) return null;
  const given = uniqueCells(request.cells);
  if (request.kind === "road") return { cells: given, cost: given.length * def.cost, validShape: given.length > 0 };
  if (!given.length) return { cells: [], cost: def.cost, validShape: false };
  const cells = footprint(given.reduce((a, c) => c.x < a.x || (c.x === a.x && c.y < a.y) ? c : a), def);
  const actual = new Set(given.map(key));
  return { cells, cost: def.cost, validShape: cells.length === given.length && cells.every(c => actual.has(key(c))) };
}

export function createInitialSimulationState(content: SimulationContent, seed = 0x51f15e): SimulationState {
  const state: SimulationState = {
    runPhase: "paused", calendar: { day: 1, stableDays: 0, speed: 1, dayAccumulatorMs: 0 },
    economy: { funds: 12000, dailyIncome: 0, dailyMaintenance: 0, milestones: new Set(), quickRecoveryCount: 0 },
    cityMetrics: { population: 0, pollution: 0, satisfaction: 60, score: 0, powerDemand: 0, powerCapacity: 0, waterDemand: 0, waterCapacity: 0, scoreParts: { population: 0, economy: 0, satisfaction: 15, utilities: 0, resilience: 10 } },
    failureClocks: { bankruptcyDays: 0, abandonmentDays: 0 }, roadNetworks: [], activeDisasters: [],
    disasterSchedule: { nextEligibleDay: 45, safeUntilDay: 20 }, buildings: new Map(), content,
    nextBuildingId: 1, nextDisasterId: 1, randomSeed: seed >>> 0, outcome: null, finalScore: null,
  };
  for (const cell of content.cityMap.starterRoad ?? []) {
    const id = `b${state.nextBuildingId++}`;
    state.buildings.set(id, makeBuilding(id, "road", [cell], content.buildingCatalog.road));
  }
  recalculateNetworks(state);
  return state;
}

export function validatePlacement(state: SimulationState, request: PlacementRequest): PlacementValidation {
  const normalized = normalizedPlacement(state, request);
  if (!normalized) return { ok: false, reason: "unknownKind", cells: [], cost: 0 };
  if (!normalized.validShape) return { ok: false, reason: "invalidCells", cells: normalized.cells, cost: normalized.cost };
  const { cols, rows, blockedCells } = state.content.cityMap;
  if (normalized.cells.some(c => c.x < 0 || c.y < 0 || c.x >= cols || c.y >= rows)) return { ok: false, reason: "outOfBounds", cells: normalized.cells, cost: normalized.cost };
  const blocked = new Set(blockedCells.map(key));
  if (normalized.cells.some(c => blocked.has(key(c)))) return { ok: false, reason: "blocked", cells: normalized.cells, cost: normalized.cost };
  const used = occupied(state);
  if (normalized.cells.some(c => used.has(key(c)))) return { ok: false, reason: "overlap", cells: normalized.cells, cost: normalized.cost };
  const countAdded = request.kind === "road" ? normalized.cells.length : 1;
  if (state.buildings.size + countAdded > MAX_BUILDINGS) return { ok: false, reason: "buildingLimit", cells: normalized.cells, cost: normalized.cost };
  if (state.economy.funds < normalized.cost) return { ok: false, reason: "insufficientFunds", cells: normalized.cells, cost: normalized.cost };
  return { ok: true, cells: normalized.cells, cost: normalized.cost };
}
function makeBuilding(id: string, kind: BuildingKind, cells: Cell[], def: BuildingDefinition): BuildingInstance {
  return { id, kind, cells: cells.map(c => ({ ...c })), cost: def.cost, networkId: null, connectedToRoad: kind === "road", powered: kind === "road", watered: kind === "road", efficiency: kind === "road" ? 1 : 0, population: 0, operating: kind === "road", damaged: false };
}
export function placeBuilding(state: SimulationState, request: PlacementRequest): PlacementResult {
  const check = validatePlacement(state, request); if (!check.ok) return { ...check, state, buildingIds: [], changedNetworks: [] };
  const next = cloneState(state); const def = next.content.buildingCatalog[request.kind]; const ids: string[] = [];
  if (request.kind === "road") for (const cell of check.cells) { const id = `b${next.nextBuildingId++}`; next.buildings.set(id, makeBuilding(id, "road", [cell], def)); ids.push(id); }
  else { const id = `b${next.nextBuildingId++}`; next.buildings.set(id, makeBuilding(id, request.kind, check.cells, def)); ids.push(id); }
  next.economy.funds -= check.cost; const changedNetworks = recalculateNetworks(next);
  return { ...check, state: next, buildingIds: ids, changedNetworks };
}
export function demolishBuilding(state: SimulationState, buildingId: string): DemolitionResult {
  const found = state.buildings.get(buildingId);
  if (!found) return { ok: false, state, buildingId, refund: 0, disconnectedBuildingIds: [], changedNetworks: [] };
  const before = new Map([...state.buildings].map(([id, b]) => [id, b.connectedToRoad])); const next = cloneState(state); next.buildings.delete(buildingId);
  const refund = Math.floor(found.cost * 0.4); next.economy.funds += refund; const changedNetworks = recalculateNetworks(next);
  const disconnectedBuildingIds = [...next.buildings.values()].filter(b => before.get(b.id) && !b.connectedToRoad).map(b => b.id);
  return { ok: true, state: next, buildingId, refund, disconnectedBuildingIds, changedNetworks };
}

function recalculateNetworks(state: SimulationState): string[] {
  const old = new Map(state.roadNetworks.map(n => [n.id, n.roadIds.slice().sort().join("|")]));
  for (const b of state.buildings.values()) b.damaged = activeDisaster(state, "storm", b.id) || activeDisaster(state, "fire", b.id);
  const roads = [...state.buildings.values()].filter(b => b.kind === "road" && !b.damaged); const byCell = new Map(roads.map(r => [key(r.cells[0]), r]));
  const unseen = new Set(roads.map(r => r.id)); const networks: RoadNetwork[] = [];
  while (unseen.size) {
    const firstId = unseen.values().next().value as string; const queue = [state.buildings.get(firstId)!]; unseen.delete(firstId); const component: BuildingInstance[] = [];
    while (queue.length) { const road = queue.shift()!; component.push(road); const c = road.cells[0]; for (const d of [{x:0,y:-1},{x:1,y:0},{x:0,y:1},{x:-1,y:0}]) { const n = byCell.get(`${c.x+d.x},${c.y+d.y}`); if (n && unseen.delete(n.id)) queue.push(n); } }
    const roadIds = component.map(r => r.id).sort(); networks.push({ id: `net:${roadIds[0]}`, roadIds, buildingIds: [], powerCapacity: 0, powerDemand: 0, waterCapacity: 0, waterDemand: 0, powerCoverage: 1, waterCoverage: 1 });
  }
  const roadToNetwork = new Map<string, RoadNetwork>(); for (const n of networks) for (const id of n.roadIds) roadToNetwork.set(id, n);
  for (const b of state.buildings.values()) {
    if (b.kind === "road") { b.networkId = roadToNetwork.get(b.id)?.id ?? null; continue; }
    const adjacentRoad = roads.find(r => b.cells.some(c => orthogonal(c, r.cells[0]))); const network = adjacentRoad ? roadToNetwork.get(adjacentRoad.id) : undefined;
    b.networkId = network?.id ?? null; b.connectedToRoad = !!network; if (network) network.buildingIds.push(b.id);
  }
  state.roadNetworks = networks; applyUtilities(state);
  const now = new Map(networks.map(n => [n.id, n.roadIds.slice().sort().join("|")]));
  return [...new Set([...old.keys(), ...now.keys()].filter(id => old.get(id) !== now.get(id)))];
}
function activeDisaster(state: SimulationState, kind: DisasterKind, id?: string): boolean { return state.activeDisasters.some(d => d.phase === "active" && d.kind === kind && (!id || d.affectedIds.includes(id))); }
function applyUtilities(state: SimulationState): void {
  const pressure = state.cityMetrics.population >= 300 ? 1.2 : state.cityMetrics.population >= 120 ? 1.1 : 1;
  for (const n of state.roadNetworks) {
    const bs = n.buildingIds.map(id => state.buildings.get(id)!).filter(Boolean); n.powerCapacity = 0; n.waterCapacity = 0; n.powerDemand = 0; n.waterDemand = 0;
    for (const b of bs) { const def = state.content.buildingCatalog[b.kind]; let pc = def.powerCapacity ?? 0; let wc = def.waterCapacity ?? 0;
      if (activeDisaster(state, "facilityFailure", b.id)) { pc *= .5; wc *= .5; }
      n.powerCapacity += pc; n.waterCapacity += wc; n.powerDemand += (def.powerDemand ?? 0) * pressure; n.waterDemand += (def.waterDemand ?? 0) * pressure;
    }
    if (activeDisaster(state, "blackout", n.id)) { const reserve = n.powerCapacity - n.powerDemand; n.powerCapacity *= reserve >= n.powerDemand * .2 ? .8 : .6; }
    n.powerCoverage = n.powerDemand ? clamp(n.powerCapacity / n.powerDemand, 0, 1) : 1; n.waterCoverage = n.waterDemand ? clamp(n.waterCapacity / n.waterDemand, 0, 1) : 1;
    for (const b of bs) { b.powered = n.powerCoverage > 0; b.watered = n.waterCoverage > 0 && !activeDisaster(state, "pipeBreak", b.id); b.efficiency = Math.min(n.powerCoverage, b.watered ? n.waterCoverage : 0); b.operating = b.connectedToRoad && b.efficiency > 0 && !activeDisaster(state, "fire", b.id); }
  }
  for (const b of state.buildings.values()) if (b.kind !== "road" && !b.networkId) { b.connectedToRoad = false; b.powered = false; b.watered = false; b.efficiency = 0; b.operating = false; }
}
function distance(a: BuildingInstance, b: BuildingInstance): number { let best = Infinity; for (const x of a.cells) for (const y of b.cells) best = Math.min(best, Math.abs(x.x-y.x)+Math.abs(x.y-y.y)); return best; }
function calculateMetrics(state: SimulationState): void {
  applyUtilities(state); const buildings = [...state.buildings.values()]; const homes = buildings.filter(b => b.kind === "home"); const plants = buildings.filter(b => b.kind === "power");
  const population = homes.reduce((s, b) => s + b.population, 0); let pollution = 0; let residentialPenalty = 0;
  for (const p of plants) for (const h of homes) { const d = distance(p, h); if (d <= 2) { pollution += 10; residentialPenalty += 12; } else if (d <= 5) { pollution += 4; residentialPenalty += 5; } }
  const stagePollution = population >= 120 ? 1.25 : 1; pollution = clamp(Math.round(pollution * stagePollution), 0, 100);
  const utilityCoverage = homes.length ? homes.reduce((s,h) => s + h.efficiency, 0) / homes.length : 1;
  const satisfaction = clamp(Math.round(55 + utilityCoverage * 30 - residentialPenalty / Math.max(1, homes.length) - pollution * .15 + (state.economy.dailyIncome >= state.economy.dailyMaintenance ? 5 : -8)), 0, 100);
  const totals = state.roadNetworks.reduce((a,n) => ({pd:a.pd+n.powerDemand,pc:a.pc+n.powerCapacity,wd:a.wd+n.waterDemand,wc:a.wc+n.waterCapacity}), {pd:0,pc:0,wd:0,wc:0});
  const parts = { population: clamp(population / 500 * 25, 0, 25), economy: state.economy.dailyIncome > state.economy.dailyMaintenance ? 20 : clamp(10 + (state.economy.dailyIncome-state.economy.dailyMaintenance)/50,0,20), satisfaction: satisfaction/100*25, utilities: utilityCoverage*20, resilience: clamp(10-pollution/10-state.activeDisasters.filter(d=>d.phase==="active").length*2+Math.min(2,state.economy.quickRecoveryCount),0,10) };
  state.cityMetrics = { population, pollution, satisfaction, score: clamp(Math.round(parts.population+parts.economy+parts.satisfaction+parts.utilities+parts.resilience),0,100), powerDemand: Math.round(totals.pd), powerCapacity: Math.round(totals.pc), waterDemand: Math.round(totals.wd), waterCapacity: Math.round(totals.wc), scoreParts: parts };
}
function settleBuildings(state: SimulationState): void {
  const beforePopulation = state.cityMetrics.population; const stageMaintenance = beforePopulation >= 300 ? 1.2 : 1; let income = 0, maintenance = 0;
  for (const b of state.buildings.values()) { const def = state.content.buildingCatalog[b.kind]; maintenance += def.dailyMaintenance * stageMaintenance;
    if (b.kind === "home") { const desired = b.operating && state.cityMetrics.satisfaction >= 20 ? Math.max(1, Math.floor(2*b.efficiency)) : -2; b.population = clamp(b.population + desired, 0, 40); income += b.population * def.dailyIncome * b.efficiency; }
    else if (b.kind === "commercial" && beforePopulation >= 30 && b.operating) { const boost = beforePopulation >= 120 ? 1.25 : 1; const storm = activeDisaster(state,"storm") ? .8 : 1; income += def.dailyIncome * b.efficiency * boost * storm; }
    else if (b.operating) income += def.dailyIncome * b.efficiency;
  }
  state.economy.dailyIncome = Math.round(income); state.economy.dailyMaintenance = Math.round(maintenance); state.economy.funds += state.economy.dailyIncome-state.economy.dailyMaintenance;
}
function durationFor(state: SimulationState, kind: DisasterKind): number { const ranges: Record<DisasterKind,[number,number]> = {facilityFailure:[8,12],fire:[6,10],storm:[10,15],blackout:[6,9],pipeBreak:[8,12]}; return randomInt(state,...ranges[kind]); }
function scheduleDisaster(state: SimulationState): DisasterInstance | null {
  if (state.calendar.day <= 20 || state.calendar.day < state.disasterSchedule.nextEligibleDay || state.calendar.day < state.disasterSchedule.safeUntilDay || state.activeDisasters.length >= 2 || state.cityMetrics.population < 120) return null;
  const early: DisasterKind[] = ["facilityFailure","fire"]; const pool = state.cityMetrics.population >= 300 ? [...early,"storm","blackout","pipeBreak"] as DisasterKind[] : early; const kind = pool[randomInt(state,0,pool.length-1)];
  const all = [...state.buildings.values()]; let targets: string[] = [];
  const pickOne = (ids: string[]): string[] => ids.length ? [ids[randomInt(state,0,ids.length-1)]] : [];
  if (kind === "facilityFailure") targets = pickOne(all.filter(b=>b.kind==="power"||b.kind==="water").map(b=>b.id));
  else if (kind === "fire") targets = pickOne(all.filter(b=>b.kind!=="road").map(b=>b.id));
  else if (kind === "blackout") targets = pickOne(state.roadNetworks.map(n=>n.id));
  else if (kind === "pipeBreak") { const candidates=all.filter(b=>b.kind==="home"||b.kind==="commercial").map(b=>b.id); targets=candidates.sort(()=>random(state)-.5).slice(0,3); }
  else { const candidates=all.filter(b=>b.kind==="road").map(b=>b.id); targets=candidates.sort(()=>random(state)-.5).slice(0,3); }
  if (!targets.length) { state.disasterSchedule.nextEligibleDay = state.calendar.day + 10; return null; }
  const duration = durationFor(state,kind); const actionCost = kind==="facilityFailure" ? Math.ceil((state.buildings.get(targets[0])?.cost??0)*.15) : kind==="fire" ? 600 : kind==="pipeBreak" ? 500 : 0;
  const d: DisasterInstance = { id:`d${state.nextDisasterId++}`,kind,phase:"warning",targetIds:targets,affectedIds:[...targets],warningDays:3,remainingDays:duration,originalDuration:duration,mitigated:false,actionCost };
  state.activeDisasters.push(d); state.disasterSchedule.nextEligibleDay = state.calendar.day + randomInt(state,45,70); return d;
}
function progressDisasters(state: SimulationState): { id:string; phase:"started"|"resolved"; affectedIds:string[] }[] {
  const changes: { id:string; phase:"started"|"resolved"; affectedIds:string[] }[] = [];
  for (const d of state.activeDisasters) { if (d.phase === "warning") { d.warningDays--; if (d.warningDays <= 0) { d.phase="active"; changes.push({id:d.id,phase:"started",affectedIds:[...d.affectedIds]}); } } else { d.remainingDays--; if (d.remainingDays <= 0) changes.push({id:d.id,phase:"resolved",affectedIds:[...d.affectedIds]}); } }
  const resolved = new Set(changes.filter(c=>c.phase==="resolved").map(c=>c.id)); if (resolved.size) { state.activeDisasters=state.activeDisasters.filter(d=>!resolved.has(d.id)); state.disasterSchedule.safeUntilDay=Math.max(state.disasterSchedule.safeUntilDay,state.calendar.day+30); }
  return changes;
}
function finalScore(state: SimulationState): number { const milestoneRewards = state.content.milestones.filter(m=>state.economy.milestones.has(m.population)).reduce((s,m)=>s+m.amount,0); return Math.round(state.cityMetrics.score*100+state.economy.funds+milestoneRewards+Math.max(0,5000-state.calendar.day*10)+state.economy.quickRecoveryCount*250); }
export function advanceSimulationDay(state: SimulationState): DayResult {
  if (state.runPhase !== "running") return { state, milestonesAwarded: [], disasterWarnings: [], disasterChanges: [], runEnded: null };
  const next=cloneState(state); next.calendar.day++; const disasterChanges=progressDisasters(next); recalculateNetworks(next); calculateMetrics(next); settleBuildings(next); calculateMetrics(next);
  const milestonesAwarded: MilestoneDefinition[]=[]; for (const m of next.content.milestones) if (next.cityMetrics.population>=m.population&&!next.economy.milestones.has(m.population)) { next.economy.milestones.add(m.population); next.economy.funds+=m.amount; milestonesAwarded.push(m); }
  next.failureClocks.bankruptcyDays=next.economy.funds < -2000 ? next.failureClocks.bankruptcyDays+1 : 0; next.failureClocks.abandonmentDays=next.cityMetrics.satisfaction < 10 ? next.failureClocks.abandonmentDays+1 : 0;
  const stable=next.cityMetrics.population>=500&&next.cityMetrics.satisfaction>=70&&next.cityMetrics.score>=80&&next.failureClocks.bankruptcyDays===0; next.calendar.stableDays=stable?next.calendar.stableDays+1:0;
  const warning=scheduleDisaster(next); let runEnded: SimulationState["outcome"]=null;
  if(next.failureClocks.bankruptcyDays>=30) runEnded="bankruptcy"; else if(next.failureClocks.abandonmentDays>=30) runEnded="abandonment"; else if(next.calendar.stableDays>=60) runEnded="victory";
  if(runEnded){next.outcome=runEnded;next.runPhase=runEnded==="victory"?"victory":"defeat";next.finalScore=finalScore(next);}
  return {state:next,milestonesAwarded,disasterWarnings:warning?[{...warning,targetIds:[...warning.targetIds],affectedIds:[...warning.affectedIds]}]:[],disasterChanges,runEnded};
}
export function advanceSimulationTime(state: SimulationState, elapsedMs: number): { state: SimulationState; days: DayResult[] } {
  if(state.runPhase!=="running"||elapsedMs<=0)return {state,days:[]}; let next=cloneState(state);next.calendar.dayAccumulatorMs+=elapsedMs*next.calendar.speed;const days:DayResult[]=[];
  while(next.calendar.dayAccumulatorMs>=DAY_MS&&next.runPhase==="running"){next.calendar.dayAccumulatorMs-=DAY_MS;const result=advanceSimulationDay(next);next=result.state;days.push(result);}return {state:next,days};
}
export function resolveDisasterAction(state: SimulationState, disasterId: string, action: DisasterAction): DisasterActionResult {
  const found=state.activeDisasters.find(d=>d.id===disasterId);if(!found)return {ok:false,state,cost:0,remainingDays:0,reason:"notFound"};if(found.phase!=="active")return {ok:false,state,cost:0,remainingDays:found.remainingDays,reason:"notActive"};if(action==="ignore")return {ok:true,state,cost:0,remainingDays:found.remainingDays};
  if(action==="rebuild"&&found.kind!=="pipeBreak")return {ok:false,state,cost:0,remainingDays:found.remainingDays,reason:"unsupported"};if(found.actionCost<=0)return {ok:false,state,cost:0,remainingDays:found.remainingDays,reason:"unsupported"};if(state.economy.funds<found.actionCost)return {ok:false,state,cost:0,remainingDays:found.remainingDays,reason:"insufficientFunds"};
  const next=cloneState(state);const d=next.activeDisasters.find(x=>x.id===disasterId)!;next.economy.funds-=d.actionCost;d.mitigated=true;d.remainingDays=d.kind==="facilityFailure"?Math.min(d.remainingDays,3):d.kind==="fire"?Math.ceil(d.remainingDays/2):0;if(d.remainingDays===0){next.activeDisasters=next.activeDisasters.filter(x=>x.id!==d.id);next.disasterSchedule.safeUntilDay=Math.max(next.disasterSchedule.safeUntilDay,next.calendar.day+30);}else if(d.remainingDays<=Math.ceil(d.originalDuration/2))next.economy.quickRecoveryCount++;recalculateNetworks(next);return {ok:true,state:next,cost:d.actionCost,remainingDays:d.remainingDays};
}
