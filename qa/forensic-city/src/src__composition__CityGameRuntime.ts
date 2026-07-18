import Phaser from "phaser";
import { CITY_CATALOG, CITY_VISUAL_MANIFEST, TUTORIAL_SEQUENCE } from "../content/CityContent";
import { LEVEL_LAYOUT } from "../levels/CityLevel";
import {
  advanceSimulationFixedStep, applyBuildCommand, continueAfterVictory, createInitialSimulationState,
  demolishStructure, dispatchEmergency, setSimulationControl, validateBuildCommand,
  type SimulationEvent, type SimulationState, type StructureState,
} from "../domain/CitySimulation";
import { registerGameControls, type RegisteredGameControls } from "../input/GameControls";
import {
  createCityPresentationEffects, createCoverageOverlayView, createPlannerController,
  type CityPresentationEffects, type CoverageOverlayView, type PlannerController,
} from "../presentation";
import type { CityPresentationCommands, CoverageOverlay, PlannerTool } from "../presentation/CityPresentationTypes";
import { createBuildingInspector, type BuildingInspector } from "../ui/BuildingInspector";
import { createCityHud, type CityHud } from "../ui/CityHud";
import { createOutcomePanels, type OutcomePanels } from "../ui/OutcomePanels";
import {
  toBuildingPresentation, toCityHudSnapshot, toCoverageCells, toDemolitionPreview, toOutcomePresentation,
} from "../adapters/CityPresentationAdapter";
import { colorNum } from "../systems/Colors";

const CELL_W = LEVEL_LAYOUT.grid.cellWidth;
const CELL_H = LEVEL_LAYOUT.grid.cellHeight;
const cellCenter = (point: { x: number; y: number }): { x: number; y: number } => ({ x: (point.x + 0.5) * CELL_W, y: (point.y + 0.5) * CELL_H });

export class CityGameRuntime {
  private state: SimulationState = createInitialSimulationState();
  private accumulatorMs = 0;
  private effects!: CityPresentationEffects;
  private planner!: PlannerController;
  private hud!: CityHud;
  private overlay!: CoverageOverlayView;
  private inspector!: BuildingInspector;
  private outcomes!: OutcomePanels;
  private controls!: RegisteredGameControls;
  private selectedTool: PlannerTool = "inspect";
  private selectedOverlay: CoverageOverlay = "none";
  private sprites = new Map<string, Phaser.GameObjects.Sprite>();
  private labels = new Map<string, Phaser.GameObjects.Text>();
  private pointerHandlers: Array<{ event: string; fn: (...args: any[]) => void }> = [];
  private tutorialRoot?: Phaser.GameObjects.Container;
  private tutorialTitle?: Phaser.GameObjects.Text;
  private tutorialBody?: Phaser.GameObjects.Text;
  private tutorialStep = 0;
  private tutorialSkipped = false;
  private previousScore = this.state.cityMetrics.score;
  private previousPower = 0;
  private previousWater = 0;

  constructor(private readonly scene: Phaser.Scene) {}

  create(): void {
    this.effects = createCityPresentationEffects(this.scene);
    this.drawWorld();
    const commands = this.createCommands();
    this.overlay = createCoverageOverlayView(this.scene, { originX: 0, originY: 0, cellWidth: CELL_W, cellHeight: CELL_H });
    this.inspector = createBuildingInspector(this.scene, {
      onSelectDemolish: () => this.selectTool("demolish"),
      onClose: () => this.planner.cancel(),
    });
    this.outcomes = createOutcomePanels(this.scene, { commands, onVictoryLights: () => this.flashRoadLights() });
    this.hud = createCityHud(this.scene, { commands, onHelp: () => this.showTutorial(true) });
    this.planner = createPlannerController(this.scene, {
      originX: 0, originY: 0, cellWidth: CELL_W, cellHeight: CELL_H,
      validate: (tool, anchor) => {
        const result = validateBuildCommand(this.state, { tool, anchor });
        return { legal: result.valid, price: result.cost, reason: result.reason ?? undefined, footprint: result.cells, connectionDirections: this.connectionDirections(anchor) };
      },
      structureAt: (cell) => this.structureAt(cell)?.id ?? null,
      demolitionPreview: (id) => toDemolitionPreview(this.state, id),
      onInspect: (id) => this.inspect(id),
      commands,
    });
    this.controls = registerGameControls(this.scene, commands, { isPaused: () => this.state.session.paused, getOverlay: () => this.selectedOverlay });
    this.bindPointer();
    this.createTutorialPanel();
    this.renderStructures(true);
    this.refreshPresentation();
  }

