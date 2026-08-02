export type BuildTool = "road" | "residential" | "commercial" | "powerPlant" | "waterTower";
export type StructureId = string;
export type DisasterType = "fire" | "blackout" | "pipeBurst";
export type SimulationSpeed = 1 | 2 | 4;
export type OutcomeKind = "victory" | "defeat";

export interface GridPoint { x: number; y: number }
export interface StructureDefinition {
  tool: BuildTool; cost: number; maintenance: number; width: number; height: number;
  powerDemand: number; waterDemand: number; powerCapacity: number; waterCapacity: number;
  maxPopulation: number; jobs: number;
}
export interface StructureState {
  id: StructureId; tool: BuildTool; anchor: GridPoint; cells: GridPoint[];
  population: number; employees: number; roadConnected: boolean; powered: boolean; watered: boolean;
  powerDistance: number | null; waterDistance: number | null; regionId: string;
  disabled: boolean; builtAt: number;
}
export interface SessionState {
  paused: boolean; speed: SimulationSpeed; rememberedSpeed: SimulationSpeed; gameSeconds: number;
  month: number; operatingSeconds: number; status: "playing" | "victory" | "defeat";
  rngState: number; nextStructureSequence: number; nextMonthAt: number;
}
export interface EconomyState {
  funds: number; tax: number; maintenance: number; netIncome: number; recentNetIncome: number[];
  positiveIncomeStreak: number; fiscalMultiplier: 1 | 1.05 | 1.1; cumulativeTax: number;
}
export interface PopulationState { total: number; peak: number; housed: number; employed: number; jobs: number }
export interface CapacitySummary { powerSupply: number; powerDemand: number; waterSupply: number; waterDemand: number }
export interface NetworkState {
  roadComponents: Record<string, number>; powerCoverage: number; waterCoverage: number;
  capacity: CapacitySummary; affectedIds: string[];
}
export interface ScoreBreakdown {
  population: number; finance: number; services: number; satisfaction: number; pollution: number; total: number;
  powerCoverage: number; waterCoverage: number; recentAverageNet: number;
}
export interface CityMetrics {
  satisfaction: number; pollutedResidenceRatio: number; score: number; highestScore: number;
  breakdown: ScoreBreakdown; topPenalties: string[];
}
export interface ProgressionState {
  commercialPressure: boolean; pollutionIntensified: boolean; disastersEnabled: boolean; prosperityTax: boolean;
  population20ReachedAt: number | null;
}
export interface DisasterState {
  id: string; type: DisasterType; targetId: string; affectedIds: string[]; regionId: string;
  phase: "warning" | "active"; warningRemaining: number; remaining: number;
  dispatched: boolean; loss: number;
}
export interface ProsperityConditions {
  population: boolean; score: boolean; solvent: boolean; power: boolean; water: boolean; satisfaction: boolean;
}
export interface OutcomeStats {
  population: number; peakPopulation: number; cumulativeTax: number; disastersHandled: number;
  highestScore: number; operatingSeconds: number;
}
export interface OutcomeState {
  prosperitySeconds: number; insolvencySeconds: number; dissatisfactionSeconds: number;
  disasterGraceSeconds: number; reason: string | null; kind: OutcomeKind | null;
  stats: OutcomeStats; disastersHandled: number; previousSpeed: SimulationSpeed;
}
export interface SimulationState {
  session: SessionState; structures: Map<StructureId, StructureState>; economy: EconomyState;
  population: PopulationState; networks: NetworkState; cityMetrics: CityMetrics;
  progression: ProgressionState; disaster: DisasterState | null; outcome: OutcomeState;
  resilienceVoucher: boolean; scoreMilestones: number[]; nextDisasterAt: number | null; lastDisasterRegion: string | null;
}
export interface SimulationContent {
  cols: number; rows: number; maxStructures: number; blockedCells: ReadonlySet<string>;
  catalog: Readonly<Record<BuildTool, StructureDefinition>>;
}
export interface BuildCommand { tool: BuildTool; anchor: GridPoint; dragId?: string }
export interface BuildValidation { valid: boolean; reason: string | null; cost: number; cells: GridPoint[] }
export interface SimulationEvent { type: string; payload: Record<string, unknown> }
export interface SimulationStepResult { state: SimulationState; events: SimulationEvent[] }
export interface CommandResult extends SimulationStepResult { accepted: boolean; reason: string | null }

