"""ORM → 前端 DTO 序列化（字段对齐 PlayForge 设计稿 + Create 生成控制台）。"""
import json
from datetime import datetime, timezone

from app.core.config import settings
from app.storage import s3

# 主阶段（agent → step key → 中文标题），对应 Create 生成控制台
_STAGES = [
    ("SafetyIntakeAgent", "safety_intake", "检查创意和素材"),
    ("MemoryRetrievalAgent", "memory_retrieval", "检索创作记忆"),
    ("IntentSpecAgent", "intent_spec", "理解你的游戏创意"),
    ("BriefExpansionAgent", "brief_expansion", "扩展玩法简报"),
    ("MechanicPlannerAgent", "mechanic_planner", "规划核心机制"),
    ("ArchetypeRouterAgent", "archetype_router", "选择玩法原型"),
    ("AssetAgent", "asset_processing", "整理素材"),
    ("GameDesignAgent", "game_design", "设计玩法规则"),
    ("ContentPlanAgent", "content_plan", "生成关卡内容"),
    ("BalanceAgent", "balance_plan", "调试难度和平衡"),
    ("GameCodeAgent", "code_generation", "生成游戏代码"),
    ("BuildValidateAgent", "build_validation", "测试游戏是否可运行"),
    ("GameplayQAAgent", "gameplay_qa", "玩法可玩性测试"),
    ("GameplayRepairAgent", "gameplay_repair", "玩法调参修复"),
    ("PublishArtifactAgent", "publish_artifact", "准备预览版本"),
    ("MemoryUpdateAgent", "memory_update", "保存创作记忆"),
]
_REVISION_STAGES = [
    ("SafetyIntakeAgent", "safety_intake", "检查修改反馈"),
    ("MemoryRetrievalAgent", "memory_retrieval", "检索历史反馈"),
    ("FeedbackUnderstandingAgent", "feedback_understanding", "理解用户反馈"),
    ("CodeRevisionAgent", "code_revision", "修改现有代码"),
    ("BuildValidateAgent", "build_validation", "验证修改结果"),
    ("GameplayQAAgent", "gameplay_qa", "回归测试玩法"),
    ("PublishRevisionAgent", "publish_revision", "保存新版 Preview"),
    ("MemoryUpdateAgent", "memory_update", "保存修改记忆"),
]
_PROGRESS = {"safety_intake": 10, "intent_spec": 18, "brief_expansion": 24, "mechanic_planner": 30,
             "archetype_router": 34, "asset_processing": 40, "game_design": 50, "content_plan": 56,
             "balance_plan": 62, "code_generation": 72, "build_validation": 82,
             "gameplay_qa": 90, "gameplay_repair": 88, "publish_artifact": 96,
             "feedback_understanding": 25, "code_revision": 55, "revision_repair": 65,
             "publish_revision": 96, "memory_retrieval": 14, "memory_update": 98}
_ST = {"done": "completed", "running": "running", "failed": "failed"}


