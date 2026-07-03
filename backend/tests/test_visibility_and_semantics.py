"""第二批语义回归：可见性矩阵、预览不计数、is_active 全局生效、删除清理 OSS。"""
from app.models import Game, User
from app.models.common import GameSource, GameStatus, now_utc


def _auth(client, email="v@v.com", name="V"):
    reg = client.post(
        "/auth/register",
        json={"email": email, "password": "secret1", "display_name": name},
    ).json()
    return {"Authorization": f"Bearer {reg['token']}"}, reg["user"]["id"]


def _game(factory, author_id, status, title="Vis Game"):
    db = factory()
    g = Game(
        author_id=author_id,
        title=title,
        summary="s",
        genre="arcade",
        status=status,
        current_version="v1",
        source=GameSource.CREATE,
        plays_count=0,
        published_at=now_utc() if status == GameStatus.PUBLISHED else None,
    )
    db.add(g)
    db.commit()
    gid = g.id
    db.close()
    return gid


def test_draft_subresources_hidden_from_non_author(client, db_session_factory):
    """draft/preview 的评论、排行、计分、manifest、play、related 与详情页同一条可见性规则。"""
    author_h, author_id = _auth(client, email="author@v.com", name="A")
    other_h, _ = _auth(client, email="other@v.com", name="B")
    gid = _game(db_session_factory, author_id, GameStatus.PREVIEW)

    reads = [f"/games/{gid}/comments", f"/games/{gid}/leaderboard", f"/games/{gid}/manifest", f"/games/{gid}/related"]
    for path in reads:
        assert client.get(path, headers=other_h).status_code == 404, path
        assert client.get(path).status_code == 404, path  # 匿名
        assert client.get(path, headers=author_h).status_code == 200, path

    assert client.post(f"/games/{gid}/comments", json={"body": "hi"}, headers=other_h).status_code == 404
    assert client.post(f"/games/{gid}/score", json={"points": 10}, headers=other_h).status_code == 404
    assert client.post(f"/games/{gid}/play", headers=other_h).status_code == 404
    assert client.post(f"/games/{gid}/comments", json={"body": "hi"}, headers=author_h).status_code == 200


def test_author_preview_play_not_counted(client, db_session_factory):
    author_h, author_id = _auth(client, email="prev@v.com", name="P")
    gid = _game(db_session_factory, author_id, GameStatus.PREVIEW)
    r = client.post(f"/games/{gid}/play", headers=author_h).json()
    assert r["counted"] is False
    db = db_session_factory()
    assert db.get(Game, gid).plays_count == 0
    db.close()


def test_disabled_account_rejected_globally(client, db_session_factory):
    h, uid = _auth(client, email="dis@v.com", name="D")
    db = db_session_factory()
    db.get(User, uid).is_active = False
    db.commit()
    db.close()
    # 持仍然有效的旧 JWT：受保护端点一律 403，"禁用"不再只在密码登录时生效
    assert client.get("/auth/me", headers=h).status_code == 403
    assert client.get("/tasks", headers=h).status_code == 403


def test_delete_game_cleans_object_storage(client, db_session_factory, monkeypatch):
    from app.api.routers import games as games_router

    author_h, author_id = _auth(client, email="del@v.com", name="Del")
    gid = _game(db_session_factory, author_id, GameStatus.PUBLISHED)
    deleted_prefixes: list[str] = []
    monkeypatch.setattr(games_router.s3, "delete_prefix", lambda p: deleted_prefixes.append(p) or 1)

    assert client.delete(f"/games/{gid}", headers=author_h).status_code == 200
    assert deleted_prefixes == [f"games/{gid}/"]


def test_like_unlike_roundtrip_consistent(client, db_session_factory):
    _, author_id = _auth(client, email="lk-a@v.com", name="LA")
    gid = _game(db_session_factory, author_id, GameStatus.PUBLISHED)
    h, _ = _auth(client, email="lk@v.com", name="L")
    assert client.post(f"/games/{gid}/like", headers=h).json()["likes"] == 1
    assert client.post(f"/games/{gid}/like", headers=h).json()["likes"] == 1  # 幂等
    assert client.delete(f"/games/{gid}/like", headers=h).json()["likes"] == 0
    assert client.delete(f"/games/{gid}/like", headers=h).json()["likes"] == 0  # 双删不为负
