import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";
import { Sfx } from "../systems/Sfx";
import type { BuildingPresentation } from "../presentation/CityPresentationTypes";

export interface BuildingInspectorOptions {
  onClose?: () => void;
  onSelectDemolish?: (structureId: string) => void;
}

export interface BuildingInspector {
  readonly visible: boolean;
  readonly structureId: string | null;
  show(building: BuildingPresentation): void;
  update(building: BuildingPresentation): void;
  hide(): void;
  destroy(): void;
}

const meter = (used: number, capacity: number): string => `${used}/${capacity}${used > capacity ? " 超载" : ""}`;

/** Read-only building details. It never changes simulation state; demolition
 * only selects the tool and leaves impact/confirmation to the planner/rules path. */
export function createBuildingInspector(scene: Phaser.Scene, options: BuildingInspectorOptions = {}): BuildingInspector {
  const panel = scene.add.container(14, 82).setDepth(88).setScrollFactor(0).setVisible(false);
  const bg = scene.add.rectangle(0, 0, 286, 390, 0x17212b, 0.94).setOrigin(0).setStrokeStyle(3, colorNum(gameConfig.palette.primary));
  const title = scene.add.text(16, 14, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "20px", color: gameConfig.palette.accent, fontStyle: "bold",
    stroke: "#000000", strokeThickness: 2,
  });
  const body = scene.add.text(16, 54, "", {
    fontFamily: "Inter, system-ui, sans-serif", fontSize: "15px", color: "#ffffff", lineSpacing: 7,
    wordWrap: { width: 254 }, stroke: "#000000", strokeThickness: 2,
  });
  const closeBg = scene.add.rectangle(256, 24, 38, 32, colorNum(gameConfig.palette.surface), 1).setInteractive({ useHandCursor: true });
  const closeText = scene.add.text(256, 24, "×", { fontFamily: "Inter, sans-serif", fontSize: "22px", color: "#17212b", fontStyle: "bold" }).setOrigin(0.5);
  const demolishBg = scene.add.rectangle(143, 356, 246, 42, colorNum(gameConfig.palette.danger), 0.92).setInteractive({ useHandCursor: true });
  const demolishText = scene.add.text(143, 356, "⚒ 预览拆除影响（退款40%）", { fontFamily: "Inter, sans-serif", fontSize: "14px", color: "#ffffff", fontStyle: "bold" }).setOrigin(0.5);
  panel.add([bg, title, body, closeBg, closeText, demolishBg, demolishText]);
  let current: BuildingPresentation | null = null;

  const render = (building: BuildingPresentation): void => {
    current = building;
    title.setText(`ⓘ ${building.name}`);
    const populationLine = building.populationCapacity === undefined ? null : `♟ 居民 ${building.population ?? 0}/${building.populationCapacity}`;
    const jobsLine = building.jobCapacity === undefined ? null : `▤ 岗位 ${building.jobs ?? 0}/${building.jobCapacity}`;
    body.setText([
      `类型：${building.kind}`,
      `建造成本：¥${building.cost}  ·  月维护：¥${building.maintenance}`,
      `${building.roadConnected ? "✓" : "×"} 道路连接 ${building.roadConnected ? "正常" : "中断"}`,
      `${building.power.covered ? "⚡✓" : "⚡×"} 电力 ${meter(building.power.used, building.power.capacity)}${building.power.distance === undefined ? "" : ` · 路距${building.power.distance}`}`,
      `${building.water.covered ? "◆✓" : "◆×"} 水务 ${meter(building.water.used, building.water.capacity)}${building.water.distance === undefined ? "" : ` · 路距${building.water.distance}`}`,
      populationLine,
      jobsLine,
      `▧ 污染影响 ${building.pollution >= 0 ? "+" : ""}${building.pollution}`,
      `☺ 满意度影响 ${building.satisfactionImpact >= 0 ? "+" : ""}${building.satisfactionImpact}`,
      `状态：${building.statusText}`,
    ].filter((line): line is string => Boolean(line)).join("\n"));
    panel.setVisible(true);
  };

  closeBg.on("pointerdown", () => { inspector.hide(); options.onClose?.(); Sfx.play("select", 0.35); });
  demolishBg.on("pointerdown", () => { if (current) options.onSelectDemolish?.(current.id); Sfx.play("select", 0.45); });

  const inspector: BuildingInspector = {
    get visible(): boolean { return panel.visible; },
    get structureId(): string | null { return current?.id ?? null; },
    show: render,
    update(building): void { if (!current || current.id === building.id) render(building); },
    hide(): void { panel.setVisible(false); current = null; },
    destroy(): void { panel.destroy(true); },
  };
  return inspector;
}
