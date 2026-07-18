type BuildingKind = "road" | "residential" | "commercial" | "powerPlant" | "waterTower";
type DisasterKind = "fire" | "blackout" | "pollutionLeak" | "storm" | "majorStorm";
type Speed = 1 | 2 | 4;
type SliceKey = "clock" | "grid" | "economy" | "utilities" | "cityMetrics" | "disaster" | "progression";
type Cell = Readonly<{ x: number; y: number }>;
type Result = Readonly<{ ok: boolean; reason?: string; cost?: number; affectedIds?: readonly string[] }>;

interface Definition { kind: BuildingKind; cost: number; maintenance: number; maxHp: number; capacity?: number }
interface ContentInput {
  map?: { cols?: number; rows?: number; blocked?: readonly Cell[] };
  buildingDefinitions?: Partial<Record<BuildingKind, Partial<Definition>>>;
  disasterDefinitions?: unknown;
  tutorialSteps?: unknown;
  phaseSchedule?: unknown;
  stormPath?: readonly Cell[];
}
interface Building {
  id: string; kind: BuildingKind; x: number; y: number; hp: number; maxHp: number; cost: number;
  residents: number; roadConnected: boolean; powerCoverage: number; waterCoverage: number;
  pollution: number; waterBase: number; waterModifier: number; waterActual: number;
}
interface EconomyState { funds: number; taxIncome: number; commercialIncome: number; maintenance: number; grants: number; repairCosts: number; netIncome: number }
interface UtilityState { powerSupply: number; powerDemand: number; powerCoverage: number; waterSupply: number; waterDemand: number; waterCoverage: number }
interface MetricsState { population: number; averagePollution: number; satisfaction: number; score: number; highScore: number; stars: number; stableDays: number; bankruptcyDays: number; abandonmentDays: number }
interface DisasterState { phase: "none" | "warning" | "active"; kind: DisasterKind | null; targetCells: Cell[]; affectedIds: string[]; daysRemaining: number; lastImpactDay: number; immunityDays: number; majorTriggered: boolean }
interface ProgressionState { tutorialIndex: number; tutorialReward: number; grantsClaimed: number[]; aging: boolean; fullSettlement: boolean; commercialPollution: boolean; disastersUnlocked: boolean }
interface Snapshot {
  revision: number; ended: null | "victory" | "bankruptcy" | "abandoned";
  clock: { day: number; elapsedMs: number; paused: boolean; speed: Speed };
  grid: { cols: number; rows: number; blocked: readonly Cell[]; buildings: readonly Readonly<Building>[] };
  economy: Readonly<EconomyState>; utilities: Readonly<UtilityState>; cityMetrics: Readonly<MetricsState>;
  disaster: Readonly<DisasterState>; progression: Readonly<ProgressionState>;
}
interface SimulationEvent { name: string; payload: Record<string, unknown> }

