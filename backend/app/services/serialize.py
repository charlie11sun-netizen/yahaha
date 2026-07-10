"""ORM → 前端 DTO 序列化（字段对齐 GameWeave 设计稿 + Create 生成控制台）。"""
import json
from datetime import datetime, timezone

from app.core.config import settings
from app.services.runtime_urls import game_file_url, game_manifest_url
from app.services.upload_safety import presigned_asset_url
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
_REMIX_STAGES = [
    ("SafetyIntakeAgent", "safety_intake", "检查 Remix 方向"),
    ("MemoryRetrievalAgent", "memory_retrieval", "检索创作记忆"),
    ("FeedbackUnderstandingAgent", "feedback_understanding", "理解 Remix 目标"),
    ("CodeRevisionAgent", "code_revision", "改造源游戏文件"),
    ("BuildValidateAgent", "build_validation", "验证 Remix 构建"),
    ("GameplayQAAgent", "gameplay_qa", "测试 Remix 玩法"),
    ("PublishRemixAgent", "publish_remix", "保存 Remix 预览"),
    ("MemoryUpdateAgent", "memory_update", "保存创作记忆"),
]
_PROGRESS = {"safety_intake": 10, "intent_spec": 18, "brief_expansion": 24, "mechanic_planner": 30,
             "archetype_router": 34, "asset_processing": 40, "game_design": 50, "content_plan": 56,
             "balance_plan": 62, "code_generation": 72, "build_validation": 82,
             "gameplay_qa": 90, "gameplay_repair": 88, "publish_artifact": 96,
             "feedback_understanding": 25, "code_revision": 55, "revision_repair": 65,
             "publish_revision": 96, "publish_remix": 96, "memory_retrieval": 14, "memory_update": 98}
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
        "manifest_url": game_manifest_url(g.id),
        "oss_path": f"oss://{settings.S3_BUCKET}/games/{g.id}/{g.current_version}/manifest.json",
        "remixed_from_game_id": getattr(g, "remixed_from_game_id", None),
        "remixed_from_version": getattr(g, "remixed_from_version", None),
    }


def game_detail(g) -> dict:
    d = game_card(g)
    d["prompt"] = g.prompt
    d["bundle_url"] = game_file_url(g.id, g.current_version, "index.html")
    source = getattr(g, "remixed_from", None)
    d["remixed_from"] = (
        {
            "id": source.id,
            "title": source.title,
            "author": source.author.display_name if source.author else "—",
            "version": getattr(g, "remixed_from_version", None),
        }
        if source
        else None
    )
    try:
        d["remix_count"] = len(getattr(g, "remixes", []) or [])
    except Exception:  # noqa: BLE001
        d["remix_count"] = 0
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


def _parse_log_payload(raw):
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _dur(s):
    if s.started_at and s.finished_at:
        return f"{(s.finished_at - s.started_at).total_seconds():.1f}s"
    return None


def _iso(dt):
    return dt.isoformat() if dt else None


def _decimal_float(value):
    return float(value) if value is not None else None


def _latest_task_event_at(t, scan_logs: bool = True):
    latest = t.created_at
    for step in t.steps:
        for dt in (step.started_at, step.finished_at, step.created_at):
            if dt and (latest is None or dt > latest):
                latest = dt
        if scan_logs:
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


def task_out(t, include_details: bool = True) -> dict:
    """完整任务 DTO。include_details=False 产出列表用的轻量 summary：
    跳过 logs / steps / design / assets 与逐步日志行 —— 任务详情由 SSE 实时更新，
    列表只做 30s 低频兜底刷新，避免全量 payload 随任务积累线性爆炸。"""
    spec, design = _parse(t.spec_json), _parse(t.design_json)
    steps_by_agent = {s.agent: s for s in t.steps}
    latest_event_at = _latest_task_event_at(t, scan_logs=include_details)

    step_summaries = []
    progress = 0
    task_kind = getattr(t, "task_kind", "generation") or "generation"
    stages = _REMIX_STAGES if task_kind == "remix" else _REVISION_STAGES if task_kind == "revision" else _STAGES
    for agent, key, title in stages:
        s = steps_by_agent.get(agent)
        status = _ST.get(s.status, "pending") if s else "pending"
        summary = (s.logs[-1].line if (include_details and s and s.logs) else None)
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
    manifest_url = game_manifest_url(game.id) if game else None
    preview_url = f"/play/{game.id}" if game else None
    game_title = (game.title if game else None) or spec.get("title") or ""

    out = {
        "id": t.id, "status": t.status, "current_step": t.current_step, "current_agent": t.current_agent,
        "task_kind": getattr(t, "task_kind", "generation") or "generation",
        "base_game_id": getattr(t, "base_game_id", None),
        "base_version": getattr(t, "base_version", None),
        "feedback_text": getattr(t, "feedback_text", None),
        "feedback_brief": getattr(t, "feedback_brief", None),
        "repair_attempts": t.repair_attempts, "replan_attempts": t.replan_attempts,
        "max_repair_attempts": t.max_repair_attempts, "max_replan_attempts": t.max_replan_attempts,
        "tokens": t.tokens_used, "cost_usd": _decimal_float(getattr(t, "cost_usd", None)),
        "error": t.error, "error_code": t.error_code,
        "failed_stage": getattr(t, "failed_stage", None), "idea": t.idea,
        "dimension": getattr(t, "dimension", "2d") or "2d",
        "created_at": _iso(t.created_at), "started_at": _iso(t.started_at),
        "finished_at": _iso(t.finished_at), "updated_at": _iso(latest_event_at),
        "progress": progress, "game_title": game_title,
        "manifest_url": manifest_url, "preview_url": preview_url,
        "step_summaries": step_summaries,
        "game": game_detail(game) if game else None,
    }
    if not include_details:
        return out

    out["design"] = _design_preview(spec, design)
    out["assets"] = [
        {"name": a.filename, "type": "uploaded", "status": "已上传",
         "kind": a.kind, "scan_status": a.scan_status, "url": presigned_asset_url(a)}
        for a in t.assets
    ]
    out["logs"] = [
        {"agent_name": s.agent, "step": s.name,
         "message": (s.logs[-1].line if s.logs else ""),
         "created_at": _iso(s.logs[-1].created_at if s.logs else s.created_at),
         "duration": _dur(s), "status": _ST.get(s.status, "pending"),
         "lines": [log.line for log in s.logs],
         "entries": [
             {
                 "line": log.line,
                 "level": getattr(log, "level", "info"),
                 "created_at": _iso(getattr(log, "created_at", None)),
                 "event": _parse_log_payload(getattr(log, "payload_json", None)),
             }
             for log in s.logs
         ]}
        for s in t.steps
    ]
    out["steps"] = [
        {"seq": s.seq, "agent": s.agent, "name": s.name, "status": s.status,
         "tokens": getattr(s, "tokens", 0), "attempt": getattr(s, "attempt", 1),
         "caused_by_step_id": getattr(s, "caused_by_step_id", None),
         "logs": [log.line for log in s.logs]}
        for s in t.steps
    ]
    return out
