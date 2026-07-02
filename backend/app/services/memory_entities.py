"""Entity indexing and entity-based ranking for raw memory evidence."""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models import MemoryEntity, MemoryEntityLink, MemoryItem
from app.models.common import now_utc
from app.services import memory_embeddings

VALID_ENTITY_TYPES = {
    "game",
    "character",
    "mechanic",
    "control",
    "visual_style",
    "level",
    "enemy",
    "boss",
    "item",
    "asset",
    "parameter",
}

_NORMALIZE_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)


def _clean(value, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_entity_name(value: str) -> str:
    return _NORMALIZE_RE.sub("", _clean(value).lower())


def _claim_entities(claim: dict) -> list[dict]:
    entities = []
    for row in claim.get("entities") or []:
        if not isinstance(row, dict):
            continue
        entity_type = _clean(row.get("type"), 40)
        name = _clean(row.get("name"))
        if entity_type in VALID_ENTITY_TYPES and name:
            entities.append({"type": entity_type, "name": name})
    if not entities:
        profile_key = _clean(claim.get("profile_key"), 160)
        category = _clean(claim.get("category"), 40)
        fallback_type = {
            "style": "visual_style",
            "mechanics": "mechanic",
            "controls": "control",
        }.get(category, "parameter")
        if profile_key:
            entities.append({"type": fallback_type, "name": profile_key})
    return entities


def upsert_claim_entities(
    db: Session,
    *,
    user_id: str,
    items: list[MemoryItem],
    claims_by_memory_id: dict[str, list[dict]],
) -> int:
    item_ids = {item.id for item in items}
    requested: dict[tuple[str, str], str] = {}
    item_keys: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for memory_id, claims in claims_by_memory_id.items():
        if memory_id not in item_ids:
            continue
        for claim in claims:
            for row in _claim_entities(claim):
                normalized = normalize_entity_name(row["name"])
                if not normalized:
                    continue
                key = (row["type"], normalized)
                requested.setdefault(key, row["name"])
                item_keys[memory_id].add(key)
    if not requested:
        return 0

    entity_types = {key[0] for key in requested}
    normalized_names = {key[1] for key in requested}
    existing = (
        db.query(MemoryEntity)
        .filter(
            MemoryEntity.user_id == user_id,
            MemoryEntity.entity_type.in_(entity_types),
            MemoryEntity.normalized_name.in_(normalized_names),
        )
        .all()
    )
    by_key = {(entity.entity_type, entity.normalized_name): entity for entity in existing}
    model = memory_embeddings.embedding_model()
    pending_keys = [key for key in requested if key not in by_key]
    vectors = memory_embeddings.embed_texts([requested[key] for key in pending_keys]) if pending_keys else []
    for index, key in enumerate(pending_keys):
        vector = vectors[index] if vectors and index < len(vectors) else None
        entity = MemoryEntity(
            user_id=user_id,
            entity_type=key[0],
            canonical_name=requested[key],
            normalized_name=key[1],
            embedding=vector,
            embedding_model=model if vector else None,
            embedding_updated_at=now_utc() if vector else None,
        )
        db.add(entity)
        by_key[key] = entity
    db.flush()

    entity_ids = [entity.id for entity in by_key.values()]
    existing_links = {
        (link.entity_id, link.memory_id)
        for link in db.query(MemoryEntityLink)
        .filter(
            MemoryEntityLink.entity_id.in_(entity_ids),
            MemoryEntityLink.memory_id.in_(item_ids),
        )
        .all()
    }
    created = 0
    for memory_id, keys in item_keys.items():
        for key in keys:
            entity = by_key[key]
            if (entity.id, memory_id) in existing_links:
                continue
            db.add(
                MemoryEntityLink(
                    entity_id=entity.id,
                    memory_id=memory_id,
                    confidence=1.0,
                    source="claim",
                )
            )
            created += 1
    return created


def delete_links_for_memory(db: Session, memory_id: str) -> int:
    return (
        db.query(MemoryEntityLink)
        .filter(MemoryEntityLink.memory_id == memory_id)
        .delete(synchronize_session=False)
    )


def rank_candidate_memories_by_entity(
    db: Session,
    *,
    user_id: str,
    query: str,
    candidate_ids: list[str],
    query_vector: list[float] | None,
) -> tuple[list[str], dict[str, float]]:
    if not candidate_ids:
        return [], {}
    rows = (
        db.query(MemoryEntity, MemoryEntityLink.memory_id)
        .join(MemoryEntityLink, MemoryEntityLink.entity_id == MemoryEntity.id)
        .filter(
            MemoryEntity.user_id == user_id,
            MemoryEntityLink.memory_id.in_(candidate_ids),
        )
        .all()
    )
    query_normalized = normalize_entity_name(query)
    scores: dict[str, float] = {}
    for entity, memory_id in rows:
        lexical = 0.0
        if entity.normalized_name and query_normalized:
            if entity.normalized_name in query_normalized or query_normalized in entity.normalized_name:
                lexical = 1.0
        semantic = memory_embeddings.cosine_similarity(query_vector or [], entity.embedding or []) or 0.0
        score = max(lexical, semantic)
        if score > scores.get(memory_id, 0.0):
            scores[memory_id] = score
    ranking = sorted(scores, key=lambda memory_id: scores[memory_id], reverse=True)
    return ranking, scores