const KINDS: BuildingKind[] = ["road", "residential", "commercial", "powerPlant", "waterTower"];
const DEFAULT_DEFS: Record<BuildingKind, Definition> = {
  road: { kind: "road", cost: 40, maintenance: 1, maxHp: 60 },
  residential: { kind: "residential", cost: 300, maintenance: 8, maxHp: 100, capacity: 50 },
  commercial: { kind: "commercial", cost: 450, maintenance: 18, maxHp: 110 },
  powerPlant: { kind: "powerPlant", cost: 1200, maintenance: 95, maxHp: 160, capacity: 300 },
  waterTower: { kind: "waterTower", cost: 900, maintenance: 70, maxHp: 140, capacity: 260 },
};
const DEFAULT_BLOCKED: Cell[] = [
  {x:11,y:6},{x:12,y:6},{x:13,y:6},{x:11,y:7},{x:12,y:7},{x:13,y:7},
  {x:19,y:10},{x:20,y:10},{x:21,y:10},{x:22,y:10},{x:23,y:10},{x:19,y:11},{x:20,y:11},{x:21,y:11},{x:22,y:11},{x:23,y:11},
  {x:22,y:12},{x:23,y:12},{x:22,y:13},{x:23,y:13},
  {x:1,y:1},{x:4,y:1},{x:7,y:5},{x:2,y:10},{x:5,y:12},{x:9,y:10},{x:14,y:2},{x:15,y:12},{x:18,y:1},{x:21,y:3},{x:17,y:12},
];
const DEFAULT_STORM: Cell[] = [{x:23,y:2},{x:19,y:4},{x:15,y:6},{x:10,y:8},{x:5,y:11},{x:1,y:13}];
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));
const key = (x: number, y: number) => `${x},${y}`;
const dist = (a: Cell, b: Cell) => Math.abs(a.x-b.x)+Math.abs(a.y-b.y);
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/** Pure placement, demolition and repair legality/cost rules. */
export class PlacementRules {
  static validate(kind: BuildingKind, cells: readonly Cell[], sim: CitySimulation): Result {
    if (!KINDS.includes(kind) || cells.length === 0) return { ok:false, reason:"invalid-tool" };
    const unique = new Map(cells.map(c => [key(c.x,c.y), c]));
    if (unique.size !== cells.length) return { ok:false, reason:"duplicate-cell" };
    if (kind !== "road" && cells.length !== 1) return { ok:false, reason:"single-cell-building" };
    if (kind === "road" && !this.contiguous(cells)) return { ok:false, reason:"road-drag-not-contiguous" };
    for (const c of cells) {
      if (!sim.isInside(c) || sim.isBlocked(c)) return { ok:false, reason:"blocked" };
      if (sim.buildingAt(c)) return { ok:false, reason:"occupied" };
    }
    const cost = sim.definition(kind).cost * cells.length;
    if (sim.funds < cost) return { ok:false, reason:"insufficient-funds", cost };
    return { ok:true, cost };
  }

  static contiguous(cells: readonly Cell[]): boolean {
    if (cells.length < 2) return true;
    const wanted = new Set(cells.map(c => key(c.x,c.y))), seen = new Set<string>(), queue = [cells[0]];
    while (queue.length) {
      const c = queue.shift()!; const k = key(c.x,c.y); if (seen.has(k)) continue; seen.add(k);
      for (const n of [{x:c.x+1,y:c.y},{x:c.x-1,y:c.y},{x:c.x,y:c.y+1},{x:c.x,y:c.y-1}]) if (wanted.has(key(n.x,n.y))) queue.push(n);
    }
    return seen.size === wanted.size;
  }

  static repairCost(building: Readonly<Building>): number {
    const loss = 1 - building.hp / building.maxHp;
    return loss <= 0 ? 0 : Math.max(20, Math.ceil(building.cost * loss * 0.4));
  }
}

/** Daily tax, commerce, maintenance and aging calculations. */
export class EconomySystem {
  settle(sim: CitySimulation): void {
    const buildings = sim.mutableBuildings();
    const residents = buildings.filter(b=>b.kind==="residential").reduce((n,b)=>n+b.residents,0);
    const commercial = buildings.filter(b=>b.kind==="commercial" && b.roadConnected && b.powerCoverage>0 && b.waterCoverage>0);
    const support = commercial.length ? Math.min(1, residents / (commercial.length * 60)) : 0;
    const taxIncome = residents * 2;
    const commercialIncome = commercial.reduce((n,b)=>n + 120 * support * Math.min(b.powerCoverage,b.waterCoverage),0);
    const maintenance = buildings.reduce((n,b)=>n + sim.definition(b.kind).maintenance * ((sim.day>=90 && (b.kind==="powerPlant"||b.kind==="waterTower")) ? 1.25 : 1),0);
    const netIncome = taxIncome + commercialIncome - maintenance;
    sim.setEconomy({ ...sim.economy, taxIncome, commercialIncome, maintenance, netIncome });
    sim.changeFunds(netIncome);
  }
}

/** Orthogonal road networking, service-distance allocation, pollution and sensitive water capacity. */
export class UtilityNetworkSystem {
  static waterModifier(pollution: number): number {
    if (pollution <= 10) return 1;
    if (pollution <= 45) return 1 - ((pollution-10)/35)*0.45;
    return Math.max(0.3, 0.55 - (pollution-45)*0.01);
  }

