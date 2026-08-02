import { CITY_CATALOG } from "../content/CityContent";
import type { CoverageCellPresentation } from "../presentation/CoverageOverlayView";
import type {
  BuildingPresentation, CityHudSnapshot, DemolitionPreview, OutcomePresentation,
} from "../presentation/CityPresentationTypes";
import type { SimulationState, StructureState } from "../domain/CitySimulation";
import { LEVEL_LAYOUT } from "../levels/CityLevel";

const disasterCost = (type: "fire" | "blackout" | "pipeBurst"): number => type === "fire" ? 80 : type === "blackout" ? 70 : 60;

export function toCityHudSnapshot(state: SimulationState): CityHudSnapshot {
  const b = state.cityMetrics.breakdown;
  const d = state.disaster;
  const conditions = {
    population: state.population.total >= 20,
    score: state.cityMetrics.score >= 80,
    solvent: state.economy.funds >= 0,
    power: state.networks.powerCoverage >= 90,
    water: state.networks.waterCoverage >= 90,
    satisfaction: state.cityMetrics.satisfaction >= 70,
  };
  const danger = state.outcome.insolvencySeconds > 0
    ? { kind: "debt" as const, seconds: state.outcome.insolvencySeconds, reason: "资金低于−¥500" }
    : state.outcome.dissatisfactionSeconds > 0
      ? { kind: "satisfaction" as const, seconds: state.outcome.dissatisfactionSeconds, reason: "满意度低于10%" }
      : undefined;
  return {
    funds: state.economy.funds,
    population: state.population.total,
    netIncome: state.economy.netIncome,
    satisfaction: state.cityMetrics.satisfaction,
    pollution: state.cityMetrics.pollutedResidenceRatio,
    score: state.cityMetrics.score,
    speed: state.session.speed,
    paused: state.session.paused,
    gameSeconds: state.session.gameSeconds,
    month: state.session.month,
    scoreParts: [
      { label: "人口", value: b.population, max: 25, icon: "♟" },
      { label: "财政", value: b.finance, max: 20, icon: "¥" },
      { label: "双服务", value: b.services, max: 20, icon: "⚡" },
      { label: "满意度", value: b.satisfaction, max: 25, icon: "☺" },
      { label: "低污染", value: b.pollution, max: 10, icon: "▧" },
    ],
    penaltyReasons: state.cityMetrics.topPenalties,
    prosperitySeconds: state.outcome.prosperitySeconds,
    prosperityConditions: [
      { label: "人口", met: conditions.population, current: String(state.population.total), target: "20" },
      { label: "评分", met: conditions.score, current: String(Math.round(state.cityMetrics.score)), target: "80" },
      { label: "资金", met: conditions.solvent, current: state.economy.funds >= 0 ? "✓" : "×", target: "≥0" },
      { label: "电", met: conditions.power, current: `${Math.round(state.networks.powerCoverage)}%`, target: "90%" },
      { label: "水", met: conditions.water, current: `${Math.round(state.networks.waterCoverage)}%`, target: "90%" },
      { label: "满意", met: conditions.satisfaction, current: `${Math.round(state.cityMetrics.satisfaction)}%`, target: "70%" },
    ],
    danger,
    voucherAvailable: state.resilienceVoucher,
    disaster: d ? {
      id: d.id,
      type: d.type,
      targetName: state.structures.get(d.targetId)?.id ?? d.targetId,
      warning: d.phase === "warning",
      remainingSeconds: d.phase === "warning" ? d.warningRemaining : d.remaining,
      totalSeconds: d.phase === "warning" ? 5 : 30,
      dispatchCost: Math.ceil(disasterCost(d.type) * (state.resilienceVoucher ? 0.5 : 1)),
      affordable: state.economy.funds >= Math.ceil(disasterCost(d.type) * (state.resilienceVoucher ? 0.5 : 1)),
    } : undefined,
  };
}

export function toBuildingPresentation(state: SimulationState, structure: StructureState): BuildingPresentation {
  const def = CITY_CATALOG[structure.tool];
  const isConsumer = structure.tool === "residential" || structure.tool === "commercial";
  const pollution = structure.tool === "powerPlant" ? def.pollutionStrength : 0;
  return {
    id: structure.id,
    name: def.name,
    kind: structure.tool,
    cost: def.cost,
    maintenance: def.maintenance,
    roadConnected: structure.roadConnected,
    power: { used: def.powerDemand, capacity: structure.tool === "powerPlant" ? def.powerCapacity : state.networks.capacity.powerSupply, covered: !isConsumer || structure.powered, distance: structure.powerDistance ?? undefined },
    water: { used: def.waterDemand, capacity: structure.tool === "waterTower" ? def.waterCapacity : state.networks.capacity.waterSupply, covered: !isConsumer || structure.watered, distance: structure.waterDistance ?? undefined },
    population: structure.tool === "residential" ? structure.population : undefined,
    populationCapacity: structure.tool === "residential" ? def.maxPopulation : undefined,
    jobs: structure.tool === "commercial" ? structure.employees : undefined,
    jobCapacity: structure.tool === "commercial" ? def.jobs : undefined,
    pollution,
    satisfactionImpact: structure.disabled ? -20 : structure.powered && structure.watered ? 5 : isConsumer ? -10 : 0,
    statusText: structure.disabled ? "灾害停用" : !structure.roadConnected ? "道路中断" : isConsumer && (!structure.powered || !structure.watered) ? "等待双服务" : "运行正常",
  };
}

export function toOutcomePresentation(state: SimulationState): OutcomePresentation | null {
  if (!state.outcome.kind || !state.outcome.reason) return null;
  const stats = state.outcome.stats;
  return { kind: state.outcome.kind, reason: state.outcome.reason, stats: { population: stats.population, peakPopulation: stats.peakPopulation, totalTax: stats.cumulativeTax, disastersHandled: stats.disastersHandled, peakScore: stats.highestScore, operatingSeconds: stats.operatingSeconds } };
}

export function toCoverageCells(state: SimulationState, overlay: "power" | "water" | "pollution"): CoverageCellPresentation[] {
  const structures = [...state.structures.values()];
  const plants = structures.filter((s) => s.tool === "powerPlant");
  return LEVEL_LAYOUT.cells.map((cell) => {
    if (overlay === "pollution") {
      const distance = plants.length ? Math.min(...plants.map((p) => Math.abs(p.anchor.x - cell.x) + Math.abs(p.anchor.y - cell.y))) : Infinity;
      return { x: cell.x, y: cell.y, covered: distance <= 3, strength: distance <= 3 ? (4 - distance) / 4 : 0 };
    }
    const occupants = structures.filter((s) => s.cells.some((c) => c.x === cell.x && c.y === cell.y));
    const covered = occupants.some((s) => overlay === "power" ? s.powered || s.tool === "powerPlant" : s.watered || s.tool === "waterTower");
    return { x: cell.x, y: cell.y, covered, strength: covered ? 1 : 0 };
  });
}

export function toDemolitionPreview(state: SimulationState, structureId: string): DemolitionPreview {
  const structure = state.structures.get(structureId);
  if (!structure) return { structureId, name: "未知建筑", refund: 0, affectedBuildingCount: 0 };
  const def = CITY_CATALOG[structure.tool];
  const affected = structure.tool === "road" ? state.networks.affectedIds.length : 0;
  return { structureId, name: def.name, refund: Math.floor(def.cost * 0.4), affectedBuildingCount: affected, affectedLabels: affected ? ["道路/服务网络将立即重算"] : [] };
}