const key = (p: GridPoint): string => `${p.x},${p.y}`;
const clamp = (n: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, n));
const round2 = (n: number): number => Math.round(n * 100) / 100;
const CATALOG: Readonly<Record<BuildTool, StructureDefinition>> = Object.freeze({
  road: { tool: "road", cost: 8, maintenance: 1, width: 1, height: 1, powerDemand: 0, waterDemand: 0, powerCapacity: 0, waterCapacity: 0, maxPopulation: 0, jobs: 0 },
  residential: { tool: "residential", cost: 50, maintenance: 2, width: 1, height: 1, powerDemand: 4, waterDemand: 4, powerCapacity: 0, waterCapacity: 0, maxPopulation: 4, jobs: 0 },
  commercial: { tool: "commercial", cost: 70, maintenance: 4, width: 1, height: 1, powerDemand: 6, waterDemand: 5, powerCapacity: 0, waterCapacity: 0, maxPopulation: 0, jobs: 4 },
  powerPlant: { tool: "powerPlant", cost: 280, maintenance: 20, width: 2, height: 2, powerDemand: 0, waterDemand: 0, powerCapacity: 40, waterCapacity: 0, maxPopulation: 0, jobs: 0 },
  waterTower: { tool: "waterTower", cost: 220, maintenance: 16, width: 2, height: 2, powerDemand: 0, waterDemand: 0, powerCapacity: 0, waterCapacity: 40, maxPopulation: 0, jobs: 0 },
});
const blocked = new Set<string>();
for (let y = 0; y <= 4; y += 1) for (let x = 9; x <= 10; x += 1) blocked.add(`${x},${y}`);
for (let y = 7; y <= 11; y += 1) for (let x = 9; x <= 10; x += 1) blocked.add(`${x},${y}`);
for (let y = 0; y <= 1; y += 1) for (let x = 17; x <= 19; x += 1) blocked.add(`${x},${y}`);
for (let y = 10; y <= 11; y += 1) for (let x = 18; x <= 19; x += 1) blocked.add(`${x},${y}`);
[[1,1],[3,2],[7,1],[1,10],[6,9],[13,1],[16,3],[15,10]].forEach(([x,y]) => blocked.add(`${x},${y}`));
const DEFAULT_CONTENT: SimulationContent = { cols: 20, rows: 12, maxStructures: 120, blockedCells: blocked, catalog: CATALOG };
const emptyBreakdown = (): ScoreBreakdown => ({ population: 0, finance: 0, services: 0, satisfaction: 0, pollution: 10, total: 10, powerCoverage: 0, waterCoverage: 0, recentAverageNet: 0 });

function regionAt(p: GridPoint): string {
  if (p.y >= 8 && p.x >= 11) return "utility_basin";
  if (p.y >= 5 && p.y <= 7 && p.x >= 1 && p.x <= 15) return "old_town_corridor";
  if (p.x >= 11 && p.y >= 2 && p.y <= 7) return "east_market";
  return "west_reserve";
}
function cellsFor(anchor: GridPoint, def: StructureDefinition): GridPoint[] {
  const cells: GridPoint[] = [];
  for (let y = 0; y < def.height; y += 1) for (let x = 0; x < def.width; x += 1) cells.push({ x: anchor.x + x, y: anchor.y + y });
  return cells;
}
function cloneState(state: SimulationState): SimulationState {
  return {
    ...state, session: { ...state.session }, structures: new Map([...state.structures].map(([id, s]) => [id, { ...s, anchor: { ...s.anchor }, cells: s.cells.map(c => ({ ...c })) }])),
    economy: { ...state.economy, recentNetIncome: [...state.economy.recentNetIncome] }, population: { ...state.population },
    networks: { ...state.networks, roadComponents: { ...state.networks.roadComponents }, capacity: { ...state.networks.capacity }, affectedIds: [...state.networks.affectedIds] },
    cityMetrics: { ...state.cityMetrics, breakdown: { ...state.cityMetrics.breakdown }, topPenalties: [...state.cityMetrics.topPenalties] },
    progression: { ...state.progression }, disaster: state.disaster ? { ...state.disaster, affectedIds: [...state.disaster.affectedIds] } : null,
    outcome: { ...state.outcome, stats: { ...state.outcome.stats } }, scoreMilestones: [...state.scoreMilestones],
  };
}