  update(deltaMs: number): void {
    if (this.state.session.paused || this.state.session.status !== "playing") {
      this.accumulatorMs = 0;
      this.refreshPresentation();
      return;
    }
    this.accumulatorMs += Math.min(deltaMs, 250);
    let steps = 0;
    while (this.accumulatorMs >= 100 && steps < 20) {
      this.accumulatorMs -= 100;
      const result = advanceSimulationFixedStep(this.state, 0.1);
      this.state = result.state;
      wireSimulationEvents(this, result.events);
      steps += 1;
    }
    this.renderStructures(false);
    this.refreshPresentation();
  }

  destroy(): void {
    for (const handler of this.pointerHandlers) this.scene.input.off(handler.event, handler.fn);
    this.pointerHandlers.length = 0;
    this.controls?.destroy();
    this.planner?.destroy();
    this.hud?.destroy();
    this.overlay?.destroy();
    this.inspector?.destroy();
    this.outcomes?.destroy();
    this.effects?.destroy();
    this.tutorialRoot?.destroy(true);
    for (const sprite of this.sprites.values()) sprite.destroy();
    for (const label of this.labels.values()) label.destroy();
    this.sprites.clear(); this.labels.clear();
  }

  handleSimulationEvents(events: readonly SimulationEvent[]): void {
    for (const event of events) {
      if (event.type === "MonthSettled") {
        const net = Number(event.payload.net ?? 0);
        this.effects.monthSettled(net, this.state.cityMetrics.score - this.previousScore);
        this.previousScore = this.state.cityMetrics.score;
      } else if (event.type === "NetworksRecalculated") {
        const power = Number(event.payload.powerCoverage ?? 0), water = Number(event.payload.waterCoverage ?? 0);
        if (power !== this.previousPower) this.effects.networksChanged("power", power > this.previousPower);
        if (water !== this.previousWater) this.effects.networksChanged("water", water > this.previousWater);
        this.previousPower = power; this.previousWater = water;
      } else if (event.type === "DisasterWarningStarted" || event.type === "DisasterActivated" || event.type === "DisasterResolved") {
        const target = this.state.structures.get(String(event.payload.targetId ?? ""));
        if (!target) continue;
        const p = cellCenter(target.anchor);
        if (event.type === "DisasterWarningStarted") this.effects.disasterWarning(p.x, p.y);
        else if (event.type === "DisasterActivated") this.effects.disasterActivated(p.x, p.y);
        else this.effects.disasterResolved(p.x, p.y, Boolean(event.payload.dispatched));
      } else if (event.type === "ScoreMilestoneReached") {
        const milestone = Number(event.payload.milestone) as 40 | 60 | 80;
        this.effects.scoreMilestone(milestone);
        this.hud.announce(milestone === 60 ? "评分60：获得一次韧性凭证" : `城市评分达到${milestone}`, "success");
      } else if (event.type === "OutcomeReached") {
        const outcome = toOutcomePresentation(this.state);
        if (outcome?.kind === "victory") openVictoryFlow(this, outcome);
        else if (outcome) openDefeatFlow(this, outcome);
      }
    }
  }

  showOutcome(outcome: NonNullable<ReturnType<typeof toOutcomePresentation>>): void { this.outcomes.show(outcome); }

  reset(): void {
    this.state = createInitialSimulationState();
    this.accumulatorMs = 0; this.previousScore = this.state.cityMetrics.score; this.previousPower = 0; this.previousWater = 0;
    this.selectedTool = "inspect"; this.selectedOverlay = "none";
    this.tutorialStep = 0; this.tutorialSkipped = false;
    this.outcomes.hide(); this.inspector.hide(); this.overlay.close(); this.planner.cancel(); this.planner.setTool("inspect");
    this.hud.setSelectedTool("inspect"); this.hud.setSelectedOverlay("none");
    this.showTutorial(true); this.renderStructures(true); this.refreshPresentation();
  }

