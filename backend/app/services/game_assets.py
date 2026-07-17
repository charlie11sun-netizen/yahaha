"""Game-specific asset planning and generation orchestration.

Visual assets are consolidated into sprite SHEETS (strict 4x4 grids of 256px
cells) plus a small set of scene BACKGROUND variants (main stage / high-
intensity phase / alternate zone, for visible stage changes), plus — for
tile-friendly archetypes — an environment tileset rendered in the same style.
Consolidation keeps cost at a few image calls per game, gives every sprite a
consistent style, and — because we define the grid — lets the game slice
frames deterministically via Phaser's spritesheet loader.

Every actor is planned as a FRAME GROUP: the player gets an idle/move/action
core plus design-driven skill poses (up to 5 abilities), hurt/jump/death/
victory poses; enemies get attack and movement frames (bosses additionally a
special-skill frame); items get an activated frame.
Core cells (one per designed entity) are budgeted first, then remaining
capacity upgrades actors into animation frames by priority. A group's frames
never straddle pages — Phaser animations require all frames on one texture.
Rosters overflow onto "sheet-2", "sheet-3"… (capped at
settings.ASSET_SHEET_MAX_PAGES); pages are generated CONCURRENTLY
(settings.ASSET_GENERATION_CONCURRENCY, default 2 parallel image calls).

Image models reached through OpenAI-compatible gateways often ignore the
transparent-background parameter and paint a fake checkerboard instead, and may
return off-size canvases. `_postprocess_spritesheet` therefore normalizes each
sheet server-side: resize to the exact grid, then recover real transparency by
chroma-keying the solid magenta backdrop we prompt for (falling back to a
border-connected flood fill for light/checkerboard backdrops).
"""
from __future__ import annotations

import io
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.core.config import settings
from app.services.artifacts import binary_artifact
from app.services.provider_router import (
    MediaRequest,
    ProviderConfigurationError,
    ProviderGenerationError,
    ProviderRouter,
    ProviderStreamProtocolError,
)
from app.services.tilemaps import (
    TILE_SIZE,
    TILEMAP_ARCHETYPES,
    TILESET_GRID,
    TILESET_IMAGE_SIZE,
    generate_tilemap_artifacts,
)

SHEET_GRID = 4
SHEET_CELL = 256
SHEET_SIZE = SHEET_GRID * SHEET_CELL
# 同一角色的动画帧(敌人攻击帧、道具激活帧)要引用它前一格的画面;规划期还不
# 知道最终分页格位,先埋占位符,_sheet_prompt 按落定的格位替换成 row/column。
_PREV_REF = "@PREV_CELL@"


def _sheet_pages_cap() -> int:
    """图集页数上限(每页一次图像调用,16 格)。钳位防配置手滑打爆图像账单。"""
    return max(1, min(12, int(settings.ASSET_SHEET_MAX_PAGES)))


@dataclass(frozen=True)
class SheetCell:
    name: str  # semantic frame name, e.g. "player_idle"
    desc: str  # what to draw in this cell


@dataclass(frozen=True)
class PlannedAsset:
    key: str
    modality: str
    prompt: str
    size: str = "1024x1024"
    duration_seconds: int = 4
    extra: dict | None = None
    sheet_cells: tuple[SheetCell, ...] = ()
    # 本页上多帧角色的帧名组(首帧在前):manifest 的 animations 映射由此而来,
    # gameplay 代码据此建动画。组内帧保证同页(Phaser 动画帧必须同纹理)。
    sheet_groups: tuple[tuple[str, ...], ...] = ()


class AssetGenerationRetryRequired(RuntimeError):
    """A required image exhausted its automatic retry and needs user action."""


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return clean[:48]


def _frame_name(value: str, taken: set[str], default: str = "sprite") -> str:
    # 中日韩名字整串被 slug 清空(如"突击兵"),退回语义化 default
    # (enemy_3/obstacle_1...),而不是一堆 sprite_2/sprite_3。
    base = _slug(value).replace("-", "_") or _slug(default).replace("-", "_") or "sprite"
    name = base
    counter = 2
    while name in taken:
        name = f"{base}_{counter}"
        counter += 1
    taken.add(name)
    return name


def _clip_text(value, limit: int) -> str:
    """Whitespace-normalize and hard-cap a prompt fragment.

    Design fields arrive with full gameplay rule text (timers, drop rates,
    multi-sentence behavior specs). Uncapped they ballooned a sheet prompt to
    5KB+ and slowed generation past the provider timeout (2026-07-13 incident).
    """
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _entity_text(entity: dict) -> str:
    name = str(entity.get("name") or "").strip()
    # 画图提示词要的是外观：优先 visual,behavior 只在没有外观描述时兜底
    #（behavior 里常是"每2.2秒发射/35%概率掉落"这类数值规则,对图像模型是噪声）。
    desc = str(entity.get("visual") or "").strip() or str(entity.get("behavior") or "").strip()
    return _clip_text(", ".join(part for part in (name, desc) if part), 110)