export function createInitialSimulationState(seed = 0x5df6cc71): SimulationState {
  const structures = new Map<StructureId, StructureState>();
  for (let x = 2; x <= 6; x += 1) {
    const id = `road-${x - 1}`;
    structures.set(id, { id, tool: "road", anchor: { x, y: 6 }, cells: [{ x, y: 6 }], population: 0, employees: 0, roadConnected: true, powered: false, watered: false, powerDistance: null, waterDistance: null, regionId: "old_town_corridor", disabled: false, builtAt: 0 });
  }
  const state: SimulationState = {
    session: { paused: true, speed: 1, rememberedSpeed: 1, gameSeconds: 0, month: 0, operatingSeconds: 0, status: "playing", rngState: seed || 1, nextStructureSequence: 6, nextMonthAt: 10 },
    structures, economy: { funds: 1200, tax: 0, maintenance: 5, netIncome: 0, recentNetIncome: [], positiveIncomeStreak: 0, fiscalMultiplier: 1, cumulativeTax: 0 },
    population: { total: 0, peak: 0, housed: 0, employed: 0, jobs: 0 },
    networks: { roadComponents: {}, powerCoverage: 0, waterCoverage: 0, capacity: { powerSupply: 0, powerDemand: 0, waterSupply: 0, waterDemand: 0 }, affectedIds: [] },
    cityMetrics: { satisfaction: 50, pollutedResidenceRatio: 0, score: 10, highestScore: 10, breakdown: emptyBreakdown(), topPenalties: ["人口不足", "缺少电力覆盖", "缺少供水覆盖"] },
    progression: { commercialPressure: false, pollutionIntensified: false, disastersEnabled: false, prosperityTax: false, population20ReachedAt: null },
    disaster: null, outcome: { prosperitySeconds: 0, insolvencySeconds: 0, dissatisfactionSeconds: 0, disasterGraceSeconds: 10, reason: null, kind: null, disastersHandled: 0, previousSpeed: 1, stats: { population: 0, peakPopulation: 0, cumulativeTax: 0, disastersHandled: 0, highestScore: 10, operatingSeconds: 0 } },
    resilienceVoucher: false, scoreMilestones: [], nextDisasterAt: null, lastDisasterRegion: null,
  };
  return recalculateCityNetworks(state);
}

export function validateBuildCommand(state: SimulationState, command: BuildCommand, content: SimulationContent = DEFAULT_CONTENT): BuildValidation {
  const def = content.catalog[command.tool];
  if (!def) return { valid: false, reason: "未知建筑类型", cost: 0, cells: [] };
  const cells = cellsFor(command.anchor, def);
  if (state.session.status !== "playing") return { valid: false, reason: "本局已结束", cost: def.cost, cells };
  if (state.structures.size >= content.maxStructures) return { valid: false, reason: "建筑数量已达120上限", cost: def.cost, cells };
  if (state.economy.funds < def.cost) return { valid: false, reason: "资金不足", cost: def.cost, cells };
  if (cells.some(c => c.x < 0 || c.y < 0 || c.x >= content.cols || c.y >= content.rows)) return { valid: false, reason: "超出城市边界", cost: def.cost, cells };
  if (cells.some(c => content.blockedCells.has(key(c)))) return { valid: false, reason: "地形不可建设", cost: def.cost, cells };
  const occupied = new Set([...state.structures.values()].flatMap(s => s.cells.map(key)));
  if (cells.some(c => occupied.has(key(c)))) return { valid: false, reason: "与现有建筑重叠", cost: def.cost, cells };
  return { valid: true, reason: null, cost: def.cost, cells };
}

