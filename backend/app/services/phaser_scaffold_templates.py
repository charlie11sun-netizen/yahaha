"""Static source templates for the modular Phaser scaffold.

2026-07-26 拆分自 ``phaser_projects.py``:这里只有惰性字符串常量(逐字节等同
于原内联模板),一个常量对应脚手架的一个文件,按装配顺序排列。带
__TITLE__ / __CONFIG__ / __BG__ 占位符的模板由
``create_modular_phaser_project`` 在装配时替换。增删模板时同步维护
``phaser_projects.py`` 里的装配清单。
"""
from __future__ import annotations


INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>__TITLE__</title>
    <style>
      /* Critical sizing stays inline: the built bundle's deferred script can
         execute before the external stylesheet applies, and Phaser's FIT scale
         reads the parent size exactly once at boot — external CSS timing must
         never decide whether the canvas gets a size (a lost race renders the
         whole game 0x0). */
      html, body, #game-container { width: 100%; height: 100%; margin: 0; }
    </style>
  </head>
  <body>
    <main id="game-container" aria-label="Generated game"></main>
    <script type="module" src="./src/main.ts"></script>
  </body>
</html>
"""

GAME_CONFIG_TS = """// Side-effect import: installs the QA runtime probes (scene/anims/backdrop
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

export interface SemanticFrameRef {
  sheet: string;
  frame: string;
  frame_id?: string;
  frame_index: number;
  anchor?: [number, number];
  required?: boolean;
  consumer_refs?: string[];
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
  semanticFrames: Record<string, SemanticFrameRef>;
  frameAudit: Record<string, unknown>;
  frameIds: Record<string, number>;
  frameSemantics: Record<string, string>;
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
  /** Shared visual/body/timing envelopes for mechanically distinct interactions.
   * Rendering, rules, and acceptance must consume the same profile. */
  interactionProfiles: Array<Record<string, unknown>>;
  spriteDemandManifest: {
    schema_version?: string;
    demands?: Array<Record<string, unknown>>;
    runtime_manifest?: Record<string, SemanticFrameRef>;
    metrics?: Record<string, number>;
  };
}

export const gameConfig = __CONFIG__ as GeneratedGameConfig;

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

/** Resolve a semantic sprite state.  Atlas coordinates are deliberately
 * hidden behind this function so gameplay never depends on `frame index 15`.
 * `spriteFrame("residential.level_3")` remains stable when packing changes. */
export function semanticFrame(name: string): SemanticFrameRef | null {
  const direct = gameConfig.spriteDemandManifest?.runtime_manifest?.[name];
  if (direct && typeof direct.frame_index === "number") return direct;
  for (const sheet of gameConfig.sheets) {
    const frame = sheet.semanticFrames?.[name];
    if (frame && typeof frame.frame_index === "number") return { ...frame, sheet: frame.sheet || sheet.key };
  }
  return null;
}

