from app.models import Game, User
from app.models.common import GameSource, GameStatus, now_utc


def _seed_game(factory, title="Soc Game"):
    db = factory()
    user = User(email=f"{title}@s.com", display_name="Auth", avatar_initial="A")
    db.add(user)
    db.flush()
    g = Game(
        author_id=user.id, title=title, summary="s", genre="arcade",
        status=GameStatus.PUBLISHED, current_version="v1", source=GameSource.SEED,
        plays_count=1, published_at=now_utc(),
    )
    db.add(g)
    db.commit()
    gid, uid = g.id, user.id
    db.close()
    return gid, uid


def _auth(client, email="c@c.com"):
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "secret1", "display_name": "C"},
    ).json()
    return {"Authorization": f"Bearer {r['token']}"}, r["user"]["id"]


def test_author_profile_and_games(client, db_session_factory):
    gid, uid = _seed_game(db_session_factory)
    profile = client.get(f"/users/{uid}")
    assert profile.status_code == 200
    assert profile.json()["game_count"] == 1
    games = client.get(f"/users/{uid}/games").json()["items"]
    assert any(item["id"] == gid for item in games)


def test_comments_flow(client, db_session_factory):
    gid, _ = _seed_game(db_session_factory)
    h, _ = _auth(client)
    r = client.post(f"/games/{gid}/comments", json={"body": "nice game"}, headers=h)
    assert r.status_code == 200
    cid = r.json()["id"]
    assert client.get(f"/games/{gid}/comments").json()["items"][0]["body"] == "nice game"
    assert client.delete(f"/games/{gid}/comments/{cid}", headers=h).status_code == 200


def test_follow_flow(client, db_session_factory):
    _, target = _seed_game(db_session_factory)
    h, _ = _auth(client)
    assert client.post(f"/users/{target}/follow", headers=h).json()["following"] is True
    assert client.get(f"/users/{target}", headers=h).json()["followers"] == 1
    assert client.delete(f"/users/{target}/follow", headers=h).json()["following"] is False


def test_cannot_follow_self(client):
    h, me = _auth(client)
    assert client.post(f"/users/{me}/follow", headers=h).status_code == 400


def test_score_and_leaderboard(client, db_session_factory):
    gid, _ = _seed_game(db_session_factory)
    client.post(f"/games/{gid}/score", json={"points": 50, "player_name": "Zoe"})
    client.post(f"/games/{gid}/score", json={"points": 90, "player_name": "Max"})
    lb = client.get(f"/games/{gid}/leaderboard").json()["items"]
    assert lb[0]["name"] == "Max"
    assert lb[0]["rank"] == 1
    assert lb[0]["points"] == 90


def test_related_excludes_self(client, db_session_factory):
    gid, _ = _seed_game(db_session_factory, title="Base")
    _seed_game(db_session_factory, title="Other")
    r = client.get(f"/games/{gid}/related")
    assert r.status_code == 200
    assert all(item["id"] != gid for item in r.json()["items"])