  continueVictory(): void {
    this.state = continueAfterVictory(this.state);
    this.outcomes.hide(); this.accumulatorMs = 0; this.hud.announce("继续建设：已恢复胜利前速度", "success");
  }

  private createCommands(): CityPresentationCommands {
    return {
      requestBuild: (request) => {
        const result = applyBuildCommand(this.state, request);
        const p = cellCenter(request.anchor);
        if (!result.accepted) { this.effects.buildRejected(p.x, p.y, result.reason ?? undefined); this.hud.announce(result.reason ?? "建设失败", "danger"); return; }
        this.state = result.state; wireSimulationEvents(this, result.events);
        this.effects.buildAccepted(p.x, p.y, request.tool === "powerPlant" || request.tool === "waterTower");
        this.advanceTutorialAfterBuild(request.tool); this.renderStructures(false); this.refreshPresentation();
      },
      requestDemolish: (id, confirmed) => {
        const result = demolishStructure(this.state, id, confirmed);
        if (!result.accepted) { this.hud.announce(result.reason ?? "拆除失败", "danger"); return; }
        this.state = result.state; wireSimulationEvents(this, result.events); this.inspector.hide(); this.renderStructures(false); this.refreshPresentation();
      },
      requestSimulation: (control) => {
        this.state = setSimulationControl(this.state, control);
        if (!this.state.session.paused && this.tutorialStep >= 5) this.hideTutorial();
        this.refreshPresentation();
      },
      requestEmergency: (id) => {
        const result = dispatchEmergency(this.state, id);
        if (!result.accepted) this.hud.announce(result.reason ?? "无法调度", "danger");
        else { this.state = result.state; wireSimulationEvents(this, result.events); this.hud.announce("应急队已出发", "success"); }
        this.refreshPresentation();
      },
      requestRestart: () => resetGameSession(this),
      requestContinueAfterVictory: () => this.continueVictory(),
      selectTool: (tool) => this.selectTool(tool),
      setOverlay: (overlay) => this.setOverlay(overlay),
      toggleMinimap: () => { this.overlay.toggleMinimap(); },
      closeTopPanel: () => { this.inspector.hide(); this.overlay.close(); this.selectedOverlay = "none"; this.hud.setSelectedOverlay("none"); this.planner.cancel(); },
    };
  }

  private selectTool(tool: PlannerTool): void {
    this.selectedTool = tool; this.planner.setTool(tool); this.hud.setSelectedTool(tool);
    if (tool === "residential" && this.tutorialStep === 0) this.showTutorial(true);
  }

  private setOverlay(overlay: CoverageOverlay): void {
    this.selectedOverlay = overlay; this.hud.setSelectedOverlay(overlay);
    if (overlay === "none") this.overlay.setOverlay("none");
    else this.overlay.setOverlay(overlay, toCoverageCells(this.state, overlay));
    if ((overlay === "power" || overlay === "water") && this.tutorialStep === 4) { this.tutorialStep = 5; this.showTutorial(true); }
  }

  private bindPointer(): void {
    const move = (pointer: Phaser.Input.Pointer): void => this.planner.pointerMove(pointer.worldX, pointer.worldY, pointer.isDown);
    const down = (pointer: Phaser.Input.Pointer): void => this.planner.pointerDown(pointer.worldX, pointer.worldY);
    const up = (pointer: Phaser.Input.Pointer): void => this.planner.pointerUp(pointer.worldX, pointer.worldY);
    this.pointerHandlers = [{ event: "pointermove", fn: move }, { event: "pointerdown", fn: down }, { event: "pointerup", fn: up }];
    for (const handler of this.pointerHandlers) this.scene.input.on(handler.event, handler.fn);
  }