  recompute(sim: CitySimulation): void {
    const buildings=sim.mutableBuildings(), roads=buildings.filter(b=>b.kind==="road" && b.hp>0), roadMap=new Map(roads.map(r=>[key(r.x,r.y),r]));
    const pollution=this.pollutionGrid(sim, buildings);
    for (const b of buildings) {
      b.roadConnected=this.adjacentRoads(b,roadMap).length>0;
      b.powerCoverage=0; b.waterCoverage=0; b.pollution=pollution.get(key(b.x,b.y))??0;
      if (b.kind==="waterTower") {
        const values: number[]=[];
        for(let y=Math.max(0,b.y-3);y<=Math.min(sim.rows-1,b.y+3);y++) for(let x=Math.max(0,b.x-3);x<=Math.min(sim.cols-1,b.x+3);x++) if(dist(b,{x,y})<=3) values.push(pollution.get(key(x,y))??0);
        const avg=values.reduce((a,n)=>a+n,0)/Math.max(1,values.length);
        b.waterBase=260; b.waterModifier=UtilityNetworkSystem.waterModifier(avg); b.waterActual=260*b.waterModifier*(b.hp/b.maxHp);
      }
    }
    const demand=buildings.filter(b=>b.kind==="residential"||b.kind==="commercial");
    let powerSupply=0, waterSupply=0, powerDemand=0, waterDemand=0, servedPower=0, servedWater=0;
    for (const d of demand) {
      const pd=d.kind==="commercial"?35:d.residents, wd=d.kind==="commercial"?30:d.residents;
      powerDemand+=pd; waterDemand+=wd;
      if (!d.roadConnected || d.hp<=0) continue;
      const powerSources=buildings.filter(s=>s.kind==="powerPlant"&&s.roadConnected&&s.hp>0&&!sim.isBlackout(s.id)&&this.roadDistance(s,d,roadMap)<=10);
      const waterSources=buildings.filter(s=>s.kind==="waterTower"&&s.roadConnected&&s.hp>0&&this.roadDistance(s,d,roadMap)<=10);
      const competing=demand.filter(o=>o.roadConnected&&o.hp>0&&powerSources.some(s=>this.roadDistance(s,o,roadMap)<=10));
      const pTotal=competing.reduce((n,o)=>n+(o.kind==="commercial"?35:o.residents),0), pCap=powerSources.reduce((n,s)=>n+300*(s.hp/s.maxHp),0);
      const waterCompeting=demand.filter(o=>o.roadConnected&&o.hp>0&&waterSources.some(s=>this.roadDistance(s,o,roadMap)<=10));
      const wTotal=waterCompeting.reduce((n,o)=>n+(o.kind==="commercial"?30:o.residents),0), wCap=waterSources.reduce((n,s)=>n+s.waterActual,0);
      d.powerCoverage=pd===0?(powerSources.length?1:0):clamp(pCap/Math.max(pd,pTotal),0,1);
      d.waterCoverage=wd===0?(waterSources.length?1:0):clamp(wCap/Math.max(wd,wTotal),0,1);
      servedPower+=pd*d.powerCoverage; servedWater+=wd*d.waterCoverage;
    }
    for(const b of buildings) if(b.kind==="powerPlant"&&b.roadConnected&&b.hp>0&&!sim.isBlackout(b.id)) powerSupply+=300*(b.hp/b.maxHp);
    for(const b of buildings) if(b.kind==="waterTower"&&b.roadConnected&&b.hp>0) waterSupply+=b.waterActual;
    const avg=[...pollution.values()].reduce((a,n)=>a+n,0)/(sim.cols*sim.rows);
    sim.setUtilities({powerSupply,powerDemand,powerCoverage:powerDemand?servedPower/powerDemand:1,waterSupply,waterDemand,waterCoverage:waterDemand?servedWater/waterDemand:1});
    sim.setAveragePollution(avg);
  }

  private pollutionGrid(sim: CitySimulation, buildings: Building[]): Map<string,number> {
    const map=new Map<string,number>(); const activeCommercial=buildings.filter(b=>b.kind==="commercial"&&b.roadConnected&&b.hp>0).length;
    const traffic=sim.day>=25?activeCommercial*1.5:0;
    for(let y=0;y<sim.rows;y++) for(let x=0;x<sim.cols;x++) {
      let p=traffic;
      for(const plant of buildings.filter(b=>b.kind==="powerPlant"&&b.roadConnected&&b.hp>0)) p+=Math.max(0,28-dist({x,y},plant)*4)*(plant.hp/plant.maxHp);
      if(sim.pollutionLeakAt({x,y})) p+=25;
      map.set(key(x,y),p);
    }
    return map;
  }

