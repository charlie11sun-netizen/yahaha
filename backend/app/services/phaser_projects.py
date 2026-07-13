"""OpenGame-inspired modular Phaser/Vite/TypeScript project scaffolding.

The scaffold is intentionally a NEUTRAL STAGE plus quality infrastructure, not a
finished game: scene flow (Boot -> Title -> Play -> GameOver), typed config with
a per-game palette, a Juice system (flash / shake / hit-stop / particles /
floating text), and an Sfx system (WebAudio oscillator presets). PlayScene ships
a small placeholder loop (marked GW_PLACEHOLDER_GAMEPLAY) that demonstrates the
quality kit and MUST be replaced by the authoring agent with the designed game.
Keeping gameplay out of the scaffold is deliberate: a finished mother-game made
every generated title feel like a reskin of the same collect-and-dodge arena.
"""
from __future__ import annotations

import hashlib
import json
import re
from html import escape

from app.services.artifacts import text_artifact

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

# Rotating fallback palettes so games without a designed palette still differ
# visually from each other (picked deterministically from title+theme).
_PALETTES: list[dict[str, str]] = [
    {"bg": "#0b1026", "surface": "#141c33", "primary": "#67e8f9", "accent": "#f0abfc", "danger": "#fb7185"},
    {"bg": "#1f1147", "surface": "#2d1b5e", "primary": "#fbbf24", "accent": "#fb923c", "danger": "#f43f5e"},
    {"bg": "#051622", "surface": "#0a2735", "primary": "#34d399", "accent": "#38bdf8", "danger": "#f87171"},
    {"bg": "#0c1f17", "surface": "#16302a", "primary": "#a3e635", "accent": "#4ade80", "danger": "#fb7185"},
    {"bg": "#2a1033", "surface": "#3b1a47", "primary": "#f9a8d4", "accent": "#fde047", "danger": "#f87171"},
    {"bg": "#0a0f0a", "surface": "#121a12", "primary": "#4ade80", "accent": "#a3e635", "danger": "#f87171"},
    {"bg": "#1a0b0b", "surface": "#2a1212", "primary": "#fb923c", "accent": "#fbbf24", "danger": "#ef4444"},
    {"bg": "#0b1420", "surface": "#14212f", "primary": "#e0f2fe", "accent": "#7dd3fc", "danger": "#fda4af"},
    {"bg": "#140f2b", "surface": "#1e1745", "primary": "#a78bfa", "accent": "#f0abfc", "danger": "#fb7185"},
    {"bg": "#1c1410", "surface": "#2b2018", "primary": "#fcd34d", "accent": "#f97316", "danger": "#ef4444"},
]

_PALETTE_KEYS = ("bg", "surface", "primary", "accent", "danger")