export function applyBuildCommand(state: SimulationState, command: BuildCommand, content: SimulationContent = DEFAULT_CONTENT): CommandResult {
  const check = validateBuildCommand(state, command, content);
  if (!check.valid) return { state, events: [], accepted: false, reason: check.reason };
  const next = cloneState(state); const id = `${command.tool}-${next.session.nextStructureSequence++}`;
  next.structures.set(id, { id, tool: command.tool, anchor: { ...command.anchor }, cells: check.cells, population: 0, employees: 0, roadConnected: command.tool === "road", powered: false, watered: false, powerDistance: null, waterDistance: null, regionId: regionAt(command.anchor), disabled: false, builtAt: next.session.gameSeconds });
  next.economy.funds -= check.cost;
  const recalculated = recalculateCityNetworks(next, content);
  return { state: recalculated, accepted: true, reason: null, events: [{ type: "StructureStatusChanged", payload: { structureId: id, changes: ["built"] } }, networkEvent(recalculated) ] };
}

export function demolishStructure(state: SimulationState, structureId: string, confirmed = true, content: SimulationContent = DEFAULT_CONTENT): CommandResult {
  const structure = state.structures.get(structureId);
  if (!confirmed || !structure) return { state, events: [], accepted: false, reason: structure ? "需要确认拆除" : "建筑不存在" };
  const next = cloneState(state); next.structures.delete(structureId);
  next.economy.funds += Math.floor(content.catalog[structure.tool].cost * 0.4);
  const recalculated = recalculateCityNetworks(next, content);
  return { state: recalculated, accepted: true, reason: null, events: [{ type: "StructureStatusChanged", payload: { structureId, changes: ["demolished"] } }, networkEvent(recalculated) ] };
}

export function setSimulationControl(state: SimulationState, control: { paused?: boolean; speed?: SimulationSpeed }): SimulationState {
  const next = cloneState(state);
  if (control.speed) { next.session.speed = control.speed; next.session.rememberedSpeed = control.speed; }
  if (typeof control.paused === "boolean") next.session.paused = control.paused;
  return next;
}

function adjacentRoadKeys(s: StructureState, roads: Set<string>): string[] {
  const result = new Set<string>();
  for (const c of s.cells) for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) { const k = `${c.x + dx},${c.y + dy}`; if (roads.has(k)) result.add(k); }
  return [...result].sort();
}
function roadDistances(sources: string[], roads: Set<string>): Map<string, number> {
  const distance = new Map<string, number>(); const queue: string[] = [];
  for (const source of sources) { distance.set(source, 0); queue.push(source); }
  for (let i = 0; i < queue.length; i += 1) { const current = queue[i]; const [x,y] = current.split(",").map(Number); const d = distance.get(current) as number; if (d >= 10) continue;
    for (const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]) { const n = `${x+dx},${y+dy}`; if (roads.has(n) && !distance.has(n)) { distance.set(n,d+1); queue.push(n); } }
  }
  return distance;
}
function disasterBlocks(state: SimulationState, id: string, service: "power" | "water"): boolean {
  const d = state.disaster; if (!d || d.phase !== "active" || !d.affectedIds.includes(id)) return false;
  return d.type === "fire" || (service === "power" ? d.type === "blackout" : d.type === "pipeBurst");
}

