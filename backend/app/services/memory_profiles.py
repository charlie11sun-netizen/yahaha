"""Current memory profile synthesis, scope inference, and conflict lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GenerationTask, MemoryItem, MemoryProfile, MemoryProfileVersion, MemorySettings, User
from app.models.common import TaskStatus, now_utc
from app.models.memory import (
    MemoryCategory,
    MemoryExplicitness,
    MemoryProfileOperation,
    MemoryProfileStatus,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)

PROFILE_CONTEXT_CHARS = 1400
PROFILE_CONTEXT_LIMIT = 8
CANDIDATE_SUPPORT_THRESHOLD = 3
CANDIDATE_CONFIDENCE_THRESHOLD = 0.78
CANDIDATE_TTL_DAYS = 90
UTILITY_ALPHA = 0.20

_GLOBAL_SCOPE_RE = re.compile(
    r"以后|今后|默认|所有游戏|每个游戏|我通常|我一直|always|by default|all games|in every game",
    re.IGNORECASE,
)
_GAME_SCOPE_RE = re.compile(
    r"这个游戏|当前游戏|本游戏|这个项目|本项目|这一关|this game|current game|this project|this level",
    re.IGNORECASE,
)
_TASK_SCOPE_RE = re.compile(
    r"这次|本次|临时|先试试|只改这次|only this time|for now|temporarily|try it",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(
    r"可能|也许|或许|试试|能不能|可不可以|感觉.*不错|maybe|perhaps|could we|can we try|might",
    re.IGNORECASE,
)
_CLAIM_SPLIT_RE = re.compile(r"[。！？!?;；\n]+|(?=\bbut\b)|(?=但是)|(?=但)|(?=同时)|(?=另外)", re.IGNORECASE)
_NORMALIZE_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_NEGATED_VALUE_RE = re.compile(
    r"(?:不要|不再|别用|别|取消|避免|not|no longer|without|stop using)\s*$",
    re.IGNORECASE,
)

_VALID_CATEGORIES = {
    MemoryCategory.STYLE,
    MemoryCategory.MECHANICS,
    MemoryCategory.CONTROLS,
    MemoryCategory.DIFFICULTY,
    MemoryCategory.CONTENT,
    MemoryCategory.CONSTRAINTS,
    MemoryCategory.FEEDBACK,
}

_ATTRIBUTE_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("jump_height", MemoryCategory.CONTROLS, ("跳得更高", "跳高", "跳跃高度", "jump height", "jump higher")),
    ("jump_feel", MemoryCategory.CONTROLS, ("跳跃", "起跳", "jump", "手感")),
    ("movement_speed", MemoryCategory.CONTROLS, ("移动速度", "移动", "move speed", "movement speed")),
    ("game_pace", MemoryCategory.DIFFICULTY, ("节奏", "太快", "太慢", "pace")),
    ("difficulty", MemoryCategory.DIFFICULTY, ("难度", "太难", "简单", "困难", "difficulty", "hard", "easy")),
    ("visual_style", MemoryCategory.STYLE, ("像素", "写实", "卡通", "画风", "美术", "视觉", "pixel", "realistic", "cartoon", "visual style")),
    ("control_scheme", MemoryCategory.CONTROLS, ("操作方式", "按键", "键盘", "鼠标", "触屏", "controls", "keyboard", "mouse", "touch")),
    ("audio_style", MemoryCategory.STYLE, ("音乐", "音效", "配乐", "music", "audio", "sound")),
    ("core_mechanic", MemoryCategory.MECHANICS, ("核心玩法", "核心机制", "不要改玩法", "保留玩法", "core mechanic", "gameplay")),
]

_CANONICAL_VALUES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "visual_style": [
        ("pixel", ("像素", "pixel")),
        ("realistic", ("写实", "realistic")),
        ("cartoon", ("卡通", "cartoon")),
        ("minimal", ("极简", "minimal")),
        ("cozy", ("温馨", "治愈", "cozy")),
        ("3d", ("3d", "三维")),
        ("2d", ("2d", "二维")),
    ],
    "difficulty": [
        ("easy", ("简单", "容易", "easy")),
        ("hard", ("困难", "更难", "太难", "hard")),
        ("medium", ("中等", "适中", "medium")),
    ],
    "jump_height": [
        ("keep", ("不要跳得更高", "保持高度", "不变", "keep", "same height")),
        ("higher", ("跳得更高", "跳高一点", "higher")),
        ("lower", ("跳低", "降低高度", "lower")),
    ],
    "jump_feel": [
        ("lighter", ("轻快", "更轻", "灵敏", "snappy", "lighter")),
        ("heavier", ("更重", "沉重", "heavy", "heavier")),
        ("floaty", ("飘", "floaty")),
    ],
    "movement_speed": [
        ("faster", ("更快", "加快", "faster")),
        ("slower", ("更慢", "减慢", "slower")),
    ],
    "game_pace": [
        ("faster", ("更快", "加快", "faster")),
        ("slower", ("更慢", "减慢", "slower")),
    ],
}


def _float(value) -> float:
    return float(value) if isinstance(value, Decimal) else float(value or 0)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _clean(text: str | None, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _normalized(text: str) -> str:
    return _NORMALIZE_RE.sub("", text.lower())


def _candidate_expires_at():
    return now_utc() + timedelta(days=CANDIDATE_TTL_DAYS)


def profile_out(profile: MemoryProfile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "scope_type": profile.scope_type,
        "scope_id": profile.scope_id,
        "profile_key": profile.profile_key,
        "category": profile.category,
        "value_text": profile.value_text,
        "summary_text": profile.summary_text,
        "evidence_span": profile.evidence_span,
        "confidence": _float(profile.confidence),
        "scope_confidence": _float(profile.scope_confidence),
        "explicitness": profile.explicitness,
        "status": profile.status,
        "source_memory_id": profile.source_memory_id,
        "conflicts_with_id": profile.conflicts_with_id,
        "support_count": int(profile.support_count or 1),
        "utility_score": _float(profile.utility_score) if profile.utility_score is not None else 0.5,
        "utility_observation_count": int(profile.utility_observation_count or 0),
        "last_supported_at": profile.last_supported_at.isoformat() if profile.last_supported_at else None,
        "expires_at": profile.expires_at.isoformat() if profile.expires_at else None,
        "version": profile.version,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def version_out(version: MemoryProfileVersion) -> dict:
    return {
        "id": version.id,
        "profile_id": version.profile_id,
        "version": version.version,
        "operation": version.operation,
        "snapshot": version.snapshot_json,
        "source_memory_id": version.source_memory_id,
        "reason": version.reason,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


def _snapshot(profile: MemoryProfile) -> dict:
    return {
        "scope_type": profile.scope_type,
        "scope_id": profile.scope_id,
        "profile_key": profile.profile_key,
        "category": profile.category,
        "value_text": profile.value_text,
        "summary_text": profile.summary_text,
        "evidence_span": profile.evidence_span,
        "confidence": _float(profile.confidence),
        "scope_confidence": _float(profile.scope_confidence),
        "explicitness": profile.explicitness,
        "status": profile.status,
        "source_memory_id": profile.source_memory_id,
        "conflicts_with_id": profile.conflicts_with_id,
        "support_count": int(profile.support_count or 1),
        "utility_score": _float(profile.utility_score) if profile.utility_score is not None else 0.5,
        "utility_observation_count": int(profile.utility_observation_count or 0),
        "last_supported_at": profile.last_supported_at.isoformat() if profile.last_supported_at else None,
        "expires_at": profile.expires_at.isoformat() if profile.expires_at else None,
    }


def _record_version(
    db: Session,
    profile: MemoryProfile,
    operation: str,
    *,
    source_memory_id: str | None = None,
    reason: str | None = None,
) -> MemoryProfileVersion:
    db.flush()
    version = MemoryProfileVersion(
        profile_id=profile.id,
        version=profile.version,
        operation=operation,
        snapshot_json=_snapshot(profile),
        source_memory_id=source_memory_id or profile.source_memory_id,
        reason=_clean(reason, 500) if reason else None,
    )
    db.add(version)
    return version


def _split_claims(text: str) -> list[str]:
    parts = [_clean(part, 500).strip("；; ") for part in _CLAIM_SPLIT_RE.split(text)]
    return [part for part in parts if len(part) >= 4] or [_clean(text, 500)]


def _attribute_for(claim: str, category: str) -> str:
    low = claim.lower()
    for key, _, terms in _ATTRIBUTE_RULES:
        if any(term in low for term in terms):
            return key
    digest = hashlib.sha256(_normalized(claim).encode("utf-8")).hexdigest()[:16]
    return f"{category}:{digest}"


def _category_for_attribute(attribute: str, fallback: str) -> str:
    for key, category, _ in _ATTRIBUTE_RULES:
        if key == attribute:
            return category
    return fallback if fallback in _VALID_CATEGORIES else MemoryCategory.FEEDBACK


def _value_for(attribute: str, claim: str) -> str:
    low = claim.lower()
    matches: list[tuple[int, str]] = []
    for value, terms in _CANONICAL_VALUES.get(attribute, []):
        for term in terms:
            start = low.find(term)
            while start >= 0:
                prefix = low[max(0, start - 20) : start]
                if not _NEGATED_VALUE_RE.search(prefix):
                    matches.append((start, value))
                start = low.find(term, start + len(term))
    if matches:
        return max(matches, key=lambda match: match[0])[1]
    return _normalized(claim)[:500] or claim[:500]


def _scope_for(
    claim: str,
    item: MemoryItem,
    *,
    game_id: str | None,
    task_id: str | None,
) -> tuple[str, str | None, float, str]:
    if item.source_type == MemorySource.MANUAL:
        return item.scope_type, item.scope_id, 1.0, MemoryExplicitness.MANUAL
    if _GLOBAL_SCOPE_RE.search(claim):
        return MemoryScope.USER, None, 0.97, MemoryExplicitness.EXPLICIT
    if _TASK_SCOPE_RE.search(claim):
        return MemoryScope.TASK, task_id or item.source_task_id, 0.95, MemoryExplicitness.EXPLICIT
    if _GAME_SCOPE_RE.search(claim):
        return MemoryScope.GAME, game_id or item.source_game_id or item.scope_id, 0.96, MemoryExplicitness.EXPLICIT
    if item.source_type == MemorySource.IDEA:
        return MemoryScope.GAME, game_id or item.source_game_id or item.scope_id, 0.90, MemoryExplicitness.EXPLICIT
    return MemoryScope.GAME, game_id or item.source_game_id or item.scope_id, 0.84, MemoryExplicitness.INFERRED


def _base_confidence(item: MemoryItem, evidence: str) -> tuple[float, str]:
    hedged = bool(_HEDGE_RE.search(evidence))
    if item.source_type == MemorySource.MANUAL:
        return 1.0, MemoryExplicitness.MANUAL
    if hedged:
        return 0.64, MemoryExplicitness.INFERRED
    if item.source_type == MemorySource.IDEA:
        return 0.84, MemoryExplicitness.EXPLICIT
    return 0.88, MemoryExplicitness.EXPLICIT


def _deterministic_claims(
    item: MemoryItem,
    *,
    game_id: str | None,
    task_id: str | None,
) -> list[dict]:
    from app.services.memory import _category_for

    claims = []
    for evidence in _split_claims(item.raw_text):
        scope_type, scope_id, scope_confidence, scope_explicitness = _scope_for(
            evidence, item, game_id=game_id, task_id=task_id
        )
        if scope_type != MemoryScope.USER and not scope_id:
            continue
        fallback_category = item.category or _category_for(evidence)
        attribute = _attribute_for(evidence, fallback_category)
        category = _category_for_attribute(attribute, fallback_category)
        confidence, explicitness = _base_confidence(item, evidence)
        claims.append({
            "scope_type": scope_type,
            "scope_id": scope_id,
            "profile_key": attribute,
            "category": category,
            "value_text": _value_for(attribute, evidence),
            "summary_text": evidence,
            "evidence_span": evidence,
            "confidence": confidence,
            "scope_confidence": scope_confidence,
            "explicitness": explicitness,
            "scope_explicitness": scope_explicitness,
        })
    return claims


def _parse_json_object(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _active_profiles_for_extraction(
    db: Session,
    *,
    user_id: str,
    game_id: str | None,
    task_id: str | None,
) -> list[dict]:
    settings_row = db.get(MemorySettings, user_id)
    clauses = []
    if task_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.TASK, MemoryProfile.scope_id == task_id))
    if game_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.GAME, MemoryProfile.scope_id == game_id))
    if not settings_row or settings_row.allow_cross_game_memory:
        clauses.append(MemoryProfile.scope_type == MemoryScope.USER)
    if not clauses:
        clauses.append(MemoryProfile.scope_type == MemoryScope.USER)
    profiles = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.status == MemoryProfileStatus.ACTIVE,
            or_(*clauses),
        )
        .order_by(MemoryProfile.updated_at.desc())
        .limit(50)
        .all()
    )
    scope_order = {MemoryScope.TASK: 0, MemoryScope.GAME: 1, MemoryScope.USER: 2}
    profiles.sort(
        key=lambda profile: (
            scope_order.get(profile.scope_type, 9),
            -_float(profile.confidence),
            -(_float(profile.utility_score) if profile.utility_score is not None else 0.5),
            -int(profile.support_count or 1),
        )
    )
    profiles = profiles[:PROFILE_CONTEXT_LIMIT]
    return [
        {
            "id": profile.id,
            "scope_type": profile.scope_type,
            "scope_id": profile.scope_id,
            "profile_key": profile.profile_key,
            "category": profile.category,
            "value_text": profile.value_text,
            "summary_text": profile.summary_text,
            "support_count": int(profile.support_count or 1),
        }
        for profile in profiles
    ]


def _recent_game_user_messages(
    db: Session,
    *,
    user_id: str,
    game_id: str | None,
    current_task_id: str | None,
    limit: int = 10,
) -> list[dict]:
    if not game_id:
        return []
    tasks = (
        db.query(GenerationTask)
        .filter(
            GenerationTask.user_id == user_id,
            or_(GenerationTask.base_game_id == game_id, GenerationTask.result_game_id == game_id),
            or_(GenerationTask.status == TaskStatus.SUCCEEDED, GenerationTask.id == current_task_id),
        )
        .order_by(GenerationTask.created_at.desc())
        .limit(max(1, min(limit, 10)))
        .all()
    )
    messages = []
    for task in reversed(tasks):
        content = task.feedback_text if task.task_kind == "revision" else task.idea
        content = _clean(content, 4000)
        if not content:
            continue
        messages.append(
            {
                "content": content,
                "version": task.base_version or ("v1" if task.task_kind == "generation" else None),
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }
        )
    return messages


def _llm_claims_batch(
    items: list[MemoryItem],
    *,
    active_profiles: list[dict],
    recent_user_messages: list[dict],
    game_id: str | None,
    task_id: str | None,
) -> dict[str, list[dict]] | None:
    eligible = [item for item in items if item.source_type != MemorySource.MANUAL]
    if not eligible:
        return {}
    model = settings.MEMORY_EXTRACTION_MODEL.strip()
    api_key = settings.OPENAI_API_KEY.strip()
    if not api_key or api_key == "sk-your-key-here" or not model:
        return None

    from app.agents import llm
    from app.services.memory import _category_for

    system = (
        "You are a memory extractor for a game-generation agent. Return one strict JSON object. "
        "Use active_profiles and recent_user_messages only to resolve context, duplicates, and conflicts. "
        "Every claim must come from current_evidence and cite an exact evidence_span copied from that "
        "evidence's raw_text. System and assistant messages are intentionally absent. Do not invent user "
        "preferences. Return all claims in one response; no follow-up or tool calls. Use decision=skip or "
        "evidence_only when no durable profile should be created. Scope is advisory and will be revalidated."
    )
    user = json.dumps(
        {
            "active_profiles": active_profiles,
            "recent_user_messages": recent_user_messages,
            "current_evidence": [
                {
                    "source_memory_id": item.id,
                    "raw_text": item.raw_text,
                    "source_type": item.source_type,
                    "source_version": item.source_version,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in eligible
            ],
            "available_categories": sorted(_VALID_CATEGORIES),
            "allowed_scope_types": [MemoryScope.USER, MemoryScope.GAME, MemoryScope.TASK],
            "allowed_decisions": ["active", "candidate", "evidence_only", "skip"],
            "output_schema": {
                "claims": [
                    {
                        "source_memory_id": "id from current_evidence",
                        "decision": "active|candidate|evidence_only|skip",
                        "profile_key": "stable attribute key",
                        "category": "style|mechanics|controls|difficulty|content|constraints|feedback",
                        "value_text": "canonical concise value",
                        "summary_text": "natural-language summary",
                        "evidence_span": "exact substring from the matching raw_text",
                        "suggested_scope": "user|game|task",
                        "explicitness": "explicit|inferred",
                        "confidence": 0.0,
                        "entities": [{"type": "control", "name": "jump"}],
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    try:
        raw, _ = llm.chat(
            system,
            user,
            temperature=0,
            model=model,
            timeout=settings.MEMORY_EXTRACTION_TIMEOUT,
            response_format={"type": "json_object"},
        )
    except Exception:
        return None

    payload = _parse_json_object(raw)
    if not isinstance(payload.get("claims"), list):
        return None
    by_id = {item.id: item for item in eligible}
    output: dict[str, list[dict]] = {item.id: [] for item in eligible}
    for row in payload.get("claims") or []:
        if not isinstance(row, dict):
            continue
        item = by_id.get(_clean(row.get("source_memory_id"), 36))
        decision = _clean(row.get("decision"), 30)
        if not item or decision not in {"active", "candidate", "evidence_only", "skip"}:
            continue
        if decision in {"evidence_only", "skip"}:
            continue
        evidence = _clean(row.get("evidence_span"), 500)
        if not evidence or evidence not in item.raw_text:
            continue
        scope_type, scope_id, scope_confidence, scope_explicitness = _scope_for(
            evidence, item, game_id=game_id, task_id=task_id
        )
        if scope_type != MemoryScope.USER and not scope_id:
            continue
        fallback_category = item.category or _category_for(evidence)
        profile_key = _clean(row.get("profile_key"), 160) or _attribute_for(evidence, fallback_category)
        category = _clean(row.get("category"), 40)
        if category not in _VALID_CATEGORIES:
            category = _category_for_attribute(profile_key, fallback_category)
        base_confidence, rule_explicitness = _base_confidence(item, evidence)
        try:
            llm_confidence = _clamp(float(row.get("confidence", base_confidence) or base_confidence))
        except (TypeError, ValueError):
            llm_confidence = base_confidence
        confidence = min(0.94, max(base_confidence, min(llm_confidence, base_confidence + 0.04)))
        llm_explicitness = _clean(row.get("explicitness"), 20)
        explicitness = (
            MemoryExplicitness.INFERRED
            if decision == "candidate"
            or rule_explicitness == MemoryExplicitness.INFERRED
            or llm_explicitness == MemoryExplicitness.INFERRED
            else rule_explicitness
        )
        output[item.id].append(
            {
                "decision": decision,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "profile_key": profile_key,
                "category": category,
                "value_text": _clean(row.get("value_text"), 500) or _value_for(profile_key, evidence),
                "summary_text": _clean(row.get("summary_text"), 1000) or evidence,
                "evidence_span": evidence,
                "confidence": confidence,
                "scope_confidence": scope_confidence,
                "explicitness": explicitness,
                "scope_explicitness": scope_explicitness,
                "entities": row.get("entities") if isinstance(row.get("entities"), list) else [],
            }
        )
    return output


def extract_profile_claims(
    item: MemoryItem,
    *,
    game_id: str | None = None,
    task_id: str | None = None,
) -> list[dict]:
    return _deterministic_claims(item, game_id=game_id, task_id=task_id)


def extract_profile_claims_batch(
    db: Session,
    items: list[MemoryItem],
    *,
    game_id: str | None,
    task_id: str | None,
) -> dict[str, list[dict]]:
    if not items:
        return {}
    user_id = items[0].user_id
    active_profiles = _active_profiles_for_extraction(
        db, user_id=user_id, game_id=game_id, task_id=task_id
    )
    recent_messages = _recent_game_user_messages(
        db,
        user_id=user_id,
        game_id=game_id,
        current_task_id=task_id,
        limit=10,
    )
    extracted = _llm_claims_batch(
        items,
        active_profiles=active_profiles,
        recent_user_messages=recent_messages,
        game_id=game_id,
        task_id=task_id,
    )
    if extracted is not None:
        return extracted
    return {
        item.id: _deterministic_claims(item, game_id=game_id, task_id=task_id)
        for item in items
    }


def _same_value(left: str, right: str) -> bool:
    a, b = _normalized(left), _normalized(right)
    return bool(a and b and (a == b or (len(a) >= 8 and a in b) or (len(b) >= 8 and b in a)))


def _active_conflict(db: Session, user_id: str, claim: dict) -> MemoryProfile | None:
    return (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.scope_type == claim["scope_type"],
            MemoryProfile.scope_id == claim["scope_id"],
            MemoryProfile.profile_key == claim["profile_key"],
            MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        )
        .order_by(MemoryProfile.updated_at.desc())
        .first()
    )


def _matching_candidate(db: Session, user_id: str, claim: dict) -> MemoryProfile | None:
    candidates = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.scope_type == claim["scope_type"],
            MemoryProfile.scope_id == claim["scope_id"],
            MemoryProfile.profile_key == claim["profile_key"],
            MemoryProfile.status == MemoryProfileStatus.CANDIDATE,
        )
        .order_by(MemoryProfile.updated_at.desc())
        .limit(20)
        .all()
    )
    return next((profile for profile in candidates if _same_value(profile.value_text, claim["value_text"])), None)


def _retire_memory_source_if_unused(db: Session, memory_id: str | None, replacement: MemoryItem | None) -> None:
    if not memory_id or not replacement:
        return
    active_count = (
        db.query(MemoryProfile.id)
        .filter(
            MemoryProfile.source_memory_id == memory_id,
            MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        )
        .count()
    )
    if active_count:
        return
    old_item = db.get(MemoryItem, memory_id)
    if old_item and old_item.status == MemoryStatus.ACTIVE:
        old_item.status = MemoryStatus.SUPERSEDED
        old_item.supersedes_id = None
        old_item.updated_at = now_utc()
        replacement.supersedes_id = old_item.id


def _retire_source_if_unused(db: Session, profile: MemoryProfile, replacement: MemoryItem | None) -> None:
    _retire_memory_source_if_unused(db, profile.source_memory_id, replacement)


def _support_adjusted_confidence(profile: MemoryProfile, claim_confidence: float) -> float:
    support_count = max(1, int(profile.support_count or 1))
    base = max(_float(profile.confidence), claim_confidence)
    return round(min(0.98, base + 0.07 * max(0, support_count - 1)), 3)


def _reinforce_profile(
    db: Session,
    profile: MemoryProfile,
    item: MemoryItem,
    claim: dict,
    *,
    reason: str,
) -> MemoryProfile:
    if profile.source_memory_id != item.id:
        profile.support_count = max(1, int(profile.support_count or 1)) + 1
    profile.confidence = _support_adjusted_confidence(profile, claim["confidence"])
    profile.scope_confidence = max(_float(profile.scope_confidence), claim["scope_confidence"])
    profile.summary_text = claim["summary_text"]
    profile.evidence_span = claim["evidence_span"]
    profile.source_memory_id = item.id
    profile.last_supported_at = now_utc()
    if profile.status == MemoryProfileStatus.CANDIDATE:
        profile.expires_at = _candidate_expires_at()
    profile.version += 1
    profile.updated_at = now_utc()
    _record_version(
        db,
        profile,
        MemoryProfileOperation.REINFORCED,
        source_memory_id=item.id,
        reason=reason,
    )
    return profile


def _supersede_profile(
    db: Session,
    profile: MemoryProfile,
    *,
    source_memory_id: str | None,
    reason: str,
) -> None:
    profile.status = MemoryProfileStatus.SUPERSEDED
    profile.version += 1
    profile.updated_at = now_utc()
    _record_version(
        db,
        profile,
        MemoryProfileOperation.SUPERSEDED,
        source_memory_id=source_memory_id,
        reason=reason,
    )


def _promote_candidate_if_ready(
    db: Session,
    profile: MemoryProfile,
    item: MemoryItem,
    *,
    force: bool = False,
    reason: str | None = None,
) -> bool:
    if profile.status != MemoryProfileStatus.CANDIDATE:
        return False
    ready = (
        int(profile.support_count or 1) >= CANDIDATE_SUPPORT_THRESHOLD
        and _float(profile.confidence) >= CANDIDATE_CONFIDENCE_THRESHOLD
        and _float(profile.scope_confidence) >= 0.80
    )
    if not (ready or force):
        return False

    conflict = db.get(MemoryProfile, profile.conflicts_with_id) if profile.conflicts_with_id else None
    if not conflict:
        conflict = _active_conflict(db, profile.user_id, {
            "scope_type": profile.scope_type,
            "scope_id": profile.scope_id,
            "profile_key": profile.profile_key,
        })
    if conflict and conflict.id != profile.id and conflict.status == MemoryProfileStatus.ACTIVE:
        if _same_value(conflict.value_text, profile.value_text):
            profile.status = MemoryProfileStatus.DELETED
            profile.version += 1
            profile.updated_at = now_utc()
            _record_version(
                db,
                profile,
                MemoryProfileOperation.DELETED,
                source_memory_id=item.id,
                reason="Candidate duplicated an already active value.",
            )
            return False
        _supersede_profile(
            db,
            conflict,
            source_memory_id=item.id,
            reason="A repeatedly supported candidate replaced this active value.",
        )
        _retire_source_if_unused(db, conflict, item)

    profile.status = MemoryProfileStatus.ACTIVE
    profile.expires_at = None
    profile.version += 1
    profile.updated_at = now_utc()
    _record_version(
        db,
        profile,
        MemoryProfileOperation.AUTO_PROMOTED,
        source_memory_id=item.id,
        reason=reason or "Candidate reached repeated independent support and confidence thresholds.",
    )
    return True


def _create_profile(
    db: Session,
    item: MemoryItem,
    claim: dict,
    *,
    status: str,
    conflicts_with_id: str | None = None,
) -> MemoryProfile:
    now = now_utc()
    profile = MemoryProfile(
        user_id=item.user_id,
        scope_type=claim["scope_type"],
        scope_id=claim["scope_id"],
        profile_key=claim["profile_key"],
        category=claim["category"],
        value_text=claim["value_text"],
        summary_text=claim["summary_text"],
        evidence_span=claim["evidence_span"],
        confidence=claim["confidence"],
        scope_confidence=claim["scope_confidence"],
        explicitness=claim["explicitness"],
        status=status,
        source_memory_id=item.id,
        conflicts_with_id=conflicts_with_id,
        support_count=1,
        utility_score=0.5,
        utility_observation_count=0,
        last_supported_at=now,
        expires_at=_candidate_expires_at() if status == MemoryProfileStatus.CANDIDATE else None,
        version=1,
    )
    db.add(profile)
    db.flush()
    return profile


def expire_stale_candidates(db: Session, user_id: str | None = None) -> int:
    q = db.query(MemoryProfile).filter(
        MemoryProfile.status == MemoryProfileStatus.CANDIDATE,
        MemoryProfile.expires_at.isnot(None),
        MemoryProfile.expires_at <= now_utc(),
    )
    if user_id:
        q = q.filter(MemoryProfile.user_id == user_id)
    expired = q.all()
    for profile in expired:
        profile.status = MemoryProfileStatus.DELETED
        profile.version += 1
        profile.updated_at = now_utc()
        _record_version(
            db,
            profile,
            MemoryProfileOperation.EXPIRED,
            reason="Candidate memory expired without enough repeated support.",
        )
    return len(expired)


def _reconcile_claims_for_item(
    db: Session,
    item: MemoryItem,
    claims: list[dict],
) -> list[MemoryProfile]:
    results: list[MemoryProfile] = []
    for claim in claims:
        existing = _active_conflict(db, item.user_id, claim)
        if existing and _same_value(existing.value_text, claim["value_text"]):
            _reinforce_profile(
                db,
                existing,
                item,
                claim,
                reason="New evidence supports the existing active value.",
            )
            results.append(existing)
            continue

        decisive = (
            claim["confidence"] >= 0.80
            and claim["scope_confidence"] >= 0.80
            and claim["explicitness"] != MemoryExplicitness.INFERRED
        )
        candidate = _matching_candidate(db, item.user_id, claim)

        if candidate:
            if existing and not candidate.conflicts_with_id:
                candidate.conflicts_with_id = existing.id
            _reinforce_profile(
                db,
                candidate,
                item,
                claim,
                reason=(
                    "Explicit evidence confirmed the candidate value."
                    if decisive
                    else "Repeated evidence supports the candidate value."
                ),
            )
            _promote_candidate_if_ready(
                db,
                candidate,
                item,
                force=decisive,
                reason=(
                    "Explicit evidence confirmed the candidate memory."
                    if decisive
                    else None
                ),
            )
            results.append(candidate)
            continue

        if not decisive:
            profile = _create_profile(
                db,
                item,
                claim,
                status=MemoryProfileStatus.CANDIDATE,
                conflicts_with_id=existing.id if existing else None,
            )
            _record_version(
                db,
                profile,
                MemoryProfileOperation.CANDIDATE,
                reason="Inferred or ambiguous evidence is stored as an inactive candidate.",
            )
            results.append(profile)
            continue

        profile = _create_profile(
            db,
            item,
            claim,
            status=MemoryProfileStatus.ACTIVE,
            conflicts_with_id=existing.id if existing else None,
        )
        if existing:
            _supersede_profile(
                db,
                existing,
                source_memory_id=item.id,
                reason="A newer explicit claim replaced this value in the same scope.",
            )
        _record_version(
            db,
            profile,
            MemoryProfileOperation.CREATED,
            reason="Explicit evidence created the active profile.",
        )
        if existing:
            _retire_source_if_unused(db, existing, item)
        results.append(profile)
    return results


def reconcile_memory_items(
    db: Session,
    items: list[MemoryItem],
    *,
    claims_by_memory_id: dict[str, list[dict]] | None = None,
    game_id: str | None = None,
    task_id: str | None = None,
) -> list[MemoryProfile]:
    if not items:
        return []
    user_id = items[0].user_id
    if any(item.user_id != user_id for item in items):
        raise ValueError("A memory reconciliation batch must belong to one user")
    # One row lock serializes the whole batch so concurrent tasks cannot create
    # multiple active values for the same user/scope/profile_key.
    db.query(User.id).filter(User.id == user_id).with_for_update().one()
    expire_stale_candidates(db, user_id)
    claims_by_memory_id = claims_by_memory_id or {
        item.id: extract_profile_claims(item, game_id=game_id, task_id=task_id)
        for item in items
    }
    results: list[MemoryProfile] = []
    for item in items:
        results.extend(_reconcile_claims_for_item(db, item, claims_by_memory_id.get(item.id, [])))
    return results


def reconcile_memory_item(
    db: Session,
    item: MemoryItem,
    *,
    game_id: str | None = None,
    task_id: str | None = None,
) -> list[MemoryProfile]:
    return reconcile_memory_items(
        db,
        [item],
        game_id=game_id,
        task_id=task_id,
    )


def backfill_missing_profiles(db: Session, user_id: str, *, limit: int = 200) -> int:
    direct_ids = {
        row[0]
        for row in db.query(MemoryProfile.source_memory_id)
        .filter(MemoryProfile.user_id == user_id)
        .all()
        if row[0]
    }
    version_ids = {
        row[0]
        for row in db.query(MemoryProfileVersion.source_memory_id)
        .join(MemoryProfile, MemoryProfile.id == MemoryProfileVersion.profile_id)
        .filter(MemoryProfile.user_id == user_id, MemoryProfileVersion.source_memory_id.isnot(None))
        .all()
        if row[0]
    }
    profiled_ids = direct_ids | version_ids
    q = db.query(MemoryItem).filter(
        MemoryItem.user_id == user_id,
        MemoryItem.status == MemoryStatus.ACTIVE,
    )
    if profiled_ids:
        q = q.filter(~MemoryItem.id.in_(profiled_ids))
    items = q.order_by(MemoryItem.created_at.asc()).limit(max(1, min(limit, 500))).all()
    for item in items:
        reconcile_memory_item(
            db,
            item,
            game_id=item.source_game_id or (item.scope_id if item.scope_type == MemoryScope.GAME else None),
            task_id=item.source_task_id or (item.scope_id if item.scope_type == MemoryScope.TASK else None),
        )
    return len(items)


def list_profiles(
    db: Session,
    user_id: str,
    *,
    status: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    limit: int = 100,
) -> list[MemoryProfile]:
    backfill_missing_profiles(db, user_id)
    expire_stale_candidates(db, user_id)
    q = db.query(MemoryProfile).filter(MemoryProfile.user_id == user_id)
    if status:
        q = q.filter(MemoryProfile.status == status)
    if scope_type:
        q = q.filter(MemoryProfile.scope_type == scope_type)
    if scope_id:
        q = q.filter(MemoryProfile.scope_id == scope_id)
    return q.order_by(MemoryProfile.updated_at.desc()).limit(max(1, min(limit, 200))).all()


def get_owned_profile(db: Session, user_id: str, profile_id: str) -> MemoryProfile | None:
    return (
        db.query(MemoryProfile)
        .filter(MemoryProfile.id == profile_id, MemoryProfile.user_id == user_id)
        .first()
    )


def profile_history(db: Session, profile_id: str) -> list[MemoryProfileVersion]:
    return (
        db.query(MemoryProfileVersion)
        .filter(MemoryProfileVersion.profile_id == profile_id)
        .order_by(MemoryProfileVersion.version.desc(), MemoryProfileVersion.created_at.desc())
        .all()
    )


def correct_profile(
    db: Session,
    profile: MemoryProfile,
    *,
    value_text: str | None = None,
    summary_text: str | None = None,
) -> MemoryProfile:
    from app.services.memory import create_memory

    correction_text = _clean(summary_text or value_text or profile.summary_text, 1000)
    old_source_id = profile.source_memory_id
    source = create_memory(
        db,
        profile.user_id,
        scope_type=profile.scope_type,
        scope_id=profile.scope_id,
        category=profile.category,
        raw_text=correction_text,
        extracted_text=correction_text,
        source_type=MemorySource.MANUAL,
        importance=5,
        confidence=1.0,
        pinned=profile.scope_type == MemoryScope.USER,
    )
    if value_text is not None:
        profile.value_text = _clean(value_text, 500)
    if summary_text is not None:
        profile.summary_text = _clean(summary_text, 1000)
        profile.evidence_span = profile.summary_text
        if value_text is None:
            profile.value_text = _value_for(profile.profile_key, profile.summary_text)
    profile.source_memory_id = source.id
    profile.confidence = 1.0
    profile.scope_confidence = 1.0
    profile.explicitness = MemoryExplicitness.MANUAL
    profile.status = MemoryProfileStatus.ACTIVE
    profile.support_count = max(1, int(profile.support_count or 1))
    profile.last_supported_at = now_utc()
    profile.expires_at = None
    profile.version += 1
    profile.updated_at = now_utc()
    _record_version(
        db,
        profile,
        MemoryProfileOperation.CORRECTED,
        reason="User manually corrected the profile.",
    )
    _retire_memory_source_if_unused(db, old_source_id, source)
    from app.services import memory_entities

    memory_entities.upsert_claim_entities(
        db,
        user_id=profile.user_id,
        items=[source],
        claims_by_memory_id={
            source.id: [
                {
                    "profile_key": profile.profile_key,
                    "category": profile.category,
                    "entities": [],
                }
            ]
        },
    )
    return profile


def retire_profiles_for_memory(db: Session, memory_id: str, *, reason: str) -> None:
    profiles = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.source_memory_id == memory_id,
            MemoryProfile.status.in_([MemoryProfileStatus.ACTIVE, MemoryProfileStatus.CANDIDATE]),
        )
        .all()
    )
    for profile in profiles:
        profile.status = MemoryProfileStatus.DELETED
        profile.expires_at = None
        profile.version += 1
        profile.updated_at = now_utc()
        _record_version(
            db,
            profile,
            MemoryProfileOperation.DELETED,
            reason=reason,
        )


def record_profile_utility(
    db: Session,
    *,
    user_id: str | None,
    profile_ids: Iterable[str],
    outcome_score: float,
    reason: str,
) -> list[MemoryProfile]:
    if not user_id:
        return []
    ids = list(dict.fromkeys(profile_id for profile_id in profile_ids if profile_id))
    if not ids:
        return []
    score = _clamp(outcome_score)
    profiles = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.id.in_(ids),
            MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        )
        .all()
    )
    for profile in profiles:
        count = int(profile.utility_observation_count or 0)
        old_score = _float(profile.utility_score) if profile.utility_score is not None else 0.5
        profile.utility_score = round(score if count == 0 else old_score * (1 - UTILITY_ALPHA) + score * UTILITY_ALPHA, 3)
        profile.utility_observation_count = count + 1
        profile.version += 1
        profile.updated_at = now_utc()
        _record_version(
            db,
            profile,
            MemoryProfileOperation.UTILITY_UPDATED,
            reason=reason,
        )
    return profiles


def record_generation_profile_utility(
    db: Session,
    *,
    user_id: str | None,
    state: dict,
) -> list[MemoryProfile]:
    profiles = state.get("retrieved_memory_profiles") or []
    profile_ids = [item.get("id") for item in profiles if isinstance(item, dict)]
    if not profile_ids:
        return []

    valid = bool((state.get("validation_result") or {}).get("valid"))
    gameplay_passed = bool((state.get("gameplay_qa_result") or {}).get("passed"))
    base_score = 1.0 if valid and gameplay_passed else 0.0
    penalty = (
        0.08 * int(state.get("repair_attempts") or 0)
        + 0.10 * int(state.get("gameplay_repair_attempts") or 0)
        + 0.15 * int(state.get("replan_attempts") or 0)
    )
    score = _clamp(base_score - penalty)
    reason = (
        f"Generation outcome utility: validation={valid}, gameplay={gameplay_passed}, "
        f"repair_attempts={state.get('repair_attempts') or 0}, "
        f"gameplay_repair_attempts={state.get('gameplay_repair_attempts') or 0}, "
        f"replan_attempts={state.get('replan_attempts') or 0}."
    )
    return record_profile_utility(
        db,
        user_id=user_id,
        profile_ids=profile_ids,
        outcome_score=score,
        reason=reason,
    )


def retrieve_profiles(
    db: Session,
    *,
    user_id: str,
    game_id: str | None = None,
    task_id: str | None = None,
    categories: Iterable[str] | None = None,
    limit: int = PROFILE_CONTEXT_LIMIT,
) -> list[dict]:
    settings_row = db.get(MemorySettings, user_id)
    if settings_row and not settings_row.enabled:
        return []
    backfill_missing_profiles(db, user_id)
    expire_stale_candidates(db, user_id)
    clauses = []
    if task_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.TASK, MemoryProfile.scope_id == task_id))
    if game_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.GAME, MemoryProfile.scope_id == game_id))
    if not settings_row or settings_row.allow_cross_game_memory:
        clauses.append(MemoryProfile.scope_type == MemoryScope.USER)
    if not clauses:
        clauses.append(MemoryProfile.scope_type == MemoryScope.USER)
    q = db.query(MemoryProfile).filter(
        MemoryProfile.user_id == user_id,
        MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        or_(*clauses),
    )
    cats = [category for category in (categories or []) if category]
    if cats:
        q = q.filter(MemoryProfile.category.in_(cats))
    profiles = q.order_by(
        MemoryProfile.confidence.desc(),
        MemoryProfile.utility_score.desc(),
        MemoryProfile.updated_at.desc(),
    ).limit(max(1, min(limit, 20))).all()
    scope_order = {MemoryScope.TASK: 0, MemoryScope.GAME: 1, MemoryScope.USER: 2}
    profiles.sort(
        key=lambda item: (
            scope_order.get(item.scope_type, 9),
            -_float(item.confidence),
            -(_float(item.utility_score) if item.utility_score is not None else 0.5),
            -int(item.support_count or 1),
        )
    )
    return [profile_out(profile) for profile in profiles]


def render_profile_context(items: list[dict], *, max_chars: int = PROFILE_CONTEXT_CHARS) -> str:
    if not items:
        return ""
    lines = ["Active memory profile (current user request wins on conflict):"]
    total = len(lines[0])
    for item in items:
        line = (
            f"- [{item['scope_type']}/{item['category']}/{item['profile_key']}] "
            f"{_clean(item['summary_text'], 260)} "
            f"(support={item.get('support_count', 1)}, utility={float(item.get('utility_score') or 0.5):.2f})"
        )
        if total + len(line) > max_chars:
            lines.append("- ...")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)
