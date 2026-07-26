"""Memory profile claim extraction and scope inference."""

from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GenerationTask, MemoryItem, MemoryProfile, MemorySettings
from app.models.common import TaskStatus, now_utc
from app.models.memory import (
    MemoryCategory,
    MemoryExplicitness,
    MemoryProfileStatus,
    MemoryScope,
    MemorySource,
)
from app.services import memory_embeddings
from app.services.memory_profile_common import (
    ATTRIBUTE_RULES,
    CANONICAL_VALUES,
    CLAIM_SPLIT_PATTERN,
    GAME_SCOPE_PATTERN,
    GENERALIZABLE_CATEGORIES,
    GLOBAL_SCOPE_PATTERN,
    HASH_KEY_PATTERN,
    HEDGE_PATTERN,
    KEY_ADOPTION_PEER_LIMIT,
    NEGATED_VALUE_PATTERN,
    NEGATION_TOKEN_PATTERN,
    PROFILE_CONTEXT_LIMIT,
    PROFILE_KEY_SIMILARITY_THRESHOLD,
    PROFILE_VALUE_SIMILARITY_THRESHOLD,
    TASK_SCOPE_PATTERN,
    TASTE_PATTERN,
    VALID_CATEGORIES,
    clamp_score,
    clean_profile_text,
    normalize_profile_text,
    profile_number,
    scope_priority_expr,
)
from app.services.memory_rules import category_for_text


def split_profile_claims(text: str) -> list[str]:
    parts = [clean_profile_text(part, 500).strip("；;，, ") for part in CLAIM_SPLIT_PATTERN.split(text)]
    return [part for part in parts if len(part) >= 4] or [clean_profile_text(text, 500)]


def has_persistent_profile_claim(raw: str) -> bool:
    """Return whether at least one claim is not explicitly task-scoped."""
    return any(not TASK_SCOPE_PATTERN.search(claim) for claim in split_profile_claims(raw))


def _attribute_for(claim: str, category: str) -> str:
    low = claim.lower()
    for key, _, terms in ATTRIBUTE_RULES:
        if any(term in low for term in terms):
            return key
    digest = hashlib.sha256(normalize_profile_text(claim).encode("utf-8")).hexdigest()[:16]
    return f"{category}:{digest}"


def _category_for_attribute(attribute: str, fallback: str) -> str:
    for key, category, _ in ATTRIBUTE_RULES:
        if key == attribute:
            return category
    return fallback if fallback in VALID_CATEGORIES else MemoryCategory.FEEDBACK


def canonical_profile_value(attribute: str, claim: str) -> str:
    low = claim.lower()
    matches: list[tuple[int, str]] = []
    for value, terms in CANONICAL_VALUES.get(attribute, []):
        for term in terms:
            start = low.find(term)
            while start >= 0:
                prefix = low[max(0, start - 20) : start]
                if not NEGATED_VALUE_PATTERN.search(prefix):
                    matches.append((start, value))
                start = low.find(term, start + len(term))
    if matches:
        return max(matches, key=lambda match: match[0])[1]
    return normalize_profile_text(claim)[:500] or claim[:500]


def _is_hash_key(profile_key: str) -> bool:
    return bool(HASH_KEY_PATTERN.match(profile_key or ""))


def _negation_parity(text: str) -> bool:
    return bool(NEGATION_TOKEN_PATTERN.search(text or ""))


# 反义方向词对：一字之差的反向偏好（"不要太高" vs "不要太低"）embedding 相似度
# 极高、否定奇偶性又相同，仅靠这两者会被错并成"强化"。方向冲突时禁止复用 value，
# 让它走冲突状态机。
_DIRECTION_PAIRS = [
    ("高", "低"), ("快", "慢"), ("大", "小"), ("多", "少"), ("难", "易"),
    ("难", "简单"), ("强", "弱"), ("亮", "暗"), ("重", "轻"), ("长", "短"),
    ("high", "low"), ("fast", "slow"), ("big", "small"), ("large", "small"),
    ("more", "less"), ("hard", "easy"), ("strong", "weak"), ("bright", "dark"),
    ("long", "short"), ("loud", "quiet"),
]


