"""雪碧图素材管线与出界防线的回归测试。

覆盖:规划集中为多页图集+1 背景、角色动画帧组(玩家姿势/技能、敌人攻击帧、
Boss 特技、道具激活帧)与不跨页分页、并行图像生成、品红抠色与棋盘泛洪后处理、
spritesheet manifest、脚手架图集加载与 Bounds 系统、gameplay QA 的出界处理检查。
"""
import copy
import io
import threading

import pytest
from PIL import Image, ImageDraw

from app.agents import validation_nodes
from app.services.game_assets import (
    AssetGenerationRetryRequired,
    SHEET_CELL,
    SHEET_GRID,
    SHEET_SIZE,
    _postprocess_spritesheet,
    _normalize_repair_cell,
    _generate_with_retry,
    generate_game_assets,
    plan_game_assets,
)
from app.services.phaser_projects import create_modular_phaser_project
from app.services.provider_router import GeneratedMedia, MediaRequest

_SHOOTER_STATE = {
    "prompt": "top-down gun battle with soldiers",
    "game_spec": {"title": "Steel Rain", "theme": "military", "visual_style": "16-bit pixel art", "genre": "shooter"},
    "game_design": {
        "player": {"visual": "green beret soldier with rifle", "abilities": ["shoot"]},
        "entities": [
            {"name": "Grunt", "role": "enemy", "visual": "enemy rifleman", "behavior": "advances"},
            {"name": "Heavy", "role": "enemy", "visual": "armored brute with minigun"},
        ],
        "boss": {"name": "Warlord", "visual": "elite commander in red cape"},
        "powerups": [{"name": "Medkit", "effect": "heals"}, {"name": "Shield", "effect": "blocks one hit"}],
        "palette": {"bg": "#101820", "primary": "#9ae66e"},
    },
}