  private adjacentRoads(b: Building, roads: Map<string,Building>): Building[] { return [{x:b.x+1,y:b.y},{x:b.x-1,y:b.y},{x:b.x,y:b.y+1},{x:b.x,y:b.y-1}].map(c=>roads.get(key(c.x,c.y))).filter((r):r is Building=>!!r); }
  private roadDistance(a: Building,b: Building,roads: Map<string,Building>): number {
    const starts=this.adjacentRoads(a,roads), goals=new Set(this.adjacentRoads(b,roads).map(r=>key(r.x,r.y))); if(!starts.length||!goals.size)return Infinity;
    const q=starts.map(r=>({r,d:0})), seen=new Set<string>();
    while(q.length){const {r,d}=q.shift()!,k=key(r.x,r.y);if(seen.has(k))continue;seen.add(k);if(goals.has(k))return d;
      for(const c of [{x:r.x+1,y:r.y},{x:r.x-1,y:r.y},{x:r.x,y:r.y+1},{x:r.x,y:r.y-1}]){const n=roads.get(key(c.x,c.y));if(n&&!seen.has(key(c.x,c.y)))q.push({r:n,d:d+1});}}
    return Infinity;
  }
}

/** Seeded, telegraphed and bounded normal/major disaster scheduler. */
export class DisasterSystem {
  tick(sim: CitySimulation): void {
    const d=sim.mutableDisaster(); if(d.immunityDays>0)d.immunityDays--;
    if(d.phase==="warning"){ if(--d.daysRemaining<=0)this.impact(sim); return; }
    if(d.phase==="active"){ if(--d.daysRemaining<=0){sim.emit("DisasterResolved",{kind:d.kind,affectedIds:[...d.affectedIds],recoveryDays:d.kind==="majorStorm"?5:0}); if(d.kind==="majorStorm")d.immunityDays=5; d.phase="none";d.kind=null;d.targetCells=[];d.affectedIds=[];} return; }
    if(!d.majorTriggered&&sim.metrics.population>=400&&sim.metrics.score>=700){d.majorTriggered=true;this.warn(sim,"majorStorm",3,4);return;}
    if(!sim.progression.disastersUnlocked||d.immunityDays>0||sim.day-d.lastImpactDay<12)return;
    if(sim.day>=40&&sim.day%13===sim.randomInt(0,12))this.warn(sim,["fire","blackout","pollutionLeak","storm"][sim.randomInt(0,3)] as DisasterKind,2,6);
  }

  private warn(sim: CitySimulation,kind: DisasterKind,days:number,max:number):void {
    const d=sim.mutableDisaster(), candidates=kind==="majorStorm"?sim.stormCandidates():sim.mutableBuildings().filter(b=>b.kind!=="road"||kind==="storm").map(b=>({x:b.x,y:b.y}));
    d.phase="warning";d.kind=kind;d.daysRemaining=days;d.targetCells=sim.pickCells(candidates,kind==="majorStorm"?Math.min(4,max):kind==="storm"?Math.min(6,max):1);
    sim.emit("DisasterTelegraphed",{kind,targetCells:clone(d.targetCells),daysRemaining:days});
  }

  private impact(sim: CitySimulation):void {
    const d=sim.mutableDisaster(), targets=d.targetCells.map(c=>sim.buildingAt(c)).filter((b):b is Building=>!!b), affected: Building[]=[];
    if(d.kind==="blackout"){const plants=targets.filter(b=>b.kind==="powerPlant");affected.push(...(plants.length?plants:sim.mutableBuildings().filter(b=>b.kind==="powerPlant").slice(0,1)));d.daysRemaining=sim.randomInt(2,4);}
    else if(d.kind==="pollutionLeak"){affected.push(...targets.slice(0,1));d.daysRemaining=3;}
    else {
      const limit=d.kind==="fire"?2:d.kind==="majorStorm"?4:targets.filter(b=>b.kind!=="road").length?3:6;
      let chosen=targets.slice(0,limit);
      if(d.kind==="majorStorm")chosen=sim.preserveCriticalSources(chosen);
      for(const b of chosen){b.hp=Math.max(1,b.hp-(d.kind==="majorStorm"?65:40));affected.push(b);}
      d.daysRemaining=1;
    }
    d.affectedIds=affected.map(b=>b.id);d.phase="active";d.lastImpactDay=sim.day;
  }
}

