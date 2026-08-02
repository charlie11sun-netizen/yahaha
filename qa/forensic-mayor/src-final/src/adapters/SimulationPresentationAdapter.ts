import Phaser from "phaser";
import { BUILDING_CATALOG, CITY_MAP, DISASTER_CATALOG, MILESTONE_CATALOG, POPULATION_TIERS, TUTORIAL_STEPS, createInitialWorldState } from "../content";
import {
  advanceSimulationTime, createInitialSimulationState, demolishBuilding, placeBuilding,
  resolveDisasterAction, validatePlacement,
  type BuildingInstance, type BuildingKind, type Cell, type SimulationContent, type SimulationState,
} from "../domain/CitySimulation";
import { GridInteractionController, registerGameInput, type RegisteredGameInput } from "../input/GameInput";
import { CityRenderer, type OverlayCellVisual } from "../presentation/CityRenderer";
import { FeedbackController } from "../presentation/FeedbackController";
import type { BuildTool, CityHudSnapshot, DisasterNotice, OverlayKind, PlacementPreview, PresentationCommands } from "../presentation/types";
import { AccessibilityController } from "../ui/AccessibilityController";
import { CityHud } from "../ui/CityHud";

const simulationContent: SimulationContent = {
  cityMap: {
    cols: CITY_MAP.cols,
    rows: CITY_MAP.rows,
    blockedCells: [...CITY_MAP.boundaryCells, ...CITY_MAP.reservedTreeCells],
    starterRoad: CITY_MAP.starterRoadCells,
  },
  buildingCatalog: Object.fromEntries(Object.entries(BUILDING_CATALOG).map(([kind, definition]) => [kind, {
    kind: definition.kind,
    width: definition.footprint.width,
    height: definition.footprint.height,
    cost: definition.cost,
    dailyIncome: definition.dailyIncome,
    dailyMaintenance: definition.dailyMaintenance,
    powerDemand: definition.powerDemand,
    waterDemand: definition.waterDemand,
    powerCapacity: definition.powerCapacity,
    waterCapacity: definition.waterCapacity,
  }])) as SimulationContent["buildingCatalog"],
  milestones: MILESTONE_CATALOG.map(({ population, amount }) => ({ population, amount })),
};

const reasonText: Record<string, string> = {
  unknownKind: "未知设施", invalidCells: "蓝图尺寸不正确", outOfBounds: "超出城市边界",
  blocked: "边界或保留树木阻挡", overlap: "该位置已被占用", insufficientFunds: "资金不足",
  buildingLimit: "已达到160个建筑上限",
};

export class SimulationPresentationAdapter implements PresentationCommands {
  private state: SimulationState = createInitialSimulationState(simulationContent);
  private readonly renderer: CityRenderer;
  private readonly hud: CityHud;
  private readonly feedback: FeedbackController;
  private readonly accessibility: AccessibilityController;
  private readonly interaction: GridInteractionController;
  private input: RegisteredGameInput | null = null;
  private renderedIds = new Set<string>();
  private tutorialIndex = 0;
  private tutorialSkipped = false;
  private settingsVisible = false;
  private ended = false;
  private populationTier = "growth";

  constructor(private readonly scene: Phaser.Scene) {
    const world = createInitialWorldState();
    if (world.grid.length !== 24 || world.grid.some(column => column.length !== 14) || world.buildings.size !== 8) {
      throw new Error("Initial city world failed contract dimensions");
    }
    this.renderer = new CityRenderer(scene);
    this.feedback = new FeedbackController(scene);
    this.accessibility = new AccessibilityController(scene);
    this.hud = new CityHud(scene, this);
    this.interaction = new GridInteractionController(scene, {
      cols: CITY_MAP.cols,
      rows: CITY_MAP.rows,
      cellWidth: CITY_MAP.cellWidth,
      cellHeight: CITY_MAP.cellHeight,
      preview: (tool, cells) => this.preview(tool, cells),
      buildingAt: cell => this.buildingAt(cell),
      onToolSelected: ({ tool }) => this.hud.selectTool(tool),
      onPlacementRequested: payload => this.place(payload.kind, payload.cells),
      onDemolitionRequested: ({ buildingId }) => this.demolish(buildingId),
      onPreviewChanged: preview => this.renderer.showPreview(preview),
    });
  }