def _direction_conflict(a: str, b: str) -> bool:
    la, lb = (a or "").lower(), (b or "").lower()
    for pos, neg in _DIRECTION_PAIRS:
        a_pos, a_neg = pos in la, neg in la
        b_pos, b_neg = pos in lb, neg in lb
        if (a_pos and not a_neg and b_neg and not b_pos) or (a_neg and not a_pos and b_pos and not b_neg):
            return True
    return False


def _backfill_profile_embeddings(peers: list[MemoryProfile]) -> None:
    model = memory_embeddings.embedding_model()
    stale = [
        peer
        for peer in peers
        if not memory_embeddings.vector_values(peer.embedding) or peer.embedding_model != model
    ]
    if not stale:
        return
    refreshed = memory_embeddings.embed_texts([clean_profile_text(peer.summary_text, 500) for peer in stale])
    if not refreshed or len(refreshed) != len(stale):
        return
    now = now_utc()
    for peer, vector in zip(stale, refreshed):
        peer.embedding = vector
        peer.embedding_model = model
        peer.embedding_updated_at = now


def _postgres_profile_ann_candidates(
    db: Session,
    query,
    claim_vector: list[float],
) -> tuple[list[MemoryProfile], dict[str, float]]:
    if db.get_bind().dialect.name != "postgresql" or not claim_vector:
        return [], {}
    ef_search = max(40, min(int(settings.MEMORY_HNSW_EF_SEARCH), 1000))
    db.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))
    distance = MemoryProfile.embedding.cosine_distance(claim_vector).label("cosine_distance")
    rows = (
        query.with_entities(MemoryProfile, distance)
        .filter(MemoryProfile.embedding.isnot(None))
        .order_by(distance.asc())
        .limit(max(1, min(int(settings.MEMORY_ANN_CANDIDATES), KEY_ADOPTION_PEER_LIMIT)))
        .all()
    )
    peers = []
    scores = {}
    for peer, value in rows:
        if value is None:
            continue
        peers.append(peer)
        scores[peer.id] = 1.0 - float(value)
    return peers, scores


def _adopt_similar_key(
    db: Session,
    *,
    user_id: str,
    claim_text: str,
) -> tuple[str | None, str | None, list[float] | None]:
    """Match an out-of-vocabulary claim to an existing profile by embedding.

    Returns (profile_key, value_text, claim_vector). Key adoption means "same
    topic"; the value is only adopted when the claim is nearly identical and
    has the same negation parity, so opposite preferences stay in the
    conflict path instead of silently reinforcing each other.
    """
    peer_query = db.query(MemoryProfile).filter(
        MemoryProfile.user_id == user_id,
        MemoryProfile.status.in_([MemoryProfileStatus.ACTIVE, MemoryProfileStatus.CANDIDATE]),
    )
    policy_peers = (
        peer_query
        .order_by(MemoryProfile.updated_at.desc())
        .limit(KEY_ADOPTION_PEER_LIMIT)
        .all()
    )
    if not policy_peers:
        return None, None, None
    vectors = memory_embeddings.embed_texts([clean_profile_text(claim_text, 500)])
    if not vectors:
        return None, None, None
    claim_vector = vectors[0]
    peers = policy_peers
    ann_scores: dict[str, float] = {}
    if db.get_bind().dialect.name == "postgresql":
        ann_peers, ann_scores = _postgres_profile_ann_candidates(db, peer_query, claim_vector)
        by_id = {peer.id: peer for peer in policy_peers}
        for peer in ann_peers:
            by_id.setdefault(peer.id, peer)
        peers = list(by_id.values())
        _backfill_profile_embeddings(policy_peers)
    else:
        _backfill_profile_embeddings(peers)
    best_peer, best_score = None, 0.0
    for peer in peers:
        score = ann_scores.get(peer.id)
        if score is None:
            score = memory_embeddings.cosine_similarity(claim_vector, peer.embedding)
        if score is not None and score > best_score:
            best_peer, best_score = peer, score
    if not best_peer or best_score < PROFILE_KEY_SIMILARITY_THRESHOLD:
        return None, None, claim_vector
    same_value = (
        best_score >= PROFILE_VALUE_SIMILARITY_THRESHOLD
        and _negation_parity(claim_text) == _negation_parity(best_peer.summary_text)
        and not _direction_conflict(claim_text, best_peer.summary_text)
    )
    return best_peer.profile_key, best_peer.value_text if same_value else None, claim_vector