/** Score, grants, stability and recoverable loss counters. */
export class VictorySystem {
  tick(sim: CitySimulation): void {
    const m=sim.mutableMetrics(), buildings=sim.mutableBuildings(), occupied=buildings.filter(b=>b.kind!=="road"), connected=occupied.length?occupied.filter(b=>b.roadConnected).length/occupied.length:0;
    const pop=200*clamp(m.population/500,0,1), fiscal=140*clamp((sim.economy.netIncome+100)/900,0,1), road=120*connected;
    const power=120*sim.utilities.powerCoverage, water=120*sim.utilities.waterCoverage, happy=160*(m.satisfaction/100), clean=140*clamp(1-m.averagePollution/70,0,1);
    m.score=Math.round(clamp(pop+fiscal+road+power+water+happy+clean,0,1000));m.highScore=Math.max(m.highScore,m.score);m.stars=m.score<200?1:m.score<400?2:m.score<600?3:m.score<800?4:5;
    for(const [threshold,reward] of [[400,300],[600,500],[800,700]] as const)if(m.score>=threshold&&!sim.progression.grantsClaimed.includes(threshold)){sim.progression.grantsClaimed.push(threshold);sim.changeFunds(reward);sim.addGrant(reward);sim.emit("ProgressMilestoneReached",{kind:"grant",value:threshold,reward});}
    const stable=m.population>=500&&m.satisfaction>=75&&m.averagePollution<35&&m.score>=800;m.stableDays=stable?m.stableDays+1:0;
    m.bankruptcyDays=sim.funds < -2000?m.bankruptcyDays+1:0;m.abandonmentDays=m.satisfaction<10?m.abandonmentDays+1:0;
    if(m.stableDays>=30)sim.end("victory");else if(m.bankruptcyDays>=20)sim.end("bankruptcy");else if(m.abandonmentDays>=15)sim.end("abandoned");
  }
}

/** Headless deterministic city simulation. Inject content constants or use contract defaults. */
export class CitySimulation {
  readonly cols:number;readonly rows:number;readonly blocked:Cell[];
  private defs:Record<BuildingKind,Definition>;private buildings:Building[]=[];private nextId=1;private revision=0;private accumulator=0;private rng:number;private events:SimulationEvent[]=[];private ended:null|"victory"|"bankruptcy"|"abandoned"=null;
  private clock={day:1,elapsedMs:0,paused:false,speed:1 as Speed};
  economy:EconomyState={funds:5000,taxIncome:0,commercialIncome:0,maintenance:0,grants:0,repairCosts:0,netIncome:0};
  utilities:UtilityState={powerSupply:0,powerDemand:0,powerCoverage:1,waterSupply:0,waterDemand:0,waterCoverage:1};
  metrics:MetricsState={population:0,averagePollution:0,satisfaction:60,score:0,highScore:0,stars:1,stableDays:0,bankruptcyDays:0,abandonmentDays:0};
  progression:ProgressionState={tutorialIndex:0,tutorialReward:0,grantsClaimed:[],aging:false,fullSettlement:false,commercialPollution:false,disastersUnlocked:false};
  private disaster:DisasterState={phase:"none",kind:null,targetCells:[],affectedIds:[],daysRemaining:0,lastImpactDay:-99,immunityDays:0,majorTriggered:false};
  private utilitySystem=new UtilityNetworkSystem();private economySystem=new EconomySystem();private disasterSystem=new DisasterSystem();private victorySystem=new VictorySystem();private stormPath:Cell[];

