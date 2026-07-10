"""Current memory profile synthesis, scope inference, and conflict lifecycle."""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, case
from sqlalchemy.orm import Session

from app.models import (
    MemoryItem,
    MemoryProfile,
    MemoryProfileEvidence,
    MemoryProfileVersion,
)
from app.models.common import now_utc
from app.models.memory import (
    MemoryCategory,
    MemoryScope,
    MemoryStatus,
)
from app.services import memory_embeddings

PROFILE_CONTEXT_CHARS = 1400
PROFILE_CONTEXT_LIMIT = 8
CANDIDATE_SUPPORT_THRESHOLD = 3
CANDIDATE_CONFIDENCE_THRESHOLD = 0.78
CANDIDATE_TTL_DAYS = 90
UTILITY_ALPHA = 0.20
# Same topic -> reuse the peer's profile_key; nearly identical claim -> also reuse its value.
PROFILE_KEY_SIMILARITY_THRESHOLD = 0.82
PROFILE_VALUE_SIMILARITY_THRESHOLD = 0.90
KEY_ADOPTION_PEER_LIMIT = 200
# A user-scope candidate only activates once the same preference appeared in this many games.
USER_PROMOTION_DISTINCT_GAMES = 2

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
# 除句读外，还在作用域信号词（这次/以后/…）前切分：混合表达
# "以后默认像素风，这次先调跳跃" 必须拆成两个不同作用域的 claim。
_CLAIM_SPLIT_RE = re.compile(
    r"[。！？!?;；\n]+|(?=\bbut\b)|(?=但是)|(?=但)|(?=同时)|(?=另外)"
    r"|(?=这次)|(?=本次)|(?=以后)|(?=今后)|(?=\bfor now\b)|(?=\bthis time\b)|(?=\bfrom now on\b)",
    re.IGNORECASE,
)
_NORMALIZE_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_NEGATED_VALUE_RE = re.compile(
    r"(?:不要|不再|别用|别|取消|避免|not|no longer|without|stop using)\s*$",
    re.IGNORECASE,
)
_TASTE_RE = re.compile(
    r"我(不太?|很|超|特别)?(喜欢|讨厌|偏好|偏爱)|我一向|我向来|我总是|我从来不"
    r"|I (really )?(don't |do not |)(like|love|prefer|hate|enjoy)|I always|I never",
    re.IGNORECASE,
)
_HASH_KEY_RE = re.compile(r"^[a-z]+:[0-9a-f]{16}$")
_NEGATION_TOKEN_RE = re.compile(r"不|别|没|勿|avoid|not|never|without|stop", re.IGNORECASE)

_GENERALIZABLE_CATEGORIES = {
    MemoryCategory.STYLE,
    MemoryCategory.DIFFICULTY,
    MemoryCategory.CONTROLS,
}

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


def _scope_priority_expr(*, game_id: str | None, task_id: str | None):
    priorities = []
    if task_id:
        priorities.append(
            (and_(MemoryProfile.scope_type == MemoryScope.TASK, MemoryProfile.scope_id == task_id), 0)
        )
    if game_id:
        priorities.append(
            (and_(MemoryProfile.scope_type == MemoryScope.GAME, MemoryProfile.scope_id == game_id), 1)
        )
    priorities.append((MemoryProfile.scope_type == MemoryScope.USER, 2))
    return case(*priorities, else_=3)


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


def _link_profile_evidence(
    db: Session,
    profile: MemoryProfile,
    item: MemoryItem,
    claim: dict,
) -> MemoryProfileEvidence:
    link = (
        db.query(MemoryProfileEvidence)
        .filter(
            MemoryProfileEvidence.profile_id == profile.id,
            MemoryProfileEvidence.memory_id == item.id,
        )
        .first()
    )
    if not link:
        link = MemoryProfileEvidence(profile_id=profile.id, memory_id=item.id)
        db.add(link)
    link.evidence_span = claim["evidence_span"]
    link.value_text = claim["value_text"]
    link.summary_text = claim["summary_text"]
    link.confidence = claim["confidence"]
    link.scope_confidence = claim["scope_confidence"]
    link.explicitness = claim["explicitness"]
    link.is_active = True
    db.flush()
    return link