export function spriteFrame(name: string): { key: string; index: number } | null {
  const frame = semanticFrame(name);
  return frame ? { key: frame.sheet, index: frame.frame_index } : null;
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
"""

COLORS_TS = """/** Convert a "#rrggbb" palette string to the numeric color Phaser APIs expect. */
export function colorNum(hex: string): number {
  const clean = hex.trim().replace("#", "");
  const expanded = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const value = Number.parseInt(expanded, 16);
  return Number.isFinite(value) ? value : 0xffffff;
}
"""

PROBE_TS = """import Phaser from "phaser";

/** Runtime behavior probes for automated QA.
 *
 * The QA sandbox reads `window.__GW_PROBES__.counts` after driving the game to
 * verify that declared content actually happens at runtime (scenes reached,
 * backdrops drawn, animations played, actors spawned, input processed).
 * Everything here is best-effort and bounded: a probe must never break or
 * slow the game.
 *
 * Scaffold systems report automatically (scene starts, animation playback,
 * Backdrop.draw, pointer processing, interactive registrations, key
 * registrations, display-scale discipline, text-legibility discipline,
 * area-hint affordances). Gameplay
 * code adds the calls QA reconciles against the design roster:
 * - `Probe.spawn("enemy", definition.id)` whenever an enemy or boss enters play
 * - `Probe.emit("projectile:spawn", projectileId)` when a projectile is fired
 * - `Probe.action("jump", "attempt")` when a player action reaches rules
 * - `Probe.window("low-crate", "open")` when its actionable timing window opens
 * - `Probe.outcome("low-crate", "success")` when an interaction resolves
 * - `Probe.despawn("pickup", actorId, "collected")` after its render/physics entity leaves play
 * - `Probe.status("won" | "lost")` exactly once when the rules layer reaches its terminal outcome
 * - `Probe.stat("gold", value)` for every WinScript-referenced numeric the moment it changes
 */
interface ProbeStore {
  counts: Record<string, number>;
  total: number;
}

const MAX_KEYS = 300;
const MAX_DETAIL = 80;
const MAX_INTERACTIVE_TARGETS = 80;

function store(): ProbeStore | null {
  if (typeof window === "undefined") return null;
  const host = window as unknown as { __GW_PROBES__?: ProbeStore };
  if (!host.__GW_PROBES__) host.__GW_PROBES__ = { counts: {}, total: 0 };
  return host.__GW_PROBES__;
}

export const Probe = {
  /** Count a named runtime event, optionally qualified: emit("projectile:spawn", "bolt"). */
  emit(kind: string, detail = ""): void {
    try {
      const data = store();
      if (!data) return;
      const key = detail ? `${kind}|${String(detail).slice(0, MAX_DETAIL)}` : kind;
      if (data.counts[key] === undefined && Object.keys(data.counts).length >= MAX_KEYS) return;
      data.counts[key] = (data.counts[key] ?? 0) + 1;
      data.total += 1;
    } catch {
      /* probes must never break gameplay */
    }
  },

  /** Report an actor entering play, e.g. Probe.spawn("enemy", "grunt"). */
  spawn(category: string, id: string): void {
    Probe.emit(`spawn:${category}`, id);
  },

  /** Report a real player/rules action, not merely an input event or animation. */
  action(id: string, phase: "attempt" | "start" | "triggered" | "end" = "attempt"): void {
    Probe.emit(`action:${phase}`, id);
  },

  /** Report the actionable interval for a spatial or timed interaction. */
  window(id: string, phase: "open" | "close"): void {
    Probe.emit(`window:${phase}`, id);
  },

  /** Report the rules-owned result of an interaction. */
  outcome(id: string, result: "success" | "failure" | "blocked" = "success"): void {
    Probe.emit(`outcome:${result}`, id);
  },

  /** Report that a resolved runtime entity is no longer rendered or collidable. */
  despawn(category: string, id: string, reason = "resolved"): void {
    Probe.emit(`despawn:${category}`, `${id}:${reason}`);
  },

  /** Publish a rules-owned numeric gauge (latest value wins). The QA win-path
   * simulation reads `window.__GW_STATS__` to evaluate WinScript conditions,
   * so every stat a WinScript rule references must be published on change. */
  stat(id: string, value: number): void {
    try {
      if (typeof window === "undefined" || !Number.isFinite(value)) return;
      const host = window as unknown as { __GW_STATS__?: Record<string, number> };
      if (!host.__GW_STATS__) host.__GW_STATS__ = {};
      const stats = host.__GW_STATS__;
      const key = String(id).slice(0, 40);
      if (stats[key] === undefined && Object.keys(stats).length >= 60) return;
      stats[key] = value;
    } catch {
      /* probes must never break gameplay */
    }
  },

  /** Report the rules-owned terminal outcome exactly once per run. */
  status(result: "won" | "lost"): void {
    Probe.emit("game:status", result);
  },
};

function resolvedKeyCode(key: unknown): number | undefined {
  if (typeof key === "number") return key;
  if (typeof key === "string") {
    const codes = Phaser.Input.Keyboard.KeyCodes as unknown as Record<string, number | undefined>;
    return codes[key.toUpperCase()];
  }
  if (key && typeof key === "object") return (key as { keyCode?: number }).keyCode;
  return undefined;
}

function resolvedKeyName(key: unknown, code: number | undefined): string {
  if (typeof key === "string") return key.toUpperCase();
  const codes = Phaser.Input.Keyboard.KeyCodes as unknown as Record<string, number | undefined>;
  const match = Object.entries(codes).find(([, value]) => value === code);
  return match?.[0] ?? String(code ?? "");
}

function install(): void {
  try {
    const host = window as unknown as { __GW_PROBE_HOOKS__?: boolean };
    if (host.__GW_PROBE_HOOKS__) return;
    host.__GW_PROBE_HOOKS__ = true;
    Probe.emit("probe:ready");

    const scenePrototype = Phaser.Scenes.ScenePlugin.prototype;
    const originalStart = scenePrototype.start;
    scenePrototype.start = function (this: Phaser.Scenes.ScenePlugin, key?: unknown, data?: object) {
      if (typeof key === "string" && key) Probe.emit("scene:start", key);
      return originalStart.call(this, key as never, data);
    };

    const animsPrototype = Phaser.Animations.AnimationState.prototype;
    const originalPlay = animsPrototype.play;
    animsPrototype.play = function (
      this: Phaser.Animations.AnimationState,
      key: unknown,
      ignoreIfPlaying?: boolean,
    ) {
      const name = typeof key === "string" ? key : ((key as { key?: string } | null)?.key ?? "");
      if (name) Probe.emit("anims:play", name);
      return originalPlay.call(this, key as never, ignoreIfPlaying);
    };

    // Raw input reaching the page at all (QA injects pointer/key events and
    // compares these against what the game actually processed).
    window.addEventListener("mousedown", () => Probe.emit("dom:down", "pointer"), { capture: true, passive: true });
    window.addEventListener("touchstart", () => Probe.emit("dom:down", "pointer"), { capture: true, passive: true });
    window.addEventListener("keydown", () => Probe.emit("dom:down", "key"), { capture: true, passive: true });

    // Pointer downs processed by scene input plugins. dom:down|pointer > 0
    // with input:down == 0 means the game's input pipeline is dead.
    const inputPrototype = Phaser.Input.InputPlugin.prototype as unknown as {
      processDownEvents: (pointer: Phaser.Input.Pointer) => number;
    };
    const originalProcessDown = inputPrototype.processDownEvents;
    inputPrototype.processDownEvents = function (
      this: { scene?: Phaser.Scene },
      pointer: Phaser.Input.Pointer,
    ): number {
      const sceneKey = this.scene && this.scene.scene ? this.scene.scene.key : "";
      Probe.emit("input:down", sceneKey);
      return originalProcessDown.call(this, pointer);
    };

    // Interactive registrations. A steady per-frame stream long after load
    // means UI is destroyed and rebuilt every tick — such buttons never enter
    // input hit-testing (they read as unclickable) and leak objects.
    const gameObjectPrototype = Phaser.GameObjects.GameObject.prototype as unknown as {
      setInteractive: (...args: unknown[]) => unknown;
    };
    const originalSetInteractive = gameObjectPrototype.setInteractive;
    gameObjectPrototype.setInteractive = function (
      this: Phaser.GameObjects.GameObject,
      ...args: unknown[]
    ): unknown {
      Probe.emit("ui:interactive");
      const result = originalSetInteractive.apply(this, args);
      try {
        // Keep live object references inside the page so the QA sandbox can
        // query their CURRENT bounds after menus reflow or scenes change. The
        // sandbox projects them to canvas CSS coordinates and performs a small,
        // bounded interaction exploration without relying on English labels or
        // genre-specific selectors.
        const targetHost = window as unknown as {
          __GW_INTERACTIVE_TARGETS__?: Phaser.GameObjects.GameObject[];
        };
        if (!targetHost.__GW_INTERACTIVE_TARGETS__) {
          targetHost.__GW_INTERACTIVE_TARGETS__ = [];
        }
        const targets = targetHost.__GW_INTERACTIVE_TARGETS__;
        if (
          targets.length < MAX_INTERACTIVE_TARGETS
          && !targets.includes(this)
        ) {
          targets.push(this);
        }
      } catch {
        /* bounded QA target discovery must never affect gameplay */
      }
      return result;
    };

    // Dead key registrations: addKey resolving to no key code (for example
    // KeyCodes["2"] instead of KeyCodes.TWO) registers a key that never fires.
    const keyboardPrototype = Phaser.Input.Keyboard.KeyboardPlugin.prototype as unknown as {
      addKey: (key: unknown, enableCapture?: boolean, emitOnRepeat?: boolean) => Phaser.Input.Keyboard.Key;
    };
    const originalAddKey = keyboardPrototype.addKey;
    keyboardPrototype.addKey = function (
      this: unknown,
      key: unknown,
      enableCapture?: boolean,
      emitOnRepeat?: boolean,
    ): Phaser.Input.Keyboard.Key {
      const code = resolvedKeyCode(key);
      if (!code || Number.isNaN(code)) Probe.emit("key:invalid");
      else Probe.emit("key:registered", resolvedKeyName(key, code));
      return originalAddKey.call(this, key, enableCapture, emitOnRepeat);
    };

    // A 0x0 canvas after load means the game runs but renders invisible
    // (stylesheet race or broken scale wiring).
    window.addEventListener("load", () => {
      window.setTimeout(() => {
        try {
          const canvas = document.querySelector("canvas");
          if (canvas && canvas.getBoundingClientRect().width === 0) Probe.emit("canvas:zerosize");
        } catch {
          /* bounded */
        }
      }, 600);
    });

    // Display-scale discipline. Generated sheet frames are large source art
    // (typically 256px); gameplay actors must be normalized down to their
    // logical footprint. Two failure modes are detected automatically:
    // scale:conflict — an object normalized with setDisplaySize(w, h) later
    //   receives an ABSOLUTE setScale(...): setScale is relative to the NATIVE
    //   frame size, not the normalized display size, so the actor snaps back
    //   to raw art resolution (a 48px unit re-renders at 256px).
    // scale:native — a visible sprite keeps rendering a large art frame at
    //   near-native scale, i.e. normalization never happened at all.
    const intendedSizes = new WeakMap<object, { w: number; h: number }>();
    const conflictReported = new Set<string>();
    const nativeReported = new Set<string>();
    const textBlobReported = new Set<string>();
    const textTinyReported = new Set<string>();
    const parseHexColor = (value: unknown): [number, number, number] | null => {
      const raw = String(value ?? "").trim().toLowerCase();
      const match = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
      if (!match) return null;
      const hex = match[1].length === 3
        ? match[1].split("").map((part) => part + part).join("")
        : match[1];
      return [0, 2, 4].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16)) as [number, number, number];
    };
    const contrastRatio = (left: unknown, right: unknown): number | null => {
      const a = parseHexColor(left);
      const b = parseHexColor(right);
      if (!a || !b) return null;
      const luminance = (rgb: [number, number, number]): number => {
        const channels = rgb.map((channel) => {
          const value = channel / 255;
          return value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
        });
        return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
      };
      const la = luminance(a);
      const lb = luminance(b);
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    };
    const textureOf = (target: object): string => {
      const texture = (target as { texture?: { key?: string } }).texture;
      return texture && typeof texture.key === "string" ? texture.key : "untextured";
    };
    const sizedPrototypes: object[] = [
      Phaser.GameObjects.Sprite.prototype,
      Phaser.GameObjects.Image.prototype,
    ];
    for (const proto of sizedPrototypes) {
      const sized = proto as {
        setDisplaySize?: (width: number, height: number) => unknown;
        setScale?: (x?: number, y?: number) => unknown;
      };
      if (typeof sized.setDisplaySize !== "function" || typeof sized.setScale !== "function") continue;
      const originalSetDisplaySize = sized.setDisplaySize;
      sized.setDisplaySize = function (this: object, width: number, height: number): unknown {
        const result = originalSetDisplaySize.call(this, width, height);
        if (Number.isFinite(width) && width > 0) intendedSizes.set(this, { w: width, h: height });
        return result;
      };
      const originalSetScale = sized.setScale;
      sized.setScale = function (this: object, x?: number, y?: number): unknown {
        const result = originalSetScale.call(this, x, y);
        const intended = intendedSizes.get(this);
        if (intended) {
          const displayWidth = Math.abs(Number((this as { displayWidth?: number }).displayWidth) || 0);
          if (displayWidth > intended.w * 2.5) {
            const key = textureOf(this);
            if (!conflictReported.has(key) && conflictReported.size < 24) {
              conflictReported.add(key);
              Probe.emit("scale:conflict", key);
            }
          }
        }
        return result;
      };
    }

    // Capture the live Game instance without a global registry.
    let liveGame: Phaser.Game | null = null;
    const gamePrototype = Phaser.Game.prototype as unknown as {
      step: (time: number, delta: number) => void;
    };
    const originalStep = gamePrototype.step;
    gamePrototype.step = function (this: Phaser.Game, time: number, delta: number): void {
      liveGame = this;
      return originalStep.call(this, time, delta);
    };

    const sampleNativeScale = (): void => {
      try {
        const game = liveGame;
        if (!game || !game.scene) return;
        const canvasWidth = Number(game.scale && game.scale.width) || 1280;
        for (const scene of game.scene.getScenes(true)) {
          const children = (scene.children && scene.children.list) || [];
          let inspected = 0;
          for (const child of children) {
            if (inspected++ > 1500) break;
            const target = child as {
              visible?: boolean;
              alpha?: number;
              depth?: number;
              frame?: { realWidth?: number; width?: number; name?: string | number };
              displayWidth?: number;
              scaleX?: number;
              getData?: (key: string) => unknown;
              texture?: { key?: string };
            };
            if (!target.visible || (target.alpha ?? 1) < 0.05) continue;
            // The backdrop band and tagged scenery legitimately render huge.
            if ((target.depth ?? 0) <= -10) continue;
            if (typeof target.getData === "function" && target.getData("gwScenery")) continue;
            const frame = target.frame;
            const frameWidth = Number(frame && (frame.realWidth ?? frame.width)) || 0;
            const textureKey = (target.texture && target.texture.key) || "";
            if (!frame || frameWidth < 96 || !textureKey || textureKey.startsWith("__")) continue;
            const displayWidth = Math.abs(Number(target.displayWidth) || 0);
            const scaleX = Math.abs(Number(target.scaleX) || 0);
            if (scaleX < 0.9 || displayWidth < 120) continue;
            // Full-bleed art (covers, splashes) is plausibly intentional.
            if (displayWidth >= canvasWidth * 0.85) continue;
            if (nativeReported.size >= 24) return;
            const reportKey = `${textureKey}#${String(frame.name ?? "")}`;
            if (!nativeReported.has(reportKey)) {
              nativeReported.add(reportKey);
              Probe.emit("scale:native", reportKey);
            }
          }
        }
      } catch {
        /* sampling is best-effort */
      }
    };
    const sampleTextLegibility = (): void => {
      try {
        const game = liveGame;
        if (!game || !game.scene || !game.canvas) return;
        const rect = game.canvas.getBoundingClientRect();
        const logicalWidth = Math.max(1, Number(game.scale && game.scale.width) || game.canvas.width || 1);
        const logicalHeight = Math.max(1, Number(game.scale && game.scale.height) || game.canvas.height || 1);
        const cssScale = Math.max(0.01, Math.min(rect.width / logicalWidth, rect.height / logicalHeight));
        for (const scene of game.scene.getScenes(true)) {
          const children = (scene.children && scene.children.list) || [];
          // Text inside a Phaser Container is removed from the scene display
          // list, so walk nested container lists too. Most HUDs and card/shop
          // UIs are container-based; sampling only top-level children would
          // systematically miss the text that matters most.
          const pending = [...children] as object[];
          let inspected = 0;
          for (let index = 0; index < pending.length && inspected < 1500; index += 1) {
            inspected += 1;
            const child = pending[index];
            const target = child as {
              type?: string;
              visible?: boolean;
              alpha?: number;
              depth?: number;
              scaleY?: number;
              scrollFactorX?: number;
              scrollFactorY?: number;
              text?: unknown;
              input?: { enabled?: boolean };
              list?: object[];
              parentContainer?: {
                visible?: boolean;
                alpha?: number;
                depth?: number;
                scaleY?: number;
                scrollFactorX?: number;
                scrollFactorY?: number;
              };
              style?: {
                fontSize?: string | number;
                strokeThickness?: number;
                color?: string;
                stroke?: string;
              };
            };
            if (Array.isArray(target.list)) pending.push(...target.list);
            const parent = target.parentContainer;
            if (target.type !== "Text" || !target.visible || (target.alpha ?? 1) < 0.1) continue;
            if (parent && (!parent.visible || (parent.alpha ?? 1) < 0.1)) continue;
            const text = String(target.text ?? "").trim().replace(/\\s+/g, " ");
            if (!text) continue;
            const style = target.style;
            const fontPx = Number.parseFloat(String(style && style.fontSize || "0"));
            if (!Number.isFinite(fontPx) || fontPx <= 0) continue;
            const strokePx = Math.max(0, Number(style && style.strokeThickness) || 0);
            const objectScale = Math.abs(Number(target.scaleY) || 1) * Math.abs(Number(parent && parent.scaleY) || 1);
            const effectivePx = fontPx * objectScale * cssScale;
            const denseGlyphs = /[\u2e80-\u9fff\u3040-\u30ff\uac00-\ud7af]/.test(text);
            const strokeLimit = denseGlyphs ? 0.10 : 0.16;
            const contrast = contrastRatio(style && style.color, style && style.stroke);
            const excessiveStroke = strokePx >= 2 && strokePx / fontPx > strokeLimit;
            const sameToneStroke = strokePx >= 1 && contrast !== null && contrast < 1.45;
            const sceneKey = scene.scene && scene.scene.key ? scene.scene.key : "scene";
            const sample = text.slice(0, 18).replace(/[,|]/g, " ");
            const parentDepth = Number(parent && parent.depth) || 0;
            const hudLike = Boolean(
              target.input && target.input.enabled
              || target.scrollFactorX === 0
              || target.scrollFactorY === 0
              || (parent && (parent.scrollFactorX === 0 || parent.scrollFactorY === 0))
              || (Number(target.depth) || 0) >= 100
              || parentDepth >= 100
            );
            // Ignore large title lettering and short incidental score pops;
            // a compact multi-word label is still checked even if an author
            // forgot the normal HUD depth/scroll-factor conventions.
            const essentialLike = hudLike || text.length >= 6;
            if (
              essentialLike
              && text.length >= 2
              && effectivePx <= 32
              && (excessiveStroke || sameToneStroke)
              && textBlobReported.size < 24
            ) {
              const detail = `${sceneKey},font=${fontPx.toFixed(1)},stroke=${strokePx.toFixed(1)},contrast=${contrast === null ? "?" : contrast.toFixed(2)},text=${sample}`;
              if (!textBlobReported.has(detail)) {
                textBlobReported.add(detail);
                Probe.emit("text:blob", detail);
              }
            }
            if (hudLike && text.length >= 2 && effectivePx < 12 && textTinyReported.size < 24) {
              const detail = `${sceneKey},effective=${effectivePx.toFixed(1)},source=${fontPx.toFixed(1)},text=${sample}`;
              if (!textTinyReported.has(detail)) {
                textTinyReported.add(detail);
                Probe.emit("text:tiny", detail);
              }
            }
          }
        }
      } catch {
        /* sampling is best-effort */
      }
    };
    for (const delayMs of [2500, 5500, 9500]) {
      window.setTimeout(sampleNativeScale, delayMs);
      window.setTimeout(sampleTextLegibility, delayMs + 100);
    }
  } catch {
    /* instrumentation is best-effort */
  }
}

