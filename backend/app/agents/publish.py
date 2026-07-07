"""Publish nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *


def publish_artifact_node(state: dict) -> dict:
    from app.services import packaging

    game_id, version_id, manifest_url = packaging.publish_generated(state)
    return {
        "status": "succeeded",
        "game_id": game_id,
        "version_id": version_id,
        "manifest_url": manifest_url,
        "preview_url": f"/play/{game_id}",
        "_agent": "PublishArtifactAgent",
        "_logs": [
            f"uploaded files: {', '.join(file.get('path', '?') for file in state.get('generated_files') or [])}",
            f"manifest url: {manifest_url}",
            f"game id: {game_id}",
            f"version id: {version_id}",
            "database saved: game + game_version with preview status",
        ],
    }


def publish_revision_node(state: dict) -> dict:
    from app.services import packaging

    game_id, version_id, version, manifest_url = packaging.publish_revision(state)
    return {
        "status": "succeeded",
        "game_id": game_id,
        "version_id": version_id,
        "manifest_url": manifest_url,
        "preview_url": f"/play/{game_id}",
        "_agent": "PublishRevisionAgent",
        "_logs": [
            f"incremental files: {', '.join((state.get('revision_result') or {}).get('changed_files') or [])}",
            f"saved preview version: {version}",
            f"manifest url: {manifest_url}",
            "previous version retained for rollback",
        ],
    }


def publish_remix_node(state: dict) -> dict:
    from app.services import packaging

    game_id, version_id, manifest_url = packaging.publish_remix(state)
    return {
        "status": "succeeded",
        "game_id": game_id,
        "version_id": version_id,
        "manifest_url": manifest_url,
        "preview_url": f"/play/{game_id}",
        "_agent": "PublishRemixAgent",
        "_logs": [
            f"source game: {state.get('base_game_id')}@{state.get('base_version')}",
            f"remix files: {', '.join((state.get('revision_result') or {}).get('changed_files') or [])}",
            f"manifest url: {manifest_url}",
            "database saved: new remixed game + v1",
        ],
    }


__all__ = [
    'publish_artifact_node',
    'publish_revision_node',
    'publish_remix_node',
]
