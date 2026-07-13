"""Deterministic Phaser-compatible Tiled JSON generation.

The World layer is deliberately SPARSE structure/decor over the generated
background image (gid 0 = empty lets the background show through). The tileset
image is either AI-generated upstream (game_assets passes in the post-processed
PNG) or drawn procedurally from the design palette — never a hardcoded
placeholder: the old 2-tile SVG shipped a giant purple X next to real AI art
(2026-07-12 实测事故) and was dropped by the scaffold anyway because its
manifest entry had no key.

Tile vocabulary (4x4 grid of 32px tiles, gid = cell index + 1):
  1-4   floors   full-square ground tiles (non-solid; grid archetypes use them)
  5-8   solids   wall block / wall variant / crate / barricade (collision set)
  9-12  props    standalone decor objects on a transparent backdrop
  13-16 overlays translucent decals: crack, warning stripe, lights, marking
"""
from __future__ import annotations

import hashlib
import io
import json
import random

from app.services.artifacts import binary_artifact, text_artifact

TILE_SIZE = 32
TILESET_GRID = 4
TILESET_TILE_COUNT = TILESET_GRID * TILESET_GRID
TILESET_IMAGE_SIZE = TILESET_GRID * TILE_SIZE
TILESET_NAME = "gameweave"
SOLID_GIDS = (5, 6, 7, 8)

GID_FLOORS = (1, 2, 3, 4)
GID_WALL, GID_WALL_ALT, GID_CRATE, GID_BARRICADE = SOLID_GIDS
GID_PROPS = (9, 10, 11, 12)
GID_OVERLAYS = (13, 14, 15, 16)

TILEMAP_ARCHETYPES = {
    "lane_runner",
    "logic_grid",
    "topdown_collect",
    "vertical_shooter",
}