def refresh_profile_embedding(profile: MemoryProfile, previous_summary: str | None) -> None:
    """Refresh the profile vector whenever its summary changes."""
    if _clean(previous_summary or "") == _clean(profile.summary_text or ""):
        return
    refreshed = memory_embeddings.embed_texts([_clean(profile.summary_text, 500)])
    profile.embedding = refreshed[0] if refreshed else None
    profile.embedding_model = memory_embeddings.embedding_model() if refreshed else None
    profile.embedding_updated_at = now_utc() if refreshed else None


def count_distinct_supporting_games(db: Session, profile: MemoryProfile) -> int:
    """Count distinct games represented by active evidence for a profile."""
    db.flush()
    rows = (
        db.query(MemoryItem.source_game_id, MemoryItem.scope_type, MemoryItem.scope_id)
        .join(MemoryProfileEvidence, MemoryProfileEvidence.memory_id == MemoryItem.id)
        .filter(
            MemoryProfileEvidence.profile_id == profile.id,
            MemoryProfileEvidence.is_active.is_(True),
            MemoryItem.status != MemoryStatus.DELETED,
        )
        .distinct()
        .all()
    )
    games = {
        source_game_id or (scope_id if scope_type == MemoryScope.GAME else None)
        for source_game_id, scope_type, scope_id in rows
    }
    games.discard(None)
    return len(games)


# Public vocabulary shared by the profile domain services.  The private names
# above remain implementation details of this module; consumers import only
# these aliases so dependencies stay explicit and one-way.
GLOBAL_SCOPE_PATTERN = _GLOBAL_SCOPE_RE
GAME_SCOPE_PATTERN = _GAME_SCOPE_RE
TASK_SCOPE_PATTERN = _TASK_SCOPE_RE
HEDGE_PATTERN = _HEDGE_RE
CLAIM_SPLIT_PATTERN = _CLAIM_SPLIT_RE
NORMALIZE_PATTERN = _NORMALIZE_RE
NEGATED_VALUE_PATTERN = _NEGATED_VALUE_RE
TASTE_PATTERN = _TASTE_RE
HASH_KEY_PATTERN = _HASH_KEY_RE
NEGATION_TOKEN_PATTERN = _NEGATION_TOKEN_RE
GENERALIZABLE_CATEGORIES = _GENERALIZABLE_CATEGORIES
VALID_CATEGORIES = _VALID_CATEGORIES
ATTRIBUTE_RULES = _ATTRIBUTE_RULES
CANONICAL_VALUES = _CANONICAL_VALUES
profile_number = _float
clamp_score = _clamp
clean_profile_text = _clean
normalize_profile_text = _normalized
candidate_expires_at = _candidate_expires_at
scope_priority_expr = _scope_priority_expr
record_profile_version = _record_version
link_profile_evidence = _link_profile_evidence


__all__ = [
    "ATTRIBUTE_RULES",
    "CANDIDATE_CONFIDENCE_THRESHOLD",
    "CANDIDATE_SUPPORT_THRESHOLD",
    "CANONICAL_VALUES",
    "CLAIM_SPLIT_PATTERN",
    "GAME_SCOPE_PATTERN",
    "GENERALIZABLE_CATEGORIES",
    "GLOBAL_SCOPE_PATTERN",
    "HASH_KEY_PATTERN",
    "HEDGE_PATTERN",
    "KEY_ADOPTION_PEER_LIMIT",
    "NEGATED_VALUE_PATTERN",
    "NEGATION_TOKEN_PATTERN",
    "NORMALIZE_PATTERN",
    "PROFILE_CONTEXT_CHARS",
    "PROFILE_CONTEXT_LIMIT",
    "PROFILE_KEY_SIMILARITY_THRESHOLD",
    "PROFILE_VALUE_SIMILARITY_THRESHOLD",
    "TASK_SCOPE_PATTERN",
    "TASTE_PATTERN",
    "USER_PROMOTION_DISTINCT_GAMES",
    "UTILITY_ALPHA",
    "VALID_CATEGORIES",
    "candidate_expires_at",
    "clamp_score",
    "clean_profile_text",
    "count_distinct_supporting_games",
    "link_profile_evidence",
    "normalize_profile_text",
    "profile_number",
    "profile_out",
    "record_profile_version",
    "refresh_profile_embedding",
    "scope_priority_expr",
    "version_out",
]
