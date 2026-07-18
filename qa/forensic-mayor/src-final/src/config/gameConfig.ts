// Side-effect import: installs the QA runtime probes (scene/anims/backdrop
// instrumentation) in every game, since every module imports gameConfig.
import "../systems/Probe";

export type AssetKind = "image" | "spritesheet" | "audio" | "video" | "tilemap";

export interface AssetEntry {
  key: string;
  path: string;
  kind: AssetKind;
  frameWidth?: number;
  frameHeight?: number;
}

/** Per-game color identity. Use these for EVERY color so each game keeps its own look. */
export interface GamePalette {
  bg: string;
  surface: string;
  primary: string;
  accent: string;
  danger: string;
}

/** One connectable structure's tile variants (roads, pipes, rails, fences).
 * Slot -> frame name on the same sheet. Canonical art orientations:
 * straight = left-right, end = opens right, corner = right+down,
 * tee = left+right+down, cross = all four. Pick with tileVariant() below. */
export interface TileFamily {
  straight: string;
  end: string;
  corner: string;
  tee: string;
  cross: string;
}

/** Generated sprite sheet: one texture, named frame indices (BootScene preloads it).
 * Use `sheet.frames` for sprites and animations instead of procedural circles, e.g.
 * `this.add.sprite(x, y, sheet.key, sheet.frames["player_idle"])` and
 * `this.anims.create({ key: "run", frames: this.anims.generateFrameNumbers(sheet.key,
 *   { frames: [sheet.frames["player_move_a"], sheet.frames["player_move_b"]] }), frameRate: 8, repeat: -1 })`.
 * `animations` groups the frames of each multi-frame actor (first frame name -> all of
 * its frames ON THIS SHEET, in sheet order): the player pose set (idle/move_a/move_b/
 * action plus player_skill_N / player_hurt when designed), each enemy's idle+attack
 * pair ("grunt" -> ["grunt", "grunt_b"]), boss idle/attack/special trios, and item
 * idle+activated pairs. Same-group frames always share this texture, so wire them
 * straight into anims.create (attack toggles, activation pulses, boss phases).
 *
 * `frameMeta` is GROUND TRUTH for what each frame's art actually shows (written by
 * the asset planner from the design roster). Frame names like "entity_3" carry NO
 * meaning on their own — ALWAYS bind design entities to frames by reading frameMeta;
 * guessing by name order mis-skins the whole game (a power plant wearing the water
 * tower's art). `tileFamilies` lists connectable structures: draw those per-cell via
 * tileVariant() at EXACTLY the grid cell size (no margins, no shrink factor) so
 * adjacent pieces join seamlessly, and refresh the 4 orthogonal neighbors of a cell
 * after every placement/removal. */
export interface SheetInfo {
  key: string;
  frameWidth: number;
  frameHeight: number;
  frames: Record<string, number>;
  animations: Record<string, string[]>;
  frameMeta: Record<string, string>;
  tileFamilies: Record<string, TileFamily>;
}

/** Generated Tiled map (BootScene preloads the JSON and the tileset image).
 * Draw it as ground decor beneath gameplay:
 * `const map = this.make.tilemap({ key: tilemap.key });`
 * `const tiles = map.addTilesetImage(tilemap.tilesetName, tilemap.tilesetKey);`
 * `if (tiles) map.createLayer(tilemap.layer, tiles, 0, 0)?.setDepth(-15);`
 * Tiles with a gid in `solidGids` are wall/cover art; for tile-wall designs call
 * `map.setCollision(tilemap.solidGids)` on the layer and add colliders. */
export interface TilemapInfo {
  key: string;
  layer: string;
  tilesetKey: string;
  tilesetName: string;
  tileSize: number;
  solidGids: number[];
}

export interface LayoutRect { x: number; y: number; width: number; height: number }
export interface LayoutRegion extends LayoutRect { id: string; name: string; kind: string }
export interface LayoutPath { id: string; points: { x: number; y: number }[] }
export interface LayoutPoint { id: string; kind: string; x: number; y: number }

/** THE designed floor plan, pre-scaled to pixels — the SINGLE SOURCE OF TRUTH
 * for level geometry. The painted backdrop was composed from this same plan, so
 * building collision and routes from it makes the picture and the game agree:
 * - walls/cover: solid blocking rectangles → static physics bodies
 *   (LevelLayout.buildStatics does this in one call)
 * - paths: ordered waypoint routes — guard patrols, creep lanes, platform runs
 * - points: named markers (kind: spawn | objective | exit | hazard | item)
 * - regions: named areas for zone logic, HUD labels, or camera hints.
 * Do NOT invent a second, conflicting set of level coordinates. */