install();
"""

INPUT_ROUTER_TS = """import Phaser from "phaser";

/** Pointer routing that keeps WORLD input (build/aim/select on the stage)
 * from firing underneath UI (HUD buttons, toolbars, panels, modals).
 *
 * Phaser delivers scene-level pointer events regardless of what was clicked:
 * a raw `scene.input.on("pointerdown", ...)` world handler ALSO fires when the
 * player presses a HUD button, placing/attacking/selecting behind the UI.
 * Register world handlers through `InputRouter.worldPointer` instead — they
 * are skipped whenever the pointer is over ANY interactive object, while a
 * drag that started on the stage keeps streaming to the world even if it
 * crosses UI mid-drag.
 *
 * Plain panels (non-interactive rectangles behind HUD text) do not block
 * clicks by themselves: call `InputRouter.shield(panel)` on every opaque UI
 * surface so presses on it stop reaching the world layer. */
export interface WorldPointerHandlers {
  down?(pointer: Phaser.Input.Pointer): void;
  move?(pointer: Phaser.Input.Pointer): void;
  up?(pointer: Phaser.Input.Pointer): void;
}

export const InputRouter = {
  /** Route stage-level pointer input, skipping presses that land on UI.
   * Returns a dispose function (also runs automatically on scene shutdown). */
  worldPointer(scene: Phaser.Scene, handlers: WorldPointerHandlers): () => void {
    let worldDrag = false;
    const onDown = (pointer: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]): void => {
      if (over.length > 0) return; // pointer is on UI — the world must not react
      worldDrag = true;
      handlers.down?.(pointer);
    };
    const onMove = (pointer: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]): void => {
      if (!worldDrag && over.length > 0) return;
      handlers.move?.(pointer);
    };
    const onUp = (pointer: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]): void => {
      const startedOnWorld = worldDrag;
      worldDrag = false;
      if (!startedOnWorld && over.length > 0) return;
      handlers.up?.(pointer);
    };
    scene.input.on("pointerdown", onDown);
    scene.input.on("pointermove", onMove);
    scene.input.on("pointerup", onUp);
    const dispose = (): void => {
      scene.input.off("pointerdown", onDown);
      scene.input.off("pointermove", onMove);
      scene.input.off("pointerup", onUp);
    };
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, dispose);
    return dispose;
  },

  /** Make a UI surface swallow pointer input so world handlers skip its area.
   * Call on every opaque panel/bar rectangle that is not itself a button.
   * (Containers need an explicit hit area — shield the background rectangle
   * inside them, not the container.) */
  shield<T extends Phaser.GameObjects.GameObject>(surface: T): T {
    if (!surface.input) surface.setInteractive();
    return surface;
  },
};
"""

BACKDROP_TS = """import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "./Colors";
import { Probe } from "./Probe";