# 实体分桶不做语义猜测:GameDesign 提示词强制 role 以这些小写英文标签开头
# (后可跟任意语言修饰语),这里只做标签前缀精确匹配。管线真正区分的桶只有
# 5 个;标签是给设计模型用的别名词表,按游戏类型自然表达(塔防的 structure、
# 平台跳跃的 platform、打砖块的 block...)。没带标签/词表外的标签一律进中性
# others 桶——照样分格子,但绝不冒充敌人;所以词表遗漏最坏也只是中性命名。
_ROLE_TAG_BUCKETS = {
    "player": "player",
    # 敌意实体:主动伤害玩家的东西
    "enemy": "enemy",
    "boss": "enemy",
    "hazard": "enemy",
    # 阻挡类场景:掩体/墙/平台/砖块——都参与"设计了就必须实现"的 QA 门禁
    "obstacle": "obstacle",
    "wall": "obstacle",
    "platform": "obstacle",
    "barrier": "obstacle",
    "block": "obstacle",
    "terrain": "obstacle",
    # 可拾取
    "pickup": "item",
    "item": "item",
    "powerup": "item",
    "collectible": "item",
    # 中性:友方/装置/目标物/弹体/装饰
    "npc": "other",
    "ally": "other",
    "structure": "other",
    "projectile": "other",
    "objective": "other",
    "decoration": "other",
}


def _entity_bucket(entity: dict) -> str:
    role = str(entity.get("role") or entity.get("type") or "").strip().lower()
    for tag, bucket in _ROLE_TAG_BUCKETS.items():
        if role == tag or (role.startswith(tag) and not role[len(tag)].isalnum()):
            return bucket
    return "other"


def _is_boss(entity: dict) -> bool:
    """Boss 拿第三帧(特技姿势)。role 前缀合同 + boss 字段合成实体的 behavior 标记。"""
    role = str(entity.get("role") or entity.get("type") or "").strip().lower()
    if role == "boss" or (role.startswith("boss") and not role[4:5].isalnum()):
        return True
    return str(entity.get("behavior") or "").strip().lower() == "boss"


def design_obstacles(design: dict) -> list[dict]:
    """Obstacle/cover entities declared by the design (shared with gameplay QA)."""
    return [
        entity
        for entity in (design or {}).get("entities") or []
        if isinstance(entity, dict) and _entity_bucket(entity) == "obstacle"
    ]


def _design_roster(design: dict) -> tuple[str, list[dict], list[str], list[dict], list[dict]]:
    """Extract (player desc, enemies, item descs, obstacles, neutral entities).

    分桶按 role 的规范标签前缀(生成合同,见 GAME_DESIGN_SYSTEM_PROMPT),
    不做语义猜测。任何实体都会拿到图集格子:旧实现把非白名单 role 直接丢掉,
    中文设计的 8 种敌人一个都没画进图集(2026-07-12 火线武装实测);未带
    标签的实体现在进中性 others 桶(entity_N)——有格子但不冒充敌人。
    """
    player_desc = ""
    player = design.get("player")
    if isinstance(player, dict):
        player_desc = str(player.get("visual") or "").strip()
    enemies: list[dict] = []
    items: list[str] = []
    obstacles: list[dict] = []
    others: list[dict] = []
    for entity in design.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        bucket = _entity_bucket(entity)
        if bucket == "player":
            if not player_desc:
                player_desc = _entity_text(entity)
        elif bucket == "obstacle":
            obstacles.append(entity)
        elif bucket == "item":
            items.append(_entity_text(entity))
        elif bucket == "enemy":
            enemies.append(entity)
        else:
            others.append(entity)
    boss = design.get("boss")
    if isinstance(boss, dict) and boss.get("name"):
        # 设计里 boss 常同时出现在 entities（role=boss）和 boss 字段:去重,
        # 否则同一个 Boss 占掉两个敌人格子（2026-07-13 实测事故）。
        boss_name = str(boss.get("name")).strip().casefold()
        if all(str(e.get("name") or "").strip().casefold() != boss_name for e in enemies + others):
            enemies.append({"name": boss.get("name"), "visual": boss.get("visual"), "behavior": "boss"})
    for item in (design.get("powerups") or []) + (design.get("reward_items") or []):
        if isinstance(item, dict) and item.get("name"):
            desc = str(item.get("name"))
            if item.get("effect"):
                desc += f" ({item.get('effect')})"
            items.append(_clip_text(desc, 90))
        elif isinstance(item, str):
            items.append(_clip_text(item, 90))
    return player_desc, enemies, items, obstacles, others


def _combat_arena(spec: dict, design: dict) -> bool:
    """枪战/射击/竞技场类:这些类型没有掩体就没有战术,图集必须画掩体格。

    只看 genre/archetype——两者都是上游提示词约定的规范标签(IntentSpec 的
    genre 词表、路由的 archetype 集合),不去扫标题/简介猜语义。
    """
    text = " ".join(
        str(value or "")
        for value in (spec.get("genre"), spec.get("archetype"), (design or {}).get("archetype"))
    ).lower()
    return any(word in text for word in ("shoot", "shooter", "battle", "arena", "gun"))


def _default_cover(title: str) -> list[dict]:
    return [
        {"name": "cover_block", "visual": f"a sturdy waist-high cover block / armored crate fitting {title}"},
        {"name": "cover_barrier", "visual": f"a wide barricade / sandbag wall segment fitting {title}"},
    ]