  constructor(content:ContentInput={},seed=0x51f15e){this.cols=content.map?.cols??24;this.rows=content.map?.rows??14;this.blocked=[...(content.map?.blocked??DEFAULT_BLOCKED)];this.stormPath=[...(content.stormPath??DEFAULT_STORM)];this.rng=seed>>>0;this.defs={...DEFAULT_DEFS};for(const k of KINDS)this.defs[k]={...DEFAULT_DEFS[k],...(content.buildingDefinitions?.[k]??{}),kind:k};}
  get day(){return this.clock.day} get funds(){return this.economy.funds}
  definition(kind:BuildingKind){return this.defs[kind]} isInside(c:Cell){return c.x>=0&&c.y>=0&&c.x<this.cols&&c.y<this.rows&&Number.isInteger(c.x)&&Number.isInteger(c.y)}
  isBlocked(c:Cell){return this.blocked.some(b=>b.x===c.x&&b.y===c.y)} buildingAt(c:Cell){return this.buildings.find(b=>b.x===c.x&&b.y===c.y)}
  mutableBuildings(){return this.buildings} mutableDisaster(){return this.disaster} mutableMetrics(){return this.metrics}
  setEconomy(v:EconomyState){this.economy=v} setUtilities(v:UtilityState){this.utilities=v} setAveragePollution(v:number){this.metrics.averagePollution=v}
  changeFunds(v:number){this.economy.funds+=v} addGrant(v:number){this.economy.grants+=v}
  emit(name:string,payload:Record<string,unknown>){this.events.push({name,payload})}

  place(kind:BuildingKind,cellOrCells:Cell|readonly Cell[]):Result {const cells=Array.isArray(cellOrCells)?cellOrCells:[cellOrCells as Cell],valid=PlacementRules.validate(kind,cells,this);if(!valid.ok)return valid;this.changeFunds(-(valid.cost??0));for(const c of cells){const d=this.defs[kind];this.buildings.push({id:`b${this.nextId++}`,kind,x:c.x,y:c.y,hp:d.maxHp,maxHp:d.maxHp,cost:d.cost,residents:0,roadConnected:false,powerCoverage:0,waterCoverage:0,pollution:0,waterBase:kind==="waterTower"?260:0,waterModifier:1,waterActual:kind==="waterTower"?260:0});}this.advanceTutorial(kind);this.recompute(["grid","economy","utilities","progression"]);return {ok:true,cost:valid.cost,affectedIds:this.buildings.slice(-cells.length).map(b=>b.id)};}
  demolish(cell:Cell):Result {const b=this.buildingAt(cell);if(!b)return{ok:false,reason:"empty"};const refund=Math.floor(b.cost*.25);this.buildings=this.buildings.filter(x=>x!==b);this.changeFunds(refund);this.recompute(["grid","economy","utilities"]);return{ok:true,cost:-refund,affectedIds:[b.id]};}
  repair(buildingId:string):Result {const b=this.buildings.find(x=>x.id===buildingId);if(!b)return{ok:false,reason:"missing"};const cost=PlacementRules.repairCost(b);if(!cost)return{ok:false,reason:"not-damaged"};if(this.funds<cost)return{ok:false,reason:"insufficient-funds",cost};this.changeFunds(-cost);this.economy.repairCosts+=cost;b.hp=b.maxHp;this.recompute(["grid","economy","utilities"]);return{ok:true,cost,affectedIds:[b.id]};}
  setTimeControl(input:{paused?:boolean;speed?:Speed}):void {if(typeof input.paused==="boolean")this.clock.paused=input.paused;if(input.speed)this.clock.speed=input.speed;this.changed(["clock"]);}
  update(realMs:number):void {if(this.clock.paused||this.ended||realMs<=0)return;this.accumulator+=realMs*this.clock.speed;while(this.accumulator>=8000&&!this.ended){this.accumulator-=8000;this.advanceDay();}this.clock.elapsedMs=this.accumulator;}
  advanceDay():void {if(this.ended)return;const previousDay=this.day;this.clock.day++;this.applyPhases();this.utilitySystem.recompute(this);this.economySystem.settle(this);this.updatePopulation();this.updateSatisfaction();this.disasterSystem.tick(this);this.utilitySystem.recompute(this);this.victorySystem.tick(this);this.emit("DayAdvanced",{day:this.day,previousDay});this.changed(["clock","grid","economy","utilities","cityMetrics","disaster","progression"]);}
  snapshot():Readonly<Snapshot>{return clone({revision:this.revision,ended:this.ended,clock:this.clock,grid:{cols:this.cols,rows:this.rows,blocked:this.blocked,buildings:this.buildings},economy:this.economy,utilities:this.utilities,cityMetrics:this.metrics,disaster:this.disaster,progression:this.progression});}
  drainEvents():readonly SimulationEvent[]{const out=this.events;this.events=[];return out;}
  isBlackout(id:string){return this.disaster.phase==="active"&&this.disaster.kind==="blackout"&&this.disaster.affectedIds.includes(id)}
  pollutionLeakAt(c:Cell){return this.disaster.phase==="active"&&this.disaster.kind==="pollutionLeak"&&this.disaster.targetCells.some(t=>dist(t,c)<=2)}
  randomInt(min:number,max:number){this.rng=(Math.imul(this.rng,1664525)+1013904223)>>>0;return min+Math.floor((this.rng/4294967296)*(max-min+1))}
  pickCells(cells:readonly Cell[],count:number){const pool=[...cells],out:Cell[]=[];while(pool.length&&out.length<count)out.push(pool.splice(this.randomInt(0,pool.length-1),1)[0]);return out}
  stormCandidates(){const near=this.buildings.filter(b=>this.stormPath.some(p=>dist(p,b)<=3)).map(b=>({x:b.x,y:b.y}));return near.length?near:this.buildings.map(b=>({x:b.x,y:b.y}))}
  preserveCriticalSources(chosen:Building[]){for(const kind of ["powerPlant","waterTower"] as const){const all=this.buildings.filter(b=>b.kind===kind&&b.hp>0),hit=chosen.filter(b=>b.kind===kind);if(all.length&&hit.length===all.length)chosen=chosen.filter(b=>b!==hit[hit.length-1]);}return chosen}
  end(result:"victory"|"bankruptcy"|"abandoned"){if(this.ended)return;this.ended=result;this.clock.paused=true;this.emit("GameEnded",{result,summary:{reason:result,finalPopulation:this.metrics.population,highestScore:this.metrics.highScore,operatingDays:this.day}})}