/** Show a generated background image when one exists (cover-fit at the
 * lowest depth, dimmed toward the palette bg so gameplay sprites stay
 * readable). Returns null when no background asset was generated — callers
 * fall back to a palette gradient.
 *
 * Several scene variants may exist (gameConfig.assetKeys.backgrounds: main
 * stage, high-intensity / boss phase, alternate zone). Switch stages with
 * Backdrop.swap: it crossfades from the current backdrop to the named one —
 * call it on phase changes (boss spawn, new wave tier, level change). */
export const Backdrop = {
  /** Omit `dim` to use the measured per-image strength (gameConfig.backdropDims):
   * generated dark art gets a light overlay, bright art a stronger one — never
   * double-darken an already moody scene. Pass an explicit dim only for special
   * screens (e.g. the title screen dims harder behind its text). */
  draw(scene: Phaser.Scene, dim?: number, key?: string): Phaser.GameObjects.Image | null {
    const textureKey = key ?? gameConfig.assetKeys.background;
    if (!textureKey || !scene.textures.exists(textureKey)) return null;
    Probe.emit("backdrop:draw", scene.scene.key);
    const { width, height } = scene.scale;
    const image = scene.add.image(width / 2, height / 2, textureKey).setDepth(-20);
    // Scenery tag: the QA scale probe must not read cover-fit background art
    // as an unnormalized gameplay sprite.
    image.setData("gwScenery", true);
    const scale = Math.max(width / image.width, height / image.height);
    image.setScale(scale);
    const applied = dim ?? gameConfig.backdropDims[textureKey] ?? 0.35;
    if (applied > 0) {
      scene.add
        .rectangle(width / 2, height / 2, width, height, colorNum(gameConfig.palette.bg), applied)
        .setDepth(-19);
    }
    return image;
  },

  /** Crossfade the stage to another generated scene variant. `current` is the
   * image returned by draw()/swap() (null-safe); returns the new backdrop (or
   * the old one when the target texture is missing). */
  swap(
    scene: Phaser.Scene,
    current: Phaser.GameObjects.Image | null,
    key: string,
    durationMs = 600,
  ): Phaser.GameObjects.Image | null {
    if (!key || !scene.textures.exists(key)) return current;
    const next = this.draw(scene, 0, key);
    if (!next) return current;
    // 在旧背景之上、暗化层(-19)之下淡入,交叉渐变全程可见。
    next.setDepth(-19.5).setAlpha(0);
    scene.tweens.add({
      targets: next,
      alpha: 1,
      duration: durationMs,
      onComplete: () => {
        next.setDepth(-20);
        current?.destroy();
      },
    });
    return next;
  },
};
"""

AREA_HINT_TS = """import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "./Colors";
import { Probe } from "./Probe";

/** In-world affordances for spatial mechanics. The rule, for every genre:
 * every range/radius/area number a game rule consults must be VISIBLE to the
 * player at the moment they can act on it — attack/effect radius on selection
 * or hover, coverage while previewing a placement, blast area while aiming,
 * aura extent while a buff runs. A mechanic the player can only guess at
 * reads as a broken game, not a subtle one.
 *
 * Hints are keyed per scene: drawing the same key again just redraws it in
 * place (safe to call every frame from a hover/drag handler), `hide(key)`
 * conceals one, `clear()` removes all. Styling defaults to the game palette.
 * Hints report `hint:area` probes automatically; QA reconciles them against
 * designs that declare ranged/area mechanics. */
export interface AreaHintStyle {
  /** "#rrggbb"; defaults to gameConfig.palette.accent. */
  color?: string;
  fillAlpha?: number;
  lineAlpha?: number;
  lineWidth?: number;
  depth?: number;
}

const registries = new WeakMap<Phaser.Scene, Map<string, Phaser.GameObjects.Graphics>>();

function registry(scene: Phaser.Scene): Map<string, Phaser.GameObjects.Graphics> {
  let map = registries.get(scene);
  if (!map) {
    map = new Map();
    registries.set(scene, map);
    scene.events.once(Phaser.Scenes.Events.SHUTDOWN, () => registries.delete(scene));
  }
  return map;
}

function hintGraphics(
  scene: Phaser.Scene,
  key: string,
  style: AreaHintStyle | undefined,
  kind: string,
): Phaser.GameObjects.Graphics {
  const map = registry(scene);
  let gfx = map.get(key);
  if (!gfx || !gfx.scene) {
    gfx = scene.add.graphics();
    map.set(key, gfx);
    Probe.emit("hint:area", kind);
  }
  gfx.clear();
  gfx.setVisible(true);
  gfx.setDepth(style?.depth ?? 5);
  return gfx;
}

function hintColor(style: AreaHintStyle | undefined): number {
  return colorNum(style?.color ?? gameConfig.palette.accent);
}

export const AreaHint = {
  /** Circular extent (attack/effect/aggro/heal radius) centered on (x, y). */
  circle(
    scene: Phaser.Scene,
    key: string,
    x: number,
    y: number,
    radius: number,
    style?: AreaHintStyle,
  ): Phaser.GameObjects.Graphics {
    const gfx = hintGraphics(scene, key, style, "circle");
    const color = hintColor(style);
    gfx.fillStyle(color, style?.fillAlpha ?? 0.1);
    gfx.fillCircle(x, y, radius);
    gfx.lineStyle(style?.lineWidth ?? 2, color, style?.lineAlpha ?? 0.55);
    gfx.strokeCircle(x, y, radius);
    return gfx;
  },

  /** Rectangular extent (placement footprint, zone coverage) centered on (x, y). */
  rect(
    scene: Phaser.Scene,
    key: string,
    x: number,
    y: number,
    width: number,
    height: number,
    style?: AreaHintStyle,
  ): Phaser.GameObjects.Graphics {
    const gfx = hintGraphics(scene, key, style, "rect");
    const color = hintColor(style);
    gfx.fillStyle(color, style?.fillAlpha ?? 0.1);
    gfx.fillRect(x - width / 2, y - height / 2, width, height);
    gfx.lineStyle(style?.lineWidth ?? 2, color, style?.lineAlpha ?? 0.55);
    gfx.strokeRect(x - width / 2, y - height / 2, width, height);
    return gfx;
  },

  /** Conceal one hint (cheap to re-show with the same key). */
  hide(scene: Phaser.Scene, key: string): void {
    const gfx = registries.get(scene)?.get(key);
    if (gfx && gfx.scene) gfx.setVisible(false);
  },

  /** Remove every hint in the scene (e.g. on deselect-all). */
  clear(scene: Phaser.Scene): void {
    const map = registries.get(scene);
    if (!map) return;
    for (const gfx of map.values()) {
      if (gfx.scene) gfx.destroy();
    }
    map.clear();
  },
};
"""

LEVEL_LAYOUT_TS = """import Phaser from "phaser";
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
"""

BOUNDS_TS = """import Phaser from "phaser";

export type Actor = Phaser.GameObjects.Sprite | Phaser.GameObjects.Image;