def _plan_sheet_pages(spec: dict, design: dict) -> list[tuple[tuple[SheetCell, ...], tuple[tuple[str, ...], ...]]]:
    """Roster → 16-cell pages plus the per-page animation frame groups.

    每个角色规划成一个"帧组":玩家 idle/move/action 核心姿势 + 设计驱动的
    技能/受伤姿势,敌人 idle+攻击帧(Boss 再加特技帧),道具 idle+激活帧。
    核心格(每个设计实体至少 1 格)先占预算,剩余容量按"玩家看得最多的先
    动起来"的优先级升级成动画帧;超出预算的升级直接放弃,设计实体绝不因
    动画帧被挤掉。
    """
    taken: set[str] = set()
    title = str(spec.get("title") or "the game")
    player_desc, enemies, items, obstacles, others = _design_roster(design)
    if not obstacles and _combat_arena(spec, design):
        # 枪战/竞技场设计缺掩体实体时补默认掩体格:游戏逻辑门禁要求真的用上。
        obstacles = _default_cover(title)
    player = _clip_text(player_desc, 160) or f"the hero of {title}"
    # abilities 是列表:逐条截断。直接 str(list) 会把 Python repr
    #（含整段玩法规则）泄进画图提示词（2026-07-13 实测事故）。
    raw_abilities = (design.get("player") or {}).get("abilities")
    if isinstance(raw_abilities, (list, tuple)):
        abilities = [text for text in (_clip_text(a, 60) for a in raw_abilities) if text]
    else:
        abilities = [text for text in [_clip_text(raw_abilities, 60)] if text]
    action = abilities[0] if abilities else "using the main ability"
    # 玩家外观只完整描述一次;后续姿势格引用第一格,避免同一段长描述重复 N 遍。
    # 玩家组永远是第一组,从第 1 页第 1 格起排,所以 row 1 column 1 引用恒成立。
    player_group: list[SheetCell] = [
        SheetCell(_frame_name("player_idle", taken), f"THE PLAYER: {player}. Idle standing pose"),
        SheetCell(_frame_name("player_move_a", taken), "the SAME player character as row 1 column 1, moving, animation frame A"),
        SheetCell(_frame_name("player_move_b", taken), "the SAME player character as row 1 column 1, moving, animation frame B (legs opposite to frame A)"),
        SheetCell(_frame_name("player_action", taken), f"the SAME player character as row 1 column 1, action pose: {action}"),
    ]
    groups: list[list[SheetCell]] = [player_group]
    enemy_groups: list[list[SheetCell]] = []
    enemy_descs: list[str] = []
    boss_flags: list[bool] = []
    for index, source in enumerate(enemies[:12]):
        desc = _entity_text(source) or "hostile creature"
        enemy_descs.append(desc)
        boss_flags.append(_is_boss(source))
        group = [SheetCell(_frame_name(str(source.get("name") or ""), taken, default=f"enemy_{index + 1}"), desc)]
        enemy_groups.append(group)
        groups.append(group)
    for index, source in enumerate(obstacles[:4]):
        desc = _entity_text(source) or f"a solid blocking obstacle fitting {title}"
        groups.append(
            [
                SheetCell(
                    _frame_name(str(source.get("name") or ""), taken, default=f"obstacle_{index + 1}"),
                    f"OBSTACLE / SOLID SCENERY: {desc}. A blocking object with a clean readable silhouette",
                )
            ]
        )
    item_groups: list[list[SheetCell]] = []
    for index, desc in enumerate(items[:6]):
        # 道具描述是 "名字, 外观" 或 "名字 (效果)":帧名只取名字段。
        label = desc.split("(")[0].split(",")[0]
        group = [SheetCell(_frame_name(label, taken, default=f"item_{index + 1}"), desc)]
        item_groups.append(group)
        groups.append(group)
    # 中性实体(npc/未带 role 标签的旧设计):有格子,但绝不标成 enemy_N,
    # 也不吃动画帧升级。旧设计整批落在这个桶里,上限给到 8。
    for index, source in enumerate(others[:8]):
        desc = _entity_text(source) or f"a neutral character or device fitting {title}"
        groups.append([SheetCell(_frame_name(str(source.get("name") or ""), taken, default=f"entity_{index + 1}"), desc)])
    for name, desc in (
        ("projectile", "the main projectile / bullet / thrown object, small and readable"),
        ("explosion", "impact explosion / burst effect"),
        ("flash", "action flash / sparkle / hit effect"),
        ("prop", f"a themed environment prop for {title}"),
    ):
        groups.append([SheetCell(_frame_name(name, taken), desc)])

    # —— 动画帧升级:核心格之外的剩余容量,优先级 = 玩家技能/受伤姿势 →
    # Boss 攻击+特技帧 → 普通敌人攻击帧 → 道具激活帧。预算耗尽即止。
    budget = SHEET_GRID * SHEET_GRID * _sheet_pages_cap() - sum(len(g) for g in groups)
    upgrades: list[tuple[list[SheetCell], str, str]] = []
    for order, ability in enumerate(abilities[1:3], start=2):
        upgrades.append(
            (player_group, f"player_skill_{order}", f"the SAME player character as row 1 column 1, alternate skill pose: {ability}")
        )
    upgrades.append((player_group, "player_hurt", "the SAME player character as row 1 column 1, hurt / knockback pose, flinching"))
    for i in sorted(range(len(enemy_groups)), key=lambda idx: not boss_flags[idx]):
        base = enemy_groups[i][0].name
        upgrades.append((enemy_groups[i], f"{base}_b", f"the SAME character as {_PREV_REF}, attack / action pose, animation frame B"))
        if boss_flags[i]:
            upgrades.append(
                (enemy_groups[i], f"{base}_c", f"the SAME character as {_PREV_REF}, unleashing its special skill, dramatic charged-up pose, animation frame C")
            )
    for group in item_groups:
        upgrades.append((group, f"{group[0].name}_b", f"the SAME item as {_PREV_REF}, activated state, glowing and sparkling, animation frame B"))
    # —— 第二梯队(容量富余时,页数上限高的环境才吃得到):玩家通用动作姿势、
    # 第 4-5 个技能、全体敌人移动帧。顺序仍按"玩家看得最多的先动起来"。
    upgrades.append((player_group, "player_jump", "the SAME player character as row 1 column 1, jumping / airborne pose"))
    upgrades.append((player_group, "player_death", "the SAME player character as row 1 column 1, defeated / knocked-down pose"))
    upgrades.append((player_group, "player_victory", "the SAME player character as row 1 column 1, victory celebration pose"))
    for order, ability in enumerate(abilities[3:5], start=4):
        upgrades.append(
            (player_group, f"player_skill_{order}", f"the SAME player character as row 1 column 1, alternate skill pose: {ability}")
        )
    for i in sorted(range(len(enemy_groups)), key=lambda idx: not boss_flags[idx]):
        base = enemy_groups[i][0].name
        upgrades.append(
            (enemy_groups[i], f"{base}_move", f"the SAME character as {_PREV_REF}, moving / walking, mid-stride, movement animation frame")
        )
    for group, seed, desc in upgrades:
        if budget <= 0:
            break
        group.append(SheetCell(_frame_name(seed, taken), desc))
        budget -= 1

    # 补缝/补满用的中性内容:已付费的画布不留空白品红格。
    fillers = [
        "score pickup / collectible",
        "health or shield pickup",
        "power-up item",
        f"a decorative environment prop for {title}",
    ] + [f"a distinct variant of: {desc}"[:160] for desc in enemy_descs[:4]]
    return _paginate(groups, fillers, taken)