export interface LevelLayoutInfo {
  cellWidth: number;
  cellHeight: number;
  regions: LayoutRegion[];
  walls: LayoutRect[];
  cover: LayoutRect[];
  paths: LayoutPath[];
  points: LayoutPoint[];
}

export interface GeneratedGameConfig {
  title: string;
  /** Planning metadata only — implement the GameDesign, not this label. */
  archetype: string;
  width: number;
  height: number;
  palette: GamePalette;
  hint: string;
  lives: number;
  targetScore: number;
  /** Free-form tuning numbers from the design/balance plan. Meaning is defined by gameplay code. */
  params: Record<string, number>;
  assets: AssetEntry[];
  /** backgrounds lists EVERY generated scene backdrop in order (main stage,
   * high-intensity / boss phase, alternate zone). Switch stages at runtime with
   * Backdrop.draw(this, dim, gameConfig.assetKeys.backgrounds[i]). */
  assetKeys: { background: string; backgrounds: string[]; player: string; enemy: string; reward: string };
  /** Measured per-background dim overlay strength (0-0.35). Backdrop.draw uses
   * this automatically: dark art gets a light overlay, bright art a stronger one. */
  backdropDims: Record<string, number>;
  /** First generated sheet (kept for compatibility). Prefer sheetFrame() lookups. */
  sheet: SheetInfo | null;
  /** Every generated sheet. Large rosters overflow onto "sheet-2". */
  sheets: SheetInfo[];
  tilemap: TilemapInfo | null;
  levelLayout: LevelLayoutInfo | null;
}

export const gameConfig = {
  "title": "像素市长：迷你都市",
  "archetype": "city_builder",
  "width": 1280,
  "height": 720,
  "palette": {
    "bg": "#8fbf8a",
    "surface": "#e8e1c5",
    "primary": "#3d78a8",
    "accent": "#f2a23a",
    "danger": "#d94b55"
  },
  "hint": "Move with arrows or WASD.",
  "lives": 3,
  "targetScore": 120,
  "params": {},
  "assets": [],
  "assetKeys": {
    "background": "",
    "backgrounds": [],
    "player": "player-fallback",
    "enemy": "enemy-fallback",
    "reward": "reward-fallback"
  },
  "backdropDims": {},
  "sheet": null,
  "sheets": [],
  "tilemap": null,
  "levelLayout": {
    "cellWidth": 53.33,
    "cellHeight": 51.43,
    "regions": [
      {
        "id": "sunny_meadows",
        "name": "暖阳住宅草坪",
        "kind": "低污染住宅规划区",
        "x": 53.3,
        "y": 51.4,
        "width": 426.7,
        "height": 308.6
      },
      {
        "id": "civic_start",
        "name": "市政起步区",
        "kind": "教学与初始道路周边建设区",
        "x": 480.0,
        "y": 51.4,
        "width": 373.3,
        "height": 308.6
      },
      {
        "id": "utility_buffer",
        "name": "东部设施缓冲地",
        "kind": "适合电厂和供水设施的远郊工程区",
        "x": 853.3,
        "y": 51.4,
        "width": 373.3,
        "height": 308.6
      },
      {
        "id": "south_expansion",
        "name": "南部扩建平原",
        "kind": "中后期综合城市扩建区",
        "x": 53.3,
        "y": 360.0,
        "width": 1173.3,
        "height": 308.6
      }
    ],
    "walls": [
      {
        "x": 0.0,
        "y": 0.0,
        "width": 1280.0,
        "height": 51.4
      },
      {
        "x": 0.0,
        "y": 668.6,
        "width": 1280.0,
        "height": 51.4
      },
      {
        "x": 0.0,
        "y": 51.4,
        "width": 53.3,
        "height": 617.1
      },
      {
        "x": 1226.7,
        "y": 51.4,
        "width": 53.3,
        "height": 617.1
      }
    ],
    "cover": [
      {
        "x": 106.7,
        "y": 102.9,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 320.0,
        "y": 102.9,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 160.0,
        "y": 257.1,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 960.0,
        "y": 102.9,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 1120.0,
        "y": 205.7,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 106.7,
        "y": 514.3,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 320.0,
        "y": 565.7,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 960.0,
        "y": 514.3,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 1120.0,
        "y": 565.7,
        "width": 53.3,
        "height": 51.4
      }
    ],
    "paths": [
      {
        "id": "starter_road",
        "points": [
          {
            "x": 453.3,
            "y": 385.7
          },
          {
            "x": 506.7,
            "y": 385.7
          },
          {
            "x": 560.0,
            "y": 385.7
          },
          {
            "x": 613.3,
            "y": 385.7
          },
          {
            "x": 666.7,
            "y": 385.7
          },
          {
            "x": 720.0,
            "y": 385.7
          },
          {
            "x": 773.3,
            "y": 385.7
          },
          {
            "x": 826.7,
            "y": 385.7
          }
        ]
      },
      {
        "id": "tutorial_utility_route",
        "points": [
          {
            "x": 826.7,
            "y": 385.7
          },
          {
            "x": 880.0,
            "y": 385.7
          },
          {
            "x": 933.3,
            "y": 385.7
          },
          {
            "x": 986.7,
            "y": 385.7
          },
          {
            "x": 986.7,
            "y": 334.3
          },
          {
            "x": 986.7,
            "y": 282.9
          }
        ]
      },
      {
        "id": "tutorial_residential_route",
        "points": [
          {
            "x": 453.3,
            "y": 385.7
          },
          {
            "x": 400.0,
            "y": 385.7
          },
          {
            "x": 346.7,
            "y": 385.7
          },
          {
            "x": 346.7,
            "y": 334.3
          },
          {
            "x": 346.7,
            "y": 282.9
          }
        ]
      }
    ],
    "points": [
      {
        "id": "mayor_cursor_spawn",
        "kind": "spawn",
        "x": 613.3,
        "y": 385.7
      },
      {
        "id": "first_power_hint",
        "kind": "objective",
        "x": 986.7,
        "y": 180.0
      },
      {
        "id": "first_water_hint",
        "kind": "objective",
        "x": 1093.3,
        "y": 385.7
      },
      {
        "id": "first_home_hint",
        "kind": "objective",
        "x": 293.3,
        "y": 282.9
      },
      {
        "id": "first_shop_hint",
        "kind": "objective",
        "x": 560.0,
        "y": 282.9
      },
      {
        "id": "pollution_warning_marker",
        "kind": "hazard",
        "x": 880.0,
        "y": 180.0
      },
      {
        "id": "milestone_banner_origin",
        "kind": "item",
        "x": 666.7,
        "y": 128.6
      },
      {
        "id": "city_hall_goal",
        "kind": "exit",
        "x": 666.7,
        "y": 540.0
      }
    ]
  }
} as GeneratedGameConfig;

