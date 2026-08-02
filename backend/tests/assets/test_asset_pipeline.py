import base64
import json

import pytest


def _legacy_phaser_bundle():
    return [
        {
            "path": "index.html",
            "content": (
                '<!doctype html><link rel="stylesheet" href="style.css">'
                '<script src="phaser.min.js"></script><script src="game.js"></script>'
            ),
        },
        {"path": "style.css", "content": "body{margin:0}"},
        {
            "path": "game.js",
            "content": (
                "class Play extends Phaser.Scene{create(){this.input.on('pointerdown',()=>{});"
                "this.scene.restart();}update(){}}new Phaser.Game({scene:[Play]});"
                + "// padding\n" * 50
            ),
        },
    ]


def test_artifact_binary_roundtrip_and_nested_path():
    from app.services.artifacts import artifact_bytes, binary_artifact, normalize_artifact_path

    item = binary_artifact("assets/sprites/player.png", b"\x89PNG\r\n", "image/png")
    assert artifact_bytes(item) == b"\x89PNG\r\n"
    assert normalize_artifact_path("/assets\\sprites/player.png") == "assets/sprites/player.png"


def test_local_asset_generation_and_tilemap_are_checkpoint_safe(monkeypatch):
    from app.core.config import settings
    from app.services.artifacts import artifact_bytes
    from app.services.game_assets import generate_game_assets

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_GENERATION_MAX_ITEMS", 3)
    monkeypatch.setattr(settings, "ASSET_IMAGE_PROVIDER", "local")
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", True)
    result = generate_game_assets(
        {
            "task_id": "asset-task",
            "prompt": "a neon top down collector",
            "game_spec": {
                "title": "Neon Garden",
                "theme": "neon",
                "genre": "arcade",
                "archetype": "topdown_collect",
            },
            "game_design": {"entities": [{"role": "player", "name": "Courier"}]},
        }
    )

    paths = {item["path"] for item in result["artifacts"]}
    assert "public/assets/background.svg" in paths
    assert "public/assets/tilemap.json" in paths
    # local provider 只会给 SVG 占位图 → AI tileset 后处理失败 → 回退调色板程序化 PNG
    assert "public/assets/tileset.png" in paths
    assert all(isinstance(item.get("content") or item.get("content_b64"), str) for item in result["artifacts"])
    assert all(artifact_bytes(item) for item in result["artifacts"])


def test_vite_scaffold_uses_fixed_phaser_dependency_and_assets():
    from app.services.artifacts import binary_artifact
    from app.services.vite_projects import create_phaser_vite_project, validate_vite_project

    project = create_phaser_vite_project(
        _legacy_phaser_bundle(),
        [binary_artifact("public/assets/player.png", b"png", "image/png")],
        title="Vite Game",
    )
    by_path = {item["path"]: item for item in project}
    package = json.loads(by_path["package.json"]["content"])
    assert package["dependencies"] == {"phaser": "3.90.0"}
    assert package["devDependencies"] == {"typescript": "5.8.3", "vite": "6.4.3"}
    assert 'import Phaser from "phaser"' in by_path["game.js"]["content"]
    assert "phaser.min.js" not in by_path["index.html"]["content"]
    assert 'type="module"' in by_path["index.html"]["content"]
    assert "public/assets/player.png" in by_path
    assert validate_vite_project(project) == []


def test_vite_source_rejects_unpinned_or_extra_dependencies():
    from app.services.vite_projects import create_phaser_vite_project, validate_vite_project

    project = create_phaser_vite_project(_legacy_phaser_bundle())
    package_item = next(item for item in project if item["path"] == "package.json")
    package = json.loads(package_item["content"])
    package["dependencies"]["phaser"] = "latest"
    package["dependencies"]["left-pad"] = "1.3.0"
    package_item["content"] = json.dumps(package)
    errors = " ".join(validate_vite_project(project))
    assert "unsupported Vite dependencies" in errors
    assert "unsupported version for phaser" in errors


def test_vite_source_accepts_assets_above_old_twelve_mb_limit():
    from app.services.artifacts import binary_artifact
    from app.services.vite_projects import create_phaser_vite_project, validate_vite_project

    project = create_phaser_vite_project(
        _legacy_phaser_bundle(),
        [binary_artifact("public/assets/background.png", b"x" * 12_000_001, "image/png")],
    )

    assert validate_vite_project(project) == []


