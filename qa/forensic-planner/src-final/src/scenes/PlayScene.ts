import Phaser from "phaser";
import { BUILDING_DEFINITIONS, CITY_MAP, TUTORIAL_STEPS, VISUAL_CATALOG } from "../content/CityContent";
import { CitySimulation, PlacementRules } from "../domain/CitySimulation";
import { InputController } from "../input/InputController";
import { CityRenderer } from "../presentation/CityRenderer";
import { FeedbackController } from "../presentation/FeedbackController";
import { OverlayRenderer } from "../presentation/OverlayRenderer";
import { AccessibilityController } from "../ui/AccessibilityController";
import { HudController } from "../ui/Hud";
import { gameConfig, sheetFrame } from "../config/gameConfig";
import { Probe } from "../systems/Probe";
import { SimulationPresentationAdapter } from "../adapters/SimulationPresentationAdapter";
import { GameCoordinator } from "../composition/GameCoordinator";

type Tool = "road" | "residential" | "commercial" | "powerPlant" | "waterTower" | "demolish" | null;
type BuildTool = Exclude<Tool, "demolish" | null>;
type Overlay = "power" | "water" | "pollution" | null;
type Cell = { x: number; y: number };
type Snapshot = ReturnType<CitySimulation["snapshot"]>;
type SimBuilding = Snapshot["grid"]["buildings"][number];

const MAP_TOP = 96;
const MAP_BOTTOM = 612;
const MAP_HEIGHT = MAP_BOTTOM - MAP_TOP;

/** CityScene implementation: lifecycle and orchestration only; rules and presentation remain role-owned. */
export class PlayScene extends Phaser.Scene {
  private simulation!: CitySimulation;
  private coordinator!: GameCoordinator;
  private city!: CityRenderer;
  private overlays!: OverlayRenderer;
  private hud!: HudController;
  private inputController!: InputController;
  private feedback!: FeedbackController;
  private accessibility!: AccessibilityController;
  private presentation!: SimulationPresentationAdapter<Snapshot>;
  private selectedId: string | null = null;
  private activeTool: Tool = null;
  private activeOverlay: Overlay = null;
  private lastRevision = -1;
  private lastSnapshot!: Snapshot;
  private lastPopulation = 0;
  private lastStars = 1;
  private destroyed = false;

  constructor() { super("PlayScene"); }