/** Read a tuning number with a safe fallback. */
export function param(name: string, fallback: number): number {
  const value = gameConfig.params[name];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** Resolve a named frame across every generated sheet ("enemy_5" may live on
 * sheet-2). Returns the texture key + frame index for add.sprite/setTexture. */
export function sheetFrame(name: string): { key: string; index: number } | null {
  for (const sheet of gameConfig.sheets) {
    const index = sheet.frames[name];
    if (typeof index === "number") return { key: sheet.key, index };
  }
  return null;
}

/** Find a connectable structure's tile family across every generated sheet. */
export function tileFamily(base: string): TileFamily | null {
  for (const sheet of gameConfig.sheets) {
    const family = sheet.tileFamilies[base];
    if (family) return family;
  }
  return null;
}

/** Frame + clockwise rotation (degrees, for sprite.setAngle) for a connectable
 * tile, from its orthogonal same-family neighbor mask. Matches the canonical
 * art orientations documented on TileFamily. Re-run this for the 4 neighbors
 * of any cell the player changes, and draw results at exactly cell size. */
export function tileVariant(
  family: TileFamily,
  up: boolean,
  right: boolean,
  down: boolean,
  left: boolean,
): { frame: string; angle: number } {
  const count = (up ? 1 : 0) + (right ? 1 : 0) + (down ? 1 : 0) + (left ? 1 : 0);
  if (count === 4) return { frame: family.cross, angle: 0 };
  if (count === 3) {
    if (!up) return { frame: family.tee, angle: 0 };
    if (!right) return { frame: family.tee, angle: 90 };
    if (!down) return { frame: family.tee, angle: 180 };
    return { frame: family.tee, angle: 270 };
  }
  if (count === 2) {
    if (left && right) return { frame: family.straight, angle: 0 };
    if (up && down) return { frame: family.straight, angle: 90 };
    if (right && down) return { frame: family.corner, angle: 0 };
    if (down && left) return { frame: family.corner, angle: 90 };
    if (left && up) return { frame: family.corner, angle: 180 };
    return { frame: family.corner, angle: 270 };
  }
  if (right) return { frame: family.end, angle: 0 };
  if (down) return { frame: family.end, angle: 90 };
  if (left) return { frame: family.end, angle: 180 };
  if (up) return { frame: family.end, angle: 270 };
  return { frame: family.straight, angle: 0 };
}