export function recalculateCityNetworks(state: SimulationState, content: SimulationContent = DEFAULT_CONTENT): SimulationState {
  const next = cloneState(state); const all = [...next.structures.values()]; const roads = new Set(all.filter(s => s.tool === "road").flatMap(s => s.cells.map(key)));
  const components: Record<string, number> = {}; let component = 0;
  for (const start of [...roads].sort()) if (components[start] === undefined) { const q=[start]; components[start]=component; for(let i=0;i<q.length;i+=1){const [x,y]=q[i].split(",").map(Number); for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){const n=`${x+dx},${y+dy}`; if(roads.has(n)&&components[n]===undefined){components[n]=component;q.push(n);}}} component+=1; }
  const consumers = all.filter(s => s.tool === "residential" || s.tool === "commercial");
  for (const s of all) { s.roadConnected = s.tool === "road" || adjacentRoadKeys(s, roads).length > 0; s.powered = false; s.watered = false; s.powerDistance = null; s.waterDistance = null; s.disabled = !!next.disaster && next.disaster.phase === "active" && next.disaster.affectedIds.includes(s.id) && next.disaster.type === "fire"; }
  const allocate = (service: "power"|"water"): { supply:number; demand:number } => {
    const capacityField = service === "power" ? "powerCapacity" : "waterCapacity"; const demandField = service === "power" ? "powerDemand" : "waterDemand";
    const facilities = all.filter(s => content.catalog[s.tool][capacityField] > 0 && !disasterBlocks(next,s.id,service)); let supply=facilities.reduce((n,s)=>n+content.catalog[s.tool][capacityField],0);
    const sourceRoads=facilities.flatMap(s=>adjacentRoadKeys(s,roads)); const distances=roadDistances(sourceRoads,roads);
    const ranked=consumers.map(s=>({s,d:Math.min(...adjacentRoadKeys(s,roads).map(k=>distances.get(k) ?? Infinity))})).filter(v=>v.d<=10).sort((a,b)=>a.d-b.d||a.s.id.localeCompare(b.s.id));
    const demand=consumers.reduce((n,s)=>n+content.catalog[s.tool][demandField],0); let remaining=supply;
    for(const item of ranked){const need=content.catalog[item.s.tool][demandField]; if(remaining>=need&&!disasterBlocks(next,item.s.id,service)){remaining-=need; if(service==="power"){item.s.powered=true;item.s.powerDistance=item.d;}else{item.s.watered=true;item.s.waterDistance=item.d;}}}
    return {supply,demand};
  };
  const power=allocate("power"), water=allocate("water"); const eligible=consumers.length;
  next.networks={ roadComponents:components, powerCoverage:eligible?100*consumers.filter(s=>s.powered).length/eligible:0, waterCoverage:eligible?100*consumers.filter(s=>s.watered).length/eligible:0, capacity:{powerSupply:power.supply,powerDemand:power.demand,waterSupply:water.supply,waterDemand:water.demand}, affectedIds:consumers.filter(s=>!s.roadConnected||!s.powered||!s.watered).map(s=>s.id) };
  updateMetrics(next, content); return next;
}

function updateMetrics(state: SimulationState, content: SimulationContent): void {
  const all=[...state.structures.values()], homes=all.filter(s=>s.tool==="residential"), shops=all.filter(s=>s.tool==="commercial");
  const pop=homes.reduce((n,s)=>n+s.population,0), jobs=shops.reduce((n,s)=>n+content.catalog.commercial.jobs,0), employed=Math.min(pop,jobs,shops.filter(s=>s.roadConnected&&s.powered&&s.watered&&!s.disabled).length*4);
  let polluted=0; const plants=all.filter(s=>s.tool==="powerPlant"); for(const h of homes) if(plants.some(p=>Math.abs(p.anchor.x-h.anchor.x)+Math.abs(p.anchor.y-h.anchor.y)<=3)) polluted+=h.population;
  const pollutionRatio=pop?polluted/pop:0; const employmentRate=pop?employed/pop:1; const serviceRate=(state.networks.powerCoverage+state.networks.waterCoverage)/200;
  const satisfaction=clamp(35+serviceRate*40+employmentRate*25-pollutionRatio*(state.progression.pollutionIntensified?30:20)-(state.economy.netIncome<0?10:0),0,100);
  state.population={total:pop,peak:Math.max(state.population.peak,pop),housed:pop,employed,jobs}; state.cityMetrics.satisfaction=round2(satisfaction); state.cityMetrics.pollutedResidenceRatio=round2(pollutionRatio*100);
  const avg=state.economy.recentNetIncome.length?state.economy.recentNetIncome.reduce((a,b)=>a+b,0)/state.economy.recentNetIncome.length:0;
  const populationScore=clamp(pop/40*25,0,25), financeScore=clamp((avg+20)/120*20*state.economy.fiscalMultiplier,0,20), servicesScore=clamp(state.networks.powerCoverage/100*10+state.networks.waterCoverage/100*10,0,20), satisfactionScore=satisfaction/100*25, pollutionScore=(1-pollutionRatio)*10;
  const total=round2(clamp(populationScore+financeScore+servicesScore+satisfactionScore+pollutionScore,0,100));
  state.cityMetrics.breakdown={population:round2(populationScore),finance:round2(financeScore),services:round2(servicesScore),satisfaction:round2(satisfactionScore),pollution:round2(pollutionScore),total,powerCoverage:round2(state.networks.powerCoverage),waterCoverage:round2(state.networks.waterCoverage),recentAverageNet:round2(avg)};
  state.cityMetrics.score=total; state.cityMetrics.highestScore=Math.max(state.cityMetrics.highestScore,total);
  const penalties:[[string,number],[string,number],[string,number],[string,number],[string,number]]=[["人口不足",25-populationScore],["财政贡献偏低",20-financeScore],["公共服务覆盖不足",20-servicesScore],["满意度偏低",25-satisfactionScore],["住宅污染暴露",10-pollutionScore]];
  state.cityMetrics.topPenalties=penalties.sort((a,b)=>b[1]-a[1]).slice(0,3).map(v=>v[0]);
}