def _paginate(
    groups: list[list[SheetCell]], fillers: list[str], taken: set[str]
) -> list[tuple[tuple[SheetCell, ...], tuple[tuple[str, ...], ...]]]:
    """Pack frame groups into 16-cell pages; a group never straddles pages
    (Phaser animations require all frames on one texture).

    页尾装不下下一个帧组时,先把后面的单格组拉上来填缝(真内容优先),
    还不满再用 filler 格补齐。页数到达上限后丢弃剩余组——升级预算已按
    总容量收口,只有极端的跨页碎缝才会走到这一步。
    """
    page_size = SHEET_GRID * SHEET_GRID
    pages_cap = _sheet_pages_cap()
    pages: list[tuple[tuple[SheetCell, ...], tuple[tuple[str, ...], ...]]] = []
    current: list[SheetCell] = []
    current_groups: list[tuple[str, ...]] = []
    bonus = 0

    def close_page() -> None:
        nonlocal current, current_groups, bonus
        while len(current) < page_size:
            current.append(SheetCell(_frame_name("", taken, default=f"bonus_{bonus + 1}"), fillers[bonus % len(fillers)]))
            bonus += 1
        pages.append((tuple(current), tuple(current_groups)))
        current, current_groups = [], []

    queue = list(groups)
    index = 0
    while index < len(queue) and len(pages) < pages_cap:
        group = queue[index]
        if len(current) + len(group) <= page_size:
            current.extend(group)
            if len(group) > 1:
                current_groups.append(tuple(cell.name for cell in group))
            index += 1
            continue
        scan = index + 1
        while len(current) < page_size and scan < len(queue):
            if len(queue[scan]) == 1:
                current.extend(queue.pop(scan))
            else:
                scan += 1
        close_page()
    if len(pages) < pages_cap and (current or not pages):
        close_page()
    return pages


def _style_line(spec: dict, design: dict) -> str:
    style = _clip_text(spec.get("visual_style") or spec.get("theme") or "vibrant stylized", 120)
    palette = design.get("palette")
    hint = ""
    if isinstance(palette, dict):
        colors = [str(v) for v in palette.values() if isinstance(v, str) and v.startswith("#")]
        if colors:
            hint = f" Palette accents: {', '.join(colors[:5])}."
    return f"{style} 2D game art, crisp silhouettes with dark outlines, consistent style, palette and lighting across ALL sprites.{hint}"


def _sheet_prompt(spec: dict, design: dict, cells: tuple[SheetCell, ...], page: int = 0, pages: int = 1) -> str:
    series = (
        ""
        if pages <= 1
        else (
            f" This is sheet {page + 1} of {pages} for the SAME game: keep characters, palette,"
            " outline weight, and lighting IDENTICAL across all sheets."
        )
    )
    lines = [
        f"Sprite sheet for the browser game '{spec.get('title') or 'Untitled'}'. {_style_line(spec, design)}{series}",
        f"EXACTLY a {SHEET_GRID}x{SHEET_GRID} grid of equal {SHEET_CELL}x{SHEET_CELL} cells filling the whole {SHEET_SIZE}x{SHEET_SIZE} canvas.",
        "One sprite centered per cell, filling about 70% of its cell, never touching or crossing cell edges.",
    ]
    for index, cell in enumerate(cells):
        row, col = divmod(index, SHEET_GRID)
        desc = cell.desc
        if _PREV_REF in desc and index > 0:
            # 动画帧引用同组前一帧:组不跨页,前一帧必在本页,替换成确切格位。
            prev_row, prev_col = divmod(index - 1, SHEET_GRID)
            desc = desc.replace(_PREV_REF, f"the cell at row {prev_row + 1} column {prev_col + 1}")
        lines.append(f"Cell row {row + 1} column {col + 1}: {desc}.")
    lines.append(
        "The ENTIRE background of the whole canvas must be one solid pure magenta color (#FF00FF), "
        "including between and around sprites. Never use magenta inside any sprite. "
        "No grid lines, no cell borders, no checkerboard pattern, no text, no labels, no watermark."
    )
    return " ".join(lines)