def _scope_for(
    claim: str,
    item: MemoryItem,
    *,
    game_id: str | None,
    task_id: str | None,
) -> tuple[str, str | None, float, str]:
    if item.source_type == MemorySource.MANUAL:
        return item.scope_type, item.scope_id, 1.0, MemoryExplicitness.MANUAL
    if GLOBAL_SCOPE_PATTERN.search(claim):
        return MemoryScope.USER, None, 0.97, MemoryExplicitness.EXPLICIT
    if TASK_SCOPE_PATTERN.search(claim):
        return MemoryScope.TASK, task_id or item.source_task_id, 0.95, MemoryExplicitness.EXPLICIT
    if GAME_SCOPE_PATTERN.search(claim):
        return MemoryScope.GAME, game_id or item.source_game_id or item.scope_id, 0.96, MemoryExplicitness.EXPLICIT
    if item.source_type == MemorySource.IDEA:
        return MemoryScope.GAME, game_id or item.source_game_id or item.scope_id, 0.90, MemoryExplicitness.EXPLICIT
    return MemoryScope.GAME, game_id or item.source_game_id or item.scope_id, 0.84, MemoryExplicitness.INFERRED


def _base_confidence(item: MemoryItem, evidence: str) -> tuple[float, str]:
    hedged = bool(HEDGE_PATTERN.search(evidence))
    if item.source_type == MemorySource.MANUAL:
        return 1.0, MemoryExplicitness.MANUAL
    if hedged:
        return 0.64, MemoryExplicitness.INFERRED
    if item.source_type == MemorySource.IDEA:
        return 0.84, MemoryExplicitness.EXPLICIT
    return 0.88, MemoryExplicitness.EXPLICIT


def _deterministic_claims(
    db: Session,
    item: MemoryItem,
    *,
    game_id: str | None,
    task_id: str | None,
) -> list[dict]:
    claims = []
    for evidence in split_profile_claims(item.raw_text):
        scope_type, scope_id, scope_confidence, scope_explicitness = _scope_for(
            evidence, item, game_id=game_id, task_id=task_id
        )
        if scope_type != MemoryScope.USER and not scope_id:
            continue
        fallback_category = item.category or category_for_text(evidence)
        attribute = _attribute_for(evidence, fallback_category)
        value_text = None
        claim_vector = None
        if _is_hash_key(attribute):
            adopted_key, adopted_value, claim_vector = _adopt_similar_key(
                db, user_id=item.user_id, claim_text=evidence
            )
            if adopted_key:
                attribute = adopted_key
                value_text = adopted_value
        category = _category_for_attribute(attribute, fallback_category)
        confidence, explicitness = _base_confidence(item, evidence)
        claims.append({
            "scope_type": scope_type,
            "scope_id": scope_id,
            "profile_key": attribute,
            "category": category,
            "value_text": value_text or canonical_profile_value(attribute, evidence),
            "summary_text": evidence,
            "evidence_span": evidence,
            "confidence": confidence,
            "scope_confidence": scope_confidence,
            "explicitness": explicitness,
            "scope_explicitness": scope_explicitness,
            "embedding": claim_vector,
        })
    return _with_user_shadow_claims(claims, item)