  create(): void {
    this.destroyed = false;
    this.cameras.main.setBackgroundColor(gameConfig.palette.bg);
    this.simulation = this.createSimulation();
    this.coordinator = new GameCoordinator(this.simulation);
    this.presentation = new SimulationPresentationAdapter((snapshot, changed) => this.present(snapshot, changed));
    this.drawAuthoredScenery();
    this.drawTutorialGuide();

    const renderOptions = {
      cols: CITY_MAP.grid.cols,
      rows: CITY_MAP.grid.rows,
      originX: 0,
      originY: MAP_TOP,
      width: this.scale.width,
      height: MAP_HEIGHT,
      drawBackdrop: true,
    };
    this.city = new CityRenderer(this, renderOptions);
    this.overlays = new OverlayRenderer(this, { ...renderOptions, depth: 30 });
    this.feedback = new FeedbackController(this);
    this.accessibility = new AccessibilityController(this);

    this.hud = new HudController(this, {
      onTool: (tool) => this.inputController.selectTool(tool),
      onPause: () => this.inputController.togglePause(),
      onSpeed: (speed) => this.inputController.requestSpeed(speed),
      onOverlay: (overlay) => this.setOverlay(this.activeOverlay === overlay ? null : overlay),
      onRepair: () => this.repairSelected(),
      onAlertLocate: () => this.locateAlert(),
      onRestart: () => this.resetGameSession(),
    });

    this.inputController = new InputController(this, {
      worldToCell: (x, y) => y >= MAP_TOP && y < MAP_BOTTOM ? this.city.cellAtWorld(x, y) : null,
      onToolSelected: (tool) => {
        this.activeTool = tool;
        this.hud.updateInteraction(tool, this.activeOverlay);
        if (tool) this.hud.hideDetails();
      },
      onPlacementRequested: (request) => this.place(request.tool, request.dragCells ?? [request.cell]),
      onDemolitionRequested: ({ cell }) => this.demolish(cell),
      onSelectionRequested: ({ cell }) => this.selectCell(cell),
      onTimeControlRequested: (request) => this.coordinator.setTimeControl(request),
      onHoverChanged: (hover) => this.preview(hover.tool, hover.dragCells ?? (hover.cell ? [hover.cell] : [])),
      onCancel: () => {
        this.selectedId = null;
        this.city.setSelection(null);
        this.hud.hideDetails();
      },
    });

    this.lastSnapshot = this.simulation.snapshot();
    this.presentation.push({ revision: this.lastSnapshot.revision, snapshot: this.lastSnapshot, changed: ["clock", "grid", "economy", "utilities", "cityMetrics", "disaster", "progression"] });
    this.createDecorativeTraffic();
    this.accessibility.announce("规划局已开放。先按R或点击道路，沿白色引导线铺设道路；空格可暂停规划。", "polite", 4800);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.shutdown());
  }

  update(_time: number, delta: number): void {
    this.coordinator.update(delta);
    this.consumeEvents();
  }

  /** Contract-named clean-session entry point. */
  resetGameSession(): void {
    this.scene.restart();
  }

  private createSimulation(): CitySimulation {
    const blocked: Cell[] = [];
    for (const wall of CITY_MAP.walls) {
      const [left, top, right, bottom] = wall.cells;
      for (let y = top; y <= bottom; y += 1) for (let x = left; x <= right; x += 1) blocked.push({ x, y });
    }
    blocked.push(...CITY_MAP.cover.map(({ cell }) => ({ x: cell[0], y: cell[1] })));
    const definitions = Object.fromEntries(Object.values(BUILDING_DEFINITIONS).map((definition) => {
      const authored = definition as typeof definition & { electricityCapacity?: number; waterCapacity?: number; populationCapacity?: number };
      return [definition.id, {
        kind: definition.id,
        cost: definition.buildCost,
        maintenance: definition.dailyMaintenance,
        maxHp: definition.maxHealth,
        capacity: authored.electricityCapacity ?? authored.waterCapacity ?? authored.populationCapacity,
      }];
    }));
    return new CitySimulation({
      map: { cols: CITY_MAP.grid.cols, rows: CITY_MAP.grid.rows, blocked },
      buildingDefinitions: definitions,
      disasterDefinitions: undefined,
      tutorialSteps: TUTORIAL_STEPS,
      phaseSchedule: undefined,
      stormPath: CITY_MAP.paths.find((path) => path.id === "major_storm_track")?.points.map(([x, y]) => ({ x, y })),
    }, 0x51f15e);
  }

  private place(tool: BuildTool, cells: Cell[]): void {
    const result = this.coordinator.place(tool, cells);
    const at = this.city.cellCenter(cells[cells.length - 1]);
    if (!result.ok) {
      this.feedback.illegal(at, this.reasonText(result.reason));
      this.accessibility.describeBlocked("建造", [this.reasonText(result.reason)]);
      return;
    }
    this.feedback.built(at);
    if (tool === "road" && cells.length > 1) this.feedback.connection(at);
    this.consumeEvents();
  }

  private demolish(cell: Cell): void {
    const result = this.coordinator.demolish(cell);
    const at = this.city.cellCenter(cell);
    if (!result.ok) {
      this.feedback.illegal(at, this.reasonText(result.reason));
      return;
    }
    this.selectedId = null;
    this.hud.hideDetails();
    this.feedback.connection(at);
    this.consumeEvents();
  }

  private repairSelected(): void {
    if (!this.selectedId) return;
    const building = this.lastSnapshot.grid.buildings.find((item) => item.id === this.selectedId);
    if (!building) return;
    const result = this.coordinator.repair(this.selectedId);
    const at = this.city.cellCenter({ x: building.x, y: building.y });
    if (result.ok) this.feedback.repaired(at);
    else this.feedback.illegal(at, this.reasonText(result.reason));
    this.consumeEvents();
  }

  private preview(tool: Tool, cells: Cell[]): void {
    if (!tool || tool === "demolish" || cells.length === 0) {
      this.city.setPreview(null);
      return;
    }
    const result = PlacementRules.validate(tool, cells, this.simulation);
    this.city.setPreview({ tool, cells, legal: result.ok, reason: this.reasonText(result.reason), cost: result.cost });
  }

  private selectCell(cell: Cell | null): void {
    const building = cell ? this.lastSnapshot.grid.buildings.find((item) => item.x === cell.x && item.y === cell.y) : undefined;
    this.selectedId = building?.id ?? null;
    this.city.setSelection(building ? { x: building.x, y: building.y } : null);
    if (!building) {
      this.hud.hideDetails();
      return;
    }
    this.showDetails(building);
  }

  private showDetails(building: SimBuilding): void {
    const definition = BUILDING_DEFINITIONS[building.kind];
    const repairCost = building.hp >= building.maxHp ? 0 : Math.max(20, Math.ceil(building.cost * (1 - building.hp / building.maxHp) * 0.4));
    const causes = [!building.roadConnected && building.kind !== "road" ? "连接道路" : "", building.powerCoverage < 1 && (building.kind === "residential" || building.kind === "commercial") ? "补充电力" : "", building.waterCoverage < 1 && (building.kind === "residential" || building.kind === "commercial") ? "补充供水" : ""].filter(Boolean);
    this.hud.showDetails({
      title: definition.name,
      roadConnected: building.kind === "road" || building.roadConnected,
      power: `${Math.round(building.powerCoverage * 100)}%`,
      water: `${Math.round(building.waterCoverage * 100)}%`,
      pollution: building.pollution,
      capacity: building.kind === "residential" ? `${building.residents}/50居民` : building.kind === "powerPlant" ? "300电" : building.kind === "waterTower" ? `${Math.round(building.waterActual)}/260水` : building.kind === "commercial" ? "120/日满负荷" : "道路网络",
      maintenance: definition.dailyMaintenance * (this.lastSnapshot.clock.day >= 90 && (building.kind === "powerPlant" || building.kind === "waterTower") ? 1.25 : 1),
      health: building.hp,
      maxHealth: building.maxHp,
      repairCost,
      waterBaseCapacity: building.kind === "waterTower" ? building.waterBase : undefined,
      waterPollutionModifier: building.kind === "waterTower" ? building.waterModifier : undefined,
      waterActualCapacity: building.kind === "waterTower" ? building.waterActual : undefined,
      actionableCause: causes.join("；"),
      canRepair: repairCost > 0 && this.lastSnapshot.economy.funds >= repairCost,
    });
  }

  private setOverlay(overlay: Overlay): void {
    this.activeOverlay = overlay;
    this.overlays.setOverlay(overlay);
    this.hud.updateInteraction(this.activeTool, overlay);
    this.accessibility.announceOverlay(overlay);
  }

  private locateAlert(): void {
    const cell = this.lastSnapshot.disaster.targetCells[0];
    if (cell) this.city.focusCell(cell, "灾害目标");
  }

  private consumeEvents(): void {
    for (const event of this.simulation.drainEvents()) {
      if (event.name === "SimulationChanged") {
        const payload = event.payload as unknown as { changed: string[]; snapshot: Snapshot };
        this.presentation.push({ revision: payload.snapshot.revision, snapshot: payload.snapshot, changed: payload.changed });
      } else if (event.name === "DisasterTelegraphed") {
        const payload = event.payload as unknown as { kind: "fire" | "blackout" | "pollutionLeak" | "storm" | "majorStorm"; targetCells: Cell[]; daysRemaining: number };
        this.feedback.disasterAlert(payload.kind, payload.daysRemaining);
        this.hud.showAlert(`${payload.kind === "majorStorm" ? "大型风暴" : "灾害"}将在${payload.daysRemaining}日后影响${payload.targetCells.length}处设施`);
        this.accessibility.announce("灾害预警已发布，可暂停并点击定位查看目标。", "assertive");
      } else if (event.name === "DisasterResolved") {
        this.hud.hideAlert();
      } else if (event.name === "ProgressMilestoneReached") {
        const payload = event.payload as unknown as { kind: "tutorial" | "grant" | "star" | "stability"; value: number; reward?: number };
        this.feedback.milestone(payload.kind, payload.value, payload.reward);
      } else if (event.name === "GameEnded") {
        const payload = event.payload as unknown as { result: "victory" | "bankruptcy" | "abandoned"; summary: { finalPopulation: number; highestScore: number; operatingDays: number } };
        this.feedback.gameEnded(payload.result);
        this.hud.showOutcome(payload.result, { population: payload.summary.finalPopulation, highestScore: payload.summary.highestScore, days: payload.summary.operatingDays });
      }
    }
  }

  private present(snapshot: Snapshot, changed: readonly string[]): void {
    if (snapshot.revision === this.lastRevision && this.lastRevision >= 0) return;
    const previous = this.lastSnapshot;
    this.lastRevision = snapshot.revision;
    this.lastSnapshot = snapshot;
    this.inputController?.setTimeState(snapshot.clock.paused, snapshot.clock.speed);

    if (changed.includes("grid") || changed.includes("utilities") || changed.includes("cityMetrics")) {
      this.city.updateCity({
        revision: snapshot.revision,
        roads: snapshot.grid.buildings.filter((building) => building.kind === "road").map((building) => ({ x: building.x, y: building.y })),
        buildings: snapshot.grid.buildings.filter((building) => building.kind !== "road").map((building) => ({
          id: building.id, kind: building.kind, cell: { x: building.x, y: building.y }, health: building.hp, maxHealth: building.maxHp,
          occupancy: building.residents, powered: building.kind === "powerPlant" || building.kind === "waterTower" || building.powerCoverage > 0,
          watered: building.kind === "powerPlant" || building.kind === "waterTower" || building.waterCoverage > 0,
          roadConnected: building.roadConnected, pollution: building.pollution, waterModifier: building.waterModifier,
        })),
      });
      this.overlays.update(this.overlaySnapshot(snapshot));
    }

    this.hud.updateSimulation(changed, {
      clock: snapshot.clock,
      economy: { ...snapshot.economy, bankruptcyDays: snapshot.cityMetrics.bankruptcyDays },
      utilities: { ...snapshot.utilities, blockedCauses: this.blockedCauses(snapshot) },
      cityMetrics: {
        population: snapshot.cityMetrics.population,
        pollution: snapshot.cityMetrics.averagePollution,
        happiness: snapshot.cityMetrics.satisfaction,
        score: snapshot.cityMetrics.score,
        stars: snapshot.cityMetrics.stars,
        stabilityDays: snapshot.cityMetrics.stableDays,
        abandonmentDays: snapshot.cityMetrics.abandonmentDays,
      },
    });
    this.updateAvailability(snapshot);

    if (previous) {
      const populationDelta = snapshot.cityMetrics.population - this.lastPopulation;
      if (populationDelta !== 0) {
        const home = snapshot.grid.buildings.find((building) => building.kind === "residential");
        if (home) this.feedback.residents(this.city.cellCenter({ x: home.x, y: home.y }), populationDelta);
      }
      if (snapshot.cityMetrics.stars > this.lastStars) this.feedback.milestone("star", snapshot.cityMetrics.stars);
    }
    this.lastPopulation = snapshot.cityMetrics.population;
    this.lastStars = snapshot.cityMetrics.stars;
    if (this.selectedId) {
      const selected = snapshot.grid.buildings.find((building) => building.id === this.selectedId);
      if (selected) this.showDetails(selected); else this.hud.hideDetails();
    }
  }

  private overlaySnapshot(snapshot: Snapshot): Parameters<OverlayRenderer["update"]>[0] {
    const cells: Cell[] = [];
    for (let y = 0; y < CITY_MAP.grid.rows; y += 1) for (let x = 0; x < CITY_MAP.grid.cols; x += 1) cells.push({ x, y });
    const plants = snapshot.grid.buildings.filter((building) => building.kind === "powerPlant" && building.roadConnected && building.hp > 0);
    const traffic = snapshot.clock.day >= 25 ? snapshot.grid.buildings.filter((building) => building.kind === "commercial" && building.roadConnected && building.hp > 0).length * 1.5 : 0;
    const pollutionAt = (cell: Cell): number => traffic + plants.reduce((sum, plant) => sum + Math.max(0, 28 - (Math.abs(cell.x - plant.x) + Math.abs(cell.y - plant.y)) * 4) * (plant.hp / plant.maxHp), 0);
    return {
      revision: snapshot.revision,
      power: cells.map((cell) => ({ ...cell, value: snapshot.utilities.powerCoverage * 100, disconnected: snapshot.utilities.powerCoverage < 1, source: plants.some((plant) => plant.x === cell.x && plant.y === cell.y) ? "power" as const : undefined })),
      water: cells.map((cell) => ({ ...cell, value: snapshot.utilities.waterCoverage * 100, disconnected: snapshot.utilities.waterCoverage < 1, source: snapshot.grid.buildings.some((building) => building.kind === "waterTower" && building.x === cell.x && building.y === cell.y) ? "water" as const : undefined })),
      pollution: cells.map((cell) => ({ ...cell, value: pollutionAt(cell), source: plants.some((plant) => plant.x === cell.x && plant.y === cell.y) ? "pollution" as const : undefined })),
      towers: snapshot.grid.buildings.filter((building) => building.kind === "waterTower").map((tower) => ({ id: tower.id, cell: { x: tower.x, y: tower.y }, baseCapacity: tower.waterBase, pollutionModifier: tower.waterModifier, actualCapacity: tower.waterActual })),
    };
  }

  private blockedCauses(snapshot: Snapshot): string[] {
    const causes: string[] = [];
    if (snapshot.utilities.powerDemand > snapshot.utilities.powerSupply) causes.push("电力不足");
    if (snapshot.utilities.waterDemand > snapshot.utilities.waterSupply) causes.push("供水不足");
    if (snapshot.cityMetrics.averagePollution >= 35) causes.push("污染须低于35");
    return causes;
  }

  private updateAvailability(snapshot: Snapshot): void {
    for (const tool of ["road", "residential", "commercial", "powerPlant", "waterTower"] as const) {
      const cost = BUILDING_DEFINITIONS[tool].buildCost;
      this.hud.setToolAvailability(tool, snapshot.economy.funds >= cost, snapshot.economy.funds >= cost ? "" : `资金不足：需要$${cost}`);
    }
    this.hud.setToolAvailability("demolish", true);
  }

  private drawAuthoredScenery(): void {
    const cellWidth = this.scale.width / CITY_MAP.grid.cols;
    const cellHeight = MAP_HEIGHT / CITY_MAP.grid.rows;
    const add = (x: number, y: number, frameName: string, tint?: number): void => {
      const frame = sheetFrame(frameName);
      if (!frame) return;
      this.add.sprite((x + 0.5) * cellWidth, MAP_TOP + (y + 0.5) * cellHeight, frame.key, frame.index)
        .setDisplaySize(cellWidth, cellHeight).setDepth(2).setTint(tint ?? 0xffffff);
    };
    for (const cover of CITY_MAP.cover) add(cover.cell[0], cover.cell[1], VISUAL_CATALOG.scenery.ancientTree.frame);
    for (const wall of CITY_MAP.walls) {
      const frame = wall.scenery === "ridge" ? VISUAL_CATALOG.scenery.ridge.frame : VISUAL_CATALOG.scenery.canal.frame;
      for (let y = wall.cells[1]; y <= wall.cells[3]; y += 1) for (let x = wall.cells[0]; x <= wall.cells[2]; x += 1) add(x, y, frame);
    }
  }

  private drawTutorialGuide(): void {
    const guide = CITY_MAP.paths.find((path) => path.id === "tutorial_road_guide");
    if (!guide) return;
    const graphics = this.add.graphics().setDepth(3);
    graphics.lineStyle(3, 0xffffff, 0.68);
    for (const [x, y] of guide.points) {
      const center = this.cityCenter({ x, y });
      graphics.strokeRect(center.x - 18, center.y - 14, 36, 28);
    }
  }

  private createDecorativeTraffic(): void {
    const frame = sheetFrame(VISUAL_CATALOG.vehicle.frame);
    const route = CITY_MAP.paths.find((path) => path.id === VISUAL_CATALOG.vehicle.routeId);
    if (!frame || !route) return;
    const points = route.points.map(([x, y]) => this.cityCenter({ x, y }));
    for (let index = 0; index < 8; index += 1) {
      const car = this.add.sprite(points[0].x, points[0].y, frame.key, frame.index).setDepth(8).setDisplaySize(22, 14).setTint([0xff6b5f, 0x62b7ff, 0xffffff][index % 3]);
      Probe.spawn("actor", "decorative-vehicle");
      this.tweens.chain({ targets: car, loop: -1, tweens: points.slice(1).map((point, pointIndex) => ({ x: point.x, y: point.y, duration: 850, delay: pointIndex === 0 ? index * 170 : 0 })) });
    }
  }

  private cityCenter(cell: Cell): Phaser.Math.Vector2 {
    return new Phaser.Math.Vector2((cell.x + 0.5) * this.scale.width / CITY_MAP.grid.cols, MAP_TOP + (cell.y + 0.5) * MAP_HEIGHT / CITY_MAP.grid.rows);
  }

  private reasonText(reason?: string): string {
    return ({ blocked: "该格被地形阻挡", occupied: "该格已有设施", "insufficient-funds": "资金不足", "road-drag-not-contiguous": "道路必须连续", empty: "该格没有可拆除设施", missing: "建筑已不存在", "not-damaged": "建筑无需修复" } as Record<string, string>)[reason ?? ""] ?? (reason || "操作不可用");
  }

  private shutdown(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.inputController?.destroy();
    this.city?.destroy();
    this.overlays?.destroy();
    this.hud?.destroy();
    this.accessibility?.destroy();
  }
}

export { PlayScene as CityScene };
export const resetGameSession = (scene: PlayScene): void => scene.resetGameSession();