export function resolveMonthlyLedger(state: SimulationState, content: SimulationContent = DEFAULT_CONTENT): SimulationStepResult {
  const next=cloneState(state); const all=[...next.structures.values()];
  for(const home of all.filter(s=>s.tool==="residential").sort((a,b)=>a.id.localeCompare(b.id))) if(home.roadConnected&&home.powered&&home.watered&&!home.disabled&&home.population<content.catalog.residential.maxPopulation) home.population+=1;
  let recalculated=recalculateCityNetworks(next,content); const activeShops=[...recalculated.structures.values()].filter(s=>s.tool==="commercial"&&s.roadConnected&&s.powered&&s.watered&&!s.disabled);
  for(const shop of activeShops) shop.employees=Math.min(4,Math.max(0,recalculated.population.total-activeShops.filter(s=>s.id<shop.id).reduce((n,s)=>n+s.employees,0)));
  recalculated=recalculateCityNetworks(recalculated,content);
  const taxBase=recalculated.population.total*5+recalculated.population.employed*6; const tax=Math.floor(taxBase*(recalculated.progression.prosperityTax?1.2:1)); const maintenance=[...recalculated.structures.values()].reduce((n,s)=>n+content.catalog[s.tool].maintenance,0); const net=tax-maintenance;
  recalculated.economy.tax=tax; recalculated.economy.maintenance=maintenance; recalculated.economy.netIncome=net; recalculated.economy.funds+=net; recalculated.economy.cumulativeTax+=tax; recalculated.economy.recentNetIncome.push(net); if(recalculated.economy.recentNetIncome.length>3) recalculated.economy.recentNetIncome.shift();
  recalculated.economy.positiveIncomeStreak=net>0?recalculated.economy.positiveIncomeStreak+1:0; recalculated.economy.fiscalMultiplier=recalculated.economy.positiveIncomeStreak>=6?1.1:recalculated.economy.positiveIncomeStreak>=3?1.05:1; recalculated.session.month+=1;
  updateProgression(recalculated); updateMetrics(recalculated,content);
  return {state:recalculated,events:[{type:"MonthSettled",payload:{tax,maintenance,net,score:recalculated.cityMetrics.breakdown,streak:recalculated.economy.positiveIncomeStreak}}]};
}