/** World-edge handling. EVERY moving actor must use exactly one of these —
 * bodies that ignore the world edge drift offscreen and linger forever:
 * - collideWorld: contained actors (players, bouncing hazards, arena enemies)
 * - clamp: steered actors you position manually each tick
 * - wrap: asteroids-style screen wrapping
 * - despawnOutside: projectiles and spawned waves (call it in a timer or update) */
export const Bounds = {
  /** Keep an Arcade body inside the world; bounce > 0 makes it ricochet. */
  collideWorld(actor: Actor, bounce = 0): void {
    const body = actor.body as Phaser.Physics.Arcade.Body | null;
    if (!body) return;
    body.setCollideWorldBounds(true);
    if (bounce > 0) body.setBounce(bounce, bounce);
  },

  /** Clamp a manually-steered actor inside the camera view. */
  clamp(scene: Phaser.Scene, actor: Actor, inset = 24): void {
    actor.x = Phaser.Math.Clamp(actor.x, inset, scene.scale.width - inset);
    actor.y = Phaser.Math.Clamp(actor.y, inset, scene.scale.height - inset);
  },

  /** Wrap an actor to the opposite edge once it fully leaves the screen. */
  wrap(scene: Phaser.Scene, actor: Actor, margin = 32): void {
    const w = scene.scale.width;
    const h = scene.scale.height;
    if (actor.x < -margin) actor.x = w + margin;
    else if (actor.x > w + margin) actor.x = -margin;
    if (actor.y < -margin) actor.y = h + margin;
    else if (actor.y > h + margin) actor.y = -margin;
  },

  /** Destroy group members that left the screen by more than margin. */
  despawnOutside(scene: Phaser.Scene, group: Phaser.GameObjects.Group, margin = 64): number {
    const w = scene.scale.width;
    const h = scene.scale.height;
    let removed = 0;
    for (const child of group.getChildren().slice()) {
      const actor = child as Actor;
      if (!actor.active) continue;
      if (actor.x < -margin || actor.x > w + margin || actor.y < -margin || actor.y > h + margin) {
        actor.destroy();
        removed += 1;
      }
    }
    return removed;
  },
};
"""

GAME_STATE_TS = """import { Probe } from "./Probe";

export type GameStatus = "playing" | "won" | "lost";

export class GameState {
  score = 0;
  status: GameStatus = "playing";

  constructor(
    public lives: number,
    readonly targetScore: number,
  ) {
    Probe.stat("score", 0);
    Probe.stat("lives", lives);
  }

  addScore(points: number): void {
    if (this.status !== "playing") return;
    this.score += points;
    Probe.stat("score", this.score);
    if (this.score >= this.targetScore) {
      this.status = "won";
      Probe.status("won");
    }
  }

  loseLife(): void {
    if (this.status !== "playing") return;
    this.lives = Math.max(0, this.lives - 1);
    Probe.stat("lives", this.lives);
    if (this.lives === 0) {
      this.status = "lost";
      Probe.status("lost");
    }
  }
}
"""

GAME_WEAVE_BRIDGE_TS = """/** Sandboxed, host-backed persistence for saves, settings, and key bindings.
 * Generated games must not access browser storage directly. The GameWeave host
 * namespaces values by game id and answers through this postMessage bridge.
 * In the isolated QA sandbox (where no host answers), an in-memory fallback keeps
 * the game playable and load() resolves quickly instead of hanging startup. */

type StoredValue = unknown;

type StorageResponse = {
  type: "gameweave:storage:response";
  requestId: string;
  ok: boolean;
  found?: boolean;
  value?: StoredValue;
  error?: string;
};

type CloneResult<T> = { ok: true; value: T } | { ok: false };

export class GameWeaveBridge {
  private static readonly memory = new Map<string, StoredValue>();
  private static sequence = 0;

  private static safeSlot(slot: string): string {
    const normalized = String(slot || "default").replace(/[^A-Za-z0-9_.-]/g, "-").slice(0, 64);
    return normalized || "default";
  }

  /** JSON-only values keep host persistence deterministic and give the memory
   * fallback value semantics: callers never share an object reference with the
   * cached copy. The byte check mirrors the host's per-slot limit. */
  private static clone<T>(value: T): CloneResult<T> {
    const ancestors = new Set<object>();
    const isJsonValue = (candidate: unknown): boolean => {
      if (candidate === null || typeof candidate === "string" || typeof candidate === "boolean") return true;
      if (typeof candidate === "number") return Number.isFinite(candidate);
      if (typeof candidate !== "object" || ancestors.has(candidate)) return false;
      const prototype = Object.getPrototypeOf(candidate);
      if (!Array.isArray(candidate) && prototype !== Object.prototype && prototype !== null) return false;
      if (Object.getOwnPropertySymbols(candidate).length > 0) return false;
      ancestors.add(candidate);
      try {
        if (Array.isArray(candidate)) {
          for (let index = 0; index < candidate.length; index += 1) {
            if (!(index in candidate) || !isJsonValue(candidate[index])) return false;
          }
        } else {
          for (const key of Object.keys(candidate)) {
            if (!isJsonValue((candidate as Record<string, unknown>)[key])) return false;
          }
        }
        return true;
      } finally {
        ancestors.delete(candidate);
      }
    };
    try {
      if (!isJsonValue(value)) return { ok: false };
      const encoded = JSON.stringify(value);
      if (typeof encoded !== "string" || new TextEncoder().encode(encoded).byteLength > 64 * 1024) {
        return { ok: false };
      }
      return { ok: true, value: JSON.parse(encoded) as T };
    } catch {
      return { ok: false };
    }
  }

  static save(slot: string, value: StoredValue, timeoutMs = 250): Promise<boolean> {
    const key = GameWeaveBridge.safeSlot(slot);
    const cloned = GameWeaveBridge.clone(value);
    if (!cloned.ok) return Promise.resolve(false);
    const hadPrevious = GameWeaveBridge.memory.has(key);
    const previous = GameWeaveBridge.memory.get(key);
    GameWeaveBridge.memory.set(key, cloned.value);
    const requestId = `gw-storage-${Date.now()}-${++GameWeaveBridge.sequence}`;
    return new Promise<boolean>((resolve) => {
      let settled = false;
      let timer = 0;
      const finish = (ok: boolean, rollback = false): void => {
        if (settled) return;
        settled = true;
        window.removeEventListener("message", onMessage);
        window.clearTimeout(timer);
        if (rollback) {
          if (hadPrevious) GameWeaveBridge.memory.set(key, previous);
          else GameWeaveBridge.memory.delete(key);
        }
        resolve(ok);
      };
      const onMessage = (event: MessageEvent<StorageResponse>): void => {
        if (event.source !== window.parent) return;
        const data = event.data;
        if (!data || data.type !== "gameweave:storage:response" || data.requestId !== requestId) return;
        finish(data.ok, !data.ok);
      };
      // Keep the in-memory copy for a hostless QA sandbox, but do not claim
      // durable persistence unless the host explicitly acknowledges the write.
      timer = window.setTimeout(() => finish(false), Math.max(50, timeoutMs));
      window.addEventListener("message", onMessage);
      try {
        window.parent.postMessage({ type: "gameweave:storage:set", key, value: cloned.value, requestId }, "*");
      } catch {
        finish(false, true);
      }
    });
  }

  static load<T>(slot: string, fallback: T, timeoutMs = 250): Promise<T> {
    const key = GameWeaveBridge.safeSlot(slot);
    const clonedFallback = GameWeaveBridge.clone(fallback);
    const safeFallback = clonedFallback.ok ? clonedFallback.value : fallback;
    const memoryValue = GameWeaveBridge.memory.has(key) ? GameWeaveBridge.memory.get(key) : safeFallback;
    const clonedMemory = GameWeaveBridge.clone(memoryValue as T);
    const memoryFallback = clonedMemory.ok ? clonedMemory.value : safeFallback;
    const requestId = `gw-storage-${Date.now()}-${++GameWeaveBridge.sequence}`;
    return new Promise<T>((resolve) => {
      let settled = false;
      let timer = 0;
      const finish = (value: T): void => {
        if (settled) return;
        settled = true;
        window.removeEventListener("message", onMessage);
        window.clearTimeout(timer);
        resolve(value);
      };
      const onMessage = (event: MessageEvent<StorageResponse>): void => {
        if (event.source !== window.parent) return;
        const data = event.data;
        if (!data || data.type !== "gameweave:storage:response" || data.requestId !== requestId) return;
        if (data.ok && data.found) {
          const remote = GameWeaveBridge.clone(data.value as T);
          if (!remote.ok) return finish(memoryFallback);
          const cached = GameWeaveBridge.clone(remote.value);
          if (cached.ok) GameWeaveBridge.memory.set(key, cached.value);
          finish(remote.value);
        } else if (data.ok) {
          GameWeaveBridge.memory.delete(key);
          const freshFallback = GameWeaveBridge.clone(fallback);
          finish(freshFallback.ok ? freshFallback.value : fallback);
        } else {
          finish(memoryFallback);
        }
      };
      timer = window.setTimeout(() => finish(memoryFallback), Math.max(50, timeoutMs));
      window.addEventListener("message", onMessage);
      try {
        window.parent.postMessage({ type: "gameweave:storage:get", key, requestId }, "*");
      } catch {
        finish(memoryFallback);
      }
    });
  }
}
"""

SFX_TS = """/** Procedural WebAudio sound presets — no audio files, sandbox-safe.
 * Call Sfx.play("pickup" | "hit" | ...) on gameplay events; every key action
 * should be audible. playPitched() steps pitch up for combo chains. */