def plan_game_assets(state: dict) -> list[PlannedAsset]:
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    title = str(spec.get("title") or "GameWeave game")
    theme = str(spec.get("theme") or "stylized arcade")
    prompt = str(state.get("normalized_prompt") or state.get("prompt") or "")
    pages = _plan_sheet_pages(spec, design)
    # quality=medium 是硬约束不是省钱：网关经 Cloudflare 代理,~100s 超时墙,
    # 16 精灵图集按默认质量常需 100-180s 被 524 掐死;medium 实测 ~72s 且
    # 像素风画质无损（2026-07-13 基准）。不认识该参数的网关会忽略它。
    planned = [
        PlannedAsset(
            "sheet" if index == 0 else f"sheet-{index + 1}",
            "image",
            _sheet_prompt(spec, design, cells, index, len(pages)),
            size=f"{SHEET_SIZE}x{SHEET_SIZE}",
            extra={"background": "transparent", "quality": "medium"},
            sheet_cells=cells,
            sheet_groups=cell_groups,
        )
        for index, (cells, cell_groups) in enumerate(pages)
    ]
    # 场景背景变体:主场景 / 同场景高压(Boss)阶段 / 换区。gameplay 代码按阶段
    # 切换 Backdrop(assetKeys.backgrounds),游戏有可感知的场景变化。
    scene_variants = [
        ("background", "This is the MAIN gameplay stage in its normal state."),
        (
            "background-2",
            "This is the SAME location as the main stage but in a LATER, high-intensity phase: "
            "dramatically shifted lighting (danger / boss-fight mood), heavier atmosphere, small "
            "environmental damage or energy effects. Same composition family, clearly the same place.",
        ),
        (
            "background-3",
            "This is a DIFFERENT area of the same game world, used for a stage change: new landmark "
            "composition and layout, unmistakably the same world and rendering style.",
        ),
    ][: max(1, min(3, int(settings.ASSET_BACKGROUND_VARIANTS)))]
    for index, (bg_key, variant) in enumerate(scene_variants):
        series = (
            ""
            if len(scene_variants) <= 1
            else (
                f" Scene {index + 1} of {len(scene_variants)} for the SAME game: keep the art style,"
                " palette, lighting language and rendering IDENTICAL across all scenes."
            )
        )
        planned.append(
            PlannedAsset(
                bg_key,
                "image",
                (
                    f"Wide scenic background for the browser game '{title}'. {_style_line(spec, design)} "
                    f"Theme: {theme}. An atmospheric game environment with depth, darker and less detailed toward the center "
                    f"so gameplay sprites stay readable on top. {variant}{series} "
                    "No characters, no creatures, no UI, no text, no watermark."
                ),
                "1536x1024",
                extra={"quality": "medium"},
            )
        )
    lower = prompt.lower()
    if any(word in lower for word in ("music", "soundtrack", "bgm", "音乐", "配乐")):
        planned.append(PlannedAsset("bgm", "audio", f"Short looping {theme} game music for {title}", duration_seconds=8))
    if any(word in lower for word in ("video background", "animated background", "视频背景", "动态背景")):
        planned.append(PlannedAsset("background-loop", "video", f"Seamless {theme} animated game background for {title}", duration_seconds=4))
    return planned[: max(0, int(settings.ASSET_GENERATION_MAX_ITEMS))]


def _is_light_bg(r: int, g: int, b: int) -> bool:
    mx = max(r, g, b)
    return mx >= 172 and mx - min(r, g, b) <= 48


def _magenta_distance(r: int, g: int, b: int) -> int:
    return (255 - r) + g + (255 - b)