function updateProgression(s:SimulationState):void { const p=s.population.total; s.progression.commercialPressure=p>=10; s.progression.pollutionIntensified=p>=20; s.progression.disastersEnabled=p>=20; s.progression.prosperityTax=p>=35; if(p>=20&&s.progression.population20ReachedAt===null)s.progression.population20ReachedAt=s.session.gameSeconds; }
function random(s:SimulationState):number { let x=s.session.rngState|0; x^=x<<13;x^=x>>>17;x^=x<<5;s.session.rngState=x>>>0;return s.session.rngState/4294967296; }
function disasterCost(t:DisasterType):number{return t==="fire"?80:t==="blackout"?70:60;}
function networkEvent(s:SimulationState):SimulationEvent{return{type:"NetworksRecalculated",payload:{powerCoverage:s.networks.powerCoverage,waterCoverage:s.networks.waterCoverage,capacity:s.networks.capacity,affectedIds:s.networks.affectedIds}};}
function scheduleDisaster(s:SimulationState,events:SimulationEvent[]):void {
  if(s.disaster||!s.progression.disastersEnabled||s.session.gameSeconds<60||s.outcome.disasterGraceSeconds>0)return;
  const reached=s.progression.population20ReachedAt; if(reached===null||s.session.gameSeconds<reached+30)return;
  if(s.nextDisasterAt===null){s.nextDisasterAt=s.session.gameSeconds+30;return;} if(s.session.gameSeconds<s.nextDisasterAt)return;
  const candidates=[...s.structures.values()].filter(v=>v.tool!=="road"&&v.regionId!==s.lastDisasterRegion); if(!candidates.length)return;
  const type=(['fire','blackout','pipeBurst'] as DisasterType[])[Math.floor(random(s)*3)]; let typed=candidates;
  if(type==="blackout"){const utilities=candidates.filter(v=>v.tool==="powerPlant");if(utilities.length)typed=utilities;} if(type==="pipeBurst"){const utilities=candidates.filter(v=>v.tool==="waterTower");if(utilities.length)typed=utilities;}
  const target=typed[Math.floor(random(s)*typed.length)]; const affected=[target.id]; if(type==="fire") for(const v of candidates)if(v.id!==target.id&&Math.abs(v.anchor.x-target.anchor.x)+Math.abs(v.anchor.y-target.anchor.y)<=1&&affected.length<3)affected.push(v.id);
  s.disaster={id:`disaster-${Math.floor(s.session.gameSeconds)}`,type,targetId:target.id,affectedIds:affected,regionId:target.regionId,phase:"warning",warningRemaining:5,remaining:20+Math.floor(random(s)*11),dispatched:false,loss:0}; s.lastDisasterRegion=target.regionId;
  events.push({type:"DisasterWarningStarted",payload:{type,targetId:target.id,warningSeconds:5}});
}

export function dispatchEmergency(state:SimulationState,disasterId:string):CommandResult {
  if(!state.disaster||state.disaster.id!==disasterId)return{state,events:[],accepted:false,reason:"灾害不存在"}; const next=cloneState(state); const d=next.disaster as DisasterState; const cost=Math.ceil(disasterCost(d.type)*(next.resilienceVoucher?0.5:1));
  if(next.economy.funds<cost)return{state,events:[],accepted:false,reason:"应急资金不足"}; next.economy.funds-=cost; if(next.resilienceVoucher)next.resilienceVoucher=false; d.remaining*=0.4; d.warningRemaining*=0.4; d.dispatched=true;
  return{state:next,events:[{type:"StructureStatusChanged",payload:{structureId:d.targetId,changes:["emergencyDispatched"]}}],accepted:true,reason:null};
}

