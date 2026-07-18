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
  "title": "像素都市规划师",
  "archetype": "simulation",
  "width": 1280,
  "height": 720,
  "palette": {
    "bg": "#78b95a",
    "surface": "#f4e8c1",
    "primary": "#237f83",
    "accent": "#ffd447",
    "danger": "#d94b3d"
  },
  "hint": "Move with arrows or WASD.",
  "lives": 3,
  "targetScore": 120,
  "params": {},
  "assets": [
    {
      "key": "sheet",
      "path": "assets/sheet.webp",
      "kind": "spritesheet",
      "frameWidth": 256,
      "frameHeight": 256
    },
    {
      "key": "sheet-2",
      "path": "assets/sheet-2.webp",
      "kind": "spritesheet",
      "frameWidth": 256,
      "frameHeight": 256
    },
    {
      "key": "sheet-3",
      "path": "assets/sheet-3.webp",
      "kind": "spritesheet",
      "frameWidth": 256,
      "frameHeight": 256
    },
    {
      "key": "background",
      "path": "assets/background.webp",
      "kind": "image"
    },
    {
      "key": "background-2",
      "path": "assets/background-2.webp",
      "kind": "image"
    },
    {
      "key": "background-3",
      "path": "assets/background-3.webp",
      "kind": "image"
    }
  ],
  "assetKeys": {
    "background": "background",
    "backgrounds": [
      "background",
      "background-2",
      "background-3"
    ],
    "player": "player-fallback",
    "enemy": "enemy-fallback",
    "reward": "reward-fallback"
  },
  "backdropDims": {
    "background": 0.35,
    "background-2": 0.35,
    "background-3": 0.35
  },
  "sheet": {
    "key": "sheet",
    "frameWidth": 256,
    "frameHeight": 256,
    "frames": {
      "player_idle": 0,
      "player_move_a": 1,
      "player_move_b": 2,
      "player_action": 3,
      "player_skill_2": 4,
      "player_skill_3": 5,
      "player_hurt": 6,
      "player_jump": 7,
      "player_death": 8,
      "player_victory": 9,
      "player_skill_4": 10,
      "obstacle_1": 11,
      "obstacle_2": 12,
      "obstacle_3": 13,
      "item_1": 14,
      "item_1_b": 15
    },
    "animations": {
      "player_idle": [
        "player_idle",
        "player_move_a",
        "player_move_b",
        "player_action",
        "player_skill_2",
        "player_skill_3",
        "player_hurt",
        "player_jump",
        "player_death",
        "player_victory",
        "player_skill_4"
      ],
      "item_1": [
        "item_1",
        "item_1_b"
      ]
    },
    "frameMeta": {
      "player_idle": "THE PLAYER: 玩家没有可移动市长角色，而是控制一个白色像素描边的规划光标。光标覆盖一个网格，当前工具图标悬浮在右上角；合法放置时格子呈绿色网纹，非法放置时呈红色斜纹。拖动道路时显示从起点到…",
      "player_move_a": "the SAME player character as row 1 column 1, moving, animation frame A",
      "player_move_b": "the SAME player character as row 1 column 1, moving, animation frame B (legs opposite to frame A)",
      "player_action": "the SAME player character as row 1 column 1, action pose: 暂停期间可免费检查、规划、放置、修复和拆除，但人口、资金、灾害倒计时与失败倒计时停…",
      "player_skill_2": "the SAME player character as row 1 column 1, alternate skill pose: 拆除建筑或道路返还其原始建设费用的25%，返还额不受建筑当前损伤…",
      "player_skill_3": "the SAME player character as row 1 column 1, alternate skill pose: 玩家可支付建筑原价乘以损失生命比例再乘以0.4的费用进行修复，最…",
      "player_hurt": "the SAME player character as row 1 column 1, hurt / knockback pose, flinching",
      "player_jump": "the SAME player character as row 1 column 1, jumping / airborne pose",
      "player_death": "the SAME player character as row 1 column 1, defeated / knocked-down pose",
      "player_victory": "the SAME player character as row 1 column 1, victory celebration pose",
      "player_skill_4": "the SAME player character as row 1 column 1, alternate skill pose: 选择建筑时可预览道路网络服务路径和设施的实际覆盖范围。",
      "obstacle_1": "OBSTACLE / SOLID SCENERY: 测绘古树, 深绿树冠、浅绿高光和棕色树干，树根占据完整网格。. A blocking object with a clean readable s…",
      "obstacle_2": "OBSTACLE / SOLID SCENERY: 灰石山脊, 灰褐色层叠岩石、草缝和朝东南的短阴影。. A blocking object with a clean readable silhou…",
      "obstacle_3": "OBSTACLE / SOLID SCENERY: 排水渠, 浅蓝流水、石砌边缘、芦苇和周期性波纹。. A blocking object with a clean readable silhoue…",
      "item_1": "二星规划补助 (城市评分首次达到400时立即获得300资金；每局仅触发一次，用于补充早期扩建或纠错资金。)",
      "item_1_b": "the SAME item as @PREV_CELL@, activated state, glowing and sparkling, animation frame B"
    },
    "tileFamilies": {}
  },
  "sheets": [
    {
      "key": "sheet",
      "frameWidth": 256,
      "frameHeight": 256,
      "frames": {
        "player_idle": 0,
        "player_move_a": 1,
        "player_move_b": 2,
        "player_action": 3,
        "player_skill_2": 4,
        "player_skill_3": 5,
        "player_hurt": 6,
        "player_jump": 7,
        "player_death": 8,
        "player_victory": 9,
        "player_skill_4": 10,
        "obstacle_1": 11,
        "obstacle_2": 12,
        "obstacle_3": 13,
        "item_1": 14,
        "item_1_b": 15
      },
      "animations": {
        "player_idle": [
          "player_idle",
          "player_move_a",
          "player_move_b",
          "player_action",
          "player_skill_2",
          "player_skill_3",
          "player_hurt",
          "player_jump",
          "player_death",
          "player_victory",
          "player_skill_4"
        ],
        "item_1": [
          "item_1",
          "item_1_b"
        ]
      },
      "frameMeta": {
        "player_idle": "THE PLAYER: 玩家没有可移动市长角色，而是控制一个白色像素描边的规划光标。光标覆盖一个网格，当前工具图标悬浮在右上角；合法放置时格子呈绿色网纹，非法放置时呈红色斜纹。拖动道路时显示从起点到…",
        "player_move_a": "the SAME player character as row 1 column 1, moving, animation frame A",
        "player_move_b": "the SAME player character as row 1 column 1, moving, animation frame B (legs opposite to frame A)",
        "player_action": "the SAME player character as row 1 column 1, action pose: 暂停期间可免费检查、规划、放置、修复和拆除，但人口、资金、灾害倒计时与失败倒计时停…",
        "player_skill_2": "the SAME player character as row 1 column 1, alternate skill pose: 拆除建筑或道路返还其原始建设费用的25%，返还额不受建筑当前损伤…",
        "player_skill_3": "the SAME player character as row 1 column 1, alternate skill pose: 玩家可支付建筑原价乘以损失生命比例再乘以0.4的费用进行修复，最…",
        "player_hurt": "the SAME player character as row 1 column 1, hurt / knockback pose, flinching",
        "player_jump": "the SAME player character as row 1 column 1, jumping / airborne pose",
        "player_death": "the SAME player character as row 1 column 1, defeated / knocked-down pose",
        "player_victory": "the SAME player character as row 1 column 1, victory celebration pose",
        "player_skill_4": "the SAME player character as row 1 column 1, alternate skill pose: 选择建筑时可预览道路网络服务路径和设施的实际覆盖范围。",
        "obstacle_1": "OBSTACLE / SOLID SCENERY: 测绘古树, 深绿树冠、浅绿高光和棕色树干，树根占据完整网格。. A blocking object with a clean readable s…",
        "obstacle_2": "OBSTACLE / SOLID SCENERY: 灰石山脊, 灰褐色层叠岩石、草缝和朝东南的短阴影。. A blocking object with a clean readable silhou…",
        "obstacle_3": "OBSTACLE / SOLID SCENERY: 排水渠, 浅蓝流水、石砌边缘、芦苇和周期性波纹。. A blocking object with a clean readable silhoue…",
        "item_1": "二星规划补助 (城市评分首次达到400时立即获得300资金；每局仅触发一次，用于补充早期扩建或纠错资金。)",
        "item_1_b": "the SAME item as @PREV_CELL@, activated state, glowing and sparkling, animation frame B"
      },
      "tileFamilies": {}
    },
    {
      "key": "sheet-2",
      "frameWidth": 256,
      "frameHeight": 256,
      "frames": {
        "item_2": 0,
        "item_2_b": 1,
        "item_3": 2,
        "item_3_b": 3,
        "entity_1": 4,
        "entity_1_end": 5,
        "entity_1_corner": 6,
        "entity_1_tee": 7,
        "entity_1_cross": 8,
        "entity_2": 9,
        "entity_3": 10,
        "entity_4": 11,
        "entity_5": 12,
        "entity_6": 13,
        "projectile": 14,
        "explosion": 15
      },
      "animations": {
        "item_2": [
          "item_2",
          "item_2_b"
        ],
        "item_3": [
          "item_3",
          "item_3_b"
        ]
      },
      "frameMeta": {
        "item_2": "三星基础设施补助 (城市评分首次达到600时立即获得500资金；每局仅触发一次，足以承担部分备用水塔、电厂或灾害修复费用。)",
        "item_2_b": "the SAME item as @PREV_CELL@, activated state, glowing and sparkling, animation frame B",
        "item_3": "四星韧性基金 (城市评分首次达到800时立即获得700资金；每局仅触发一次，为大型风暴前的维修储备提供帮助，但不足以替代稳定收入。)",
        "item_3_b": "the SAME item as @PREV_CELL@, activated state, glowing and sparkling, animation frame B",
        "entity_1": "像素道路, 深灰路面、浅灰边缘和黄色中心标记，根据邻接自动显示端头、直线、转角、丁字、十字变体。 — straight piece of a connectable tile family",
        "entity_1_end": "像素道路, 深灰路面、浅灰边缘和黄色中心标记，根据邻接自动显示端头、直线、转角、丁字、十字变体。 — end piece of a connectable tile family",
        "entity_1_corner": "像素道路, 深灰路面、浅灰边缘和黄色中心标记，根据邻接自动显示端头、直线、转角、丁字、十字变体。 — corner piece of a connectable tile family",
        "entity_1_tee": "像素道路, 深灰路面、浅灰边缘和黄色中心标记，根据邻接自动显示端头、直线、转角、丁字、十字变体。 — tee piece of a connectable tile family",
        "entity_1_cross": "像素道路, 深灰路面、浅灰边缘和黄色中心标记，根据邻接自动显示端头、直线、转角、丁字、十字变体。 — cross piece of a connectable tile family",
        "entity_2": "青瓦住宅, 一格宽的米白墙体、蓝绿色屋顶、小花园和随入住率增加而亮起的四扇窗。",
        "entity_3": "金牌商业区, 黄色雨棚、橙色招牌、玻璃橱窗和屋顶通风机；正常营业时招牌闪烁。",
        "entity_4": "赤焰电厂, 橙红砖墙、两根红白烟囱、黄色警示灯和向西北飘散的灰橙像素烟。",
        "entity_5": "蓝泉水塔, 亮蓝球形水罐、银白支架、旋转水滴标牌和显示洁净度的透明水窗。",
        "entity_6": "通勤小车, 红、蓝、白三种两格像素小车，带一像素车灯。",
        "projectile": "the main projectile / bullet / thrown object, small and readable",
        "explosion": "impact explosion / burst effect"
      },
      "tileFamilies": {
        "entity_1": {
          "straight": "entity_1",
          "end": "entity_1_end",
          "corner": "entity_1_corner",
          "tee": "entity_1_tee",
          "cross": "entity_1_cross"
        }
      }
    },
    {
      "key": "sheet-3",
      "frameWidth": 256,
      "frameHeight": 256,
      "frames": {
        "flash": 0,
        "prop": 1,
        "bonus_1": 2,
        "bonus_2": 3,
        "bonus_3": 4,
        "bonus_4": 5,
        "bonus_5": 6,
        "bonus_6": 7,
        "bonus_7": 8,
        "bonus_8": 9,
        "bonus_9": 10,
        "bonus_10": 11,
        "bonus_11": 12,
        "bonus_12": 13,
        "bonus_13": 14,
        "bonus_14": 15
      },
      "animations": {},
      "frameMeta": {
        "flash": "action flash / sparkle / hit effect",
        "prop": "a themed environment prop for 像素都市规划师",
        "bonus_1": "score pickup / collectible",
        "bonus_2": "health or shield pickup",
        "bonus_3": "power-up item",
        "bonus_4": "a decorative environment prop for 像素都市规划师",
        "bonus_5": "score pickup / collectible",
        "bonus_6": "health or shield pickup",
        "bonus_7": "power-up item",
        "bonus_8": "a decorative environment prop for 像素都市规划师",
        "bonus_9": "score pickup / collectible",
        "bonus_10": "health or shield pickup",
        "bonus_11": "power-up item",
        "bonus_12": "a decorative environment prop for 像素都市规划师",
        "bonus_13": "score pickup / collectible",
        "bonus_14": "health or shield pickup"
      },
      "tileFamilies": {}
    }
  ],
  "tilemap": null,
  "levelLayout": {
    "cellWidth": 53.33,
    "cellHeight": 51.43,
    "regions": [
      {
        "id": "west_residential_terrace",
        "name": "西部住宅台地",
        "kind": "平坦低污染建设区，教学阶段推荐建立首个住宅街区",
        "x": 0.0,
        "y": 0.0,
        "width": 533.3,
        "height": 411.4
      },
      {
        "id": "central_planning_cross",
        "name": "中央规划十字区",
        "kind": "道路网络汇合区，地块规整且靠近全图中心",
        "x": 480.0,
        "y": 0.0,
        "width": 426.7,
        "height": 462.9
      },
      {
        "id": "east_industrial_buffer",
        "name": "东部工业缓冲区",
        "kind": "远离西侧住宅的设施用地，适合电厂和备用基础设施",
        "x": 853.3,
        "y": 0.0,
        "width": 426.7,
        "height": 411.4
      },
      {
        "id": "south_expansion_plain",
        "name": "南部扩建平原",
        "kind": "中后期住宅与商业扩建区，面积大但需要延伸道路网络",
        "x": 0.0,
        "y": 360.0,
        "width": 906.7,
        "height": 360.0
      },
      {
        "id": "southeast_water_lowland",
        "name": "东南蓄水低地",
        "kind": "低初始污染的供水设施候选区，靠近排水渠与风暴路径",
        "x": 853.3,
        "y": 360.0,
        "width": 426.7,
        "height": 360.0
      }
    ],
    "walls": [
      {
        "x": 586.7,
        "y": 308.6,
        "width": 160.0,
        "height": 102.9
      },
      {
        "x": 1013.3,
        "y": 514.3,
        "width": 266.7,
        "height": 102.9
      },
      {
        "x": 1173.3,
        "y": 565.7,
        "width": 106.7,
        "height": 154.3
      }
    ],
    "cover": [
      {
        "x": 53.3,
        "y": 51.4,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 213.3,
        "y": 51.4,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 373.3,
        "y": 257.1,
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
        "x": 266.7,
        "y": 617.1,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 480.0,
        "y": 514.3,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 746.7,
        "y": 102.9,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 800.0,
        "y": 617.1,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 960.0,
        "y": 51.4,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 1120.0,
        "y": 154.3,
        "width": 53.3,
        "height": 51.4
      },
      {
        "x": 906.7,
        "y": 617.1,
        "width": 53.3,
        "height": 51.4
      }
    ],
    "paths": [
      {
        "id": "tutorial_road_guide",
        "points": [
          {
            "x": 133.3,
            "y": 180.0
          },
          {
            "x": 186.7,
            "y": 180.0
          },
          {
            "x": 240.0,
            "y": 180.0
          },
          {
            "x": 293.3,
            "y": 180.0
          },
          {
            "x": 346.7,
            "y": 180.0
          },
          {
            "x": 400.0,
            "y": 180.0
          },
          {
            "x": 453.3,
            "y": 180.0
          },
          {
            "x": 506.7,
            "y": 180.0
          }
        ]
      },
      {
        "id": "city_vehicle_loop",
        "points": [
          {
            "x": 186.7,
            "y": 231.4
          },
          {
            "x": 453.3,
            "y": 231.4
          },
          {
            "x": 560.0,
            "y": 231.4
          },
          {
            "x": 560.0,
            "y": 488.6
          },
          {
            "x": 346.7,
            "y": 488.6
          },
          {
            "x": 186.7,
            "y": 488.6
          },
          {
            "x": 186.7,
            "y": 231.4
          }
        ]
      },
      {
        "id": "major_storm_track",
        "points": [
          {
            "x": 1253.3,
            "y": 128.6
          },
          {
            "x": 1040.0,
            "y": 231.4
          },
          {
            "x": 826.7,
            "y": 334.3
          },
          {
            "x": 560.0,
            "y": 437.1
          },
          {
            "x": 293.3,
            "y": 591.4
          },
          {
            "x": 80.0,
            "y": 694.3
          }
        ]
      }
    ],
    "points": [
      {
        "id": "player_spawn",
        "kind": "spawn",
        "x": 133.3,
        "y": 180.0
      },
      {
        "id": "first_district_objective",
        "kind": "objective",
        "x": 346.7,
        "y": 180.0
      },
      {
        "id": "industrial_recommendation",
        "kind": "objective",
        "x": 1040.0,
        "y": 231.4
      },
      {
        "id": "clean_water_recommendation",
        "kind": "objective",
        "x": 986.7,
        "y": 488.6
      },
      {
        "id": "storm_entry",
        "kind": "hazard",
        "x": 1253.3,
        "y": 128.6
      },
      {
        "id": "planning_grant_marker",
        "kind": "item",
        "x": 560.0,
        "y": 282.9
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
