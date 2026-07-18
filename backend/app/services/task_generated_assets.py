"""Read generated image previews from a task's durable LangGraph checkpoint."""
from __future__ import annotations

import base64
from pathlib import PurePosixPath

from app.core.checkpointing import checkpoint_config, open_checkpointer
from app.services.artifacts import artifact_bytes, artifact_content_type, normalize_artifact_path


def _checkpoint_values(task_id: str) -> dict:
    # Use LangGraph's public state API rather than depending on saver internals;
    # this works for both the in-memory test saver and PostgresSaver.
    from app.agents.graph import build_graph

    with open_checkpointer() as saver:
        snapshot = build_graph(checkpointer=saver).get_state(checkpoint_config(task_id))
        return dict(snapshot.values or {})


def generated_image_previews(task_id: str) -> list[dict]:
    values = _checkpoint_values(task_id)
    artifacts = list(values.get("generated_assets") or [])
    manifest = dict(values.get("asset_manifest") or {})
    entries = list(manifest.get("assets") or [])
    by_path = {
        normalize_artifact_path(str(entry.get("path") or "")): entry
        for entry in entries
        if entry.get("path")
    }

    previews: list[dict] = []
    for artifact in artifacts:
        try:
            source_path = normalize_artifact_path(str(artifact.get("path") or ""))
            runtime_path = source_path[len("public/") :] if source_path.startswith("public/") else source_path
            content_type = artifact_content_type(artifact).split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                continue
            raw = artifact_bytes(artifact)
        except (TypeError, ValueError):
            continue
        entry = by_path.get(runtime_path) or {}
        key = str(entry.get("key") or PurePosixPath(runtime_path).stem)
        semantic_frames = entry.get("semantic_frames") or {}
        previews.append(
            {
                "key": key,
                "name": key.replace("-", " ").replace("_", " ").title(),
                "kind": str(entry.get("kind") or "image"),
                "content_type": content_type,
                "bytes": len(raw),
                "semantic_ids": list(semantic_frames.keys()) if isinstance(semantic_frames, dict) else [],
                "frame_audit": entry.get("frame_audit") or {},
                "data_url": f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}",
            }
        )
    return previews


__all__ = ["generated_image_previews"]