def _unmix_magenta(r: int, g: int, b: int, a: int) -> tuple[int, int, int]:
    """Recover the sprite color from an anti-aliased edge pixel.

    Edge pixels are `a*sprite + (1-a)*magenta`; without unmixing they render as
    a pink fringe around every sprite. Solve back for the sprite color.
    """
    if a <= 0 or a >= 255:
        return r, g, b
    inv = 255 - a
    red = min(255, max(0, (255 * r - 255 * inv) // a))
    blue = min(255, max(0, (255 * b - 255 * inv) // a))
    green = min(255, (255 * g) // a)
    return red, green, blue


def _dilate_rgb_into_transparent(data: list, width: int, height: int, passes: int = 2) -> list:
    """Bleed sprite RGB one ring at a time into fully-transparent neighbors.

    GPU linear filtering samples the RGB of transparent texels next to sprite
    edges; leaving the keyed backdrop color there produces colored halos.
    """
    colored = bytearray(a > 32 for _, _, _, a in data)
    for _ in range(max(0, passes)):
        src = list(data)
        source_mask = bytes(colored)
        for idx, (r, g, b, a) in enumerate(src):
            if a != 0 or colored[idx]:
                continue
            x, y = idx % width, idx // width
            rs = gs = bs = count = 0
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    nidx = ny * width + nx
                    if source_mask[nidx]:
                        nr, ng, nb, _na = src[nidx]
                        rs += nr
                        gs += ng
                        bs += nb
                        count += 1
            if count:
                data[idx] = (rs // count, gs // count, bs // count, 0)
                colored[idx] = 1
    return data


_COMPRESS_MIN_BYTES = 262_144
_COMPRESS_KEEP_RATIO = 0.85


def _compress_image_asset(
    content: bytes, content_type: str, extension: str, *, keep_alpha: bool
) -> tuple[bytes, str, str]:
    """Re-encode large raster assets as WebP.

    Provider PNGs run 1.5-2.7MB each; a bundle of sheets and background
    variants pushed total payloads past 14MB and browser load times past 20s.
    Sprite sheets keep alpha (lossless vs q95, whichever is smaller); plain
    backgrounds go lossy q85. The original is kept when WebP does not win by
    a meaningful margin, so this can never make a bundle worse.
    """
    lowered = (content_type or "").lower()
    if len(content) < _COMPRESS_MIN_BYTES or ("png" not in lowered and "jpeg" not in lowered):
        return content, content_type, extension
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content))
        candidates: list[bytes] = []
        if keep_alpha:
            rgba = img.convert("RGBA")
            for kwargs in (
                {"lossless": True, "method": 4},
                {"quality": 95, "method": 5},
            ):
                out = io.BytesIO()
                rgba.save(out, format="WEBP", **kwargs)
                candidates.append(out.getvalue())
        else:
            out = io.BytesIO()
            img.convert("RGB").save(out, format="WEBP", quality=85, method=5)
            candidates.append(out.getvalue())
        best = min(candidates, key=len)
        if len(best) <= len(content) * _COMPRESS_KEEP_RATIO:
            return best, "image/webp", ".webp"
    except Exception:  # noqa: BLE001 - compression is best-effort
        import logging

        logging.getLogger(__name__).exception(
            "image asset compression failed; keeping original"
        )
    return content, content_type, extension


def _postprocess_spritesheet(raw: bytes, content_type: str) -> bytes:
    """Normalize a generated sheet: exact size + real alpha transparency."""
    if "svg" in (content_type or "").lower():
        raise ValueError("vector placeholder cannot be sliced into a spritesheet")
    from PIL import Image

    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    if img.size != (SHEET_SIZE, SHEET_SIZE):
        img = img.resize((SHEET_SIZE, SHEET_SIZE), Image.LANCZOS)

    data = list(img.getdata())
    total = len(data)
    transparent = sum(1 for _, _, _, a in data if a < 16)
    if transparent >= total * 0.05:
        pass  # provider delivered real alpha — keep as-is
    else:
        magenta_hits = sum(1 for r, g, b, _ in data if _magenta_distance(r, g, b) <= 120)
        if magenta_hits >= total * 0.03:
            # Chroma-key the prompted magenta backdrop: hard-key the flat area,
            # feather + unmix the anti-aliased edge band, then bleed sprite RGB
            # into the cleared pixels so linear filtering cannot show pink halos.
            keyed = []
            for r, g, b, a in data:
                dist = _magenta_distance(r, g, b)
                if dist <= 120:
                    keyed.append((r, g, b, 0))
                elif dist <= 200:
                    alpha = min(a, (dist - 120) * 255 // 80)
                    keyed.append((*_unmix_magenta(r, g, b, alpha), alpha))
                else:
                    keyed.append((r, g, b, a))
            img.putdata(_dilate_rgb_into_transparent(keyed, img.width, img.height))
        else:
            # Fallback: the model painted a light/checkerboard backdrop. Clear
            # everything light-and-unsaturated that connects to the sheet border;
            # sprites survive as interior islands behind their dark outlines.
            width, height = img.size
            seen = bytearray(total)
            queue: deque[int] = deque()
            for x in range(width):
                for y in (0, height - 1):
                    idx = y * width + x
                    if not seen[idx] and _is_light_bg(*data[idx][:3]):
                        seen[idx] = 1
                        queue.append(idx)
            for y in range(height):
                for x in (0, width - 1):
                    idx = y * width + x
                    if not seen[idx] and _is_light_bg(*data[idx][:3]):
                        seen[idx] = 1
                        queue.append(idx)
            while queue:
                idx = queue.popleft()
                x, y = idx % width, idx // width
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        nidx = ny * width + nx
                        if not seen[nidx] and _is_light_bg(*data[nidx][:3]):
                            seen[nidx] = 1
                            queue.append(nidx)
            cleared = [
                (r, g, b, 0) if seen[i] else (r, g, b, a)
                for i, (r, g, b, a) in enumerate(data)
            ]
            if sum(1 for flag in seen if flag) < total * 0.02:
                raise ValueError("could not identify a keyable sheet background")
            img.putdata(_dilate_rgb_into_transparent(cleared, img.width, img.height))

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _sheet_manifest_extra(cells: tuple[SheetCell, ...], groups: tuple[tuple[str, ...], ...]) -> dict:
    return {
        "frame_width": SHEET_CELL,
        "frame_height": SHEET_CELL,
        "frames": {cell.name: index for index, cell in enumerate(cells)},
        # 每个多帧角色一条:首帧名 → 该角色的全部帧(按图集顺序)。gameplay
        # 代码据此建动画:移动/攻击双帧循环、Boss 特技帧、道具激活态。
        "animations": {names[0]: list(names) for names in groups if names},
    }


def _tileset_prompt(spec: dict, design: dict) -> str:
    """AI tileset in the SAME style pipeline as the sheet/background.

    旧实现直接船一张硬编码 2 格 SVG(紫色大 X 占位图),与 AI 图集/背景放在
    同一个资产面板里画风天差地别(2026-07-12 用户实测反馈)。
    """
    title = str(spec.get("title") or "Untitled")
    cell_px = SHEET_SIZE // TILESET_GRID
    return " ".join(
        [
            f"Top-down 2D game environment tileset for the browser game '{title}'. {_style_line(spec, design)}",
            f"EXACTLY a {TILESET_GRID}x{TILESET_GRID} grid of equal {cell_px}x{cell_px} cells filling the whole {SHEET_SIZE}x{SHEET_SIZE} canvas.",
            "Row 1: four seamless ground/floor tiles filling their cells completely edge-to-edge (base floor, worn variant, detailed variant, floor with glowing accent lines).",
            "Row 2: four solid structure tiles filling their cells completely edge-to-edge: reinforced wall block, damaged wall block, heavy cover crate, barricade segment.",
            "Row 3: four standalone props centered in their cells at about 80% cell size: barrel or container, machinery or vent, rubble or debris pile, glowing hazard marker.",
            "Row 4: four subtle decal tiles: floor crack or stain, warning stripe strip, small light cluster, directional floor marking.",
            "The backdrop around and between the standalone props and decals of rows 3 and 4 must be one solid pure magenta color (#FF00FF). Never use magenta inside any tile art.",
            "No grid lines, no cell borders, no checkerboard pattern, no text, no labels, no watermark.",
        ]
    )


def _postprocess_tileset(raw: bytes, content_type: str) -> bytes:
    """Key the generated tileset like a sheet, then downscale per cell to the
    runtime tile grid. Per-cell resize keeps LANCZOS from bleeding one cell's
    colors across its neighbor's border, which would leave semi-transparent
    seams on adjoining floor tiles."""
    from PIL import Image

    keyed = Image.open(io.BytesIO(_postprocess_spritesheet(raw, content_type))).convert("RGBA")
    cell_px = SHEET_SIZE // TILESET_GRID
    out_img = Image.new("RGBA", (TILESET_IMAGE_SIZE, TILESET_IMAGE_SIZE), (0, 0, 0, 0))
    for index in range(TILESET_GRID * TILESET_GRID):
        col, row = index % TILESET_GRID, index // TILESET_GRID
        cell = keyed.crop((col * cell_px, row * cell_px, (col + 1) * cell_px, (row + 1) * cell_px))
        out_img.paste(cell.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS), (col * TILE_SIZE, row * TILE_SIZE))
    out = io.BytesIO()
    out_img.save(out, format="PNG")
    return out.getvalue()


def _screen_size(design: dict) -> tuple[int, int]:
    """Design screen size with the scaffold's own clamps (defaults 1152x768)."""
    screen = design.get("screen") if isinstance(design.get("screen"), dict) else {}

    def _num(value, default: int, lo: int, hi: int) -> int:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            parsed = default
        return max(lo, min(hi, parsed))

    return _num(screen.get("width"), 1152, 640, 1600), _num(screen.get("height"), 768, 480, 1000)


def _generate_with_retry(router: ProviderRouter, request: MediaRequest, logs: list[str], key: str):
    """Retry ordinary generation errors before requiring manual retry.

    Configuration failures do not heal. An invalid/empty final streaming event
    is also not retried because the provider may already have generated and
    billed the image; repeating it can duplicate both output and cost.
    """
    retries = max(0, min(4, int(settings.ASSET_PROVIDER_MAX_RETRIES)))
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            return router.generate(request)
        except ProviderStreamProtocolError:
            raise
        except ProviderGenerationError as exc:
            if attempt >= attempts:
                raise
            logs.append(
                f"{key}: attempt {attempt} failed ({_clip_text(exc, 140)}); "
                f"retrying attempt {attempt + 1}/{attempts}"
            )
    raise AssertionError("asset generation retry loop exited unexpectedly")


def _produce_media(router: ProviderRouter, item: PlannedAsset) -> tuple:
    """Worker: generate one planned asset off-thread → (media, error, local logs).

    异常作为返回值带回,由主循环按计划顺序统一定夺——错误语义与日志顺序
    因此保持串行版的确定性,与线程完成的先后无关。
    """
    logs: list[str] = []
    try:
        media = _generate_with_retry(
            router,
            MediaRequest(
                modality=item.modality,  # type: ignore[arg-type]
                prompt=item.prompt,
                size=item.size,
                duration_seconds=item.duration_seconds,
                extra=item.extra,
            ),
            logs,
            item.key,
        )
    except Exception as exc:  # noqa: BLE001 —— 跨线程传回,主循环分类处理
        return None, exc, logs
    return media, None, logs


def generate_game_assets(state: dict, router: ProviderRouter | None = None) -> dict:
    router = router or ProviderRouter()
    artifacts: list[dict] = []
    manifest_entries: list[dict] = []
    logs: list[str] = []

    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    tilemap_wanted = (
        settings.TILEMAP_GENERATION_ENABLED
        and state.get("dimension") != "3d"
        and str(spec.get("archetype") or "") in TILEMAP_ARCHETYPES
    )

    planned = plan_game_assets(state) if settings.ASSET_GENERATION_ENABLED else []
    results: list[tuple] = []
    tileset_result: tuple | None = None
    if planned or (tilemap_wanted and settings.ASSET_GENERATION_ENABLED):
        # 图像调用并行化:图集页数扩容后串行墙钟时间不可接受(单页实测 ~72s,
        # 3 页图集+背景串行近 5 分钟)。httpx 按请求建连,ProviderRouter 无共享
        # 可变状态,线程安全。并发保守取 2,避免踩网关限流。失败语义:所有
        # 在飞请求跑完后按计划顺序结算,首个失败的图像资产仍旧暂停整条流水线。
        workers = max(1, int(settings.ASSET_GENERATION_CONCURRENCY))
        logs.append(f"dispatching {len(planned)} asset request(s), concurrency {workers}")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_produce_media, router, item) for item in planned]
            tileset_future = None
            if tilemap_wanted and settings.ASSET_GENERATION_ENABLED:
                tileset_future = pool.submit(
                    _produce_media,
                    router,
                    PlannedAsset(
                        "tileset",
                        "image",
                        _tileset_prompt(spec, design),
                        size=f"{SHEET_SIZE}x{SHEET_SIZE}",
                        extra={"background": "transparent", "quality": "medium"},
                    ),
                )
            results = [future.result() for future in futures]
            if tileset_future is not None:
                tileset_result = tileset_future.result()

    for item, (media, error, item_logs) in zip(planned, results):
        logs.extend(item_logs)
        if error is not None:
            if not isinstance(error, (ProviderConfigurationError, ProviderGenerationError)):
                raise error
            if item.modality == "image":
                if isinstance(error, ProviderConfigurationError):
                    detail = "could not start because the image provider is not configured correctly"
                else:
                    detail = (
                        f"failed after {max(0, int(settings.ASSET_PROVIDER_MAX_RETRIES))} "
                        "automatic retries"
                    )
                raise AssetGenerationRetryRequired(
                    f"Image asset '{item.key}' {detail}: {_clip_text(error, 220)}. "
                    "Generation is paused; waiting for manual retry."
                ) from error
            if not settings.ASSET_GENERATION_FAIL_OPEN:
                raise error
            logs.append(f"{item.key}: {error}; skipped")
            continue
        content = media.content
        content_type = media.content_type
        extension = media.extension
        kind = item.modality
        entry_extra: dict = {}
        if item.sheet_cells and item.modality == "image":
            try:
                content = _postprocess_spritesheet(media.content, media.content_type)
                content_type, extension = "image/png", ".png"
                kind = "spritesheet"
                entry_extra = _sheet_manifest_extra(item.sheet_cells, item.sheet_groups)
                logs.append(
                    f"{item.key}: normalized to {SHEET_SIZE}px spritesheet "
                    f"({SHEET_GRID}x{SHEET_GRID} grid, {len(item.sheet_cells)} named frames, "
                    f"{len(item.sheet_groups)} animated actor(s))"
                )
            except Exception as exc:  # noqa: BLE001 —— invalid generated image requires manual retry
                raise AssetGenerationRetryRequired(
                    f"Image asset '{item.key}' was generated but could not be normalized as a spritesheet: "
                    f"{_clip_text(exc, 220)}. Generation is paused; waiting for manual retry."
                ) from exc
        if kind in {"image", "spritesheet"}:
            original_bytes = len(content)
            content, content_type, extension = _compress_image_asset(
                content, content_type, extension, keep_alpha=(kind == "spritesheet")
            )
            if extension == ".webp" and original_bytes != len(content):
                logs.append(
                    f"{item.key}: recompressed to WebP "
                    f"({original_bytes // 1024}KB -> {len(content) // 1024}KB)"
                )
        runtime_path = f"assets/{item.key}{extension}"
        artifacts.append(binary_artifact(f"public/{runtime_path}", content, content_type))
        manifest_entries.append(
            {
                "key": item.key,
                "kind": kind,
                "path": runtime_path,
                "content_type": content_type,
                "provider": media.provider,
                "model": media.model,
                **entry_extra,
            }
        )
        logs.append(f"{item.key}: generated {item.modality} via {media.provider}/{media.model}")

    if tilemap_wanted:
        archetype = str(spec.get("archetype") or "")
        tileset_png: bytes | None = None
        tileset_provider, tileset_model = "procedural", "palette"
        if tileset_result is not None:
            # tileset 与图集/背景走同一画风管线(并行批里一起生成);它是氛围
            # 装饰,失败不值得暂停整条流水线 —— 任何异常都回退调色板程序化 tileset。
            media, error, tileset_logs = tileset_result
            logs.extend(tileset_logs)
            if error is not None:
                if not isinstance(error, (ProviderConfigurationError, ProviderGenerationError)):
                    raise error
                if isinstance(error, ProviderConfigurationError):
                    detail = "could not start because the image provider is not configured correctly"
                else:
                    detail = (
                        f"failed after {max(0, int(settings.ASSET_PROVIDER_MAX_RETRIES))} "
                        "automatic retries"
                    )
                raise AssetGenerationRetryRequired(
                    f"Image asset 'tileset' {detail}: {_clip_text(error, 220)}. "
                    "Generation is paused; waiting for manual retry."
                ) from error
            else:
                try:
                    tileset_png = _postprocess_tileset(media.content, media.content_type)
                    tileset_provider, tileset_model = media.provider, media.model
                    logs.append(
                        f"tileset: generated via {media.provider}/{media.model}, "
                        f"normalized to {TILESET_IMAGE_SIZE}px tile grid"
                    )
                except Exception as exc:  # noqa: BLE001 —— invalid generated image requires manual retry
                    raise AssetGenerationRetryRequired(
                        "Image asset 'tileset' was generated but could not be normalized: "
                        f"{_clip_text(exc, 220)}. Generation is paused; waiting for manual retry."
                    ) from exc
        screen_width, screen_height = _screen_size(design)
        seed = str(state.get("task_id") or state.get("prompt") or archetype)
        tilemap = generate_tilemap_artifacts(
            archetype,
            seed,
            screen_width=screen_width,
            screen_height=screen_height,
            palette=design.get("palette") if isinstance(design.get("palette"), dict) else None,
            tileset_png=tileset_png,
            tileset_provider=tileset_provider,
            tileset_model=tileset_model,
        )
        if tilemap:
            tile_artifacts, tile_entries = tilemap
            artifacts.extend(tile_artifacts)
            manifest_entries.extend(tile_entries)
            logs.append(f"tilemap: generated deterministic Tiled JSON for {archetype}")

    return {"artifacts": artifacts, "manifest_entries": manifest_entries, "logs": logs}