  create(): void {
    this.registerInput();
    this.drawWorld();
    this.renderer.setPaused(true);
    this.applyAccessibility();
    void this.accessibility.load().then(() => {
      this.input?.destroy();
      this.registerInput();
      this.applyAccessibility();
    });
    this.makeUtilityButtons();
    this.showTutorial();
    this.updateHud();
  }

  update(delta: number): void {
    if (this.ended || this.state.runPhase !== "running") return;
    const advanced = advanceSimulationTime(this.state, delta);
    if (advanced.state === this.state) return;
    this.state = advanced.state;
    for (const day of advanced.days) {
      const net = day.state.economy.dailyIncome - day.state.economy.dailyMaintenance;
      this.feedback.emit("income", { amount: net, x: 220, y: 115 });
      if (day.state.calendar.stableDays > 0) this.feedback.emit("stable-day", { x: 640, y: 82 });
      for (const milestone of day.milestonesAwarded) {
        this.feedback.emit("milestone", { message: `${milestone.population}人口补助 +¥${milestone.amount}` });
      }
      for (const warning of day.disasterWarnings) {
        this.feedback.emit("disaster-warning", { message: `${this.disasterName(warning.kind)}将在3日后发生` });
      }
      for (const change of day.disasterChanges) {
        this.feedback.emit(change.phase === "started" ? "disaster-start" : "disaster-resolved");
      }
      if (day.runEnded) this.endRun(day.runEnded);
    }
    this.drawWorld();
    this.updateHud();
    this.updateDisasterPanel();
  }

  selectTool(tool: BuildTool | null, source: "keyboard" | "pointer"): void {
    this.interaction.selectTool(tool, source);
    this.hud.selectTool(tool);
  }

  setPaused(paused?: boolean): void {
    if (this.ended) return;
    const shouldPause = paused ?? this.state.runPhase === "running";
    this.state = { ...this.state, runPhase: shouldPause ? "paused" : "running" };
    this.renderer.setPaused(shouldPause);
    this.hud.showPauseMenu(shouldPause && paused !== undefined);
    this.feedback.emit("pause", { message: shouldPause ? "模拟暂停，可继续规划" : "市政时钟继续" });
    this.updateHud();
  }

  setSpeed(speed: 1 | 2 | 3): void {
    if (this.ended) return;
    this.state = { ...this.state, runPhase: "running", calendar: { ...this.state.calendar, speed } };
    this.renderer.setPaused(false);
    this.hud.showPauseMenu(false);
    this.feedback.emit("speed", { message: `模拟速度 ${speed}倍` });
    this.updateHud();
  }

  toggleOverlay(overlay: OverlayKind): void {
    const next = this.interaction.state.overlay === overlay ? null : overlay;
    this.interaction.setOverlay(next);
    this.hud.selectOverlay(next);
    this.renderer.setOverlay(next, next ? this.overlayCells(next) : []);
  }

  cancel(): void {
    this.interaction.cancel();
    this.hud.closeInspector();
  }

  confirm(): void {
    if (this.ended) this.restart("Enter");
    else if (this.state.runPhase === "paused") this.setPaused(false);
  }

  restart(_source: "Enter" | "button"): void {
    this.scene.scene.restart();
  }

  disasterAction(actionId: string): void {
    const [action, id] = actionId.split(":");
    if (!id || (action !== "pay" && action !== "rebuild" && action !== "ignore")) return;
    const result = resolveDisasterAction(this.state, id, action);
    if (!result.ok) {
      this.feedback.emit("placement-rejected", { message: result.reason === "insufficientFunds" ? "抢修资金不足" : "当前无法处理" });
      return;
    }
    this.state = result.state;
    this.feedback.emit(result.remainingDays === 0 ? "disaster-resolved" : "network-connected", { message: `已支付 ¥${result.cost}` });
    this.drawWorld();
    this.updateHud();
    this.updateDisasterPanel();
  }