export type SfxName =
  | "pickup"
  | "hit"
  | "shoot"
  | "explosion"
  | "powerup"
  | "jump"
  | "select"
  | "win"
  | "lose";

interface TonePreset {
  wave: OscillatorType;
  from: number;
  to: number;
  duration: number;
  volume: number;
}

const PRESETS: Record<SfxName, TonePreset> = {
  pickup: { wave: "triangle", from: 660, to: 990, duration: 0.09, volume: 0.35 },
  hit: { wave: "square", from: 220, to: 90, duration: 0.14, volume: 0.4 },
  shoot: { wave: "square", from: 880, to: 320, duration: 0.08, volume: 0.25 },
  explosion: { wave: "sawtooth", from: 200, to: 32, duration: 0.42, volume: 0.5 },
  powerup: { wave: "triangle", from: 330, to: 880, duration: 0.28, volume: 0.4 },
  jump: { wave: "sine", from: 330, to: 590, duration: 0.12, volume: 0.3 },
  select: { wave: "sine", from: 520, to: 640, duration: 0.06, volume: 0.25 },
  win: { wave: "triangle", from: 440, to: 880, duration: 0.5, volume: 0.45 },
  lose: { wave: "sawtooth", from: 260, to: 70, duration: 0.6, volume: 0.4 },
};

export class Sfx {
  private static ctx: AudioContext | null = null;
  private static masterVolume = 1;

  /** Global 0..1 gain used by generated settings menus. */
  static setMasterVolume(value: number): number {
    const finite = Number.isFinite(value) ? value : 1;
    Sfx.masterVolume = Math.max(0, Math.min(1, finite));
    return Sfx.masterVolume;
  }

  static getMasterVolume(): number {
    return Sfx.masterVolume;
  }

  private static context(): AudioContext | null {
    if (typeof window === "undefined" || typeof window.AudioContext !== "function") return null;
    if (!Sfx.ctx) {
      try {
        Sfx.ctx = new window.AudioContext();
      } catch {
        return null;
      }
    }
    if (Sfx.ctx.state === "suspended") void Sfx.ctx.resume();
    return Sfx.ctx;
  }

  /** Play a named preset. Never throws — sound must not break gameplay. */
  static play(name: SfxName, volume = 1): void {
    Sfx.tone(PRESETS[name], 1, volume);
  }

  /** Same preset shifted by semitone steps — rising pitch sells combo chains. */
  static playPitched(name: SfxName, steps: number, volume = 1): void {
    Sfx.tone(PRESETS[name], Math.pow(2, steps / 12), volume);
  }

  private static tone(preset: TonePreset, multiplier: number, volume: number): void {
    try {
      const effectiveVolume = preset.volume * Math.max(0, volume) * Sfx.masterVolume;
      if (effectiveVolume <= 0) return;
      const ctx = Sfx.context();
      if (!ctx) return;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const now = ctx.currentTime;
      osc.type = preset.wave;
      osc.frequency.setValueAtTime(Math.max(1, preset.from * multiplier), now);
      osc.frequency.exponentialRampToValueAtTime(Math.max(1, preset.to * multiplier), now + preset.duration);
      gain.gain.setValueAtTime(Math.max(0.0001, effectiveVolume), now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + preset.duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + preset.duration + 0.02);
    } catch {
      /* sound must never break gameplay */
    }
  }
}
"""

JUICE_TS = """import Phaser from "phaser";

type Tintable = { setTintFill: (color: number) => unknown; clearTint: () => unknown };

/** Layered gameplay feedback helpers. A satisfying hit combines several:
 * hitFlash + burst + shake (+ hitStop on big impacts) + an Sfx preset.
 * Score gains get floatText; UI reactions get pulse. Prefer these helpers
 * over reinventing effects so feedback stays consistent. */
export class Juice {
  private frozen = false;

  constructor(private readonly scene: Phaser.Scene) {}

  /** White hit-flash on a sprite/image, auto-restored. */
  hitFlash(target: Tintable, ms = 60): void {
    try {
      target.setTintFill(0xffffff);
      this.scene.time.delayedCall(ms, () => {
        try {
          target.clearTint();
        } catch {
          /* target may already be destroyed */
        }
      });
    } catch {
      /* non-tintable targets are fine to ignore */
    }
  }

  /** Camera shake; keep intensity small (0.004-0.01) for readability. */
  shake(intensity = 0.008, duration = 120): void {
    this.scene.cameras.main.shake(duration, intensity);
  }

  /** Full-screen flash, e.g. on player damage (danger color) or pickup. */
  flash(red = 255, green = 255, blue = 255, duration = 80): void {
    this.scene.cameras.main.flash(duration, red, green, blue, false);
  }

  /** Freeze physics for a beat on heavy impacts — imperceptible but felt. */
  hitStop(ms = 70): void {
    if (this.frozen) return;
    try {
      const world = this.scene.physics.world;
      this.frozen = true;
      world.pause();
      this.scene.time.delayedCall(ms, () => {
        world.resume();
        this.frozen = false;
      });
    } catch {
      this.frozen = false;
    }
  }

  /** One-shot particle burst at a point (uses an additive glow blend). */
  burst(x: number, y: number, texture: string, count = 12, speed = 170): void {
    try {
      const emitter = this.scene.add.particles(x, y, texture, {
        speed: { min: speed * 0.4, max: speed },
        lifespan: 450,
        scale: { start: 0.9, end: 0 },
        blendMode: Phaser.BlendModes.ADD,
        emitting: false,
      });
      emitter.setDepth(60);
      emitter.explode(count);
      this.scene.time.delayedCall(650, () => emitter.destroy());
    } catch {
      /* missing texture must not crash gameplay */
    }
  }

  /** Floating score/status text that drifts up and fades. */
  floatText(x: number, y: number, text: string, color = "#ffffff", size = 20): void {
    const label = this.scene.add
      .text(x, y, text, {
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: `${size}px`,
        color,
        stroke: "#020617",
        strokeThickness: 4,
      })
      .setOrigin(0.5)
      .setDepth(90);
    this.scene.tweens.add({
      targets: label,
      y: y - 46,
      alpha: 0,
      duration: 650,
      ease: "Quad.easeOut",
      onComplete: () => label.destroy(),
    });
  }

  /** Quick scale pulse for pickups, buttons, HUD reactions. The factor is
   * RELATIVE to the target's current scale: a display-size-normalized sheet
   * sprite pulses around its gameplay size instead of snapping back to raw
   * art resolution (an absolute `scale: 1.15` tween would balloon a 48px
   * actor to its native 256px frame for the duration of the pulse). */
  pulse(target: object, factor = 1.15, duration = 110): void {
    const scalable = target as { scaleX?: number; scaleY?: number };
    const baseX =
      typeof scalable.scaleX === "number" && Number.isFinite(scalable.scaleX) ? scalable.scaleX : 1;
    const baseY =
      typeof scalable.scaleY === "number" && Number.isFinite(scalable.scaleY) ? scalable.scaleY : 1;
    this.scene.tweens.add({
      targets: target,
      scaleX: baseX * factor,
      scaleY: baseY * factor,
      yoyo: true,
      duration,
      ease: "Back.easeOut",
    });
  }
}
"""

PLAYER_TS = """import Phaser from "phaser";