export function evaluateOutcome(state:SimulationState,elapsedGameSeconds=0):SimulationStepResult {
  const next=cloneState(state); const events:SimulationEvent[]=[]; if(next.session.status!=="playing")return{state:next,events};
  const c:ProsperityConditions={population:next.population.total>=20,score:next.cityMetrics.score>=80,solvent:next.economy.funds>=0,power:next.networks.powerCoverage>=90,water:next.networks.waterCoverage>=90,satisfaction:next.cityMetrics.satisfaction>=70}; const prosperous=Object.values(c).every(Boolean);
  next.outcome.prosperitySeconds=prosperous?next.outcome.prosperitySeconds+elapsedGameSeconds:0; next.outcome.insolvencySeconds=next.economy.funds< -500?next.outcome.insolvencySeconds+elapsedGameSeconds:0; next.outcome.dissatisfactionSeconds=next.cityMetrics.satisfaction<10?next.outcome.dissatisfactionSeconds+elapsedGameSeconds:0;
  events.push({type:"ProsperityProgressChanged",payload:{seconds:next.outcome.prosperitySeconds,conditions:c,reset:!prosperous}});
  let kind:OutcomeKind|null=null,reason:string|null=null; if(next.outcome.prosperitySeconds>=60){kind="victory";reason="城市繁荣条件稳定维持60秒";}else if(next.outcome.insolvencySeconds>=30){kind="defeat";reason="财政破产持续30秒";}else if(next.outcome.dissatisfactionSeconds>=30){kind="defeat";reason="市民满意度危机持续30秒";}
  if(kind){next.outcome.kind=kind;next.outcome.reason=reason;next.outcome.previousSpeed=next.session.speed;next.session.status=kind;next.session.paused=true;next.outcome.stats={population:next.population.total,peakPopulation:next.population.peak,cumulativeTax:next.economy.cumulativeTax,disastersHandled:next.outcome.disastersHandled,highestScore:next.cityMetrics.highestScore,operatingSeconds:next.session.operatingSeconds};events.push({type:"OutcomeReached",payload:{kind,reason,stats:next.outcome.stats}});}
  return{state:next,events};
}

export function continueAfterVictory(state:SimulationState):SimulationState { const next=cloneState(state); if(next.session.status==="victory"){next.session.status="playing";next.session.paused=false;next.session.speed=next.outcome.previousSpeed;next.outcome.kind=null;next.outcome.reason=null;next.outcome.prosperitySeconds=0;next.outcome.disasterGraceSeconds=10;} return next; }

export function advanceSimulationFixedStep(state:SimulationState,fixedRealSeconds:number,content:SimulationContent=DEFAULT_CONTENT):SimulationStepResult {
  if(state.session.paused||state.session.status!=="playing"||fixedRealSeconds<=0)return{state,events:[]}; let next=cloneState(state),events:SimulationEvent[]=[]; let remaining=fixedRealSeconds*next.session.speed;
  while(remaining>0){const dt=Math.min(1,remaining);remaining-=dt;next.session.gameSeconds+=dt;next.session.operatingSeconds+=dt;next.outcome.disasterGraceSeconds=Math.max(0,next.outcome.disasterGraceSeconds-dt);updateProgression(next);
    if(next.disaster){const d=next.disaster;if(d.phase==="warning"){d.warningRemaining-=dt;if(d.warningRemaining<=0){d.phase="active";events.push({type:"DisasterActivated",payload:{type:d.type,targetId:d.targetId,duration:d.remaining}});next=recalculateCityNetworks(next,content);}}else{d.remaining-=dt;if(d.remaining<=0){events.push({type:"DisasterResolved",payload:{type:d.type,targetId:d.targetId,dispatched:d.dispatched}});if(d.dispatched)next.outcome.disastersHandled+=1;const interval=next.population.total>=35?70+random(next)*40:90+random(next)*60;next.nextDisasterAt=next.session.gameSeconds+interval;next.disaster=null;next=recalculateCityNetworks(next,content);}}}
    scheduleDisaster(next,events);
    while(next.session.gameSeconds+1e-9>=next.session.nextMonthAt){const settled=resolveMonthlyLedger(next,content);next=settled.state;events.push(...settled.events);next.session.nextMonthAt+=10;}
    for(const milestone of [40,60,80])if(next.cityMetrics.score>=milestone&&!next.scoreMilestones.includes(milestone)){next.scoreMilestones.push(milestone);const voucherAwarded=milestone===60&&!next.resilienceVoucher;if(voucherAwarded)next.resilienceVoucher=true;events.push({type:"ScoreMilestoneReached",payload:{milestone,voucherAwarded}});}
    const outcome=evaluateOutcome(next,dt);next=outcome.state;events.push(...outcome.events);if(next.session.status!=="playing")break;
  }
  events.push({type:"SimulationAdvanced",payload:{gameSeconds:next.session.gameSeconds,changedStructureIds:next.networks.affectedIds}});return{state:next,events};
}

export const CITY_SIMULATION_CATALOG = CATALOG;
export const DEFAULT_SIMULATION_RULES = DEFAULT_CONTENT;