def fmt(n: int) -> str:
    if n >= 10000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def relative_time(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return "just now"
    for unit, sec in (("month", 2592000), ("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= sec:
            v = int(secs // sec)
            return f"{v} {unit}{'s' if v > 1 else ''} ago"
    return "just now"


def game_card(g) -> dict:
    return {
        "id": g.id,
        "title": g.title,
        "summary": g.summary,
        "genre": g.genre,
        "cover": g.cover,
        "version": g.current_version,
        "source": g.source,
        "from_create": g.source == "create",
        "status": g.status,
        "author": g.author.display_name if g.author else "—",
        "author_init": g.author.avatar_initial if g.author else "?",
        "author_id": g.author_id,
        "tags": [t.name for t in g.tags],
        "plays": g.plays_count,
        "plays_str": fmt(g.plays_count),
        "likes": g.likes_count,
        "likes_str": fmt(g.likes_count),
        "published_at": g.published_at.isoformat() if g.published_at else None,
        "date": relative_time(g.published_at or g.created_at),
        "manifest_url": s3.manifest_url(g.id, g.current_version),
        "oss_path": f"oss://{settings.S3_BUCKET}/games/{g.id}/{g.current_version}/manifest.json",
    }


def game_detail(g) -> dict:
    d = game_card(g)
    d["prompt"] = g.prompt
    d["bundle_url"] = s3.public_url(f"games/{g.id}/{g.current_version}/index.html")
    return d


def user_out(u) -> dict:
    return {
        "id": u.id,
        "name": u.display_name,
        "email": u.email,
        "init": u.avatar_initial,
        "created_at": _iso(u.created_at),
    }


def comment_out(c) -> dict:
    return {
        "id": c.id,
        "body": c.body,
        "created_at": _iso(c.created_at),
        "ago": relative_time(c.created_at),
        "author": c.user.display_name if c.user else "—",
        "author_init": c.user.avatar_initial if c.user else "?",
        "author_id": c.user_id,
    }


def score_out(s, rank: int | None = None) -> dict:
    name = s.player_name or (s.user.display_name if s.user else "Anonymous")
    return {"rank": rank, "name": name, "points": s.points, "ago": relative_time(s.created_at)}


def _parse(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _dur(s):
    if s.started_at and s.finished_at:
        return f"{(s.finished_at - s.started_at).total_seconds():.1f}s"
    return None


def _iso(dt):
    return dt.isoformat() if dt else None


def _latest_task_event_at(t):
    latest = t.created_at
    for step in t.steps:
        for dt in (step.started_at, step.finished_at, step.created_at):
            if dt and (latest is None or dt > latest):
                latest = dt
        for log in step.logs:
            if log.created_at and (latest is None or log.created_at > latest):
                latest = log.created_at
    if t.finished_at and (latest is None or t.finished_at > latest):
        latest = t.finished_at
    return latest


def _design_preview(spec: dict, design: dict):
    rules = design.get("rules") if isinstance(design.get("rules"), dict) else {}
    balance = design.get("balance") if isinstance(design.get("balance"), dict) else {}
    mechanics = design.get("mechanic_plan") if isinstance(design.get("mechanic_plan"), dict) else {}
    content = design.get("content_plan") if isinstance(design.get("content_plan"), dict) else {}
    fields = []

    def add(label, val):
        if val not in (None, "", [], {}):
            fields.append({"label": label, "value": str(val)[:90]})

    add("标题", spec.get("title"))
    add("类型", spec.get("genre"))
    add("维度", "3D · WebGL" if str(spec.get("dimension")) == "3d" else "2D · Canvas")
    add("主题", spec.get("theme"))
    add("视觉风格", spec.get("visual_style"))
    add("玩法原型", design.get("archetype") or spec.get("archetype"))
    add("核心机制", mechanics.get("secondary_action") or mechanics.get("primary_action"))
    add("核心玩法", spec.get("core_loop"))
    add("胜利条件", spec.get("win_condition"))
    add("失败条件", spec.get("lose_condition"))
    add("难度曲线", spec.get("difficulty_curve"))
    if rules.get("survive_seconds"):
        add("回合时长(秒)", rules.get("survive_seconds"))
    if balance:
        add("平衡参数", f"目标 {balance.get('target_score')} / 生命 {balance.get('lives')} / 障碍 {balance.get('hazard_spawn_ms')}ms")
    if content:
        add("内容波次", f"{len(content.get('waves') or [])} waves / {', '.join((content.get('powerups') or [])[:3])}")
    return {"title": spec.get("title") or "", "fields": fields} if fields else None


def task_out(t) -> dict:
    spec, design = _parse(t.spec_json), _parse(t.design_json)
    steps_by_agent = {s.agent: s for s in t.steps}
    latest_event_at = _latest_task_event_at(t)

    step_summaries = []
    progress = 0
    stages = _REVISION_STAGES if getattr(t, "task_kind", "generation") == "revision" else _STAGES
    for agent, key, title in stages:
        s = steps_by_agent.get(agent)
        status = _ST.get(s.status, "pending") if s else "pending"
        summary = (s.logs[-1].line if (s and s.logs) else None)
        if status == "completed":
            progress = max(progress, _PROGRESS[key])
        elif status == "running":
            progress = max(progress, _PROGRESS[key] - 5)
        step_summaries.append({"step": key, "title": title, "status": status, "summary": summary})
    if t.status == "succeeded":
        progress = 100
    elif t.status == "failed":
        pass

    game = t.result_game
    manifest_url = s3.manifest_url(game.id, game.current_version) if game else None
    preview_url = f"/play/{game.id}" if game else None
    game_title = (game.title if game else None) or spec.get("title") or ""

    assets = [
        {"name": a.filename, "type": "uploaded", "status": "已上传",
         "kind": a.kind, "url": s3.public_url(a.oss_key)}
        for a in t.assets
    ]

    logs = [
        {"agent_name": s.agent, "step": s.name,
         "message": (s.logs[-1].line if s.logs else ""),
         "created_at": _iso(s.logs[-1].created_at if s.logs else s.created_at),
         "duration": _dur(s), "status": _ST.get(s.status, "pending"),
         "lines": [log.line for log in s.logs]}
        for s in t.steps
    ]

    return {
        "id": t.id, "status": t.status, "current_step": t.current_step, "current_agent": t.current_agent,
        "task_kind": getattr(t, "task_kind", "generation") or "generation",
        "base_game_id": getattr(t, "base_game_id", None),
        "base_version": getattr(t, "base_version", None),
        "feedback_text": getattr(t, "feedback_text", None),
        "feedback_brief": getattr(t, "feedback_brief", None),
        "repair_attempts": t.repair_attempts, "replan_attempts": t.replan_attempts,
        "max_repair_attempts": t.max_repair_attempts, "max_replan_attempts": t.max_replan_attempts,
        "tokens": t.tokens_used, "error": t.error, "error_code": t.error_code, "idea": t.idea,
        "dimension": getattr(t, "dimension", "2d") or "2d",
        "created_at": _iso(t.created_at), "started_at": _iso(t.started_at),
        "finished_at": _iso(t.finished_at), "updated_at": _iso(latest_event_at),
        "progress": progress, "game_title": game_title,
        "manifest_url": manifest_url, "preview_url": preview_url,
        "step_summaries": step_summaries,
        "design": _design_preview(spec, design),
        "assets": assets,
        "logs": logs,
        "steps": [
            {"seq": s.seq, "agent": s.agent, "name": s.name, "status": s.status,
             "logs": [log.line for log in s.logs]}
            for s in t.steps
        ],
        "game": game_detail(game) if game else None,
    }