  destroy(): void {
    this.input?.destroy();
    this.interaction.destroy();
  }

  private registerInput(): void {
    this.input = registerGameInput(this.scene, this, this.accessibility.bindings);
  }

  private preview(tool: BuildTool, cells: readonly Cell[]): PlacementPreview {
    if (tool === "demolish") return { cells: [...cells], legal: true };
    const kind = tool as BuildingKind;
    const requestCells = kind === "road" ? this.unoccupied(cells) : this.footprint(cells[0], kind);
    if (requestCells.length === 0) return { cells: [...cells], legal: false, reason: "道路已存在", cost: 0 };
    const result = validatePlacement(this.state, { kind, cells: requestCells });
    return { cells: result.cells.length ? result.cells : requestCells, legal: result.ok, reason: result.reason ? reasonText[result.reason] : undefined, cost: result.cost };
  }

  private place(kind: BuildingKind, cells: readonly Cell[]): void {
    const requestCells = kind === "road" ? this.unoccupied(cells) : cells;
    if (requestCells.length === 0) return;
    const result = placeBuilding(this.state, { kind, cells: requestCells });
    if (!result.ok) {
      this.feedback.emit("placement-rejected", { message: reasonText[result.reason ?? ""] ?? "无法建设" });
      this.hud.showToast(reasonText[result.reason ?? ""] ?? "无法建设", "danger");
      return;
    }
    this.state = result.state;
    const first = result.cells[0];
    this.feedback.emit("placement-ok", { x: (first.x + 0.5) * CITY_MAP.cellWidth, y: (first.y + 0.5) * CITY_MAP.cellHeight, message: `建设完成 -¥${result.cost}` });
    if (result.changedNetworks.length) this.feedback.emit("network-connected");
    this.advanceTutorial(kind);
    this.drawWorld();
    this.updateHud();
  }

  private demolish(buildingId: string): void {
    const result = demolishBuilding(this.state, buildingId);
    if (!result.ok) return;
    this.state = result.state;
    this.feedback.emit("placement-ok", { message: `拆除完成 +¥${result.refund}` });
    if (result.disconnectedBuildingIds.length) this.hud.showToast(`${result.disconnectedBuildingIds.length}座建筑失去道路连接`, "warning");
    this.drawWorld();
    this.updateHud();
  }

  private drawWorld(): void {
    const roads: Cell[] = [];
    const nextIds = new Set<string>();
    for (const tree of CITY_MAP.reservedTreeCells) {
      const id = `tree:${tree.x},${tree.y}`;
      nextIds.add(id);
      this.renderer.upsertBuilding({ id, kind: "tree", cell: tree, width: 1, height: 1 });
    }
    for (const building of this.state.buildings.values()) {
      if (building.kind === "road") { roads.push(building.cells[0]); continue; }
      nextIds.add(building.id);
      this.renderer.upsertBuilding(this.visual(building));
    }
    for (const id of this.renderedIds) if (!nextIds.has(id)) this.renderer.removeBuilding(id);
    this.renderedIds = nextIds;
    this.renderer.setRoadCells(roads);
    this.renderer.clearVehicles();
    for (const road of roads.slice(0, 12)) this.renderer.addVehicle(road, 0);
    this.renderer.setPaused(this.state.runPhase !== "running");
    if (this.interaction.state.overlay) this.renderer.setOverlay(this.interaction.state.overlay, this.overlayCells(this.interaction.state.overlay));
    this.renderer.showRiskLinks(this.riskSources());
  }

  private visual(building: BuildingInstance) {
    const origin = building.cells.reduce((best, cell) => cell.x < best.x || cell.y < best.y ? cell : best, building.cells[0]);
    const pollution = building.kind === "home" ? this.pollutionAt(building) : "none";
    const disaster = this.state.activeDisasters.find(item => item.affectedIds.includes(building.id));
    const definition = BUILDING_CATALOG[building.kind];
    return {
      id: building.id, kind: building.kind, cell: origin,
      width: definition.footprint.width, height: definition.footprint.height,
      connected: building.connectedToRoad, powered: building.powered, watered: building.watered,
      operating: building.operating, pollution, disaster: disaster ? this.disasterName(disaster.kind) : null,
    } as const;
  }