def _with_user_shadow_claims(claims: list[dict], item: MemoryItem) -> list[dict]:
    """Add background user-scope candidates for generalizable game-scope claims.

    The shadow claim is always non-decisive (inferred), so it enters the
    candidate track and only activates once _promote_candidate_if_ready sees
    the same preference in multiple distinct games. Claims whose wording
    explicitly pins a scope ("这个游戏", "只改这次", ...) are respected as-is.
    """
    if item.source_type == MemorySource.MANUAL:
        return claims
    augmented = list(claims)
    for claim in claims:
        suggested_user = bool(claim.pop("suggested_user_scope", False))
        if claim["scope_type"] != MemoryScope.GAME:
            continue
        evidence = claim["evidence_span"]
        if GAME_SCOPE_PATTERN.search(evidence) or TASK_SCOPE_PATTERN.search(evidence):
            continue
        generalizable = (
            claim["category"] in GENERALIZABLE_CATEGORIES
            or suggested_user
            or bool(TASTE_PATTERN.search(evidence))
        )
        if not generalizable:
            continue
        augmented.append({
            **claim,
            "scope_type": MemoryScope.USER,
            "scope_id": None,
            "scope_confidence": 0.90 if suggested_user else 0.82,
            "explicitness": MemoryExplicitness.INFERRED,
            "scope_explicitness": MemoryExplicitness.INFERRED,
        })
    return augmented


