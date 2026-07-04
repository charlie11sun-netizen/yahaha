from app.core.config import settings
from app.models import Game, GameVersion, User
from app.models.common import GameSource, GameStatus, now_utc


def _seed_game(factory, title="Test Game", status=GameStatus.PUBLISHED, plays=5, author_id=None):
    db = factory()
    if author_id is None:
        user = User(email=f"{title}@seed.com", display_name="Author", avatar_initial="A")
        db.add(user)
        db.flush()
        author_id = user.id
    g = Game(
        author_id=author_id,
        title=title,
        summary="a summary",
        genre="arcade",
        status=status,
        current_version="v1",
        source=GameSource.SEED,
        plays_count=plays,
        published_at=now_utc(),
    )
    db.add(g)
    db.flush()
    db.add(
        GameVersion(
            game_id=g.id,
            version="v1",
            manifest_key=f"games/{g.id}/v1/manifest.json",
            bundle_key=f"games/{g.id}/v1/index.html",
            sha256="sha-v1",
            size_bytes=111,
        )
    )
    db.commit()
    gid = g.id
    db.close()
    return gid


def _auth(client, email="o@o.com"):
    reg = client.post(
        "/auth/register",
        json={"email": email, "password": "secret1", "display_name": "O"},
    ).json()
    return {"Authorization": f"Bearer {reg['token']}"}, reg["user"]["id"]


def test_list_pagination(client, db_session_factory):
    for i in range(3):
        _seed_game(db_session_factory, title=f"G{i}")
    r = client.get("/games?limit=2")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["has_more"] is True
    page2 = client.get("/games?limit=2&offset=2").json()
    assert len(page2["items"]) == 1
    assert page2["has_more"] is False


def test_get_game(client, db_session_factory):
    gid = _seed_game(db_session_factory)
    assert client.get(f"/games/{gid}").json()["id"] == gid


def test_play_dedup(client, db_session_factory):
    gid = _seed_game(db_session_factory, plays=0)
    assert client.post(f"/games/{gid}/play").json()["counted"] is True
    h, _ = _auth(client, email="p@p.com")
    assert client.post(f"/games/{gid}/play", headers=h).json()["counted"] is True
    assert client.post(f"/games/{gid}/play", headers=h).json()["counted"] is False


def test_owner_manage_game(client, db_session_factory):
    h, uid = _auth(client)
    gid = _seed_game(db_session_factory, title="Mine", author_id=uid)
    assert client.post(f"/games/{gid}/unpublish", headers=h).status_code == 200
    assert client.patch(f"/games/{gid}", json={"title": "Renamed"}, headers=h).json()["title"] == "Renamed"
    assert client.delete(f"/games/{gid}", headers=h).status_code == 200
    assert client.get(f"/games/{gid}").status_code == 404


def test_non_owner_cannot_delete(client, db_session_factory):
    gid = _seed_game(db_session_factory, title="NotMine")
    h, _ = _auth(client, email="x@x.com")
    assert client.delete(f"/games/{gid}", headers=h).status_code == 403


def test_manifest_endpoint(client, db_session_factory):
    gid = _seed_game(db_session_factory)
    r = client.get(f"/games/{gid}/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["entry"] == "index.html"
    assert body["_source"] == "oss"


def test_owner_can_list_and_activate_versions(client, db_session_factory):
    h, uid = _auth(client, email="versions@x.com")
    gid = _seed_game(db_session_factory, title="Versioned", author_id=uid)
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
    gid = _seed_game(db_session_factory, title="Foreign")
    h, _ = _auth(client, email="stranger@x.com")
    assert client.get(f"/games/{gid}/versions", headers=h).status_code == 403
    assert client.post(f"/games/{gid}/versions/v1/activate", headers=h).status_code == 403


def test_public_browse_gate_allows_read_and_play_only(client, db_session_factory, monkeypatch):
    gid = _seed_game(db_session_factory, title="PublicBrowse")
    monkeypatch.setattr(settings, "SITE_PASSWORD", "secret")
    monkeypatch.setattr(settings, "GATE_PUBLIC_BROWSE", True)

    assert client.get("/games").status_code == 200
    assert client.get(f"/games/{gid}").status_code == 200
    assert client.post(f"/games/{gid}/play").status_code == 200
    assert client.get("/tasks").status_code == 401