def _number(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clean_hex(value) -> str | None:
    text = str(value or "").strip()
    if not _HEX_RE.match(text):
        return None
    return "#" + text.lstrip("#").lower()


def _palette_for(spec: dict, design: dict) -> dict[str, str]:
    seed = f"{spec.get('title') or ''}|{spec.get('theme') or ''}"
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(_PALETTES)
    palette = dict(_PALETTES[index])
    raw = design.get("palette") if isinstance(design, dict) else None
    if isinstance(raw, dict):
        for key in _PALETTE_KEYS:
            clean = _clean_hex(raw.get(key))
            if clean:
                palette[key] = clean
    elif isinstance(raw, list):
        for key, value in zip(("bg", "primary", "accent", "danger", "surface"), raw):
            clean = _clean_hex(value)
            if clean:
                palette[key] = clean
    return palette


def _free_params(balance: dict | None, design: dict | None) -> dict[str, float]:
    """Flatten numeric tuning values into a free-form params map.

    The old scaffold hardcoded dodge-collect fields (enemySpeed/spawnMs...) into
    the config type, which nudged every game back toward the same archetype.
    Numbers now travel untyped; gameplay code decides what they mean.
    """
    params: dict[str, float] = {}
    for source in ((balance or {}), (design or {}).get("balance") or {}):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            name = str(key)[:48]
            if name:
                params[name] = float(value)
    return params


def _asset_catalog(asset_manifest: dict | None) -> tuple[list[dict], dict, list[dict], dict | None]:
    entries: list[dict] = []
    image_keys: list[str] = []
    backgrounds: list[str] = []
    sheets: list[dict] = []
    tilemap: dict | None = None
    for raw in (asset_manifest or {}).get("assets") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        path = str(raw.get("path") or "").strip().lstrip("/")
        kind = str(raw.get("kind") or "image").strip().lower()
        if not key or not path or "://" in path or ".." in path.split("/"):
            continue
        if kind not in {"image", "spritesheet", "audio", "video", "tilemap"}:
            continue
        entry: dict = {"key": key, "path": path, "kind": kind}
        if kind == "spritesheet":
            frame_w = _number(raw.get("frame_width"), 256, 8, 1024)
            frame_h = _number(raw.get("frame_height"), 256, 8, 1024)
            entry["frameWidth"] = frame_w
            entry["frameHeight"] = frame_h
            frames = raw.get("frames")
            if isinstance(frames, dict) and frames:
                # 设计实体多时图集溢出为多页(sheet, sheet-2...):全部收集,
                # gameplay 代码经 sheetFrame() 跨页找帧。
                raw_animations = raw.get("animations")
                sheets.append(
                    {
                        "key": key,
                        "frameWidth": frame_w,
                        "frameHeight": frame_h,
                        "frames": {
                            str(name)[:64]: int(index)
                            for name, index in frames.items()
                            if isinstance(index, (int, float)) and not isinstance(index, bool)
                        },
                        # 多帧角色的帧组(玩家姿势集、敌人 idle+攻击、Boss 特技、
                        # 道具激活态):同组帧保证在同一张图上,可直接建 Phaser 动画。
                        "animations": {
                            str(base)[:64]: [str(name)[:64] for name in names if isinstance(name, str)]
                            for base, names in (raw_animations.items() if isinstance(raw_animations, dict) else ())
                            if isinstance(names, (list, tuple)) and names
                        },
                    }
                )
        elif kind == "tilemap" and tilemap is None:
            tilemap = {
                "key": key,
                "layer": str(raw.get("layer") or "World")[:64],
                "tilesetKey": str(raw.get("tileset_key") or "tileset")[:64],
                "tilesetName": str(raw.get("tileset_name") or "gameweave")[:64],
                "tileSize": _number(raw.get("tile_size"), 32, 8, 256),
                "solidGids": [
                    int(gid)
                    for gid in (raw.get("solid_gids") or [])
                    if isinstance(gid, (int, float)) and not isinstance(gid, bool)
                ],
            }
        entries.append(entry)
        if kind == "image":
            if "background" in key:
                # 场景变体(background, background-2...)全部收集;它们是舞台
                # 不是演员,一张都不能漏进 player/enemy 回退键。
                backgrounds.append(key)
            elif str(raw.get("role") or "") == "tileset" or "tile" in key:
                pass  # tileset 图片不是演员,别污染 player/enemy 回退键
            else:
                image_keys.append(key)
    keys = {
        "background": backgrounds[0] if backgrounds else "",
        # 全部场景背景变体(主场景/高压阶段/换区),按生成顺序;
        # gameplay 代码按阶段切换 Backdrop.draw(scene, dim, key)。
        "backgrounds": backgrounds,
        "player": image_keys[0] if image_keys else "player-fallback",
        "enemy": image_keys[1] if len(image_keys) > 1 else "enemy-fallback",
        "reward": "reward-fallback",
    }
    return entries, keys, sheets, tilemap


def create_modular_phaser_project(
    spec: dict,
    design: dict,
    balance: dict | None = None,
    asset_manifest: dict | None = None,
) -> list[dict]:
    """Create a neutral, typed stage that an authoring agent grows into the game."""
    balance = balance or {}
    design = design if isinstance(design, dict) else {}
    title = str(spec.get("title") or "GameWeave Game")[:120]
    archetype = str(spec.get("archetype") or design.get("archetype") or "topdown_collect")
    controls = design.get("controls") if isinstance(design.get("controls"), dict) else {}
    hint = str(controls.get("hint") or "Move with arrows or WASD.")[:240]
    screen = design.get("screen") if isinstance(design.get("screen"), dict) else {}
    assets, asset_keys, sheets, tilemap = _asset_catalog(asset_manifest)
    palette = _palette_for(spec, design)
    config = {
        "title": title,
        "archetype": archetype,
        "width": _number(screen.get("width"), 1152, 640, 1600),
        "height": _number(screen.get("height"), 768, 480, 1000),
        "palette": palette,
        "hint": hint,
        "lives": _number(balance.get("lives"), 3, 1, 9),
        "targetScore": _number(balance.get("target_score"), 120, 20, 5000),
        "params": _free_params(balance, design),
        "assets": assets,
        "assetKeys": asset_keys,
        "sheet": sheets[0] if sheets else None,
        "sheets": sheets,
        "tilemap": tilemap,
    }
    config_json = json.dumps(config, ensure_ascii=False, indent=2)
    package_json = json.dumps(
        {
            "name": "gameweave-generated-game",
            "private": True,
            "version": "0.0.0",
            "type": "module",
            "scripts": {
                "typecheck": "tsc --noEmit",
                "build": "tsc --noEmit && vite build",
            },
            "dependencies": {"phaser": "3.90.0"},
            "devDependencies": {"typescript": "5.8.3", "vite": "6.4.3"},
        },
        indent=2,
    )

    files = [
        text_artifact("package.json", package_json),
        text_artifact(
            "tsconfig.json",
            json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2020",
                        "module": "ESNext",
                        "lib": ["ES2020", "DOM", "DOM.Iterable"],
                        "moduleResolution": "Bundler",
                        "resolveJsonModule": True,
                        "useDefineForClassFields": True,
                        "strict": True,
                        "noEmit": True,
                        "skipLibCheck": True,
                    },
                    "include": ["src"],
                },
                indent=2,
            ),
        ),
        text_artifact(
            "index.html",
            """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>__TITLE__</title>
  </head>
  <body>
    <main id="game-container" aria-label="Generated game"></main>
    <script type="module" src="./src/main.ts"></script>
  </body>
</html>
""".replace("__TITLE__", escape(title)),
        ),
        text_artifact(
            "src/config/gameConfig.ts",
            """export type AssetKind = "image" | "spritesheet" | "audio" | "video" | "tilemap";

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
 * straight into anims.create (attack toggles, activation pulses, boss phases). */
export interface SheetInfo {
  key: string;
  frameWidth: number;
  frameHeight: number;
  frames: Record<string, number>;
  animations: Record<string, string[]>;
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
  /** First generated sheet (kept for compatibility). Prefer sheetFrame() lookups. */
  sheet: SheetInfo | null;
  /** Every generated sheet. Large rosters overflow onto "sheet-2". */
  sheets: SheetInfo[];
  tilemap: TilemapInfo | null;
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
""".replace("__CONFIG__", config_json),
        ),
        text_artifact(
            "src/systems/Colors.ts",
            """/** Convert a "#rrggbb" palette string to the numeric color Phaser APIs expect. */
export function colorNum(hex: string): number {
  const clean = hex.trim().replace("#", "");
  const expanded = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const value = Number.parseInt(expanded, 16);
  return Number.isFinite(value) ? value : 0xffffff;
}
""",
        ),
        text_artifact(
            "src/systems/Backdrop.ts",
            """import Phaser from "phaser";
import { gameConfig } from "../config/gameConfig";
import { colorNum } from "./Colors";

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
  draw(scene: Phaser.Scene, dim = 0.35, key?: string): Phaser.GameObjects.Image | null {
    const textureKey = key ?? gameConfig.assetKeys.background;
    if (!textureKey || !scene.textures.exists(textureKey)) return null;
    const { width, height } = scene.scale;
    const image = scene.add.image(width / 2, height / 2, textureKey).setDepth(-20);
    const scale = Math.max(width / image.width, height / image.height);
    image.setScale(scale);
    if (dim > 0) {
      scene.add
        .rectangle(width / 2, height / 2, width, height, colorNum(gameConfig.palette.bg), dim)
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
""",
        ),
        text_artifact(
            "src/systems/Bounds.ts",
            """import Phaser from "phaser";

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
""",
        ),
        text_artifact(
            "src/systems/GameState.ts",
            """export type GameStatus = "playing" | "won" | "lost";

export class GameState {
  score = 0;
  status: GameStatus = "playing";

  constructor(
    public lives: number,
    readonly targetScore: number,
  ) {}

  addScore(points: number): void {
    if (this.status !== "playing") return;
    this.score += points;
    if (this.score >= this.targetScore) this.status = "won";
  }

  loseLife(): void {
    if (this.status !== "playing") return;
    this.lives = Math.max(0, this.lives - 1);
    if (this.lives === 0) this.status = "lost";
  }
}
""",
        ),
        text_artifact(
            "src/systems/Sfx.ts",
            """/** Procedural WebAudio sound presets — no audio files, sandbox-safe.
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
      const ctx = Sfx.context();
      if (!ctx) return;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const now = ctx.currentTime;
      osc.type = preset.wave;
      osc.frequency.setValueAtTime(Math.max(1, preset.from * multiplier), now);
      osc.frequency.exponentialRampToValueAtTime(Math.max(1, preset.to * multiplier), now + preset.duration);
      gain.gain.setValueAtTime(Math.max(0.0001, preset.volume * volume), now);
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
""",
        ),
        text_artifact(
            "src/systems/Juice.ts",
            """import Phaser from "phaser";

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

  /** Quick scale pulse for pickups, buttons, HUD reactions. */
  pulse(target: object, scale = 1.15, duration = 110): void {
    this.scene.tweens.add({
      targets: target,
      scale,
      yoyo: true,
      duration,
      ease: "Back.easeOut",
    });
  }
}
""",
        ),
        text_artifact(
            "src/entities/Player.ts",
            """import Phaser from "phaser";

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
""",
        ),
        text_artifact(
            "src/ui/Hud.ts",
            """import Phaser from "phaser";
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
""",
        ),
        text_artifact(
            "src/scenes/BootScene.ts",
            """import Phaser from "phaser";
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
""",
        ),
        text_artifact(
            "src/scenes/TitleScene.ts",
            """import Phaser from "phaser";
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
""",
        ),
        text_artifact(
            "src/scenes/PlayScene.ts",
            """// GW_PLACEHOLDER_GAMEPLAY — this scene is a neutral placeholder stage, NOT the game.
// The authoring agent must REPLACE this gameplay with the designed game (keep the
// scene key "PlayScene" and the Boot -> Title -> Play -> GameOver flow). It exists
// only so the scaffold boots, and to demonstrate the Juice/Sfx quality kit in use.
import Phaser from "phaser";
import { gameConfig, param } from "../config/gameConfig";
import { Player } from "../entities/Player";
import { Backdrop } from "../systems/Backdrop";
import { Bounds } from "../systems/Bounds";
import { GameState } from "../systems/GameState";
import { Juice } from "../systems/Juice";
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

  constructor() { super("PlayScene"); }

  create(): void {
    const { palette } = gameConfig;
    this.cameras.main.setBackgroundColor(palette.bg);
    this.drawStage();
    this.state = new GameState(gameConfig.lives, gameConfig.targetScore);
    this.juice = new Juice(this);
    this.streak = 0;
    this.player = new Player(
      this,
      this.scale.width / 2,
      this.scale.height / 2,
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
    // Start moving AWAY from the player so the opening seconds are safe.
    this.drifter.setVelocity(-param("hazard_speed", 120), -param("hazard_speed", 120) * 0.8);
    Bounds.collideWorld(this.drifter, 1);
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
    } else {
      this.physics.pause();
      Sfx.play(this.state.status === "won" ? "win" : "lose");
      this.scene.start("GameOverScene", { score: this.state.score, won: this.state.status === "won" });
    }
    this.hud.update(this.state);
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
""",
        ),
        text_artifact(
            "src/scenes/GameOverScene.ts",
            """import Phaser from "phaser";
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
""",
        ),
        text_artifact(
            "src/main.ts",
            """import Phaser from "phaser";
import "./styles.css";
import { gameConfig } from "./config/gameConfig";
import { BootScene } from "./scenes/BootScene";
import { TitleScene } from "./scenes/TitleScene";
import { PlayScene } from "./scenes/PlayScene";
import { GameOverScene } from "./scenes/GameOverScene";

new Phaser.Game({
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
""",
        ),
        text_artifact(
            "src/styles.css",
            """html, body, #game-container { width: 100%; height: 100%; margin: 0; }
body { overflow: hidden; background: __BG__; font-family: Inter, system-ui, sans-serif; }
#game-container { display: grid; place-items: center; }
canvas { max-width: 100%; max-height: 100%; box-shadow: 0 24px 80px rgba(0,0,0,.55); }
""".replace("__BG__", palette["bg"]),
        ),
    ]
    return files


def is_modular_phaser_project(files: list[dict] | None) -> bool:
    paths = {str(item.get("path") or "") for item in (files or [])}
    return {"package.json", "index.html", "tsconfig.json", "src/main.ts"}.issubset(paths)


def safe_project_source_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    return bool(
        normalized
        and not normalized.startswith(("/", "node_modules/", "dist/"))
        and ".." not in normalized.split("/")
        and re.fullmatch(r"[A-Za-z0-9._/-]{1,180}", normalized)
        and normalized.endswith((".ts", ".tsx", ".js", ".mjs", ".css", ".json", ".html", ".md"))
    )


__all__ = ["create_modular_phaser_project", "is_modular_phaser_project", "safe_project_source_path"]
