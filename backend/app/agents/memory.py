"""Memory retrieval and update nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *


def memory_retrieval_node(state: dict) -> dict:
    from app.db.session import SessionLocal
    from app.services import memory as memory_service
    from app.services import memory_profiles as profile_service

    user_id = state.get("user_id")
    query = state.get("source_feedback") or state.get("normalized_prompt") or state.get("prompt") or ""
    game_id = state.get("base_game_id") if state.get("task_kind") in {"revision", "remix"} else None
    if not user_id:
        return {
            "retrieved_memory_profiles": [],
            "retrieved_memories": [],
            "memory_context": "",
            "_agent": "MemoryRetrievalAgent",
            "_logs": ["memory skipped: missing user id"],
        }
    categories = (
        ["feedback", "controls", "difficulty", "constraints", "style", "mechanics"]
        if state.get("task_kind") in {"revision", "remix"}
        else ["style", "mechanics", "controls", "difficulty", "constraints", "content"]
    )
    db = SessionLocal()
    try:
        profiles = profile_service.retrieve_profiles(
            db,
            user_id=user_id,
            game_id=game_id,
            task_id=state.get("task_id"),
            categories=categories,
            limit=8,
        )
        items = memory_service.retrieve_memories(
            db,
            user_id=user_id,
            query=query,
            game_id=game_id,
            categories=categories,
            limit=8,
        )
        profile_context = profile_service.render_profile_context(profiles)
        evidence_context = memory_service.render_memory_context(items)
        context = "\n\n".join(part for part in (profile_context, evidence_context) if part)
        # Persist lazily generated vectors for memories created before the
        # embedding migration. Retrieval remains fail-open if this commit fails.
        db.commit()
    except Exception as exc:  # noqa: BLE001
        profiles, items, context = [], [], ""
        return {
            "retrieved_memory_profiles": profiles,
            "retrieved_memories": items,
            "memory_context": context,
            "_agent": "MemoryRetrievalAgent",
            "_logs": [f"memory retrieval failed open: {_clip(exc, 160)}"],
        }
    finally:
        db.close()
    scope = f"game={game_id}" if game_id else "user"
    strategy = (items[0].get("retrieval") or {}).get("strategy") if items else "none"
    return {
        "retrieved_memory_profiles": profiles,
        "retrieved_memories": items,
        "memory_context": context,
        "_agent": "MemoryRetrievalAgent",
        "_logs": [
            f"scope: {scope}",
            f"query: {_clip(query, 140)}",
            f"active profiles: {len(profiles)}",
            f"retrieved memories: {len(items)}",
            f"retrieval strategy: {strategy}",
        ]
        + [
            f"- {item.get('scope_type')}/{item.get('category')}: {_clip(item.get('raw_text'), 120)}"
            for item in items[:5]
        ],
    }


def memory_update_node(state: dict) -> dict:
    from app.db.session import SessionLocal
    from app.services import memory as memory_service
    from app.services import memory_profiles as profile_service

    task_id = state.get("task_id")
    if not task_id:
        return {
            "_agent": "MemoryUpdateAgent",
            "_logs": ["memory update skipped: missing task id"],
        }
    db = SessionLocal()
    try:
        created = memory_service.capture_success_memories(db, task_id=task_id, state=state)
        utility_updates = profile_service.record_generation_profile_utility(
            db,
            user_id=state.get("user_id"),
            state=state,
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "_agent": "MemoryUpdateAgent",
            "_logs": [f"memory update failed open: {_clip(exc, 160)}"],
        }
    finally:
        db.close()
    return {
        "_agent": "MemoryUpdateAgent",
        "_logs": [
            f"stored memory items: {len(created)}",
            f"updated active profile utility: {len(utility_updates)}",
            "memory update is non-blocking; generation result already persisted",
        ]
        + [
            f"- {item.scope_type}/{item.category}: {_clip(item.raw_text, 120)}"
            for item in created[:5]
        ],
    }


def next_after_memory_retrieval(state: dict) -> str:
    return "feedback_understanding" if state.get("task_kind") in {"revision", "remix"} else "intent_spec"


__all__ = [
    'memory_retrieval_node',
    'memory_update_node',
    'next_after_memory_retrieval',
]