  private recompute(changed:SliceKey[]){this.utilitySystem.recompute(this);this.changed(changed)}
  private changed(changed:SliceKey[]){this.revision++;this.emit("SimulationChanged",{revision:this.revision,changed,snapshot:this.snapshot()})}
  private applyPhases(){this.progression.fullSettlement=this.day>=11;this.progression.commercialPollution=this.day>=25;this.progression.disastersUnlocked=this.day>=40;this.progression.aging=this.day>=90}
  private advanceTutorial(kind:BuildingKind){const order:BuildingKind[]=["road","powerPlant","waterTower","residential","commercial"];if(this.progression.tutorialIndex<5&&order[this.progression.tutorialIndex]===kind){this.progression.tutorialIndex++;this.progression.tutorialReward+=50;this.changeFunds(50);this.emit("ProgressMilestoneReached",{kind:"tutorial",value:this.progression.tutorialIndex,reward:50});}}
  private updatePopulation(){for(const b of this.buildings.filter(x=>x.kind==="residential")){const serviced=b.roadConnected&&b.powerCoverage>=.999&&b.waterCoverage>=.999&&b.hp>0;let delta=0;if(serviced&&this.metrics.satisfaction>=30)delta=this.metrics.satisfaction>=75?8:this.metrics.satisfaction>=50?5:2;else delta=-(b.pollution>50?8:5);b.residents=clamp(b.residents+delta,0,50);}this.metrics.population=this.buildings.reduce((n,b)=>n+b.residents,0)}
  private updateSatisfaction(){const homes=this.buildings.filter(b=>b.kind==="residential"),total=Math.max(1,homes.reduce((n,b)=>n+b.residents,0));const service=homes.reduce((n,b)=>n+b.residents*Math.min(b.powerCoverage,b.waterCoverage),0)/total;const commerce=this.buildings.filter(b=>b.kind==="commercial"&&b.roadConnected&&b.powerCoverage>0&&b.waterCoverage>0).length;let positive=service*2+Math.min(1,commerce/Math.max(1,this.metrics.population/60))+(this.economy.netIncome>0?.5:0);let negative=(1-service)*4+Math.max(0,(this.metrics.averagePollution-20)/15)+(this.economy.netIncome<0?Math.min(2,-this.economy.netIncome/500):0);const delta=clamp(positive-negative,-6,3);this.metrics.satisfaction=clamp(this.metrics.satisfaction+delta,0,100)}
}