export class Player extends Phaser.Physics.Arcade.Sprite {
  private readonly cursors: Phaser.Types.Input.Keyboard.CursorKeys;
  private readonly wasd: Record<"W" | "A" | "S" | "D", Phaser.Input.Keyboard.Key>;

  constructor(
    scene: Phaser.Scene,
    x: number,
    y: number,
    texture: string,
    private readonly moveSpeed: number,
  ) {
    super(scene, x, y, texture);
    scene.add.existing(this);
    scene.physics.add.existing(this);
    this.setCollideWorldBounds(true).setDepth(10);
    this.setDisplaySize(42, 42);
    this.cursors = scene.input.keyboard!.createCursorKeys();
    this.wasd = scene.input.keyboard!.addKeys("W,A,S,D") as Record<
      "W" | "A" | "S" | "D",
      Phaser.Input.Keyboard.Key
    >;
  }

  update(): void {
    const horizontal = Number(this.cursors.right.isDown || this.wasd.D.isDown)
      - Number(this.cursors.left.isDown || this.wasd.A.isDown);
    const vertical = Number(this.cursors.down.isDown || this.wasd.S.isDown)
      - Number(this.cursors.up.isDown || this.wasd.W.isDown);
    const direction = new Phaser.Math.Vector2(horizontal, vertical).normalize();
    this.setVelocity(direction.x * this.moveSpeed, direction.y * this.moveSpeed);
    if (direction.lengthSq() > 0) this.setRotation(direction.angle() + Math.PI / 2);
  }
}
"""

HUD_TS = """import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { GameState } from "../systems/GameState";

export class Hud {
  private readonly scoreText: Phaser.GameObjects.Text;
  private readonly livesText: Phaser.GameObjects.Text;

  constructor(scene: Phaser.Scene) {
    const style: Phaser.Types.GameObjects.Text.TextStyle = {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "22px",
      color: gameConfig.palette.primary,
      stroke: "#020617",
      strokeThickness: 5,
    };
    this.scoreText = scene.add.text(24, 18, "", style).setScrollFactor(0).setDepth(50);
    this.livesText = scene.add.text(scene.scale.width - 24, 18, "", style)
      .setOrigin(1, 0).setScrollFactor(0).setDepth(50);
  }

  update(state: GameState): void {
    this.scoreText.setText(`Score ${state.score}/${state.targetScore}`);
    this.livesText.setText(`Lives ${state.lives}`);
  }
}
"""

BOOT_SCENE_TS = """import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";

export class BootScene extends Phaser.Scene {
  constructor() { super("BootScene"); }

  preload(): void {
    for (const asset of gameConfig.assets) {
      if (asset.kind === "image") this.load.image(asset.key, asset.path);
      else if (asset.kind === "spritesheet")
        this.load.spritesheet(asset.key, asset.path, {
          frameWidth: asset.frameWidth ?? 256,
          frameHeight: asset.frameHeight ?? 256,
        });
      else if (asset.kind === "audio") this.load.audio(asset.key, asset.path);
      else if (asset.kind === "video") this.load.video(asset.key, asset.path, true);
      else if (asset.kind === "tilemap") this.load.tilemapTiledJSON(asset.key, asset.path);
    }
  }

  create(): void {
    const { palette } = gameConfig;
    this.createFallbackTexture("player-fallback", colorNum(palette.primary), 16);
    this.createFallbackTexture("enemy-fallback", colorNum(palette.danger), 16);
    this.createFallbackTexture("reward-fallback", colorNum(palette.accent), 10);
    this.createGlowTexture("spark", 0xffffff, 6);
    this.scene.start("TitleScene");
  }

  private createFallbackTexture(key: string, color: number, radius: number): void {
    if (this.textures.exists(key)) return;
    const graphics = this.make.graphics({ x: 0, y: 0 }, false);
    graphics.fillStyle(color, 1);
    graphics.fillCircle(radius + 2, radius + 2, radius);
    graphics.lineStyle(3, 0xffffff, 0.85);
    graphics.strokeCircle(radius + 2, radius + 2, radius);
    graphics.generateTexture(key, radius * 2 + 4, radius * 2 + 4);
    graphics.destroy();
  }

  /** Soft radial dot for particle bursts and glows. */
  private createGlowTexture(key: string, color: number, radius: number): void {
    if (this.textures.exists(key)) return;
    const graphics = this.make.graphics({ x: 0, y: 0 }, false);
    for (let i = 3; i >= 1; i -= 1) {
      graphics.fillStyle(color, 0.25 * (4 - i));
      graphics.fillCircle(radius + 2, radius + 2, (radius * i) / 3);
    }
    graphics.generateTexture(key, radius * 2 + 4, radius * 2 + 4);
    graphics.destroy();
  }
}
"""

TITLE_SCENE_TS = """import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { Backdrop } from "../systems/Backdrop";
import { Sfx } from "../systems/Sfx";

export class TitleScene extends Phaser.Scene {
  constructor() { super("TitleScene"); }

  create(): void {
    const { width, height } = this.scale;
    const { palette } = gameConfig;
    this.cameras.main.setBackgroundColor(palette.bg);
    Backdrop.draw(this, 0.55);
    const title = this.add.text(width / 2, height * 0.34, gameConfig.title, {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "52px",
      color: palette.primary,
      align: "center",
      wordWrap: { width: width * 0.8 },
    }).setOrigin(0.5).setScale(0.9);
    this.tweens.add({ targets: title, scale: 1, duration: 420, ease: "Back.easeOut" });
    this.add.text(width / 2, height * 0.55, gameConfig.hint, {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "21px",
      color: "#cbd5e1",
      align: "center",
      wordWrap: { width: width * 0.72 },
    }).setOrigin(0.5);
    const start = this.add.text(width / 2, height * 0.72, "CLICK OR PRESS SPACE TO START", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "20px",
      color: palette.accent,
    }).setOrigin(0.5);
    this.tweens.add({ targets: start, alpha: 0.35, duration: 750, yoyo: true, repeat: -1 });
    const begin = (): void => {
      Sfx.play("select");
      this.scene.start("PlayScene");
    };
    this.input.once("pointerdown", begin);
    this.input.keyboard?.once("keydown-SPACE", begin);
  }
}
"""

PLAY_SCENE_TS = """// GW_PLACEHOLDER_GAMEPLAY — this scene is a neutral placeholder stage, NOT the game.
// The authoring agent must REPLACE this gameplay with the designed game (keep the
// scene key "PlayScene" and the Boot -> Title -> Play -> GameOver flow). It exists
// only so the scaffold boots, and to demonstrate the quality kit in use: Juice/Sfx,
// and — when the design ships a levelLayout — solid geometry and waypoint routes
// built from LevelLayout (keep THAT pattern: the layout matches the painted art).
import Phaser from "phaser";
import { gameConfig, param } from "../config/gameConfig";
import { Player } from "../entities/Player";
import { Backdrop } from "../systems/Backdrop";
import { Bounds } from "../systems/Bounds";
import { GameState } from "../systems/GameState";
import { Juice } from "../systems/Juice";
import { LevelLayout } from "../systems/LevelLayout";
import { Sfx } from "../systems/Sfx";
import { colorNum } from "../systems/Colors";
import { Hud } from "../ui/Hud";

export class PlayScene extends Phaser.Scene {
  private player!: Player;
  private sparks!: Phaser.Physics.Arcade.Group;
  private drifter!: Phaser.Physics.Arcade.Image;
  private state!: GameState;
  private hud!: Hud;
  private juice!: Juice;
  private streak = 0;
  private invulnUntil = 0;
  private patrolPoints: { x: number; y: number }[] = [];
  private patrolIndex = 0;

  constructor() { super("PlayScene"); }