  private updateHud(): void {
    const tier = POPULATION_TIERS.find(item => this.state.cityMetrics.population >= item.minPopulation && (item.maxPopulation === null || this.state.cityMetrics.population <= item.maxPopulation));
    if (tier && tier.id !== this.populationTier) {
      this.populationTier = tier.id;
      this.hud.showToast(tier.id === "metropolis" ? "都会阶段：维护费与后期灾害压力上升" : "扩张阶段：公用需求、商业收益和污染影响上升", "warning", 3200);
    }
    this.hud.update(this.snapshot());
  }

  private snapshot(): CityHudSnapshot {
    return {
      day: this.state.calendar.day, stableDays: this.state.calendar.stableDays, speed: this.state.calendar.speed,
      paused: this.state.runPhase !== "running",
      economy: this.state.economy,
      metrics: this.state.cityMetrics,
      bankruptcyDays: this.state.failureClocks.bankruptcyDays,
      abandonmentDays: this.state.failureClocks.abandonmentDays,
    };
  }

  private updateDisasterPanel(): void {
    const disaster = this.state.activeDisasters[0];
    if (!disaster) { this.hud.showDisaster(null); return; }
    const definition = this.disasterDefinition(disaster.kind);
    const notice: DisasterNotice = {
      id: disaster.id,
      title: `${definition.name}${disaster.phase === "warning" ? "预警" : ""}`,
      detail: definition.description,
      remainingDays: disaster.phase === "warning" ? disaster.warningDays : disaster.remainingDays,
      actions: disaster.phase === "active" && disaster.actionCost > 0 ? [
        { id: `${disaster.kind === "pipeBreak" ? "rebuild" : "pay"}:${disaster.id}`, label: `处理 ¥${disaster.actionCost}`, enabled: this.state.economy.funds >= disaster.actionCost },
        { id: `ignore:${disaster.id}`, label: "暂不处理" },
      ] : undefined,
    };
    this.hud.showDisaster(notice);
  }

  private endRun(outcome: NonNullable<SimulationState["outcome"]>): void {
    if (this.ended) return;
    this.ended = true;
    this.renderer.setPaused(true);
    this.feedback.emit(outcome === "victory" ? "victory" : "defeat", { severe: true });
    this.scene.time.delayedCall(650, () => this.scene.scene.start("GameOverScene", {
      outcome,
      score: this.state.finalScore ?? 0,
      day: this.state.calendar.day,
      population: this.state.cityMetrics.population,
      satisfaction: this.state.cityMetrics.satisfaction,
      cityScore: this.state.cityMetrics.score,
    }));
  }

  private makeUtilityButtons(): void {
    const settings = this.scene.add.text(1228, 108, "⚙ 设置", { fontFamily: "Inter, system-ui, sans-serif", fontSize: "16px", color: "#ffffff", backgroundColor: "#132238", padding: { x: 8, y: 5 } })
      .setOrigin(1, 0).setDepth(230).setInteractive({ useHandCursor: true });
    settings.on("pointerdown", () => {
      this.settingsVisible = !this.settingsVisible;
      this.hud.showSettingsMenu(this.accessibility.settings, patch => {
        void this.accessibility.updateSettings(patch).then(() => this.applyAccessibility());
      }, this.settingsVisible);
    });
    const skip = this.scene.add.text(18, 108, "跳过教学", { fontFamily: "Inter, system-ui, sans-serif", fontSize: "16px", color: "#ffffff", backgroundColor: "#3d78a8", padding: { x: 8, y: 5 } })
      .setDepth(230).setInteractive({ useHandCursor: true });
    skip.on("pointerdown", () => { this.tutorialSkipped = true; skip.destroy(); this.hud.showToast("教学已跳过，可自由规划", "info"); });
  }

