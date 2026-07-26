"""Read generation state through the LangGraph checkpoint API."""
from __future__ import annotations

from app.agents.graph import build_graph
from app.core.checkpointing import checkpoint_config, open_checkpointer


def checkpoint_values(task_id: str) -> dict:
    """Return the durable state for a generation task."""

    with open_checkpointer() as saver:
        snapshot = build_graph(checkpointer=saver).get_state(checkpoint_config(task_id))
        return dict(snapshot.values or {})


__all__ = ["checkpoint_values"]
