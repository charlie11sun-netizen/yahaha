import json
from urllib.parse import urlsplit

from conftest import auth_user, seed_game

from app.core.config import settings
from app.models import GameVersion
from app.models.common import GameStatus


def test_list_pagination(client, db_session_factory):
    for i in range(3):
        seed_game(db_session_factory, title=f"G{i}")
    r = client.get("/games?limit=2")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["has_more"] is True
    page2 = client.get("/games?limit=2&offset=2").json()
    assert len(page2["items"]) == 1
    assert page2["has_more"] is False


def test_my_games_paginates(client, db_session_factory):
    h, uid = auth_user(client, email="my-games-page@test.com", display_name="O")
    for i in range(3):
        seed_game(db_session_factory, title=f"MyPaged{i}", author_id=uid)
    data = client.get("/me/games?limit=2", headers=h).json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["has_more"] is True
    page2 = client.get("/me/games?limit=2&offset=2", headers=h).json()
    assert len(page2["items"]) == 1
    assert page2["has_more"] is False


def test_get_game(client, db_session_factory):
    gid = seed_game(db_session_factory)
    assert client.get(f"/games/{gid}").json()["id"] == gid


def test_play_dedup(client, db_session_factory):
    gid = seed_game(db_session_factory, plays=0)
    assert client.post(f"/games/{gid}/play").json()["counted"] is True
    h, _ = auth_user(client, email="p@p.com", display_name="O")
    assert client.post(f"/games/{gid}/play", headers=h).json()["counted"] is True
    assert client.post(f"/games/{gid}/play", headers=h).json()["counted"] is False


def test_owner_manage_game(client, db_session_factory):
    h, uid = auth_user(client, email="o@o.com", display_name="O")
    gid = seed_game(db_session_factory, title="Mine", author_id=uid)
    assert client.post(f"/games/{gid}/unpublish", headers=h).status_code == 200
    assert client.patch(f"/games/{gid}", json={"title": "Renamed"}, headers=h).json()["title"] == "Renamed"
    assert client.delete(f"/games/{gid}", headers=h).status_code == 200
    assert client.get(f"/games/{gid}").status_code == 404


def test_non_owner_cannot_delete(client, db_session_factory):
    gid = seed_game(db_session_factory, title="NotMine")
    h, _ = auth_user(client, email="x@x.com", display_name="O")
    assert client.delete(f"/games/{gid}", headers=h).status_code == 403


def test_manifest_endpoint(client, db_session_factory):
    gid = seed_game(db_session_factory)
    r = client.get(f"/games/{gid}/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["entry"] == "index.html"
    assert body["_source"] == "oss"


def test_manifest_returns_tokenized_api_file_urls(client, db_session_factory, monkeypatch):
    h, uid = auth_user(client, email="private-preview@test.com", display_name="O")
    gid = seed_game(db_session_factory, title="PrivatePreview", status=GameStatus.PREVIEW, author_id=uid)

    def fake_get_object(key):
        if key.endswith("/manifest.json"):
            return json.dumps(
                {
                    "entry": "index.html",
                    "runtime": "iframe-html",
                    "entry_url": "https://oss.test/leaked/index.html",
                    "files": [{"path": "game.js", "url": "https://oss.test/leaked/game.js"}],
                }
            ).encode("utf-8")
        if key.endswith("/index.html"):
            return b"<!doctype html><script src=\"game.js\"></script>"
        if key.endswith("/game.js"):
            return b"console.log('ok')"
        return None

    monkeypatch.setattr("app.services.game_actions.s3.get_object", fake_get_object)
    response = client.get(f"/games/{gid}/manifest", headers=h)

    assert response.status_code == 200
    manifest = response.json()
    assert "oss.test" not in manifest["entry_url"]
    assert f"/games/{gid}/files/" in manifest["entry_url"]
    assert "oss.test" not in manifest["files"][0]["url"]
    assert f"/games/{gid}/files/" in manifest["files"][0]["url"]

    entry_path = urlsplit(manifest["entry_url"]).path
    monkeypatch.setattr(settings, "SITE_PASSWORD", "secret")
    monkeypatch.setattr(settings, "GATE_PUBLIC_BROWSE", False)
    entry_response = client.get(entry_path)
    assert entry_response.status_code == 200
    assert "text/html" in entry_response.headers["content-type"]
    assert "X-Frame-Options" not in entry_response.headers

    parts = entry_path.split("/")
    parts[4] = "bad-token"
    assert client.get("/".join(parts)).status_code == 403


def test_owner_can_list_and_activate_versions(client, db_session_factory):
    h, uid = auth_user(client, email="versions@x.com", display_name="O")
    gid = seed_game(db_session_factory, title="Versioned", author_id=uid)
    db = db_session_factory()
    db.add(
        GameVersion(
            game_id=gid,
            version="v2",
            manifest_key=f"games/{gid}/v2/manifest.json",
            bundle_key=f"games/{gid}/v2/index.html",
            sha256="sha-v2",
            size_bytes=222,
        )
    )
    db.commit()
    db.close()

    listed = client.get(f"/games/{gid}/versions", headers=h)
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()["items"]] == ["v2", "v1"]

    activated = client.post(f"/games/{gid}/versions/v2/activate", headers=h)
    assert activated.status_code == 200
    assert activated.json()["version"] == "v2"
    assert client.get(f"/games/{gid}/manifest?version=v1", headers=h).status_code == 200
    assert client.get(f"/games/{gid}/manifest?version=v1").status_code == 403


def test_non_owner_cannot_manage_versions(client, db_session_factory):
    gid = seed_game(db_session_factory, title="Foreign")
    h, _ = auth_user(client, email="stranger@x.com", display_name="O")
    assert client.get(f"/games/{gid}/versions", headers=h).status_code == 403
    assert client.post(f"/games/{gid}/versions/v1/activate", headers=h).status_code == 403


def test_public_browse_gate_allows_read_and_play_only(client, db_session_factory, monkeypatch):
    gid = seed_game(db_session_factory, title="PublicBrowse")
    monkeypatch.setattr(settings, "SITE_PASSWORD", "secret")
    monkeypatch.setattr(settings, "GATE_PUBLIC_BROWSE", True)

    assert client.get("/games").status_code == 200
    assert client.get(f"/games/{gid}").status_code == 200
    assert client.post(f"/games/{gid}/play").status_code == 200
    assert client.get("/tasks").status_code == 401