  private showTutorial(): void {
    if (this.tutorialSkipped || this.tutorialIndex >= TUTORIAL_STEPS.length || this.state.calendar.day > 20) return;
    const step = TUTORIAL_STEPS[this.tutorialIndex];
    this.hud.showToast(`教学 ${step.order}/4：${step.title}\n${step.instruction}`, "info", 4200);
    this.selectTool(step.tool, "pointer");
  }

  private advanceTutorial(kind: BuildingKind): void {
    if (this.tutorialSkipped || this.tutorialIndex >= TUTORIAL_STEPS.length) return;
    const step = TUTORIAL_STEPS[this.tutorialIndex];
    if (kind !== step.completion.buildingKind) return;
    const completed = [...this.state.buildings.values()].some(building => building.kind === kind && building.connectedToRoad);
    if (!completed) return;
    this.tutorialIndex += 1;
    if (this.tutorialIndex >= TUTORIAL_STEPS.length) this.hud.showToast("四步教学完成：启动时间，让城市成长！", "success", 3500);
    else this.showTutorial();
  }

  private applyAccessibility(): void {
    const settings = this.accessibility.settings;
    this.hud.setAccessibility(settings);
    this.renderer.setReducedMotion(settings.reducedMotion);
    this.feedback.setReducedMotion(settings.reducedMotion);
  }

  private overlayCells(kind: OverlayKind): OverlayCellVisual[] {
    const result: OverlayCellVisual[] = [];
    for (const building of this.state.buildings.values()) {
      for (const cell of building.cells) {
        let status: OverlayCellVisual["status"] = "ok";
        let label = "";
        if (kind === "road") { status = building.connectedToRoad ? "ok" : "danger"; label = building.connectedToRoad ? "已连接" : "断路"; }
        else if (kind === "power") { status = building.powered ? "ok" : "danger"; label = building.powered ? "有电" : "缺电"; }
        else if (kind === "water") { status = building.watered ? "ok" : "danger"; label = building.watered ? "有水" : "缺水"; }
        else { const pollution = this.pollutionAt(building); status = pollution === "strong" ? "danger" : pollution === "weak" ? "warning" : "inactive"; label = pollution === "none" ? "清洁" : pollution === "strong" ? "强污染" : "污染"; }
        result.push({ cell, status, label });
      }
    }
    return result;
  }

  private riskSources(): Cell[] {
    const risky = [...this.state.buildings.values()].filter(building => building.kind !== "road" && (!building.connectedToRoad || !building.powered || !building.watered || this.pollutionAt(building) !== "none"));
    return risky.map(building => building.cells[0]);
  }

  private pollutionAt(building: BuildingInstance): "none" | "weak" | "strong" {
    if (building.kind !== "home") return "none";
    let best = Infinity;
    for (const plant of this.state.buildings.values()) if (plant.kind === "power") {
      for (const a of building.cells) for (const b of plant.cells) best = Math.min(best, Math.abs(a.x - b.x) + Math.abs(a.y - b.y));
    }
    return best <= 2 ? "strong" : best <= 5 ? "weak" : "none";
  }

  private footprint(origin: Cell | undefined, kind: BuildingKind): Cell[] {
    if (!origin) return [];
    const definition = BUILDING_CATALOG[kind];
    const cells: Cell[] = [];
    for (let y = 0; y < definition.footprint.height; y += 1) for (let x = 0; x < definition.footprint.width; x += 1) cells.push({ x: origin.x + x, y: origin.y + y });
    return cells;
  }

  private unoccupied(cells: readonly Cell[]): Cell[] {
    return cells.filter(cell => !this.buildingAt(cell));
  }

  private buildingAt(cell: Cell): string | null {
    for (const building of this.state.buildings.values()) if (building.cells.some(candidate => candidate.x === cell.x && candidate.y === cell.y)) return building.id;
    return null;
  }

  private disasterName(kind: string): string { return this.disasterDefinition(kind).name; }
  private disasterDefinition(kind: string) {
    const key = kind === "facilityFailure" ? "facility_failure" : kind === "pipeBreak" ? "water_main_break" : kind;
    return DISASTER_CATALOG[key as keyof typeof DISASTER_CATALOG];
  }
}

export function restartRun(scene: Phaser.Scene): void { scene.scene.restart(); }