  private drawWorld(): void {
    const g = this.scene.add.graphics().setDepth(-5);
    for (const cell of LEVEL_LAYOUT.cells) {
      const x = cell.x * CELL_W, y = cell.y * CELL_H;
      const color = cell.terrain === "river" ? 0x3e9fd1 : cell.terrain === "bridge" ? 0xc99a62 : cell.terrain === "rock" ? 0x6f756f : cell.terrain === "naturalObstacle" ? 0x2f7d4f : 0x77bd72;
      g.fillStyle(color, cell.terrain === "grass" ? 0.68 : 0.9).fillRect(x, y, CELL_W, CELL_H);
      g.lineStyle(1, 0xffffff, 0.13).strokeRect(x, y, CELL_W, CELL_H);
      if (cell.terrain === "river") { g.lineStyle(2, 0xb6efff, 0.5); g.lineBetween(x + 8, y + 18, x + 54, y + 18); g.lineBetween(x + 2, y + 42, x + 48, y + 42); }
      if (!cell.buildable) { g.lineStyle(2, 0x17212b, 0.35); g.lineBetween(x + 8, y + 8, x + CELL_W - 8, y + CELL_H - 8); }
    }
    for (const point of LEVEL_LAYOUT.points.filter((p) => p.kind === "objective" || p.kind === "item")) {
      const p = cellCenter(point); this.scene.add.text(p.x, p.y, point.kind === "objective" ? "★" : "!", { fontSize: "18px", color: point.kind === "objective" ? "#ffd34e" : "#ffffff", stroke: "#17212b", strokeThickness: 3 }).setOrigin(0.5).setDepth(2).setAlpha(0.7);
    }
  }

  private renderStructures(forceRebuild: boolean): void {
    if (forceRebuild) {
      for (const sprite of this.sprites.values()) sprite.destroy();
      for (const label of this.labels.values()) label.destroy();
      this.sprites.clear(); this.labels.clear();
    }
    for (const [id, sprite] of this.sprites) if (!this.state.structures.has(id)) { sprite.destroy(); this.sprites.delete(id); this.labels.get(id)?.destroy(); this.labels.delete(id); }
    for (const structure of this.state.structures.values()) {
      let sprite = this.sprites.get(structure.id);
      const visual = CITY_VISUAL_MANIFEST.structures[structure.tool];
      const frame = structure.disabled && visual.active ? visual.active : visual.idle;
      const center = { x: (structure.anchor.x + visual.displayCells.width / 2) * CELL_W, y: (structure.anchor.y + visual.displayCells.height / 2) * CELL_H };
      if (!sprite) {
        sprite = this.scene.add.sprite(center.x, center.y, frame.texture, frame.frame).setDepth(10);
        sprite.setDisplaySize(CELL_W * visual.displayCells.width * 0.9, CELL_H * visual.displayCells.height * 0.9);
        const targetScaleX = sprite.scaleX, targetScaleY = sprite.scaleY;
        sprite.setScale(targetScaleX * 0.2, targetScaleY * 0.2);
        this.scene.tweens.add({ targets: sprite, scaleX: targetScaleX, scaleY: targetScaleY, duration: visual.buildAnimationSeconds * 1000, ease: "Back.easeOut" });
        this.sprites.set(structure.id, sprite);
        const label = this.scene.add.text(center.x, center.y, visual.icon, { fontFamily: "Inter, sans-serif", fontSize: structure.tool === "road" ? "12px" : "17px", color: "#ffffff", fontStyle: "bold", stroke: "#17212b", strokeThickness: 3 }).setOrigin(0.5).setDepth(12);
        this.labels.set(structure.id, label);
      } else {
        sprite.setPosition(center.x, center.y).setTexture(frame.texture, frame.frame);
        this.labels.get(structure.id)?.setPosition(center.x, center.y);
      }
      sprite.setTint(structure.disabled ? colorNum("#e84a3c") : structure.tool !== "road" && (!structure.roadConnected || ((structure.tool === "residential" || structure.tool === "commercial") && (!structure.powered || !structure.watered))) ? 0xaab0b8 : 0xffffff);
    }
  }

  private refreshPresentation(): void {
    this.hud.update(toCityHudSnapshot(this.state));
    if (this.selectedOverlay !== "none") this.overlay.updateCells(toCoverageCells(this.state, this.selectedOverlay));
    if (this.inspector.visible && this.inspector.structureId) this.inspect(this.inspector.structureId);
  }