def _png_bytes(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_plan_consolidates_visuals_into_sheet_and_background():
    plans = plan_game_assets(_SHOOTER_STATE)
    keys = [p.key for p in plans]
    assert keys[:5] == ["sheet", "sheet-2", "background", "background-2", "background-3"]
    assert len([p for p in plans if p.modality == "image"]) == 5
    sheet = plans[0]
    assert len(sheet.sheet_cells) == SHEET_GRID * SHEET_GRID
    assert sheet.extra == {"background": "transparent", "quality": "medium"}
    names = [cell.name for cell in sheet.sheet_cells]
    assert names[0] == "player_idle"
    assert "player_move_a" in names and "player_move_b" in names
    # roster 全员有格子(帧组扩容后可能溢到后续页)
    all_names = [cell.name for p in plans if p.sheet_cells for cell in p.sheet_cells]
    assert "grunt" in all_names and "warlord" in all_names
    assert f"{SHEET_GRID}x{SHEET_GRID} grid" in sheet.prompt
    assert "magenta" in sheet.prompt and "#FF00FF" in sheet.prompt
    assert "checkerboard" in sheet.prompt


def test_plan_upgrades_actors_with_animation_frames():
    """姿势/技能/敌人动作/道具动画扩容:每个战斗角色不再是一张静态帧。"""
    plans = plan_game_assets(_SHOOTER_STATE)
    sheet_plans = [p for p in plans if p.sheet_cells]
    names = [cell.name for p in sheet_plans for cell in p.sheet_cells]
    # 玩家:核心 4 姿势之外还有受伤/跳跃/死亡/胜利姿势(第二梯队)
    assert {"player_hurt", "player_jump", "player_death", "player_victory"} <= set(names)
    # 敌人:idle+攻击+移动帧;Boss 额外特技帧
    assert "grunt_b" in names and "heavy_b" in names
    assert "grunt_move" in names and "heavy_move" in names
    assert "warlord_b" in names and "warlord_c" in names and "warlord_move" in names
    # 道具:idle+激活双帧
    assert "medkit_b" in names and "shield_b" in names
    # 帧组落进 manifest 用的分组:玩家组含通用动作,敌人组三帧,Boss 四帧
    groups = {g[0]: g for p in sheet_plans for g in p.sheet_groups}
    assert groups["player_idle"][:4] == ("player_idle", "player_move_a", "player_move_b", "player_action")
    assert {"player_hurt", "player_jump", "player_death", "player_victory"} <= set(groups["player_idle"])
    assert groups["grunt"] == ("grunt", "grunt_b", "grunt_move")
    assert groups["warlord"] == ("warlord", "warlord_b", "warlord_c", "warlord_move")
    assert groups["medkit"] == ("medkit", "medkit_b")
    # 占位引用必须全部替换成确切格位,不能泄漏进画图提示词
    for plan in sheet_plans:
        assert "@PREV_CELL@" not in plan.prompt
    assert "the cell at row" in sheet_plans[0].prompt


def test_animation_groups_never_straddle_pages():
    """Phaser 动画帧必须同纹理:任何帧组的所有帧都要落在同一页图集上。"""
    plans = plan_game_assets(dict(_CN_SHOOTER_STATE))
    sheet_plans = [p for p in plans if p.sheet_cells]
    assert len(sheet_plans) >= 2, "该设计应溢出为多页"
    for plan in sheet_plans:
        page_names = {cell.name for cell in plan.sheet_cells}
        for group in plan.sheet_groups:
            missing = [name for name in group if name not in page_names]
            assert not missing, f"帧组 {group} 的帧 {missing} 不在本页"


def test_maxed_roster_expands_to_more_pages_without_dropping_frames(monkeypatch):
    """满编 roster(12 敌人含 Boss+4 障碍+6 道具+8 中性)在高页数上限下应展开到
    第 5 页:所有实体核心格 + 两梯队动画帧升级一个不丢。页数按需增长——普通
    设计仍是 2-3 页,这里是上限价值的回归证明。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_SHEET_MAX_PAGES", 10)
    state = {
        "game_spec": {"title": "Legion Siege", "genre": "arena battle"},
        "game_design": {
            "player": {"visual": "knight commander in silver armor", "abilities": ["sword slash", "shield bash", "war cry"]},
            "entities": (
                [{"name": f"Raider {i}", "role": "enemy", "visual": f"raider variant {i}"} for i in range(1, 12)]
                + [{"name": "Overlord", "role": "boss", "visual": "towering warlord in black armor"}]
                + [{"name": f"Wall {i}", "role": "obstacle", "visual": f"stone wall segment {i}"} for i in range(1, 5)]
                + [{"name": f"Npc {i}", "role": "npc", "visual": f"villager {i}"} for i in range(1, 9)]
            ),
            "powerups": [{"name": f"Relic {i}", "effect": "boosts power"} for i in range(1, 7)],
        },
    }
    plans = plan_game_assets(state)
    keys = [p.key for p in plans]
    assert keys[:6] == ["sheet", "sheet-2", "sheet-3", "sheet-4", "sheet-5", "background"]
    sheet_plans = [p for p in plans if p.sheet_cells]
    assert len(sheet_plans) == 5
    names = [cell.name for p in sheet_plans for cell in p.sheet_cells]
    # 核心格全在:12 敌人、4 障碍、6 道具、8 中性;敌人两梯队动画帧齐全
    for i in range(1, 12):
        assert f"raider_{i}" in names and f"raider_{i}_b" in names and f"raider_{i}_move" in names
    assert {"overlord", "overlord_b", "overlord_c", "overlord_move"} <= set(names)
    for i in range(1, 5):
        assert f"wall_{i}" in names
    for i in range(1, 7):
        assert f"relic_{i}" in names and f"relic_{i}_b" in names
    for i in range(1, 9):
        assert f"npc_{i}" in names
    assert {"player_skill_2", "player_skill_3", "player_hurt", "player_jump", "player_death", "player_victory"} <= set(names)
    # 真实内容帧恰好 75 格(10 玩家+37 敌人+4 障碍+12 道具+8 中性+4 特效),其余为补位
    assert len([n for n in names if not n.startswith("bonus_")]) == 75


def test_player_skill_poses_follow_designed_abilities():
    state = {
        "game_spec": {"title": "Mage Trials", "genre": "arcade"},
        "game_design": {
            "player": {
                "visual": "hooded mage with a glowing staff",
                "abilities": ["fireball", "ice shield", "lightning dash", "meteor storm", "arcane ward", "never-rendered sixth"],
            },
            "entities": [{"name": "Slime", "role": "enemy", "visual": "green slime"}],
        },
    }
    plans = plan_game_assets(state)
    names = [cell.name for p in plans if p.sheet_cells for cell in p.sheet_cells]
    descs = {cell.name: cell.desc for p in plans if p.sheet_cells for cell in p.sheet_cells}
    # 第 1 个技能进 player_action;第 2/3 个是第一梯队,第 4/5 个是第二梯队;上限 5
    assert "fireball" in descs["player_action"]
    assert "player_skill_2" in names and "ice shield" in descs["player_skill_2"]
    assert "player_skill_3" in names and "lightning dash" in descs["player_skill_3"]
    assert "player_skill_4" in names and "meteor storm" in descs["player_skill_4"]
    assert "player_skill_5" in names and "arcane ward" in descs["player_skill_5"]
    assert "player_skill_6" not in names
    assert {"player_hurt", "player_jump", "player_death", "player_victory"} <= set(names)
    # 姿势格引用首格外观,不重复整段描述
    assert "row 1 column 1" in descs["player_skill_2"]


def test_plan_prompt_stays_compact_with_verbose_design():
    """复刻 2026-07-13 事故:超长设计字段把提示词撑到 5KB+,列表 repr 泄漏,Boss 双写。"""
    long_visual = (
        "名为GR-17的24×30像素青蓝轮廓机器人,深灰方形躯干、单眼青色面罩、短小磁力靴和背部双喷口。"
        "奔跑时腿部显示3帧机械步行动画,跳跃与重力翻转时喷口喷出反向青色像素焰;受伤时机体白红交替闪烁,"
        "朝天花板站立时精灵保持头朝屏幕上方但磁力靴贴住天花板,清楚表现倒挂状态。"
    )
    state = {
        "prompt": "重力翻转平台跳跃",
        "game_spec": {
            "title": "重力翻转:废弃工厂",
            "theme": "abandoned factory",
            "visual_style": "高对比度像素美术," + "细节描述" * 60 + ",所有图形均由程序化像素形状与 Phaser 绘制生成",
        },
        "game_design": {
            "player": {
                "visual": long_visual,
                "abilities": [
                    "5点生命值;受击后获得1000毫秒无敌时间并被轻微击退。",
                    "可奔跑、变向、土狼时间跳跃、跳跃输入缓冲和每次离开表面后一次二段跳。",
                ],
            },
            "entities": [
                {"name": "维护无人机M-2", "role": "enemy", "visual": "18×14像素黑红悬浮无人机", "behavior": "每2.2秒发射一枚慢速直线弹;被摧毁后有35%概率掉落道具,场上最多2台。" * 3},
                {"name": "工厂核心AXIOM-0", "role": "boss", "visual": "96×128像素机械核心", "behavior": "阶段转换" * 40},
            ],
            "boss": {"name": "工厂核心AXIOM-0", "visual": "巨型黑铁机械核心"},
            "powerups": [{"name": "过载射击", "effect": "持续8000毫秒。冷却由300毫秒降至160毫秒。" * 5}],
        },
    }
    plans = plan_game_assets(state)
    sheet = plans[0]
    # 列表 repr 不得泄漏进提示词
    assert "['" not in sheet.prompt and "']" not in sheet.prompt
    # 玩家完整外观只出现一次(后续姿势格引用第一格)
    assert sheet.prompt.count("磁力靴贴住天花板") == 1
    # Boss 去重后只占一个帧组(entities role=boss 与 boss 字段是同一个 Boss):
    # 基础格 + 攻击帧 + 特技帧,不再双写成两个角色
    names = [cell.name for p in plans if p.sheet_cells for cell in p.sheet_cells]
    assert sorted(name for name in names if "axiom" in name) == ["axiom_0", "axiom_0_b", "axiom_0_c", "axiom_0_move"]
    # 总长受控(事故时 >5000 字符)
    assert len(sheet.prompt) < 3200, f"prompt too long: {len(sheet.prompt)}"


def test_postprocess_chroma_keys_magenta_and_resizes():
    img = Image.new("RGB", (1254, 1254), (255, 0, 255))
    draw = ImageDraw.Draw(img)
    # 每个格子中心画一个深色方块精灵
    scale = 1254 / SHEET_SIZE
    for row in range(SHEET_GRID):
        for col in range(SHEET_GRID):
            cx = int((col * SHEET_CELL + SHEET_CELL / 2) * scale)
            cy = int((row * SHEET_CELL + SHEET_CELL / 2) * scale)
            draw.rectangle([cx - 60, cy - 60, cx + 60, cy + 60], fill=(40, 44, 52))
    result = Image.open(io.BytesIO(_postprocess_spritesheet(_png_bytes(img), "image/png")))
    assert result.size == (SHEET_SIZE, SHEET_SIZE)
    assert result.mode == "RGBA"
    assert result.getpixel((4, 4))[3] == 0, "背景必须被抠成透明"
    center = SHEET_CELL // 2
    assert result.getpixel((center, center))[3] == 255, "精灵必须保持不透明"
    # 反混合+膨胀防线:任何可见像素不得残留高饱和品红(否则精灵边缘出现粉边)
    hot_fringe = sum(
        1
        for r, g, b, a in result.getdata()
        if a > 40 and r > 200 and g < 70 and b > 200
    )
    assert hot_fringe == 0, f"{hot_fringe} 个可见像素仍是品红"
    # 紧贴精灵的透明像素应被膨胀成精灵色,供 GPU 线性采样:
    # 从精灵中心向右扫,精灵边缘外的前两个全透明像素必须是深色而非品红
    ring_px = []
    for x in range(center, SHEET_CELL):
        px = result.getpixel((x, center))
        if px[3] == 0:
            ring_px.append(px)
            if len(ring_px) == 2:
                break
    assert len(ring_px) == 2, "精灵右侧应存在透明背景"
    for px in ring_px:
        assert px[0] < 140, f"透明环像素应带精灵深色而非品红: {px}"


def test_postprocess_flood_fills_fake_checkerboard_keeping_interior_whites():
    img = Image.new("RGB", (SHEET_SIZE, SHEET_SIZE), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(0, SHEET_SIZE, 32):
        for x in range(0, SHEET_SIZE, 32):
            if (x // 32 + y // 32) % 2 == 0:
                draw.rectangle([x, y, x + 31, y + 31], fill=(228, 228, 228))
    # 深色描边精灵,内部带白色高光——泛洪只能清掉与边界连通的浅色背景
    draw.rectangle([100, 100, 220, 220], fill=(30, 34, 40))
    draw.rectangle([150, 150, 170, 170], fill=(255, 255, 255))
    result = Image.open(io.BytesIO(_postprocess_spritesheet(_png_bytes(img), "image/png")))
    assert result.getpixel((4, 4))[3] == 0, "棋盘背景必须被清透明"
    assert result.getpixel((160, 160))[3] == 255, "精灵内部的白色高光必须保留"
    assert result.getpixel((110, 110))[3] == 255


def test_postprocess_rejects_vector_placeholder():
    with pytest.raises(ValueError):
        _postprocess_spritesheet(b"<svg/>", "image/svg+xml")


class _StubRouter:
    def generate(self, request):
        img = Image.new("RGB", (SHEET_SIZE, SHEET_SIZE), (255, 0, 255))
        draw = ImageDraw.Draw(img)
        for index in range(SHEET_GRID * SHEET_GRID):
            col, row = index % SHEET_GRID, index // SHEET_GRID
            x0, y0 = col * SHEET_CELL, row * SHEET_CELL
            draw.rectangle(
                [x0 + 72, y0 + 60, x0 + 184, y0 + 232],
                fill=(30, 30, 30),
            )
        return GeneratedMedia(_png_bytes(img), "image/png", ".png", "stub", "stub-image")


class _FlakyRouter(_StubRouter):
    """第一次调用抛生成错误,之后成功——模拟网关 TLS 抖动(计数器线程安全)。"""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, request):
        with self._lock:
            self.calls += 1
            first = self.calls == 1
        if first:
            from app.services.provider_router import ProviderGenerationError

            raise ProviderGenerationError("image provider request failed: SSL EOF")
        return super().generate(request)


class _AlwaysFailRouter:
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, request):
        from app.services.provider_router import ProviderGenerationError

        with self._lock:
            self.calls += 1
        raise ProviderGenerationError("image provider request failed: gateway timeout")


class _TilesetFailRouter(_StubRouter):
    def __init__(self):
        self.tileset_calls = 0

    def generate(self, request):
        if "environment tileset" in request.prompt.lower():
            from app.services.provider_router import ProviderGenerationError

            self.tileset_calls += 1
            raise ProviderGenerationError("image provider request failed: tileset timeout")
        return super().generate(request)


def test_generate_game_assets_retries_transient_provider_errors(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    router = _FlakyRouter()
    result = generate_game_assets(dict(_SHOOTER_STATE), router=router)
    keys = {entry["key"] for entry in result["manifest_entries"]}
    assert "sheet" in keys and "background" in keys, "重试后两张图都应生成"
    assert any("retrying attempt 2/3" in log for log in result["logs"])


def test_generate_with_retry_retries_twice_before_succeeding(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_PROVIDER_MAX_RETRIES", 2)

    class FailTwiceThenSucceed(_StubRouter):
        def __init__(self):
            self.calls = 0

        def generate(self, request):
            self.calls += 1
            if self.calls <= 2:
                from app.services.provider_router import ProviderGenerationError

                raise ProviderGenerationError(f"transient-{self.calls}")
            return super().generate(request)

    router = FailTwiceThenSucceed()
    logs = []
    media = _generate_with_retry(
        router,
        MediaRequest(modality="image", prompt="test"),
        logs,
        "sheet",
    )

    assert media.content_type == "image/png"
    assert router.calls == 3
    assert ["retrying attempt 2/3" in logs[0], "retrying attempt 3/3" in logs[1]] == [True, True]


def test_generate_with_retry_does_not_duplicate_stream_protocol_requests(monkeypatch):
    from app.core.config import settings
    from app.services.provider_router import ProviderStreamProtocolError

    monkeypatch.setattr(settings, "ASSET_PROVIDER_MAX_RETRIES", 2)

    class BrokenStreamThenSuccess(_StubRouter):
        def __init__(self):
            self.calls = 0

        def generate(self, request):
            self.calls += 1
            if self.calls <= 2:
                raise ProviderStreamProtocolError("image provider returned no final event")
            return super().generate(request)

    router = BrokenStreamThenSuccess()
    logs = []
    with pytest.raises(ProviderStreamProtocolError, match="no final event"):
        _generate_with_retry(
            router,
            MediaRequest(modality="image", prompt="test"),
            logs,
            "sheet",
        )

    assert router.calls == 1
    assert logs == []


def test_required_image_failure_pauses_for_manual_retry_even_when_fail_open_is_enabled(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_GENERATION_FAIL_OPEN", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    router = _AlwaysFailRouter()

    with pytest.raises(AssetGenerationRetryRequired, match="waiting for manual retry"):
        generate_game_assets(dict(_SHOOTER_STATE), router=router)

    # 并行语义:所有在飞请求都会跑完(每个恰好重试一次)再按计划顺序结算失败。
    # 带 background=transparent 的图集在预算耗尽后额外获得一次剥参的最后一搏
    # (持续 5xx 时部分网关按参数路由到坏上游,2026-07-20 三路守卫)。
    image_items = [p for p in plan_game_assets(dict(_SHOOTER_STATE)) if p.modality == "image"]
    transparent_items = [
        p for p in image_items if str((p.extra or {}).get("background") or "") == "transparent"
    ]
    assert router.calls == 3 * len(image_items) + len(transparent_items)


def test_required_tileset_failure_pauses_without_palette_fallback(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_PROVIDER_MAX_RETRIES", 2)
    router = _TilesetFailRouter()

    with pytest.raises(AssetGenerationRetryRequired, match="Image asset 'tileset'.*waiting for manual retry"):
        generate_game_assets(dict(_CN_SHOOTER_STATE), router=router)

    # 3 次常规尝试 + 1 次剥掉 background=transparent 的最后一搏
    assert router.tileset_calls == 4


def test_invalid_generated_spritesheet_pauses_instead_of_shipping_plain_image(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)

    class InvalidImageRouter:
        def generate(self, request):
            return GeneratedMedia(b"not-an-image", "image/png", ".png", "stub", "broken-image")

    with pytest.raises(AssetGenerationRetryRequired, match="could not be normalized as a spritesheet"):
        generate_game_assets(dict(_SHOOTER_STATE), router=InvalidImageRouter())


def test_generate_game_assets_emits_spritesheet_manifest(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    result = generate_game_assets(dict(_SHOOTER_STATE), router=_StubRouter())
    by_key = {entry["key"]: entry for entry in result["manifest_entries"]}
    sheet = by_key["sheet"]
    assert sheet["kind"] == "spritesheet"
    assert sheet["path"] == "assets/sheet.png"
    assert sheet["frame_width"] == SHEET_CELL and sheet["frame_height"] == SHEET_CELL
    assert len(sheet["frames"]) == SHEET_GRID * SHEET_GRID
    assert sheet["frames"]["player_idle"] == 0
    # 帧组进 manifest:gameplay 代码据此建动画,组内帧保证在同一张图上
    # (帧组扩容后 warlord 组可能溢到 sheet-2,跨页收集再断言)
    animations: dict = {}
    for entry in (entry for entry in by_key.values() if entry.get("kind") == "spritesheet"):
        for base, group in entry["animations"].items():
            assert base == group[0]
            assert all(name in entry["frames"] for name in group), f"{base} 的帧不全在本页"
        animations.update(entry["animations"])
    assert animations["grunt"] == ["grunt", "grunt_b", "grunt_move"]
    assert animations["warlord"] == ["warlord", "warlord_b", "warlord_c", "warlord_move"]
    assert "player_hurt" in animations["player_idle"]
    assert by_key["background"]["kind"] == "image"
    paths = {item["path"] for item in result["artifacts"]}
    assert "public/assets/sheet.png" in paths and "public/assets/background.png" in paths


class _ConcurrencyProbeRouter(_StubRouter):
    """前两个请求必须同时在飞(共同越过 barrier);串行实现会在这里超时报错。"""

    def __init__(self):
        self.barrier = threading.Barrier(2)
        self._lock = threading.Lock()
        self.calls = 0

    def generate(self, request):
        with self._lock:
            self.calls += 1
            gated = self.calls <= 2
        if gated:
            self.barrier.wait(timeout=10)
        return super().generate(request)


def test_generate_game_assets_runs_image_calls_concurrently(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    monkeypatch.setattr(settings, "ASSET_GENERATION_CONCURRENCY", 2)
    result = generate_game_assets(dict(_SHOOTER_STATE), router=_ConcurrencyProbeRouter())
    # 并行完成后仍按计划顺序结算:manifest 顺序与计划一致,日志确定
    keys = [entry["key"] for entry in result["manifest_entries"]]
    assert keys == [p.key for p in plan_game_assets(dict(_SHOOTER_STATE))]
    assert any("concurrency 2" in log for log in result["logs"])


def test_generate_game_assets_single_worker_still_completes(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    monkeypatch.setattr(settings, "ASSET_GENERATION_CONCURRENCY", 1)
    result = generate_game_assets(dict(_SHOOTER_STATE), router=_StubRouter())
    assert {"sheet", "sheet-2", "background"} <= {entry["key"] for entry in result["manifest_entries"]}


def test_generate_game_assets_single_page_cap_never_drops_designed_entities(monkeypatch):
    """页数被压到 1 时:动画帧升级放弃,但设计实体的核心格必须一个不丢
    (预算先保核心格;超出 16 格的极端 roster 才会被 filler 兜底页截断)。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_SHEET_MAX_PAGES", 1)
    plans = plan_game_assets(dict(_SHOOTER_STATE))
    sheet_plans = [p for p in plans if p.sheet_cells]
    assert len(sheet_plans) == 1
    names = [cell.name for cell in sheet_plans[0].sheet_cells]
    for required in ("player_idle", "grunt", "heavy", "warlord", "medkit", "shield", "projectile"):
        assert required in names, f"核心格 {required} 被动画帧挤掉了"
    assert "grunt_b" not in names, "1 页容量下不该还有动画帧升级"


def test_scaffold_wires_spritesheet_and_bounds():
    files = create_modular_phaser_project(
        {"title": "Sheeted"},
        {},
        {},
        {
            "assets": [
                {
                    "key": "sheet",
                    "kind": "spritesheet",
                    "path": "assets/sheet.png",
                    "frame_width": 256,
                    "frame_height": 256,
                    "frames": {"player_idle": 0, "grunt": 4, "grunt_b": 5},
                    "animations": {"grunt": ["grunt", "grunt_b"]},
                }
            ]
        },
    )
    by_path = {item["path"]: item["content"] for item in files}
    config = by_path["src/config/gameConfig.ts"]
    assert '"sheet"' in config and '"player_idle"' in config and '"frameWidth"' in config
    # 动画帧组穿透到 gameConfig,gameplay 代码直接 anims.create
    assert '"animations"' in config and '"grunt_b"' in config
    assert "animations: Record<string, string[]>" in config
    boot = by_path["src/scenes/BootScene.ts"]
    assert "load.spritesheet" in boot
    bounds = by_path["src/systems/Bounds.ts"]
    assert "collideWorld" in bounds and "despawnOutside" in bounds and "wrap" in bounds
    assert "Bounds.collideWorld" in by_path["src/scenes/PlayScene.ts"]
    # 生成背景默认可见:场景优先 Backdrop.draw,无素材时回退渐变
    assert "textures.exists" in by_path["src/systems/Backdrop.ts"]
    assert "Backdrop.draw(this)" in by_path["src/scenes/PlayScene.ts"]
    assert "Backdrop.draw(this, 0.55)" in by_path["src/scenes/TitleScene.ts"]


def test_plan_generates_scene_background_variants(monkeypatch):
    """场景切换素材:主场景 / 同场景高压阶段 / 换区变体,同风格锁定;数量可调。"""
    from app.core.config import settings

    plans = plan_game_assets(_SHOOTER_STATE)
    bgs = [p for p in plans if p.key.startswith("background")]
    assert [p.key for p in bgs] == ["background", "background-2", "background-3"]
    assert "MAIN gameplay stage" in bgs[0].prompt
    assert "SAME location" in bgs[1].prompt and "high-intensity" in bgs[1].prompt
    assert "DIFFERENT area" in bgs[2].prompt
    assert all("IDENTICAL across all scenes" in p.prompt for p in bgs)
    assert all(p.modality == "image" and not p.sheet_cells for p in bgs)
    monkeypatch.setattr(settings, "ASSET_BACKGROUND_VARIANTS", 1)
    solo = [p for p in plan_game_assets(_SHOOTER_STATE) if p.key.startswith("background")]
    assert [p.key for p in solo] == ["background"]
    assert "Scene 1 of" not in solo[0].prompt


def test_scaffold_wires_scene_background_variants():
    files = create_modular_phaser_project(
        {"title": "Staged"},
        {},
        {},
        {
            "assets": [
                {"key": "background", "kind": "image", "path": "assets/background.png"},
                {"key": "background-2", "kind": "image", "path": "assets/background-2.png"},
                {"key": "background-3", "kind": "image", "path": "assets/background-3.png"},
                {"key": "hero", "kind": "image", "path": "assets/hero.png"},
            ]
        },
    )
    by_path = {item["path"]: item["content"] for item in files}
    config = by_path["src/config/gameConfig.ts"]
    # 变体全部进 assetKeys.backgrounds,首张仍是主背景;背景绝不污染演员回退键
    assert '"backgrounds"' in config
    assert '"background-2"' in config and '"background-3"' in config
    assert '"background": "background"' in config
    assert '"player": "hero"' in config
    backdrop = by_path["src/systems/Backdrop.ts"]
    assert "swap(" in backdrop and "key ?? gameConfig.assetKeys.background" in backdrop


# ---------------------------------------------------------------------------
# 建造/经营类:可连接图块族、帧语义 frame_meta、空地形背景
# (2026-07-17 像素都市计划回归:单十字路/作者顺序瞎猜错位/背景画成建成城)。
# ---------------------------------------------------------------------------

_CITY_BUILDER_STATE = {
    "prompt": "简化的城市建设模拟游戏",
    "game_spec": {
        "title": "像素都市",
        "theme": "sunny riverside city",
        "visual_style": "pixel art",
        "genre": "simulation",
        "archetype": "simulation",
    },
    "game_design": {
        "archetype": "simulation",
        "player": {"visual": "白色像素规划光标与半透明蓝图预览", "abilities": ["网格建设"]},
        "entities": [
            {"name": "规划光标", "role": "player 城市规划控制器", "visual": "白色角标框"},
            {
                "name": "城市道路",
                "role": "structure 交通连接",
                "visual": "深灰像素路面；相邻道路自动选择直线、转角、丁字或十字图块",
                "connects": True,
            },
            {"name": "绿色屋顶住宅", "role": "structure 人口来源", "visual": "米色墙体、绿色屋顶"},
            {"name": "蓝牌商业区", "role": "structure 就业来源", "visual": "蓝色遮阳棚与霓虹招牌"},
            {"name": "橙黑火力电厂", "role": "structure 电力供应", "visual": "2×2橙黑工业建筑"},
            {"name": "青色水塔", "role": "structure 供水设施", "visual": "2×2青色水塔"},
            {"name": "河道", "role": "terrain 不可建设水域", "visual": "青蓝水面"},
        ],
        "level_layout": {
            "grid": {"cols": 20, "rows": 12},
            "regions": [{"id": "west", "name": "河西新区", "cells": [0, 0, 8, 11], "kind": "住宅区"}],
            "walls": [[9, 0, 10, 11]],
            "cover": [[3, 3]],
        },
    },
}


def test_connectable_structure_gets_tile_family_variants():
    """可连接结构(道路)不再是单格:直/端/角/丁/十 5 变体同页且不进动画组。
    单格素材拼不出路网——像素都市计划全城道路都是同一块十字贴图。"""
    plans = plan_game_assets(dict(_CITY_BUILDER_STATE))
    sheet_plans = [p for p in plans if p.sheet_cells]
    names = {cell.name for p in sheet_plans for cell in p.sheet_cells}
    family = ("entity_1", "entity_1_end", "entity_1_corner", "entity_1_tee", "entity_1_cross")
    for name in family:
        assert name in names, f"缺图块族变体 {name}"
    for plan in sheet_plans:
        page = {cell.name for cell in plan.sheet_cells}
        if "entity_1" in page:
            assert set(family) <= page, "图块族必须同页"
            assert all("entity_1" not in group for group in plan.sheet_groups), "族不是动画组"
            assert "SEAMLESS CONNECTABLE TILE" in plan.prompt
            assert "exact cell edges" in plan.prompt
    # 非连接建筑仍是单格
    assert "entity_2_cross" not in names and "entity_3_end" not in names


def test_connectable_detection_falls_back_to_visual_vocabulary():
    """旧设计没有 connects 标记:visual 里的图块变体词表兜底;behavior 里的
    "必须正交邻接道路"这类规则文本不触发(否则全体建筑误报)。"""
    state = copy.deepcopy(_CITY_BUILDER_STATE)
    road = state["game_design"]["entities"][1]
    del road["connects"]
    state["game_design"]["entities"][2]["behavior"] = "必须正交邻接连通道路，并获得电力"
    plans = plan_game_assets(state)
    names = {cell.name for p in plans if p.sheet_cells for cell in p.sheet_cells}
    assert "entity_1_cross" in names, "visual 词表应识别道路"
    assert "entity_2_cross" not in names, "behavior 规则文本不该触发族"


def test_sheet_manifest_carries_frame_meta_and_tile_families(monkeypatch):
    """帧语义直达 manifest:作者靠 frame_meta 对号入座,不再按名字顺序瞎猜
    (像素都市计划把住/商/电/水整体错位一格);图块族五槽齐全落 manifest。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    result = generate_game_assets(dict(_CITY_BUILDER_STATE), router=_StubRouter())
    sheets = [e for e in result["manifest_entries"] if e.get("kind") == "spritesheet"]
    assert sheets
    metas: dict = {}
    families: dict = {}
    for entry in sheets:
        assert set(entry["frame_meta"]) == set(entry["frames"]), "每个帧都要有语义描述"
        metas.update(entry["frame_meta"])
        families.update(entry.get("tile_families") or {})
    assert "城市道路" in metas["entity_1"]
    assert "绿色屋顶住宅" in metas["entity_2"]
    assert "青色水塔" in metas["entity_5"]
    assert families["entity_1"] == {
        "straight": "entity_1",
        "end": "entity_1_end",
        "corner": "entity_1_corner",
        "tee": "entity_1_tee",
        "cross": "entity_1_cross",
    }


def test_builder_background_prompt_is_empty_terrain():
    """建造/经营类背景必须是纯空地形:玩家的建筑不能预先画进背景
    (像素都市计划:背景整座建成城市,玩家放置物全被淹没)。"""
    plans = plan_game_assets(dict(_CITY_BUILDER_STATE))
    bgs = [p for p in plans if p.key.startswith("background")]
    assert bgs
    for plan in bgs:
        assert "EMPTY BUILDABLE TERRAIN" in plan.prompt
        assert "NO buildings" in plan.prompt
        assert "EMPTY STAGE" not in plan.prompt
    # 布局简报换地形措辞:分区=地面色调差异,墙=天然屏障,不引导画建成区
    assert "natural ground tone" in bgs[0].prompt
    assert "natural barriers" in bgs[0].prompt
    # 战斗类背景规则不变
    shooter_bgs = [p for p in plan_game_assets(dict(_SHOOTER_STATE)) if p.key.startswith("background")]
    assert all("EMPTY STAGE" in p.prompt for p in shooter_bgs)


def test_scaffold_exposes_frame_meta_and_tile_variant():
    files = create_modular_phaser_project(
        {"title": "Tiled City"},
        {},
        {},
        {
            "assets": [
                {
                    "key": "sheet",
                    "kind": "spritesheet",
                    "path": "assets/sheet.png",
                    "frame_width": 256,
                    "frame_height": 256,
                    "frames": {
                        "entity_1": 0,
                        "entity_1_end": 1,
                        "entity_1_corner": 2,
                        "entity_1_tee": 3,
                        "entity_1_cross": 4,
                        "entity_2": 5,
                    },
                    "animations": {},
                    "frame_meta": {"entity_1": "城市道路 — straight piece", "entity_2": "绿色屋顶住宅"},
                    "tile_families": {
                        "entity_1": {
                            "straight": "entity_1",
                            "end": "entity_1_end",
                            "corner": "entity_1_corner",
                            "tee": "entity_1_tee",
                            "cross": "entity_1_cross",
                        }
                    },
                }
            ]
        },
    )
    by_path = {item["path"]: item["content"] for item in files}
    config = by_path["src/config/gameConfig.ts"]
    # 帧语义与图块族穿透进 gameConfig;作者据 frameMeta 对号入座
    assert '"frameMeta"' in config and "绿色屋顶住宅" in config
    assert '"tileFamilies"' in config and '"entity_1_tee"' in config
    assert "frameMeta: Record<string, string>" in config
    assert "tileFamilies: Record<string, TileFamily>" in config
    # 邻接掩码 → 帧+旋转 的标准助手,作者不用自己发明旋转表
    assert "export function tileVariant" in config
    assert "export function tileFamily" in config


_PAD = "// pad\n" * 80


def _vite_state(play_content: str, code_source: str = "author", asset_manifest: dict | None = None) -> dict:
    return {
        "dimension": "2d",
        "artifact_format": "phaser-vite/v1",
        "code_source": code_source,
        "game_spec": {"archetype": "topdown_collect"},
        "game_design": {},
        "asset_manifest": asset_manifest or {},
        "validation_result": {"valid": True},
        "generated_files": [],
        "project_files": [
            {"path": "package.json", "content": "{}"},
            {"path": "index.html", "content": "<html></html>"},
            {"path": "src/main.ts", "content": "import Phaser from 'phaser';"},
            # 库文件里带边界 token:必须被剔除,否则检查永真
            {"path": "src/systems/Bounds.ts", "content": "export const Bounds = { /* collideWorldBounds despawnOutside */ };"},
            # 配置文件天然含 "sheet"/"background" 字段名:同样必须被剔除
            {
                "path": "src/config/gameConfig.ts",
                "content": 'export const gameConfig = { "sheet": { "frames": { "player_idle": 0 } }, "assetKeys": { "background": "background" } };',
            },
            {"path": "src/scenes/PlayScene.ts", "content": play_content},
        ],
    }


_SHEET_MANIFEST = {
    "assets": [
        {"key": "sheet", "kind": "spritesheet", "path": "assets/sheet.png", "frames": {"player_idle": 0}},
        {"key": "background", "kind": "image", "path": "assets/background.png"},
    ]
}


def test_gameplay_qa_flags_unused_generated_assets():
    play = _PAD + "createCursorKeys();\nthis.juice.shake(0.01); // restart, procedural circles only"
    authored = validation_nodes._gameplay_qa(_vite_state(play, "author", _SHEET_MANIFEST))
    assert any("sprite sheet is preloaded but never used" in issue for issue in authored["issues"])
    assert any("background image is preloaded but never displayed" in issue for issue in authored["issues"])
    # 模板兜底只警告不拦发布
    template = validation_nodes._gameplay_qa(_vite_state(play, "template", _SHEET_MANIFEST))
    assert not any("sprite sheet" in issue for issue in template["issues"])
    assert any("sprite sheet is preloaded but never used" in w for w in template["warnings"])


def test_gameplay_qa_accepts_sheet_and_backdrop_usage():
    play = _PAD + (
        "createCursorKeys();\n"
        "Backdrop.draw(this);\n"
        "const sheet = gameConfig.sheet;\n"
        "this.add.sprite(0, 0, sheet.key, sheet.frames['player_idle']);\n"
        "this.juice.shake(0.01); // restart"
    )
    result = validation_nodes._gameplay_qa(_vite_state(play, "author", _SHEET_MANIFEST))
    assert not any("sprite sheet" in issue for issue in result["issues"])
    assert not any("background image" in w for w in result["warnings"])
    assert result["passed"], result["issues"]


def test_gameplay_qa_accepts_sheetframe_helper_usage():
    # 作者产物的规范写法:玩法代码只调 sheetFrame()——它定义在 gameConfig.ts 里,
    # 而 gameConfig.ts 被 _NON_GAMEPLAY_FILES 剔除。2026-07-13 两任务实测:漏掉
    # 该 token 会把正确用法误判为未使用,修复回环整包重生成也永远过不了门禁。
    play = _PAD + (
        "import { sheetFrame } from '../config/gameConfig';\n"
        "createCursorKeys();\n"
        "Backdrop.draw(this);\n"
        "this.add.sprite(0, 0, 'sheet', sheetFrame('player_idle'));\n"
        "this.juice.shake(0.01); // restart"
    )
    result = validation_nodes._gameplay_qa(_vite_state(play, "author", _SHEET_MANIFEST))
    assert not any("sprite sheet" in issue for issue in result["issues"])
    assert result["passed"], result["issues"]


def test_gameplay_qa_accepts_dynamic_semantic_frame_resolver_with_pre_codegen_metrics():
    manifest = copy.deepcopy(_SHEET_MANIFEST)
    manifest["sprite_demand_manifest"] = {
        "demands": [{"semantic_id": "player.idle", "required": True}],
        "runtime_manifest": {
            "player.idle": {"sheet": "sheet", "frame": "f_000"},
        },
        # This value describes the pre-codegen asset phase and must not
        # override source evidence that a dynamic resolver is wired.
        "metrics": {"unused_required_frame": 1, "required_asset_coverage": 0.0},
    }
    play = _PAD + (
        "createCursorKeys();\n"
        "Backdrop.draw(this);\n"
        "const frame = semanticFrame('player.idle');\n"
        "this.add.sprite(0, 0, frame.sheet, frame.frame);\n"
        "this.juice.shake(0.01); // restart"
    )

    result = validation_nodes._gameplay_qa(_vite_state(play, "author", manifest))

    assert not any("unused required frame" in issue for issue in result["issues"])
    assert not any("sprite sheet is preloaded" in issue for issue in result["issues"])
    assert result["passed"], result["issues"]


def test_gameplay_qa_flags_moving_bodies_without_bounds_handling():
    play = _PAD + "createCursorKeys();\nenemy.setVelocity(100, 0);\nthis.juice.shake(0.01); // restart"
    authored = validation_nodes._gameplay_qa(_vite_state(play, code_source="author"))
    assert any("world-edge" in issue for issue in authored["issues"])
    template = validation_nodes._gameplay_qa(_vite_state(play, code_source="template"))
    assert not any("world-edge" in issue for issue in template["issues"])
    assert any("world-edge" in warning for warning in template["warnings"])


def test_gameplay_qa_accepts_bounds_usage():
    play = _PAD + "createCursorKeys();\nenemy.setVelocity(100, 0);\nBounds.collideWorld(enemy, 1);\nthis.juice.shake(0.01); // restart"
    result = validation_nodes._gameplay_qa(_vite_state(play, code_source="author"))
    assert not any("world-edge" in issue for issue in result["issues"])
    assert result["passed"], result["issues"]


# ---------------------------------------------------------------------------
# role 标签合同分桶、掩体格、多页图集与 AI tileset(2026-07-12 火线武装回归)。
# 合同:GameDesign 提示词强制 role 以小写英文标签开头,代码只做前缀匹配。
# ---------------------------------------------------------------------------

_CN_SHOOTER_STATE = {
    "task_id": "cn-shooter-task",
    "prompt": "枪战游戏，有不同道具，武器可升级",
    "game_spec": {
        "title": "火线武装",
        "theme": "high-tech street war",
        "visual_style": "neon pixel art",
        "genre": "shooter",
        "archetype": "vertical_shooter",
    },
    "game_design": {
        "player": {"visual": "蓝色装甲士兵", "abilities": ["射击"]},
        "screen": {"width": 1152, "height": 768},
        "palette": {"bg": "#101820", "surface": "#1b2735", "primary": "#38e1ff", "accent": "#ffb454", "danger": "#ff4d6d"},
        "entities": [
            {"name": "突击兵", "role": "enemy 基础近战追击单位", "visual": "灰蓝色圆形士兵"},
            {"name": "疾跑兵", "role": "enemy 闪避时机测试目标", "visual": "黄色三角护肩"},
            {"name": "战术枪手", "role": "enemy 中距离远程压制单位", "visual": "紫色方形胸甲"},
            {"name": "堡垒护甲兵", "role": "enemy 正面减伤坦克", "visual": "深蓝六边形装甲"},
            {"name": "爆破兵", "role": "enemy 移动爆炸危险", "visual": "红色圆筒背包"},
            {"name": "磁轨狙击手", "role": "enemy 后期视线封锁单位", "visual": "绿色菱形机体"},
            {"name": "蜂群无人机", "role": "enemy 弹幕支援单位", "visual": "青紫色小型圆盘无人机"},
            {"name": "链路芯片", "role": "pickup 维持连击的风险收集物", "visual": "橙色发光芯片"},
        ],
        "boss": {"name": "精英火线队长", "visual": "黑金色重甲士兵"},
        "powerups": [{"name": "过载模块", "effect": "射速提升"}, {"name": "相位护盾", "effect": "挡一次伤害"}],
    },
}


def test_role_tagged_cn_design_overflows_to_more_sheets():
    plans = plan_game_assets(dict(_CN_SHOOTER_STATE))
    keys = [p.key for p in plans]
    assert keys[:4] == ["sheet", "sheet-2", "sheet-3", "background"]
    sheet_plans = [p for p in plans if p.sheet_cells]
    assert len(sheet_plans) == 3
    names = [cell.name for page in sheet_plans for cell in page.sheet_cells]
    assert len(names) == len(set(names)), "帧名必须跨页唯一"
    assert all(len(p.sheet_cells) == SHEET_GRID * SHEET_GRID for p in sheet_plans)
    # enemy 标签 + 中文修饰语:7 个敌人实体 + boss 字段都有自己的格子,
    # 且每个敌人带攻击帧(_b),Boss 再带特技帧(_c)
    joined = " ".join(names)
    base_enemies = [name for name in names if name.startswith("enemy_") and not name.endswith(("_b", "_c", "_move"))]
    assert len(base_enemies) >= 8, joined
    assert all(f"{name}_b" in names for name in base_enemies), joined
    assert sum(name.endswith("_c") for name in names) == 1, "只有 Boss 拿特技帧"
    # pickup 标签进道具桶,不占敌人格
    descs = " ".join(cell.desc for page in sheet_plans for cell in page.sheet_cells)
    assert "橙色发光芯片" in descs
    # 枪战类必须有掩体格(设计没显式给 → 默认补充)
    assert "cover_block" in names and "cover_barrier" in names
    assert "sheet 1 of 3" in sheet_plans[0].prompt and "sheet 3 of 3" in sheet_plans[2].prompt


def test_untagged_legacy_roles_get_neutral_cells_not_enemy_labels():
    """旧设计(role 无标签)降级路径:实体一个不丢,但也绝不冒充敌人。"""
    state = copy.deepcopy(_CN_SHOOTER_STATE)
    for entity in state["game_design"]["entities"]:
        entity["role"] = entity["role"].split(" ", 1)[1]  # 去掉标签,还原旧数据形态
    plans = plan_game_assets(state)
    sheet_plans = [p for p in plans if p.sheet_cells]
    names = [cell.name for page in sheet_plans for cell in page.sheet_cells]
    descs = " ".join(cell.desc for page in sheet_plans for cell in page.sheet_cells)
    # 不丢:每个实体的外观都画进图集(旧实现在这里整批丢弃)
    for visual in ("灰蓝色圆形士兵", "绿色菱形机体", "青紫色小型圆盘无人机", "橙色发光芯片"):
        assert visual in descs
    assert sum(name.startswith("entity_") for name in names) == 8
    # 不冒充:enemy_ 帧只属于结构化 boss 字段这一个角色(基础格+攻击/特技/移动帧);
    # 中性实体不吃动画帧升级
    assert {name for name in names if name.startswith("enemy_")} == {"enemy_1", "enemy_1_b", "enemy_1_c", "enemy_1_move"}


def test_role_tag_aliases_bucket_by_function():
    """别名词表:platform/collectible/projectile 等按功能落桶,词表外降级中性。"""
    plans = plan_game_assets(
        {
            "game_spec": {"title": "Cavern Hop", "genre": "platformer"},
            "game_design": {
                "entities": [
                    {"name": "moving ledge", "role": "platform 垂直移动", "visual": "stone slab"},
                    {"name": "coin", "role": "collectible", "visual": "gold coin"},
                    {"name": "plasma orb", "role": "projectile enemy plasma", "visual": "blue orb"},
                    {"name": "guard bot", "role": "enemy patroller", "visual": "red robot"},
                    {"name": "old gate", "role": "mechanism rusty", "visual": "iron gate"},
                ]
            },
        }
    )
    cells = [cell for p in plans if p.sheet_cells for cell in p.sheet_cells]
    ledge = next(cell for cell in cells if "stone slab" in cell.desc)
    assert ledge.desc.startswith("OBSTACLE"), "platform 标签应进阻挡桶"
    assert any(cell.name == "coin" for cell in cells)
    orb = next(cell for cell in cells if "blue orb" in cell.desc)
    assert not orb.desc.startswith("OBSTACLE"), "projectile 是中性,不冒充障碍/敌人"
    assert not orb.name.startswith("enemy")
    gate = next(cell for cell in cells if "iron gate" in cell.desc)
    assert not gate.name.startswith("enemy"), "词表外标签(mechanism)降级中性"


def test_gameplay_qa_accepts_platform_code_for_platform_entities():
    play = _PAD + (
        "createCursorKeys();\nBackdrop.draw(this);\nconst sheet = gameConfig.sheet;\n"
        "this.add.sprite(0, 0, sheet.key, sheet.frames['player_idle']);\n"
        "this.platforms = this.physics.add.staticGroup();\nthis.juice.shake(0.01); // restart"
    )
    state = _vite_state(play, "author", _SHEET_MANIFEST)
    state["game_design"] = {"entities": [{"name": "moving ledge", "role": "platform 垂直移动"}]}
    result = validation_nodes._gameplay_qa(state)
    assert not any("obstacle/blocking" in issue for issue in result["issues"])


def test_npc_tag_stays_neutral_with_own_frame_name():
    plans = plan_game_assets(
        {
            "game_spec": {"title": "Escort Run", "genre": "arcade"},
            "game_design": {
                "entities": [
                    {"name": "Supply Drone", "role": "npc friendly courier", "visual": "small hovering drone"},
                    {"name": "Raider", "role": "enemy melee chaser", "visual": "spiked rover"},
                ]
            },
        }
    )
    cells = [cell for p in plans if p.sheet_cells for cell in p.sheet_cells]
    drone = next(cell for cell in cells if "hovering drone" in cell.desc)
    assert drone.name == "supply_drone"
    assert not drone.name.startswith("enemy")
    assert any(cell.name == "raider" for cell in cells)


def test_generate_game_assets_emits_manifest_for_every_sheet(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    result = generate_game_assets(dict(_CN_SHOOTER_STATE), router=_StubRouter())
    by_key = {entry["key"]: entry for entry in result["manifest_entries"]}
    sheets = [by_key["sheet"], by_key["sheet-2"], by_key["sheet-3"]]
    assert all(entry["kind"] == "spritesheet" for entry in sheets)
    assert all(len(entry["frames"]) == 16 for entry in sheets)
    seen: set[str] = set()
    for entry in sheets:
        assert not (seen & set(entry["frames"])), "帧名必须跨页唯一"
        seen |= set(entry["frames"])
        # 动画帧组的每一帧都必须在本页(Phaser 动画帧同纹理)
        for base, group in entry["animations"].items():
            assert all(name in entry["frames"] for name in group), f"{base} 跨页"
    paths = {item["path"] for item in result["artifacts"]}
    assert {"public/assets/sheet.png", "public/assets/sheet-2.png", "public/assets/sheet-3.png"} <= paths


def test_tilemap_branch_generates_ai_tileset_with_stub_router(monkeypatch):
    import json as jsonlib

    from app.core.config import settings
    from app.services.artifacts import artifact_bytes

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", True)
    result = generate_game_assets(dict(_CN_SHOOTER_STATE), router=_StubRouter())
    by_key = {entry["key"]: entry for entry in result["manifest_entries"]}
    tileset = by_key["tileset"]
    assert tileset["kind"] == "image" and tileset["role"] == "tileset"
    assert tileset["provider"] == "stub", "stub 路由成功时 tileset 应走 AI 管线"
    tilemap = by_key["tilemap"]
    assert tilemap["kind"] == "tilemap"
    assert tilemap["tileset_key"] == "tileset" and tilemap["solid_gids"] == [5, 6, 7, 8]
    artifacts = {item["path"]: item for item in result["artifacts"]}
    tile_png = Image.open(io.BytesIO(artifact_bytes(artifacts["public/assets/tileset.png"])))
    assert tile_png.size == (128, 128)
    tiled = jsonlib.loads(artifacts["public/assets/tilemap.json"]["content"])
    assert tiled["tilesets"][0]["image"] == "tileset.png"
    assert tiled["width"] == 36 and tiled["height"] == 24  # 1152x768 屏 / 32px 瓦片


def test_tileset_falls_back_to_palette_png_without_asset_generation(monkeypatch):
    from app.core.config import settings
    from app.services.artifacts import artifact_bytes

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", False)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", True)
    result = generate_game_assets(dict(_CN_SHOOTER_STATE))
    by_key = {entry["key"]: entry for entry in result["manifest_entries"]}
    assert by_key["tileset"]["provider"] == "procedural"
    artifacts = {item["path"]: item for item in result["artifacts"]}
    png = Image.open(io.BytesIO(artifact_bytes(artifacts["public/assets/tileset.png"])))
    assert png.size == (128, 128)
    # 程序化 tileset 必须吃设计调色板,而不是旧版硬编码的紫色 X 占位图
    colors = {rgb for _count, rgb in png.convert("RGBA").getcolors(maxcolors=4096) or []}
    assert (167, 139, 250, 255) not in colors, "旧占位图的硬编码紫色不应再出现"


def test_scaffold_wires_sheets_tilemap_and_sheet_frame_helper():
    files = create_modular_phaser_project(
        {"title": "Sheeted 2"},
        {},
        {},
        {
            "assets": [
                {"key": "sheet", "kind": "spritesheet", "path": "assets/sheet.png", "frames": {"player_idle": 0}},
                {"key": "sheet-2", "kind": "spritesheet", "path": "assets/sheet-2.png", "frames": {"enemy_5": 0}},
                {"key": "background", "kind": "image", "path": "assets/background.png"},
                {"key": "tileset", "kind": "image", "path": "assets/tileset.png", "role": "tileset"},
                {
                    "key": "tilemap",
                    "kind": "tilemap",
                    "path": "assets/tilemap.json",
                    "layer": "World",
                    "tileset_key": "tileset",
                    "tileset_name": "gameweave",
                    "tile_size": 32,
                    "solid_gids": [5, 6, 7, 8],
                },
            ]
        },
    )
    config = next(item["content"] for item in files if item["path"] == "src/config/gameConfig.ts")
    assert '"sheets"' in config and '"sheet-2"' in config
    assert '"tilemap"' in config and '"tilesetKey"' in config and '"solidGids"' in config
    assert "export function sheetFrame(" in config
    # tileset 图片不能被当成 player/enemy 回退纹理
    assert '"player": "player-fallback"' in config
    boot = next(item["content"] for item in files if item["path"] == "src/scenes/BootScene.ts")
    assert "tilemapTiledJSON" in boot


def test_gameplay_qa_flags_designed_obstacles_missing_from_code():
    state = _vite_state(_PAD + "createCursorKeys();\nBackdrop.draw(this);\nconst sheet = gameConfig.sheet;\nthis.add.sprite(0, 0, sheet.key, sheet.frames['player_idle']);\nthis.juice.shake(0.01); // restart", "author", _SHEET_MANIFEST)
    state["game_design"] = {"entities": [{"name": "路障", "role": "obstacle 掩体", "visual": "混凝土路障"}]}
    result = validation_nodes._gameplay_qa(state)
    assert any("obstacle/blocking entities" in issue for issue in result["issues"])
    # 代码里出现掩体逻辑后放行
    state_ok = _vite_state(
        _PAD + "createCursorKeys();\nBackdrop.draw(this);\nconst sheet = gameConfig.sheet;\nthis.add.sprite(0, 0, sheet.key, sheet.frames['player_idle']);\nthis.covers = this.physics.add.staticGroup();\nthis.juice.shake(0.01); // restart",
        "author",
        _SHEET_MANIFEST,
    )
    state_ok["game_design"] = {"entities": [{"name": "路障", "role": "obstacle 掩体", "visual": "混凝土路障"}]}
    result_ok = validation_nodes._gameplay_qa(state_ok)
    assert not any("obstacle/blocking" in issue for issue in result_ok["issues"])


def test_compress_image_asset_recompresses_large_pngs_to_webp():
    import io as _io
    import random

    from PIL import Image

    from app.services.game_assets import _compress_image_asset

    rng = random.Random(3)
    noisy = Image.new("RGB", (1024, 1024))
    noisy.putdata(
        [
            (rng.randrange(256), rng.randrange(200), 40 + (i % 60))
            for i, _ in enumerate(range(1024 * 1024))
        ]
    )
    buffer = _io.BytesIO()
    noisy.save(buffer, format="PNG")
    raw = buffer.getvalue()
    assert len(raw) > 262_144

    content, content_type, extension = _compress_image_asset(
        raw, "image/png", ".png", keep_alpha=False
    )
    assert content_type == "image/webp" and extension == ".webp"
    assert len(content) < len(raw) * 0.85

    # Sheets keep their alpha channel through the WebP round trip.
    rgba = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    for x in range(0, 1024, 3):
        for y in range(0, 1024, 3):
            rgba.putpixel((x, y), (x % 256, y % 256, 128, 255))
    buffer = _io.BytesIO()
    rgba.save(buffer, format="PNG")
    sheet_raw = buffer.getvalue()
    content, content_type, extension = _compress_image_asset(
        sheet_raw, "image/png", ".png", keep_alpha=True
    )
    if extension == ".webp":
        round_trip = Image.open(_io.BytesIO(content))
        assert round_trip.mode in {"RGBA", "LA", "P"} or "A" in round_trip.getbands()


def test_compress_image_asset_keeps_small_or_marginal_files():
    from app.services.game_assets import _compress_image_asset

    tiny = b"x" * 1000
    assert _compress_image_asset(tiny, "image/png", ".png", keep_alpha=False) == (
        tiny,
        "image/png",
        ".png",
    )
    svg = b"<svg/>" * 100_000
    assert _compress_image_asset(svg, "image/svg+xml", ".svg", keep_alpha=False) == (
        svg,
        "image/svg+xml",
        ".svg",
    )


def test_repair_cell_accepts_oversized_single_sprite_canvas():
    img = Image.new("RGB", (1254, 1254), (255, 0, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([390, 250, 850, 1080], fill=(30, 90, 160))
    result = Image.open(io.BytesIO(_normalize_repair_cell(_png_bytes(img), "image/png"))).convert("RGBA")
    assert result.size == (SHEET_CELL, SHEET_CELL)
    assert result.getpixel((SHEET_CELL // 2, SHEET_CELL - 20))[3] > 0
