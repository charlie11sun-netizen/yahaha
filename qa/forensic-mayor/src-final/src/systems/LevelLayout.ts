import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import type { LayoutPath, LayoutPoint, LayoutRegion, LevelLayoutInfo } from "../config/gameConfig";
import { colorNum } from "./Colors";
import { Probe } from "./Probe";

/** Runtime access to the designed floor plan (gameConfig.levelLayout).
 *
 * The painted backdrop was generated FROM this plan, so geometry built here
 * visually matches the art: walls/cover become solid physics bodies exactly
 * where the picture shows structure, paths route enemies along designed lanes
 * and patrols, points place spawns/objectives. Use it instead of inventing
 * coordinates — it is the single source of truth for the level. */
export const LevelLayout = {
  data(): LevelLayoutInfo | null {
    return gameConfig.levelLayout;
  },

  /** Build every wall/cover rect as a static physics body in one call.
   * Blocks are drawn in palette colors (replace or skin them with sheetFrame
   * art for a richer look) and returned as a StaticGroup ready for
   * `physics.add.collider(actor, statics)`. Returns null when the design has
   * no layout. */
  buildStatics(
    scene: Phaser.Scene,
    style?: { fill?: number; alpha?: number; depth?: number },
  ): Phaser.Physics.Arcade.StaticGroup | null {
    const layout = gameConfig.levelLayout;
    if (!layout) return null;
    const blocks = [...layout.walls, ...layout.cover];
    if (!blocks.length) return null;
    const statics = scene.physics.add.staticGroup();
    const fill = style?.fill ?? colorNum(gameConfig.palette.surface);
    for (const rect of blocks) {
      const block = scene.add
        .rectangle(rect.x + rect.width / 2, rect.y + rect.height / 2, rect.width, rect.height, fill, style?.alpha ?? 0.9)
        .setStrokeStyle(2, colorNum(gameConfig.palette.primary), 0.3)
        .setDepth(style?.depth ?? 2);
      statics.add(block);
    }
    Probe.emit("layout:statics", String(blocks.length));
    return statics;
  },

  /** Ordered waypoint routes (guard patrols, creep lanes, platform runs). */
  paths(): LayoutPath[] {
    return gameConfig.levelLayout?.paths ?? [];
  },

  path(id: string): LayoutPath | null {
    return this.paths().find((path) => path.id === id) ?? null;
  },

  /** Named markers; kind is spawn | objective | exit | hazard | item | marker. */
  points(kind?: string): LayoutPoint[] {
    const all = gameConfig.levelLayout?.points ?? [];
    return kind ? all.filter((point) => point.kind === kind) : all;
  },

  point(id: string): LayoutPoint | null {
    return this.points().find((point) => point.id === id) ?? null;
  },

  /** The designed region containing (x, y), for zone rules and HUD labels. */
  regionAt(x: number, y: number): LayoutRegion | null {
    for (const region of gameConfig.levelLayout?.regions ?? []) {
      if (x >= region.x && x <= region.x + region.width && y >= region.y && y <= region.y + region.height) {
        return region;
      }
    }
    return null;
  },
};
