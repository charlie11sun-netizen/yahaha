"""Content-safety intake node for the planning pipeline."""

from app.agents.nodes_common import TaskErrorCode, _clip, content_safety
from app.agents.planning_brief import _prompt_cues


def safety_intake_node(state: dict) -> dict:
    prompt = state.get("prompt", "") or ""
    if not prompt.strip():
        return {
            "status": "failed",
            "error_code": TaskErrorCode.VALIDATION_FAILED.value,
            "error_message": "Prompt cannot be empty",
            "_agent": "SafetyIntakeAgent",
            "_logs": ["prompt is empty -> rejected"],
        }
    if len(prompt) > 2000:
        return {
            "status": "failed",
            "error_code": TaskErrorCode.PROMPT_TOO_LONG.value,
            "error_message": "Prompt too long (>2000 chars)",
            "_agent": "SafetyIntakeAgent",
            "_logs": ["prompt exceeds 2000 chars -> rejected"],
        }
    moderation_log = "moderation skipped: unable to persist event"
    moderation_unavailable = None
    try:
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            decision = content_safety.moderate_and_record(
                db,
                text=prompt,
                surface=(
                    "task.idea"
                    if state.get("task_kind") == "generation"
                    else "task.remix_prompt"
                    if state.get("task_kind") == "remix"
                    else "task.revision_feedback"
                ),
                user_id=state.get("user_id"),
                object_id=state.get("task_id"),
            )
            if decision.errored and content_safety.should_enforce():
                moderation_unavailable = ("prompt", "", decision)
            asset_blocked = None
            asset_ids = state.get("asset_ids") or []
            if asset_ids and not moderation_unavailable:
                from app.models import Asset

                for asset in db.query(Asset).filter(Asset.id.in_(asset_ids)).all():
                    asset_decision = content_safety.moderate_and_record(
                        db,
                        text=asset.filename,
                        surface="asset.filename",
                        user_id=state.get("user_id"),
                        object_id=asset.id,
                    )
                    if asset_decision.blocked:
                        asset_blocked = (asset.filename, asset_decision)
                        break
                    if asset_decision.errored and content_safety.should_enforce():
                        moderation_unavailable = ("asset", asset.filename, asset_decision)
                        break
            db.commit()
        finally:
            db.close()
        categories = ", ".join(decision.categories.keys()) or "none"
        moderation_log = f"moderation: {decision.provider}/{decision.action}, categories={categories}"
        if decision.blocked:
            return {
                "status": "failed",
                "error_code": TaskErrorCode.MODERATION_BLOCKED.value,
                "error_message": "Prompt rejected by content moderation",
                "_agent": "SafetyIntakeAgent",
                "_logs": [moderation_log, "prompt blocked before generation"],
            }
        if asset_blocked:
            filename, asset_decision = asset_blocked
            asset_categories = ", ".join(asset_decision.categories.keys()) or "none"
            return {
                "status": "failed",
                "error_code": TaskErrorCode.MODERATION_BLOCKED.value,
                "error_message": "Uploaded asset filename rejected by content moderation",
                "_agent": "SafetyIntakeAgent",
                "_logs": [
                    moderation_log,
                    f"asset filename blocked: {_clip(filename, 80)} categories={asset_categories}",
                ],
            }
        if moderation_unavailable:
            scope, filename, failure_decision = moderation_unavailable
            failure_categories = ", ".join(failure_decision.categories.keys()) or "none"
            target = "prompt" if scope == "prompt" else f"asset filename: {_clip(filename, 80)}"
            return {
                "status": "failed",
                "error_code": TaskErrorCode.SAFETY_REJECTED.value,
                "error_message": "Content moderation is unavailable",
                "_agent": "SafetyIntakeAgent",
                "_logs": [
                    moderation_log,
                    f"moderation unavailable for {target}; categories={failure_categories}",
                    "generation stopped because moderation could not verify the input",
                ],
            }
    except Exception as exc:  # noqa: BLE001
        moderation_log = f"moderation failed: {_clip(exc, 120)}"
        if content_safety.should_enforce():
            return {
                "status": "failed",
                "error_code": TaskErrorCode.SAFETY_REJECTED.value,
                "error_message": "Content moderation is unavailable",
                "_agent": "SafetyIntakeAgent",
                "_logs": [
                    moderation_log,
                    "generation stopped because moderation could not verify the input",
                ],
            }
    cues = _prompt_cues(prompt)
    return {
        "normalized_prompt": prompt.strip(),
        "safety_result": {"passed": True, "risk_level": "low"},
        "_agent": "SafetyIntakeAgent",
        "_logs": [
            f"prompt accepted: {len(prompt)} chars, {len(prompt.split())} word(s)",
            "intent cues: " + (", ".join(cues) if cues else "none detected"),
            f"uploaded asset ids received: {len(state.get('asset_ids') or [])}",
            moderation_log,
            f"policy scan passed: {len(content_safety.BLOCKLIST_PATTERNS)} blocked-pattern checks",
            f"normalized prompt: {_clip(prompt, 160)}",
        ],
    }


__all__ = ["safety_intake_node"]