def _parse_json_object(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def profiles_for_extraction_context(
    db: Session,
    *,
    user_id: str,
    game_id: str | None,
    task_id: str | None,
) -> list[dict]:
    """Active and candidate profiles the extractor should reuse keys from.

    Candidates are included so a rephrased preference reinforces the pending
    candidate instead of spawning a parallel key that can never accumulate
    support.
    """
    settings_row = db.get(MemorySettings, user_id)
    clauses = []
    if task_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.TASK, MemoryProfile.scope_id == task_id))
    if game_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.GAME, MemoryProfile.scope_id == game_id))
    if not settings_row or settings_row.allow_cross_game_memory:
        clauses.append(MemoryProfile.scope_type == MemoryScope.USER)
    if not clauses:
        return []
    profiles = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.status.in_([MemoryProfileStatus.ACTIVE, MemoryProfileStatus.CANDIDATE]),
            or_(*clauses),
        )
        .order_by(
            scope_priority_expr(game_id=game_id, task_id=task_id),
            MemoryProfile.confidence.desc(),
            MemoryProfile.support_count.desc(),
            MemoryProfile.updated_at.desc(),
        )
        .limit(80)
        .all()
    )
    scope_order = {MemoryScope.TASK: 0, MemoryScope.GAME: 1, MemoryScope.USER: 2}
    profiles.sort(
        key=lambda profile: (
            scope_order.get(profile.scope_type, 9),
            -profile_number(profile.confidence),
            -int(profile.support_count or 1),
        )
    )
    active = [profile for profile in profiles if profile.status == MemoryProfileStatus.ACTIVE]
    candidates = [profile for profile in profiles if profile.status == MemoryProfileStatus.CANDIDATE]
    profiles = active[:PROFILE_CONTEXT_LIMIT] + candidates[:PROFILE_CONTEXT_LIMIT]
    return [
        {
            "id": profile.id,
            "scope_type": profile.scope_type,
            "scope_id": profile.scope_id,
            "profile_key": profile.profile_key,
            "category": profile.category,
            "value_text": profile.value_text,
            "summary_text": profile.summary_text,
            "status": profile.status,
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
        content = clean_profile_text(content, 4000)
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
    known_profiles: list[dict],
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

    from app.llm import runtime as llm

    system = (
        "You are a memory extractor for a game-generation agent. Return one strict JSON object. "
        "Use known_profiles and recent_user_messages only to resolve context, duplicates, and conflicts. "
        "known_profiles contains active and candidate rows; when a claim expresses the same attribute as "
        "any of them, reuse that profile_key verbatim instead of inventing a new key. "
        "Every claim must come from current_evidence and cite an exact evidence_span copied from that "
        "evidence's raw_text. System and assistant messages are intentionally absent. Do not invent user "
        "preferences. Return all claims in one response; no follow-up or tool calls. Use decision=skip or "
        "evidence_only when no durable profile should be created. Report your real confidence; uncertain "
        "claims are kept as background candidates instead of being discarded. Set suggested_scope=user only "
        "for durable cross-game preferences; such claims are stored as background user-scope candidates and "
        "only activate after independent support from multiple games. Explicit scope wording in the evidence "
        "always wins over suggested_scope."
    )
    user = json.dumps(
        {
            "known_profiles": known_profiles,
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
            "available_categories": sorted(VALID_CATEGORIES),
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
        item = by_id.get(clean_profile_text(row.get("source_memory_id"), 36))
        decision = clean_profile_text(row.get("decision"), 30)
        if not item or decision not in {"active", "candidate", "evidence_only", "skip"}:
            continue
        if decision in {"evidence_only", "skip"}:
            continue
        evidence = clean_profile_text(row.get("evidence_span"), 500)
        if not evidence or evidence not in item.raw_text:
            continue
        scope_type, scope_id, scope_confidence, scope_explicitness = _scope_for(
            evidence, item, game_id=game_id, task_id=task_id
        )
        if scope_type != MemoryScope.USER and not scope_id:
            continue
        fallback_category = item.category or category_for_text(evidence)
        profile_key = clean_profile_text(row.get("profile_key"), 160) or _attribute_for(evidence, fallback_category)
        category = clean_profile_text(row.get("category"), 40)
        if category not in VALID_CATEGORIES:
            category = _category_for_attribute(profile_key, fallback_category)
        base_confidence, rule_explicitness = _base_confidence(item, evidence)
        try:
            llm_confidence = clamp_score(float(row.get("confidence", base_confidence) or base_confidence))
        except (TypeError, ValueError):
            llm_confidence = base_confidence
        # Asymmetric clamp: the model may lower its confidence freely (routes the
        # claim into the candidate track) but can only raise it marginally.
        confidence = min(0.94, min(max(llm_confidence, 0.30), base_confidence + 0.04))
        llm_explicitness = clean_profile_text(row.get("explicitness"), 20)
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
                "value_text": clean_profile_text(row.get("value_text"), 500) or canonical_profile_value(profile_key, evidence),
                "summary_text": clean_profile_text(row.get("summary_text"), 1000) or evidence,
                "evidence_span": evidence,
                "confidence": confidence,
                "scope_confidence": scope_confidence,
                "explicitness": explicitness,
                "scope_explicitness": scope_explicitness,
                "suggested_user_scope": clean_profile_text(row.get("suggested_scope"), 20) == MemoryScope.USER,
                "entities": row.get("entities") if isinstance(row.get("entities"), list) else [],
            }
        )
    return {
        memory_id: _with_user_shadow_claims(claims, by_id[memory_id])
        for memory_id, claims in output.items()
    }


def extract_profile_claims(
    db: Session,
    item: MemoryItem,
    *,
    game_id: str | None = None,
    task_id: str | None = None,
) -> list[dict]:
    return _deterministic_claims(db, item, game_id=game_id, task_id=task_id)


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
    known_profiles = profiles_for_extraction_context(
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
        known_profiles=known_profiles,
        recent_user_messages=recent_messages,
        game_id=game_id,
        task_id=task_id,
    )
    if extracted is None:
        extracted = {}
    result: dict[str, list[dict]] = {}
    for item in items:
        if item.id in extracted:
            result[item.id] = extracted[item.id]
        else:
            # Items the LLM path never considered (manual sources, or the model
            # being unavailable) still get deterministic claims.
            result[item.id] = _deterministic_claims(db, item, game_id=game_id, task_id=task_id)
    return result


__all__ = [
    "canonical_profile_value",
    "extract_profile_claims",
    "extract_profile_claims_batch",
    "has_persistent_profile_claim",
    "profiles_for_extraction_context",
    "split_profile_claims",
]