def test_vite_source_still_rejects_an_asset_above_the_relaxed_file_limit():
    from app.services.artifacts import binary_artifact
    from app.services.vite_projects import (
        MAX_PROJECT_FILE_BYTES,
        create_phaser_vite_project,
        validate_vite_project,
    )

    project = create_phaser_vite_project(
        _legacy_phaser_bundle(),
        [
            binary_artifact(
                "public/assets/background.png",
                b"x" * (MAX_PROJECT_FILE_BYTES + 1),
                "image/png",
            )
        ],
    )

    errors = " ".join(validate_vite_project(project))
    assert f"exceeds {MAX_PROJECT_FILE_BYTES} bytes" in errors


def test_modular_phaser_project_has_typed_opengame_style_boundaries():
    from app.services.phaser_projects import create_modular_phaser_project, is_modular_phaser_project
    from app.services.vite_projects import is_vite_project, validate_vite_project

    project = create_modular_phaser_project(
        {"title": "Modular Garden", "archetype": "topdown_collect"},
        {"controls": {"hint": "Collect every light"}},
        {"player_speed": 320, "target_score": 80},
        {
            "assets": [
                {"key": "hero", "kind": "image", "path": "assets/hero.png"},
                {"key": "hazard", "kind": "image", "path": "assets/hazard.png"},
            ]
        },
    )
    paths = {item["path"] for item in project}
    assert is_modular_phaser_project(project)
    assert is_vite_project(project)
    assert {
        "src/main.ts",
        "src/config/gameConfig.ts",
        "src/scenes/PlayScene.ts",
        "src/entities/Player.ts",
        "src/systems/GameState.ts",
        "src/ui/Hud.ts",
    }.issubset(paths)
    assert "tsc --noEmit" in next(item["content"] for item in project if item["path"] == "package.json")
    assert validate_vite_project(project) == []


def test_codegen_always_uses_modular_project():
    from app.agents.codegen import code_generation_node

    result = code_generation_node(
        {
            "dimension": "2d",
            "use_real": False,
            "game_spec": {"title": "Typed Run", "archetype": "lane_runner", "genre": "runner"},
            "game_design": {"controls": {"hint": "Move and survive"}},
            "balance_config": {"target_score": 60},
        }
    )
    paths = {item["path"] for item in result["project_files"]}
    assert result["artifact_format"] == "phaser-vite/v1"
    assert "src/main.ts" in paths
    assert "game.js" not in paths


def test_vite_dist_validation_accepts_hashed_nested_and_binary_files():
    from app.agents.validation import validate_files
    from app.services.artifacts import binary_artifact, text_artifact
    from app.services.vite_projects import VITE_PROJECT_FORMAT

    files = [
        text_artifact(
            "index.html",
            '<!doctype html><script type="module" src="./assets/main-a1b2.js"></script>',
        ),
        text_artifact("assets/main-a1b2.js", "requestAnimationFrame(()=>{});"),
        binary_artifact("assets/player-c3d4.png", b"\x89PNG\r\n", "image/png"),
    ]
    result = validate_files(files, bundle_type=VITE_PROJECT_FORMAT)
    assert result["valid"], result["errors"]


def test_vite_dist_validation_accepts_assets_above_old_runtime_limit():
    from app.agents.validation import validate_files
    from app.services.artifacts import binary_artifact, text_artifact
    from app.services.vite_projects import VITE_PROJECT_FORMAT

    files = [
        text_artifact("index.html", '<img src="./assets/background.png">'),
        binary_artifact("assets/background.png", b"x" * 5_000_001, "image/png"),
    ]

    result = validate_files(files, bundle_type=VITE_PROJECT_FORMAT)
    assert result["valid"], result["errors"]


def test_project_build_node_returns_dist_from_sandbox(monkeypatch):
    from app.agents.project_build import project_build_node
    from app.services import sandbox_client
    from app.services.artifacts import binary_artifact, text_artifact
    from app.services.vite_projects import VITE_PROJECT_FORMAT, create_phaser_vite_project

    project = create_phaser_vite_project(
        _legacy_phaser_bundle(),
        [binary_artifact("public/assets/source-player.png", b"source-png", "image/png")],
    )
    dist = [
        text_artifact("index.html", '<script type="module" src="./assets/main.js"></script>'),
        text_artifact("assets/main.js", "requestAnimationFrame(()=>{});"),
    ]
    monkeypatch.setattr(
        sandbox_client,
        "build_vite_project",
        lambda *_args, **_kwargs: sandbox_client.ViteBuildResult(ok=True, files=dist, duration_ms=42),
    )
    result = project_build_node(
        {"artifact_format": VITE_PROJECT_FORMAT, "project_files": project}
    )
    assert result["build_result"]["ok"] is True
    assert result["build_result"]["duration_ms"] == 42
    assert {item["path"] for item in result["generated_files"]} == {"index.html", "assets/main.js"}
    runtime_index = next(item for item in result["generated_files"] if item["path"] == "index.html")
    assert 'type="module"' not in runtime_index["content"]
    assert '<script defer src="./assets/main.js"></script>' in runtime_index["content"]