  private inspect(id: string): void { const s = this.state.structures.get(id); if (s) this.inspector.show(toBuildingPresentation(this.state, s)); }
  private structureAt(cell: { x: number; y: number }): StructureState | undefined { return [...this.state.structures.values()].find((s) => s.cells.some((c) => c.x === cell.x && c.y === cell.y)); }
  private connectionDirections(anchor: { x: number; y: number }): ("up" | "right" | "down" | "left")[] {
    const result: ("up" | "right" | "down" | "left")[] = [];
    const directions = [[0, -1, "up"], [1, 0, "right"], [0, 1, "down"], [-1, 0, "left"]] as const;
    for (const [dx, dy, name] of directions) if (this.structureAt({ x: anchor.x + dx, y: anchor.y + dy })?.tool === "road") result.push(name);
    return result;
  }

  private advanceTutorialAfterBuild(tool: string): void {
    if (this.tutorialSkipped) return;
    if (tool === "residential" && this.tutorialStep <= 0) this.tutorialStep = 1;
    else if (tool === "road" && this.tutorialStep <= 1) this.tutorialStep = 2;
    else if (tool === "powerPlant" && this.tutorialStep <= 2) this.tutorialStep = 3;
    else if (tool === "waterTower" && this.tutorialStep <= 3) this.tutorialStep = 4;
    this.showTutorial(true);
  }

  private createTutorialPanel(): void {
    const root = this.scene.add.container(320, 84).setDepth(100).setScrollFactor(0);
    const bg = this.scene.add.rectangle(0, 0, 610, 112, 0x17212b, 0.96).setOrigin(0).setStrokeStyle(3, colorNum("#ffd34e"));
    this.tutorialTitle = this.scene.add.text(16, 12, "", { fontFamily: "Inter, sans-serif", fontSize: "19px", color: "#ffd34e", fontStyle: "bold" });
    this.tutorialBody = this.scene.add.text(16, 42, "", { fontFamily: "Inter, sans-serif", fontSize: "14px", color: "#ffffff", wordWrap: { width: 470 }, lineSpacing: 4 });
    const skip = this.scene.add.text(540, 18, "跳过教学", { fontFamily: "Inter, sans-serif", fontSize: "14px", color: "#17212b", backgroundColor: "#f4e7c5", padding: { x: 8, y: 6 } }).setOrigin(0.5).setInteractive({ useHandCursor: true });
    skip.on("pointerdown", () => { this.tutorialSkipped = true; this.hideTutorial(); this.hud.announce("教学已跳过；城市仍保持暂停", "info"); });
    root.add([bg, this.tutorialTitle, this.tutorialBody, skip]); this.tutorialRoot = root;
    this.showTutorial(true);
  }

  private showTutorial(force = false): void {
    if (this.tutorialSkipped && !force) return;
    if (force) this.tutorialSkipped = false;
    const step = TUTORIAL_SEQUENCE.steps[Math.min(this.tutorialStep, TUTORIAL_SEQUENCE.steps.length - 1)];
    this.tutorialTitle?.setText(`教学 ${this.tutorialStep + 1}/${TUTORIAL_SEQUENCE.steps.length} · ${step.title}`);
    this.tutorialBody?.setText(`${step.body}\n提示：${step.completionHint}`);
    this.tutorialRoot?.setVisible(true);
  }
  private hideTutorial(): void { this.tutorialRoot?.setVisible(false); }
  private flashRoadLights(): void { for (const s of this.state.structures.values()) if (s.tool === "road") { const sprite = this.sprites.get(s.id); if (sprite) this.scene.tweens.add({ targets: sprite, alpha: 0.45, duration: 180, yoyo: true, repeat: 5 }); } }
}

export function wireSimulationEvents(runtime: CityGameRuntime, events: readonly SimulationEvent[]): void { runtime.handleSimulationEvents(events); }
export function resetGameSession(runtime: CityGameRuntime): void { runtime.reset(); }
export function openVictoryFlow(runtime: CityGameRuntime, outcome: NonNullable<ReturnType<typeof toOutcomePresentation>>): void { runtime.showOutcome(outcome); }
export function openDefeatFlow(runtime: CityGameRuntime, outcome: NonNullable<ReturnType<typeof toOutcomePresentation>>): void { runtime.showOutcome(outcome); }
export function bootstrapCityGame(scene: Phaser.Scene): CityGameRuntime { const runtime = new CityGameRuntime(scene); runtime.create(); return runtime; }