def _hex_rgb(value, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return fallback
    try:
        raw = int(text, 16)
    except ValueError:
        return fallback
    return ((raw >> 16) & 255, (raw >> 8) & 255, raw & 255)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


def _procedural_tileset(palette: dict | None) -> bytes | None:
    """Palette-driven fallback tileset used when no AI tileset image exists.

    Intentionally modest: flat fills, outlines, and simple shapes in the game's
    own palette, so even the fallback reads as part of the same visual identity.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover —— 生产依赖含 Pillow;缺失时放弃 tilemap
        return None

    palette = palette if isinstance(palette, dict) else {}
    bg = _hex_rgb(palette.get("bg"), (11, 16, 38))
    surface = _hex_rgb(palette.get("surface"), (20, 28, 51))
    primary = _hex_rgb(palette.get("primary"), (103, 232, 249))
    accent = _hex_rgb(palette.get("accent"), (240, 171, 252))
    danger = _hex_rgb(palette.get("danger"), (251, 113, 133))

    img = Image.new("RGBA", (TILESET_IMAGE_SIZE, TILESET_IMAGE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def origin(index: int) -> tuple[int, int]:
        return (index % TILESET_GRID) * TILE_SIZE, (index // TILESET_GRID) * TILE_SIZE

    # floors (gid 1-4): full opaque squares in nearby tones with light detailing
    for i, tone_t in enumerate((0.35, 0.55, 0.75, 0.45)):
        x, y = origin(i)
        tone = _mix(bg, surface, tone_t)
        draw.rectangle([x, y, x + 31, y + 31], fill=(*tone, 255), outline=(*_mix(tone, (0, 0, 0), 0.3), 255))
        detail = _mix(tone, primary, 0.25)
        if i == 1:
            draw.rectangle([x + 6, y + 6, x + 25, y + 25], outline=(*detail, 255))
        elif i == 2:
            for off in (8, 16, 24):
                draw.line([x + off, y + 3, x + off, y + 28], fill=(*detail, 255))
        elif i == 3:
            draw.line([x + 3, y + 16, x + 28, y + 16], fill=(*_mix(tone, primary, 0.5), 255), width=2)

    # solids (gid 5-8): wall / wall variant / crate / barricade
    x, y = origin(4)
    wall = _mix(surface, primary, 0.12)
    draw.rectangle([x, y, x + 31, y + 31], fill=(*wall, 255), outline=(*_mix(wall, primary, 0.5), 255), width=2)
    draw.rectangle([x + 4, y + 4, x + 27, y + 10], fill=(*_mix(wall, (255, 255, 255), 0.14), 255))
    x, y = origin(5)
    wall_alt = _mix(surface, (0, 0, 0), 0.2)
    draw.rectangle([x, y, x + 31, y + 31], fill=(*wall_alt, 255), outline=(*_mix(wall_alt, primary, 0.4), 255), width=2)
    draw.line([x + 8, y + 6, x + 14, y + 16, x + 10, y + 26], fill=(*_mix(wall_alt, (0, 0, 0), 0.5), 255), width=2)
    x, y = origin(6)
    crate = _mix(surface, accent, 0.3)
    draw.rectangle([x + 2, y + 2, x + 29, y + 29], fill=(*crate, 255), outline=(*_mix(crate, (0, 0, 0), 0.4), 255), width=2)
    draw.line([x + 2, y + 2, x + 29, y + 29], fill=(*_mix(crate, (0, 0, 0), 0.3), 255), width=2)
    draw.line([x + 29, y + 2, x + 2, y + 29], fill=(*_mix(crate, (0, 0, 0), 0.3), 255), width=2)
    x, y = origin(7)
    draw.rectangle([x + 1, y + 6, x + 30, y + 26], fill=(*surface, 255), outline=(*_mix(surface, (0, 0, 0), 0.4), 255))
    for i, sy in enumerate(range(y + 8, y + 25, 6)):
        band = danger if i % 2 == 0 else _mix(surface, (255, 255, 255), 0.18)
        draw.rectangle([x + 3, sy, x + 28, sy + 3], fill=(*band, 255))

    # props (gid 9-12): standalone objects on transparency
    x, y = origin(8)
    barrel = _mix(surface, accent, 0.45)
    draw.ellipse([x + 7, y + 5, x + 24, y + 27], fill=(*barrel, 255), outline=(*_mix(barrel, (0, 0, 0), 0.4), 255), width=2)
    draw.ellipse([x + 11, y + 9, x + 20, y + 14], fill=(*_mix(barrel, (255, 255, 255), 0.25), 255))
    x, y = origin(9)
    machine = _mix(surface, primary, 0.2)
    draw.rectangle([x + 5, y + 8, x + 26, y + 27], fill=(*machine, 255), outline=(*_mix(machine, (0, 0, 0), 0.4), 255), width=2)
    for off in range(11, 25, 4):
        draw.line([x + 8, y + off, x + 23, y + off], fill=(*_mix(machine, (0, 0, 0), 0.35), 255))
    x, y = origin(10)
    rubble = _mix(surface, (0, 0, 0), 0.1)
    for rx, ry, rw, rh in ((4, 18, 10, 9), (13, 12, 12, 15), (22, 20, 7, 7)):
        draw.rectangle([x + rx, y + ry, x + rx + rw, y + ry + rh], fill=(*rubble, 255), outline=(*_mix(rubble, (0, 0, 0), 0.4), 255))
    x, y = origin(11)
    draw.polygon(
        [(x + 16, y + 4), (x + 28, y + 16), (x + 16, y + 28), (x + 4, y + 16)],
        fill=(*_mix(danger, bg, 0.15), 255),
        outline=(*_mix(danger, (255, 255, 255), 0.3), 255),
    )
    draw.line([x + 16, y + 10, x + 16, y + 19], fill=(255, 255, 255, 230), width=3)
    draw.rectangle([x + 15, y + 22, x + 17, y + 24], fill=(255, 255, 255, 230))

    # overlays (gid 13-16): translucent decals
    x, y = origin(12)
    crack = _mix(bg, (0, 0, 0), 0.5)
    draw.line([x + 4, y + 6, x + 14, y + 14, x + 10, y + 24, x + 20, y + 29], fill=(*crack, 170), width=2)
    draw.line([x + 14, y + 14, x + 24, y + 10], fill=(*crack, 170), width=2)
    x, y = origin(13)
    for off in range(-32, 33, 12):
        draw.line([x + off, y + 32, x + off + 32, y], fill=(*danger, 120), width=4)
    x, y = origin(14)
    for cx, cy in ((8, 8), (24, 8), (8, 24), (24, 24)):
        draw.ellipse([x + cx - 3, y + cy - 3, x + cx + 3, y + cy + 3], fill=(*primary, 180))
    x, y = origin(15)
    draw.line([x + 6, y + 20, x + 16, y + 10, x + 26, y + 20], fill=(*accent, 190), width=3)
    draw.line([x + 6, y + 27, x + 16, y + 17, x + 26, y + 27], fill=(*accent, 150), width=3)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _layout(archetype: str, seed_text: str, width: int, height: int) -> list[int]:
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    data = [0] * (width * height)

    def set_tile(x: int, y: int, tile: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            data[y * width + x] = tile

    def sprinkle(count: int, gids: tuple[int, ...], x0: int, x1: int, y0: int, y1: int) -> None:
        for _ in range(count):
            x, y = rng.randint(x0, max(x0, x1)), rng.randint(y0, max(y0, y1))
            if data[y * width + x] == 0:
                set_tile(x, y, rng.choice(gids))

    if archetype == "lane_runner":
        for x in range(width):
            set_tile(x, height - 1, GID_WALL)
        for x in range(5, width - 2, 5):
            platform_y = rng.randint(height - 6, height - 3)
            for offset in range(rng.randint(2, 4)):
                set_tile(x + offset, platform_y, GID_CRATE)
        sprinkle(width // 3, GID_OVERLAYS, 1, width - 2, 1, height - 4)
    elif archetype == "logic_grid":
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                set_tile(x, y, GID_FLOORS[(x + y) % 2])
        for x in range(width):
            set_tile(x, 0, GID_WALL)
            set_tile(x, height - 1, GID_WALL)
        for y in range(height):
            set_tile(0, y, GID_WALL)
            set_tile(width - 1, y, GID_WALL)
        for _ in range(width * height // 16):
            set_tile(rng.randint(2, width - 3), rng.randint(2, height - 3), rng.choice((GID_WALL_ALT, GID_CRATE)))
    elif archetype == "topdown_collect":
        for x in range(width):
            set_tile(x, 0, GID_WALL)
            set_tile(x, height - 1, GID_WALL)
        for y in range(height):
            set_tile(0, y, GID_WALL)
            set_tile(width - 1, y, GID_WALL)
        for _ in range(max(8, width * height // 28)):
            x, y = rng.randint(3, width - 4), rng.randint(3, height - 4)
            set_tile(x, y, GID_CRATE)
            if rng.random() > 0.5:
                set_tile(x + 1, y, rng.choice((GID_CRATE, GID_BARRICADE)))
        sprinkle(width // 2, GID_PROPS, 2, width - 3, 2, height - 3)
        sprinkle(width, GID_OVERLAYS, 1, width - 2, 1, height - 2)
    else:  # vertical_shooter: decorative side strips + light field decals, no solids
        for y in range(0, height, 3):
            set_tile(1, y, GID_PROPS[y % len(GID_PROPS)])
            set_tile(width - 2, y + 1, GID_PROPS[(y + 2) % len(GID_PROPS)])
        sprinkle(width, GID_OVERLAYS, 2, width - 3, 0, height - 1)
    return data


def generate_tilemap_artifacts(
    archetype: str,
    seed_text: str,
    *,
    screen_width: int = 1152,
    screen_height: int = 768,
    palette: dict | None = None,
    tileset_png: bytes | None = None,
    tileset_provider: str = "procedural",
    tileset_model: str = "palette",
) -> tuple[list[dict], list[dict]] | None:
    """Build tilemap.json + tileset.png artifacts and their manifest entries.

    Returns None when the archetype has no tilemap or no tileset image can be
    produced. Both manifest entries carry a `key` — entries without one are
    silently dropped by the scaffold's asset catalog and the whole tilemap
    becomes dead weight in the bundle.
    """
    if archetype not in TILEMAP_ARCHETYPES:
        return None
    if tileset_png is None:
        tileset_png = _procedural_tileset(palette)
        if tileset_png is None:
            return None

    # Cover the design's screen so a drawn layer never ends mid-arena.
    width = max(20, min(50, round(screen_width / TILE_SIZE)))
    height = max(12, min(32, round(screen_height / TILE_SIZE)))
    data = _layout(archetype, seed_text, width, height)
    tilemap = {
        "compressionlevel": -1,
        "height": height,
        "infinite": False,
        "layers": [
            {
                "data": data,
                "height": height,
                "id": 1,
                "name": "World",
                "opacity": 1,
                "type": "tilelayer",
                "visible": True,
                "width": width,
                "x": 0,
                "y": 0,
            }
        ],
        "nextlayerid": 2,
        "nextobjectid": 1,
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "tiledversion": "1.11.0",
        "tileheight": TILE_SIZE,
        "tilesets": [
            {
                "columns": TILESET_GRID,
                "firstgid": 1,
                "image": "tileset.png",
                "imageheight": TILESET_IMAGE_SIZE,
                "imagewidth": TILESET_IMAGE_SIZE,
                "margin": 0,
                "name": TILESET_NAME,
                "spacing": 0,
                "tilecount": TILESET_TILE_COUNT,
                "tileheight": TILE_SIZE,
                "tilewidth": TILE_SIZE,
            }
        ],
        "tilewidth": TILE_SIZE,
        "type": "map",
        "version": "1.10",
        "width": width,
    }
    artifacts = [
        text_artifact("public/assets/tilemap.json", json.dumps(tilemap, ensure_ascii=False, indent=2)),
        binary_artifact("public/assets/tileset.png", tileset_png, "image/png"),
    ]
    manifest_entries = [
        {
            "key": "tileset",
            "kind": "image",
            "path": "assets/tileset.png",
            "content_type": "image/png",
            "role": "tileset",
            "provider": tileset_provider,
            "model": tileset_model,
        },
        {
            "key": "tilemap",
            "kind": "tilemap",
            "path": "assets/tilemap.json",
            "format": "tiled-json",
            "layer": "World",
            "tileset_key": "tileset",
            "tileset_name": TILESET_NAME,
            "tile_size": TILE_SIZE,
            "solid_gids": list(SOLID_GIDS),
            "generated_by": "gameweave-tilemap/v2",
        },
    ]
    return artifacts, manifest_entries