  create(): void {
    const { palette } = gameConfig;
    this.cameras.main.setBackgroundColor(palette.bg);
    this.drawStage();
    this.state = new GameState(gameConfig.lives, gameConfig.targetScore);
    this.juice = new Juice(this);
    this.streak = 0;
    const spawn = LevelLayout.points("spawn")[0];
    this.player = new Player(
      this,
      spawn?.x ?? this.scale.width / 2,
      spawn?.y ?? this.scale.height / 2,
      gameConfig.assetKeys.player,
      param("player_speed", 300),
    );
    this.hud = new Hud(this);
    this.sparks = this.physics.add.group();
    for (let i = 0; i < 4; i += 1) this.spawnSpark();

    this.drifter = this.physics.add.image(
      this.scale.width * 0.2,
      this.scale.height * 0.2,
      gameConfig.assetKeys.enemy,
    );
    this.drifter.setDisplaySize(36, 36).setDepth(8);
    // Designed patrol route when the layout ships one; random drift otherwise.
    const patrol = LevelLayout.paths()[0];
    if (patrol) {
      this.patrolPoints = patrol.points;
      this.patrolIndex = 0;
      this.drifter.setPosition(patrol.points[0].x, patrol.points[0].y);
    } else {
      // Start moving AWAY from the player so the opening seconds are safe.
      this.drifter.setVelocity(-param("hazard_speed", 120), -param("hazard_speed", 120) * 0.8);
    }
    Bounds.collideWorld(this.drifter, 1);
    // The designed floor plan as REAL geometry: the same walls the painted
    // backdrop shows, as static bodies both actors collide with.
    const statics = LevelLayout.buildStatics(this);
    if (statics) {
      this.physics.add.collider(this.player, statics);
      this.physics.add.collider(this.drifter, statics);
    }
    this.invulnUntil = 0;

    this.physics.add.overlap(this.player, this.sparks, (_player, rawSpark) => {
      const spark = rawSpark as Phaser.Physics.Arcade.Image;
      if (!spark.active || this.state.status !== "playing") return;
      const gained = 10 + 2 * Math.min(10, this.streak);
      this.streak += 1;
      this.state.addScore(gained);
      this.juice.burst(spark.x, spark.y, "spark", 10);
      this.juice.floatText(spark.x, spark.y - 14, `+${gained}`, gameConfig.palette.accent);
      Sfx.playPitched("pickup", Math.min(12, this.streak));
      spark.destroy();
      this.spawnSpark();
    });
    this.physics.add.overlap(this.player, this.drifter, () => {
      // I-frames: overlap fires every frame, so without a cooldown one pass of
      // the hazard would drain every life in ~50ms — an unavoidable death.
      if (this.state.status !== "playing" || this.time.now < this.invulnUntil) return;
      this.invulnUntil = this.time.now + 1100;
      this.state.loseLife();
      this.streak = 0;
      this.juice.hitFlash(this.player);
      this.juice.shake();
      this.juice.hitStop(60);
      this.juice.burst(this.player.x, this.player.y, "spark", 14);
      Sfx.play("hit");
      // Knock the hazard away so it cannot camp on the respawn spot...
      const away = new Phaser.Math.Vector2(
        this.drifter.x - this.player.x,
        this.drifter.y - this.player.y,
      ).normalize().scale(param("hazard_speed", 120) * 1.3);
      this.drifter.setVelocity(away.x || param("hazard_speed", 120), away.y || -param("hazard_speed", 120));
      // ...and blink the player for the invulnerability window.
      this.player.setAlpha(0.35);
      this.tweens.add({
        targets: this.player,
        alpha: 1,
        duration: 140,
        yoyo: true,
        repeat: 3,
        onComplete: () => this.player.setAlpha(1),
      });
    });
  }

  update(): void {
    if (this.state.status === "playing") {
      this.player.update();
      this.updatePatrol();
    } else {
      this.physics.pause();
      Sfx.play(this.state.status === "won" ? "win" : "lose");
      this.scene.start("GameOverScene", { score: this.state.score, won: this.state.status === "won" });
    }
    this.hud.update(this.state);
  }

  /** Steer the drifter along the designed waypoint route (LevelLayout.paths). */
  private updatePatrol(): void {
    if (this.patrolPoints.length < 2) return;
    const target = this.patrolPoints[this.patrolIndex];
    const dx = target.x - this.drifter.x;
    const dy = target.y - this.drifter.y;
    const remaining = Math.hypot(dx, dy);
    if (remaining < 10) {
      this.patrolIndex = (this.patrolIndex + 1) % this.patrolPoints.length;
      return;
    }
    const speed = param("hazard_speed", 120);
    this.drifter.setVelocity((dx / remaining) * speed, (dy / remaining) * speed);
  }

  private spawnSpark(): void {
    if (this.state?.status !== "playing") return;
    const spark = this.sparks.create(
      Phaser.Math.Between(70, this.scale.width - 70),
      Phaser.Math.Between(90, this.scale.height - 70),
      gameConfig.assetKeys.reward,
    ) as Phaser.Physics.Arcade.Image;
    spark.setDisplaySize(24, 24).setDepth(5);
    this.tweens.add({ targets: spark, scale: 1.18, duration: 500, yoyo: true, repeat: -1 });
  }

  private drawStage(): void {
    // Prefer the generated background image; fall back to a palette gradient.
    if (Backdrop.draw(this)) return;
    const { palette } = gameConfig;
    const graphics = this.add.graphics().setDepth(-10);
    const bg = colorNum(palette.bg);
    const surface = colorNum(palette.surface);
    graphics.fillGradientStyle(bg, bg, surface, surface, 1);
    graphics.fillRect(0, 0, this.scale.width, this.scale.height);
    graphics.lineStyle(1, colorNum(palette.primary), 0.08);
    for (let x = 0; x < this.scale.width; x += 48) graphics.lineBetween(x, 0, x, this.scale.height);
    for (let y = 0; y < this.scale.height; y += 48) graphics.lineBetween(0, y, this.scale.width, y);
  }
}
"""

GAME_OVER_SCENE_TS = """import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "../systems/Colors";

interface GameOverData {
  score?: number;
  won?: boolean;
}

export class GameOverScene extends Phaser.Scene {
  private score = 0;
  private won = false;

  constructor() { super("GameOverScene"); }

  init(data: GameOverData): void {
    this.score = Math.max(0, Math.floor(data.score ?? 0));
    this.won = Boolean(data.won);
  }

  create(): void {
    const { width, height } = this.scale;
    const { palette } = gameConfig;
    this.cameras.main.setBackgroundColor(palette.bg);
    const edge = this.won ? palette.accent : palette.danger;
    const panel = this.add.rectangle(width / 2, height / 2, 560, 250, colorNum(palette.surface), 0.94)
      .setStrokeStyle(2, colorNum(edge)).setScale(0.9);
    this.tweens.add({ targets: panel, scale: 1, duration: 300, ease: "Back.easeOut" });
    this.add.text(width / 2, height / 2 - 52, this.won ? "YOU WIN" : "GAME OVER", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "46px",
      color: this.won ? palette.accent : palette.danger,
    }).setOrigin(0.5);
    this.add.text(width / 2, height / 2 + 8, `Score ${this.score}`, {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "26px",
      color: palette.primary,
    }).setOrigin(0.5);
    this.add.text(width / 2, height / 2 + 60, "Press R or click to restart", {
      fontFamily: "Inter, system-ui, sans-serif",
      fontSize: "20px",
      color: "#cbd5e1",
    }).setOrigin(0.5);
    // Report the final score to the host exactly once. This postMessage is the
    // only allowed parent access in the sandbox.
    window.parent.postMessage({ type: "gameweave:score", points: this.score }, "*");
    const restart = (): void => { this.scene.start("PlayScene"); };
    this.input.once("pointerdown", restart);
    this.input.keyboard?.once("keydown-R", restart);
  }
}
"""

MAIN_TS = """import Phaser from "phaser";
import "./styles.css";
import { gameConfig } from "./config/gameConfig";
import { BootScene } from "./scenes/BootScene";
import { TitleScene } from "./scenes/TitleScene";
import { PlayScene } from "./scenes/PlayScene";
import { GameOverScene } from "./scenes/GameOverScene";

const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game-container",
  width: gameConfig.width,
  height: gameConfig.height,
  backgroundColor: gameConfig.palette.bg,
  scene: [BootScene, TitleScene, PlayScene, GameOverScene],
  physics: {
    default: "arcade",
    // Neutral default. Side-view / platformer designs should raise gravity.y here.
    arcade: { gravity: { x: 0, y: 0 }, debug: false },
  },
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
});

// The QA win-path simulator pumps virtual time through this handle
// (game.loop.step). Gameplay code must never read or depend on it.
(window as unknown as { __GW_GAME__?: Phaser.Game }).__GW_GAME__ = game;
"""

STYLES_CSS = """html, body, #game-container { width: 100%; height: 100%; margin: 0; }
body { overflow: hidden; background: __BG__; font-family: Inter, system-ui, sans-serif; }
#game-container { display: grid; place-items: center; }
canvas { max-width: 100%; max-height: 100%; box-shadow: 0 24px 80px rgba(0,0,0,.55); }
"""
