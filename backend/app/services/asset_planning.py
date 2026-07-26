"""Semantic asset planning: design roster → sheet pages → provider prompts.

2026-07-26 拆分自 ``game_assets.py``:本模块只做纯规划(实体分桶、帧组预算、
分页、提示词构图、manifest 元数据),不碰像素也不碰供应商。编排、供应商兜底
链、审计/评审/修复循环留在 ``app.services.game_assets``,它回导这里的全部名
字,既有调用方和测试的导入路径不变。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from app.core.config import settings
from app.services.sprite_pipeline import SpriteDemand, strip_ui_overlay_demands
from app.services.tilemaps import TILESET_GRID


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
    # 作者可读的帧语义(manifest frame_meta)。帧名(entity_3)本身不携带含义,
    # 丢掉描述作者只能按顺序瞎猜——像素都市计划把住/商/电/水整体错位一格
    # (2026-07-17)。空则回退 desc。
    meta: str = ""
    # 可连接图块族(道路/管道/铁轨):非空时本格是族内一个变体。tile_base 是
    # 族基准帧名(=straight 格帧名),tile_slot ∈ _TILE_SLOTS 槽位。族格同页
    # 但不进动画组——它们是邻接变体,不是动画帧。
    tile_base: str = ""
    tile_slot: str = ""
    # Semantic identity is deliberately separate from the legacy frame name.
    # Existing Phaser projects can keep loading `frames[name]`, while new
    # projects resolve `semantic_frames["residential.level_3"]`.
    semantic_id: str = ""
    required: bool = True
    consumer_refs: tuple[str, ...] = ()
    variant_strategy: str = "generated"
    expected_object_count: int = 1


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


def _frame_semantic_id(name: str) -> str:
    """Map legacy frame keys to stable semantic IDs.

    This is intentionally deterministic and conservative.  A future design
    may provide an explicit ``semantic_id`` on ``SheetCell``; generated legacy
    keys still get a useful dotted ID so runtime code never has to depend on a
    numeric sheet index.
    """
    value = str(name or "").strip().lower()
    if not value or value.startswith("bonus_"):
        return ""
    if value.startswith("player_"):
        return "player." + value[len("player_") :]
    if value.startswith(("projectile", "explosion", "flash", "prop")):
        return "effect." + value.replace("_", ".")
    if value.endswith("_b"):
        return value[:-2] + ".attack"
    if value.endswith("_c"):
        return value[:-2] + ".special"
    if value.endswith("_move"):
        return value[:-5] + ".move"
    if value.endswith("_activated"):
        return value[: -len("_activated")] + ".activated"
    if "_level_" in value:
        left, level = value.split("_level_", 1)
        return f"{left}.level_{level}"
    if value.endswith("_idle"):
        return value[:-5] + ".idle"
    return value + ".default"


def _cell_demand(cell: SheetCell) -> SpriteDemand:
    semantic_id = cell.semantic_id or _frame_semantic_id(cell.name) or cell.name
    state = semantic_id.rsplit(".", 1)[-1] if "." in semantic_id else "default"
    object_name = semantic_id.rsplit(".", 1)[0] if "." in semantic_id else semantic_id
    return SpriteDemand(
        semantic_id=semantic_id,
        frame_id=cell.name,
        object_name=object_name,
        state=state,
        consumer_refs=cell.consumer_refs or ((f"design:{object_name}",) if cell.required else ()),
        required=cell.required and not cell.name.startswith("bonus_"),
        animated=state not in {"default", "idle"},
        batch_group=object_name,
        expected_object_count=max(1, int(cell.expected_object_count or 1)),
        variant_strategy=cell.variant_strategy,
        metadata={"description": cell.desc, "meta": cell.meta},
    )


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
    desc = str(entity.get("visual") or "").strip()
    if not desc:
        requirements = entity.get("visual_requirements")
        if isinstance(requirements, (list, tuple, set)):
            desc = ", ".join(str(item).strip() for item in requirements if str(item).strip())
        elif requirements:
            desc = str(requirements).strip()
    desc = desc or str(entity.get("behavior") or "").strip()
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


# 可连接结构(玩家延展的道路/管道/铁轨)需要一整族邻接变体图块:单格素材
# 拼不出连续路网(2026-07-17 像素都市计划:全城道路=同一块十字贴图)。槽位
# 的画布朝向是运行时 tileVariant() 旋转表的契约,两边必须保持一致:
# straight=左右贯通、end=只开右口、corner=右+下、tee=左+右+下、cross=四向。
_TILE_SLOTS = (
    ("straight", "the STRAIGHT piece: its surface runs horizontally, entering the exact middle of the LEFT and RIGHT cell edges"),
    ("end", "the DEAD-END cap piece: the surface enters only the exact middle of the RIGHT cell edge and terminates in a closed cap near the cell center"),
    ("corner", "the 90-degree CORNER piece: the surface enters the exact middle of the RIGHT and BOTTOM cell edges and turns smoothly between them"),
    ("tee", "the T-JUNCTION piece: the surface enters the exact middle of the LEFT, RIGHT and BOTTOM cell edges"),
    ("cross", "the 4-WAY CROSSING piece: the surface enters the exact middle of ALL FOUR cell edges"),
)
_CONNECT_NAME_TOKENS = (
    "道路", "公路", "马路", "管道", "铁轨", "轨道", "铁路", "传送带",
    "road", "pipe", "rail", "track", "conveyor",
)
_CONNECT_VISUAL_TOKENS = (
    "直线", "转角", "丁字", "十字", "图块",
    "autotile", "auto-tile", "straight", "corner", "junction", "crossroad",
)


def _is_connectable(entity: dict) -> bool:
    """玩家延展的网络结构(道路/管道/铁轨):要整族邻接变体而不是单格。

    优先认设计合同的显式 connects 标记(GAME_DESIGN_SYSTEM_PROMPT);旧设计
    回退到名称/外观词表——只扫 visual 不扫 behavior:"必须正交邻接道路"这类
    规则文本出现在每个建筑的 behavior 里,扫了会全体误报。
    """
    if bool(entity.get("connects")):
        return True
    name = str(entity.get("name") or "").lower()
    if any(token in name for token in _CONNECT_NAME_TOKENS):
        return True
    visual = str(entity.get("visual") or "").lower()
    return any(token in visual for token in _CONNECT_VISUAL_TOKENS)


def _tile_family_group(base: str, desc: str, taken: set[str]) -> list[SheetCell]:
    """一个可连接结构的 5 格图块族(直/端/角/丁/十,_paginate 保证同页)。

    基准格(straight)持有完整外观描述,其余格引用前一格画风。族格的连接面
    必须贴到格边缘,_sheet_prompt 对含族的页面放开"70% 居中"约束。
    """
    cells: list[SheetCell] = []
    for order, (slot, slot_desc) in enumerate(_TILE_SLOTS):
        name = base if order == 0 else _frame_name(f"{base}_{slot}", taken)
        if order == 0:
            text = (
                f"SEAMLESS CONNECTABLE TILE ({desc}): {slot_desc}. "
                "The connecting surface touches the exact cell edges at full width so adjacent copies join seamlessly"
            )
        else:
            text = (
                f"SEAMLESS CONNECTABLE TILE, the SAME construction style, width and colors as {_PREV_REF}: {slot_desc}. "
                "Connecting ends touch the exact cell edges"
            )
        cells.append(
            SheetCell(
                name,
                text,
                meta=f"{desc} — {slot} piece of a connectable tile family",
                tile_base=base,
                tile_slot=slot,
                semantic_id=f"{base}.{slot}",
            )
        )
    return cells


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


def _builder_management(spec: dict, design: dict) -> bool:
    """建造/经营/模拟类:玩家自己放置建筑,背景画进任何建成物都会与玩家的
    放置物混同(2026-07-17 像素都市计划:背景整座建成城市,放置物全被淹没)。

    与 _combat_arena 同规矩:只看 genre/archetype 规范标签字段,不扫标题。
    """
    text = " ".join(
        str(value or "")
        for value in (
            spec.get("genre"),
            spec.get("archetype"),
            (design or {}).get("archetype"),
            ((design or {}).get("balance") or {}).get("genre"),
        )
    ).lower()
    return any(word in text for word in ("simulation", "builder", "tycoon", "management", "city", "farm", "colony"))


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
        SheetCell(_frame_name("player_idle", taken), f"THE PLAYER: {player}. Idle standing pose", semantic_id="player.idle"),
        SheetCell(_frame_name("player_move_a", taken), "the SAME player character as row 1 column 1, moving, animation frame A", semantic_id="player.move_a"),
        SheetCell(_frame_name("player_move_b", taken), "the SAME player character as row 1 column 1, moving, animation frame B (legs opposite to frame A)", semantic_id="player.move_b"),
        SheetCell(_frame_name("player_action", taken), f"the SAME player character as row 1 column 1, action pose: {action}", semantic_id="player.action"),
    ]
    groups: list[list[SheetCell]] = [player_group]
    enemy_groups: list[list[SheetCell]] = []
    enemy_descs: list[str] = []
    boss_flags: list[bool] = []
    for index, source in enumerate(enemies[:12]):
        desc = _entity_text(source) or "hostile creature"
        enemy_descs.append(desc)
        boss_flags.append(_is_boss(source))
        enemy_frame = _frame_name(str(source.get("name") or ""), taken, default=f"enemy_{index + 1}")
        enemy_semantic = _frame_semantic_id(enemy_frame)
        if enemy_semantic.endswith(".default"):
            enemy_semantic = enemy_semantic[: -len(".default")] + ".idle"
        group = [SheetCell(enemy_frame, desc, semantic_id=enemy_semantic)]
        enemy_groups.append(group)
        groups.append(group)
    for index, source in enumerate(obstacles[:4]):
        desc = _entity_text(source) or f"a solid blocking obstacle fitting {title}"
        groups.append(
            [
                SheetCell(
                    _frame_name(str(source.get("name") or ""), taken, default=f"obstacle_{index + 1}"),
                    f"OBSTACLE / SOLID SCENERY: {desc}. A blocking object with a clean readable silhouette",
                    semantic_id=(
                        _frame_semantic_id(_frame_name(str(source.get("name") or ""), set(), default=f"obstacle_{index + 1}"))
                    ),
                )
            ]
        )
    item_groups: list[list[SheetCell]] = []
    for index, desc in enumerate(items[:6]):
        # 道具描述是 "名字, 外观" 或 "名字 (效果)":帧名只取名字段。
        label = desc.split("(")[0].split(",")[0]
        item_frame = _frame_name(label, taken, default=f"item_{index + 1}")
        item_semantic = _frame_semantic_id(item_frame)
        if item_semantic.endswith(".default"):
            item_semantic = item_semantic[: -len(".default")] + ".idle"
        group = [SheetCell(item_frame, desc, semantic_id=item_semantic)]
        item_groups.append(group)
        groups.append(group)
    # 中性实体(npc/未带 role 标签的旧设计):有格子,但绝不标成 enemy_N,
    # 也不吃动画帧升级。旧设计整批落在这个桶里,上限给到 8。
    # 可连接结构(道路/管道/铁轨)升级成 5 格图块族;族上限 2 防格子爆炸。
    families = 0
    for index, source in enumerate(others[:8]):
        desc = _entity_text(source) or f"a neutral character or device fitting {title}"
        base = _frame_name(str(source.get("name") or ""), taken, default=f"entity_{index + 1}")
        if families < 2 and _is_connectable(source):
            families += 1
            groups.append(_tile_family_group(base, desc, taken))
        else:
            groups.append([SheetCell(base, desc, semantic_id=_frame_semantic_id(base))])
    for name, desc in (
        ("projectile", "the main projectile / bullet / thrown object, small and readable"),
        ("explosion", "impact explosion / burst effect"),
        ("flash", "action flash / sparkle / hit effect"),
        ("prop", f"a themed environment prop for {title}"),
    ):
        frame_name = _frame_name(name, taken)
        groups.append([SheetCell(frame_name, desc, semantic_id=f"effect.{name}", required=False, variant_strategy="programmatic")])

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
        frame_name = _frame_name(seed, taken)
        if group is player_group:
            semantic_id = f"player.{frame_name.removeprefix('player_')}"
        elif group in item_groups:
            semantic_id = f"{group[0].semantic_id.split('.', 1)[0]}.activated"
        else:
            semantic_id = _frame_semantic_id(frame_name)
        group.append(SheetCell(frame_name, desc, semantic_id=semantic_id))
        budget -= 1

    # 补缝/补满用的中性内容:已付费的画布不留空白品红格。
    # A 4x4 provider canvas may have unused slots.  They are transparent
    # placeholders, never semantic assets: the formal manifest excludes them
    # and no runtime consumer may bind to a `bonus_*` frame.
    fillers = ["EMPTY atlas slot: transparent padding only"]
    return _paginate(groups, fillers, taken)


def _prune_pages_to_consumers(
    pages: list[tuple[tuple[SheetCell, ...], tuple[tuple[str, ...], ...]]],
    consumers: dict,
) -> list[tuple[tuple[SheetCell, ...], tuple[tuple[str, ...], ...]]]:
    """Strict mode: keep only cells with an explicit runtime consumer.

    This is used when a runtime consumer map is already available (for
    revisions or incremental generation).  Normal first-pass generation uses
    the design roster as an inferred consumer and is enriched after codegen.
    """
    allowed = {str(key) for key, refs in consumers.items() if refs}
    if not allowed:
        return []
    output: list[tuple[tuple[SheetCell, ...], tuple[tuple[str, ...], ...]]] = []
    for cells, groups in pages:
        kept = [cell for cell in cells if (_cell_demand(cell).semantic_id in allowed)]
        if not kept:
            continue
        kept_names = {cell.name for cell in kept}
        kept_groups = tuple(group for group in groups if all(name in kept_names for name in group))
        # Preserve the page shape for the provider while excluding every
        # non-consumer from the formal semantic manifest.
        while len(kept) < SHEET_GRID * SHEET_GRID:
            kept.append(
                SheetCell(
                    f"bonus_{len(kept) + 1}",
                    "EMPTY atlas slot: transparent padding only",
                    required=False,
                    variant_strategy="programmatic",
                )
            )
        output.append((tuple(kept[: SHEET_GRID * SHEET_GRID]), kept_groups))
    return output


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
            current.append(
                SheetCell(
                    _frame_name("", taken, default=f"bonus_{bonus + 1}"),
                    fillers[bonus % len(fillers)],
                    required=False,
                    variant_strategy="programmatic",
                )
            )
            bonus += 1
        pages.append((tuple(current), tuple(current_groups)))
        current, current_groups = [], []

    queue = list(groups)
    index = 0
    while index < len(queue) and len(pages) < pages_cap:
        group = queue[index]
        if len(current) + len(group) <= page_size:
            current.extend(group)
            # 图块族多格但不是动画:进 animations 会被作者当帧循环播放。
            if len(group) > 1 and not group[0].tile_base:
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
    visual_terms = (
        "visual", "style", "art", "sprite", "palette", "color", "lighting",
        "appearance", "texture", "画风", "视觉", "美术", "素材", "颜色", "色彩",
        "光照", "外观", "贴图", "像素",
    )
    visual_requirements = [
        str(item.get("statement") or "")
        for item in (design.get("requirements") or [])
        if isinstance(item, dict)
        and any(term in str(item.get("statement") or "").lower() for term in visual_terms)
    ]
    requirement_hint = (
        " Visual contract requirements: " + _clip_text("; ".join(visual_requirements), 320) + "."
        if visual_requirements
        else ""
    )
    return f"{style} 2D game art, crisp silhouettes with dark outlines, consistent style, palette and lighting across ALL sprites.{hint}{requirement_hint}"


def _grid_position_word(col: float, row: float, cols: int, rows: int) -> str:
    """Cell coordinate → one of 9 coarse position words for image prompts."""
    horizontal = ("left", "center", "right")[min(2, int(col * 3 / max(1, cols)))]
    vertical = ("top", "middle", "bottom")[min(2, int(row * 3 / max(1, rows)))]
    if vertical == "middle":
        return "center of the scene" if horizontal == "center" else f"{horizontal} side"
    return f"{vertical}-{horizontal}" if horizontal != "center" else vertical

def _layout_brief(design: dict, builder: bool = False) -> str:
    """Compact spatial brief of design.level_layout for the background prompt.

    图像模型跟不了精确坐标,但跟得住"哪个区域在画面哪一侧"。把布局翻译成
    九宫格方位词,背景构图就与运行时碰撞几何共享同一张平面图——这是"生成的
    地图只是贴图、与关卡无关"问题(2026-07-17 暗影档案实测)的图像侧解法。

    建造/经营类(builder=True)措辞换成纯地形:分区=地面色调差异,墙=天然
    屏障(河/岩),cover=树木岩石——分区提示词不能引导模型把区画成建成区。
    """
    layout = design.get("level_layout") if isinstance(design, dict) else None
    if not isinstance(layout, dict):
        return ""
    grid = layout.get("grid") or {}
    cols = max(1, int(grid.get("cols") or 24))
    rows = max(1, int(grid.get("rows") or 14))
    parts: list[str] = []
    region_bits = []
    for region in (layout.get("regions") or [])[:6]:
        span = region.get("cells") or [0, 0, 0, 0]
        word = _grid_position_word((span[0] + span[2]) / 2, (span[1] + span[3]) / 2, cols, rows)
        region_bits.append(f"'{_clip_text(region.get('name'), 40)}' in the {word}")
    if region_bits:
        parts.append(
            (
                "Distinct districts, each marked ONLY by a subtle shift in natural ground tone/texture: "
                if builder
                else "Distinct areas: "
            )
            + "; ".join(region_bits)
            + "."
        )
    walls = layout.get("walls") or []
    if walls:
        placement = Counter()
        for span in walls[:40]:
            orientation = "horizontal" if (span[2] - span[0]) >= (span[3] - span[1]) else "vertical"
            placement[f"{orientation} wall near the {_grid_position_word((span[0] + span[2]) / 2, (span[1] + span[3]) / 2, cols, rows)}"] += 1
        wall_bits = [name if count == 1 else f"{count} {name}s" for name, count in placement.most_common(6)]
        parts.append(
            (
                "Impassable natural barriers (water channels / rock ridges), NOT built walls: "
                if builder
                else "Solid structural walls: "
            )
            + "; ".join(wall_bits)
            + "."
        )
    cover = layout.get("cover") or []
    if cover:
        spots = Counter(_grid_position_word(cell[0], cell[1], cols, rows) for cell in cover[:24])
        parts.append(
            (
                "Scattered natural obstacles (trees, boulders) near the "
                if builder
                else "Scattered crates/pillars as cover near the "
            )
            + ", ".join(name for name, _ in spots.most_common(4))
            + "."
        )
    if not parts:
        return ""
    parts.append("All remaining space stays open, buildable natural ground." if builder else "Everything else stays open, walkable floor.")
    return _clip_text(" ".join(parts), 620)


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
        "Each cell is one explicit semantic state and must contain exactly one subject (expected_object_count=1): "
        "never combine multiple levels, buildings, actors, or effects in one cell. Center one sprite per cell, "
        "filling about 70% of its cell, never touching or crossing cell edges.",
    ]
    if any(cell.tile_slot for cell in cells):
        # 图块族格是例外:连接面必须精确贴到格边缘中点,否则拼出的路网
        # 每格之间留一圈缝(2026-07-17 像素都市计划实测)。仍禁越界。
        lines.append(
            "Exception: cells described as SEAMLESS CONNECTABLE TILE must run their connecting "
            "surfaces all the way to the exact cell edges (still never crossing into a neighbor cell)."
        )
    for index, cell in enumerate(cells):
        row, col = divmod(index, SHEET_GRID)
        # UI 覆盖物要求(血条/横幅/标签)与评审的 no-text 规则同源剥离:画进
        # 素材会直接被判 text_present(第十二轮矛盾循环)。
        desc = strip_ui_overlay_demands(cell.desc) or cell.meta or cell.name.replace("_", " ")
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
    spec = state.get("spec_execution_view") or {}
    if not spec and not state.get("design_contract"):
        spec = state.get("game_spec") or {}
    # Once the gate has passed, the frozen contract projection is the only
    # design input.  The legacy fallback keeps standalone asset tests and old
    # revision tasks compatible when no contract exists yet.
    design = state.get("design_execution_view") or {}
    if not design and not state.get("design_contract"):
        design = state.get("game_design") or {}
    title = str(spec.get("title") or "GameWeave game")
    theme = str(spec.get("theme") or "stylized arcade")
    prompt = (
        json.dumps({"requirements": (state.get("design_contract") or {}).get("requirements") or [], "systems": design.get("systems") or []}, ensure_ascii=False)
        if state.get("design_contract")
        else str(state.get("normalized_prompt") or state.get("prompt") or "")
    )
    pages = _plan_sheet_pages(spec, design)
    explicit_consumers = state.get("runtime_consumers")
    if isinstance(explicit_consumers, dict):
        pages = _prune_pages_to_consumers(pages, explicit_consumers)
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
            "the danger / boss-fight mood comes from COLORED accent lighting (warning lamps, emergency "
            "strips, energy effects) and small environmental damage — NOT from extra darkness; overall "
            "brightness stays close to the main scene. Same composition family, clearly the same place.",
        ),
        (
            "background-3",
            "This is a DIFFERENT area of the same game world, used for a stage change: new landmark "
            "composition and layout, unmistakably the same world and rendering style.",
        ),
    ][: max(1, min(3, int(settings.ASSET_BACKGROUND_VARIANTS)))]
    # 背景是"空舞台":引擎在其上绘制所有演员。画进图里的守卫/视野锥/光束会
    # 和真实精灵混在一起变成不可交互的"假实体"(2026-07-17 暗影档案实测);
    # 压暗交给运行时 Backdrop 的自适应蒙版做,图本身必须保持可读的中间调。
    # 建造/经营类更进一步:建筑本身就是玩家的放置物,背景必须是纯空地形——
    # "禁角色/载具/UI"挡不住模型画出一座建成城市(2026-07-17 像素都市计划)。
    builder = _builder_management(spec, design)
    layout_brief = _layout_brief(design, builder=builder)
    stage_line = (
        "EMPTY BUILDABLE TERRAIN: the player constructs every building in this game, so the land is "
        "COMPLETELY UNDEVELOPED — absolutely NO buildings, houses, factories, towers, roads, bridges, "
        "plazas, fences or any other constructed structure anywhere; only natural terrain (grass, soil, "
        "water, rocks, vegetation, subtle ground variation). Also no characters, no creatures, no "
        "vehicles, no UI, no HUD icons, no minimap, no text, no watermark — the game engine draws every "
        "building and actor on top of this image. "
        if builder
        else
        "EMPTY STAGE, environment only: absolutely no characters, no creatures, no guards or "
        "enemies, no vehicles, no vision cones, no flashlight or spotlight beams cast by anyone, "
        "no UI, no HUD icons, no minimap, no text, no watermark — the game engine draws every "
        "actor and effect on top of this image. "
    )
    for index, (bg_key, variant) in enumerate(scene_variants):
        series = (
            ""
            if len(scene_variants) <= 1
            else (
                f" Scene {index + 1} of {len(scene_variants)} for the SAME game: keep the art style,"
                " palette, lighting language and rendering IDENTICAL across all scenes."
            )
        )
        # background-3 是"另一区域",不套主关卡的平面图;主图与高压变体共享布局。
        layout_line = (
            f" Composition follows this floor plan seen from above: {layout_brief}"
            if layout_brief and bg_key != "background-3"
            else ""
        )
        planned.append(
            PlannedAsset(
                bg_key,
                "image",
                (
                    f"Wide scenic background for the browser game '{title}'. {_style_line(spec, design)} "
                    f"Theme: {theme}. An atmospheric game environment with depth. {variant}{series}{layout_line} "
                    + stage_line
                    + "READABLE lighting: soft ambient light with mid-tone floors and clear local contrast; "
                    "no large near-black areas even for night scenes; keep the central play space open and "
                    "low-detail so gameplay sprites stay readable."
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


def _sheet_manifest_extra(cells: tuple[SheetCell, ...], groups: tuple[tuple[str, ...], ...]) -> dict:
    cell_demands = [_cell_demand(cell) for cell in cells]
    extra = {
        "frame_width": SHEET_CELL,
        "frame_height": SHEET_CELL,
        "frames": {cell.name: index for index, cell in enumerate(cells)},
        "semantic_frames": {
            demand.semantic_id: {
                # `frame` is a stable atlas-local identifier; the legacy
                # Phaser frame key is retained separately for compatibility.
                "frame": f"f_{index:03d}",
                "frame_id": f"f_{index:03d}",
                "legacy_frame": demand.frame_id,
                "frame_index": index,
                "required": demand.required,
                "consumer_refs": list(demand.consumer_refs),
                "anchor": list(demand.anchor),
            }
            for index, (cell, demand) in enumerate(zip(cells, cell_demands))
            if demand.semantic_id and not cell.name.startswith("bonus_")
        },
        "frame_ids": {
            cell.name: index
            for index, cell in enumerate(cells)
            if not cell.name.startswith("bonus_")
        },
        # 每个多帧角色一条:首帧名 → 该角色的全部帧(按图集顺序)。gameplay
        # 代码据此建动画:移动/攻击双帧循环、Boss 特技帧、道具激活态。
        "animations": {names[0]: list(names) for names in groups if names},
        # 帧语义直达作者(gameConfig.sheets[].frameMeta):帧名(entity_3)本身
        # 不携带含义,没有描述作者只能按顺序瞎猜,一步错整局换皮——像素都市
        # 计划把住/商/电/水全体错位一格(2026-07-17)。
        "frame_meta": {
            cell.name: _clip_text(cell.meta or cell.desc, 100)
            for cell in cells
            if cell.meta or cell.desc
        },
        "frame_semantics": {
            cell.name: demand.semantic_id
            for cell, demand in zip(cells, cell_demands)
            if demand.semantic_id and not cell.name.startswith("bonus_")
        },
    }
    # 可连接图块族:base 帧名 → {slot: 帧名}。只输出五槽齐全的族(组同页,
    # 正常必齐;页溢出被丢的残族宁可不导出,免得运行时旋转表踩空)。
    families: dict[str, dict[str, str]] = {}
    for cell in cells:
        if cell.tile_base and cell.tile_slot:
            families.setdefault(cell.tile_base, {})[cell.tile_slot] = cell.name
    complete = {base: slots for base, slots in families.items() if len(slots) == len(_TILE_SLOTS)}
    if complete:
        extra["tile_families"] = complete
    return extra


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