def test_prepare_vite_runtime_files_rejects_remaining_module_syntax():
    from app.services.artifacts import ArtifactError, text_artifact
    from app.services.vite_projects import prepare_vite_runtime_files

    dist = [
        text_artifact("index.html", '<script type="module" src="./assets/main.js"></script>'),
        text_artifact("assets/main.js", "import.meta.url;"),
    ]
    with pytest.raises(ArtifactError, match="module syntax"):
        prepare_vite_runtime_files(dist)


def test_sandbox_client_build_vite_supports_binary_project_files(monkeypatch):
    import httpx

    from app.core.config import settings
    from app.services import sandbox_client
    from app.services.artifacts import binary_artifact, text_artifact

    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "ok": True,
                "files": [
                    {
                        "path": "index.html",
                        "content_b64": base64.b64encode(b"<html></html>").decode("ascii"),
                        "content_type": "text/html; charset=utf-8",
                    }
                ],
                "duration_ms": 20,
            },
            request=httpx.Request("POST", "http://sandbox:8001/build/vite"),
        )

    monkeypatch.setattr(settings, "SANDBOX_URL", "http://sandbox:8001")
    monkeypatch.setattr(settings, "SANDBOX_REQUIRED", True)
    monkeypatch.setattr(sandbox_client.httpx, "post", fake_post)
    result = sandbox_client.build_vite_project(
        [text_artifact("index.html", "<html></html>"), binary_artifact("public/a.png", b"png", "image/png")]
    )
    assert result.ok is True
    sent = {item["path"]: item for item in captured["files"]}
    assert base64.b64decode(sent["public/a.png"]["content_b64"]) == b"png"


def test_publish_vite_dist_and_private_source_project(client, db_session_factory, monkeypatch):
    from app.models import User
    from app.services import packaging
    from app.services.artifacts import binary_artifact, text_artifact
    from app.services.vite_projects import VITE_PROJECT_FORMAT, create_phaser_vite_project
    from app.storage import s3

    client.post(
        "/auth/register",
        json={"email": "vite-publish@test.com", "password": "secret1", "display_name": "VP"},
    )
    db = db_session_factory()
    user_id = db.query(User).filter_by(email="vite-publish@test.com").one().id
    db.close()
    captured: dict[str, bytes] = {}

    def capture(key, body, _content_type):
        captured[key] = body if isinstance(body, bytes) else body.encode("utf-8")
        return key

    monkeypatch.setattr(s3, "put_object", capture)
    monkeypatch.setattr("app.db.session.SessionLocal", db_session_factory)
    project = create_phaser_vite_project(
        _legacy_phaser_bundle(),
        [binary_artifact("public/assets/source-player.png", b"source-png", "image/png")],
    )
    dist = [
        text_artifact("index.html", '<script type="module" src="./assets/main.js"></script>'),
        text_artifact("assets/main.js", "requestAnimationFrame(()=>{});"),
        binary_artifact("assets/player.png", b"png", "image/png"),
    ]
    game_id, _, _ = packaging.publish_generated(
        {
            "task_id": "vite-publish-task",
            "user_id": user_id,
            "game_spec": {"title": "Vite Publish", "genre": "arcade", "tags": []},
            "generated_files": dist,
            "project_files": project,
            "artifact_format": VITE_PROJECT_FORMAT,
            "build_result": {"ok": True, "duration_ms": 10},
            "dimension": "2d",
        }
    )

    runtime_prefix = f"games/{game_id}/v1"
    source_prefix = f"game-sources/{game_id}/v1"
    assert captured[f"{runtime_prefix}/assets/player.png"] == b"png"
    assert f"{source_prefix}/package.json" in captured
    manifest = json.loads(captured[f"{runtime_prefix}/manifest.json"])
    assert manifest["runtime"] == "phaser-vite-dist"
    assert manifest["artifact_format"] == VITE_PROJECT_FORMAT
    assert any(item["path"] == "assets/main.js" for item in manifest["files"])

    monkeypatch.setattr(s3, "get_object", lambda key: captured.get(key))
    from app.agents.pipeline import _load_revision_files

    source_files = _load_revision_files(game_id, "v1")
    source_by_path = {item["path"]: item for item in source_files}
    assert 'import Phaser from "phaser"' in source_by_path["game.js"]["content"]
    assert base64.b64decode(source_by_path["public/assets/source-player.png"]["content_b64"]) == b"source-png"
