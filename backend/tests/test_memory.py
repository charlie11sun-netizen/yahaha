def _auth(client, email="mem@test.com"):
    token = client.post(
        "/auth/register",
        json={"email": email, "password": "secret1", "display_name": "Mem"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_memory_settings_defaults_and_update(client):
    headers = _auth(client)

    defaults = client.get("/memory/settings", headers=headers)
    assert defaults.status_code == 200
    assert defaults.json()["enabled"] is True
    assert defaults.json()["allow_cross_game_memory"] is True

    updated = client.patch(
        "/memory/settings",
        json={"enabled": False, "allow_memory_extraction": False},
        headers=headers,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["enabled"] is False
    assert body["allow_memory_extraction"] is False


def test_manual_memory_crud_and_user_isolation(client):
    h1 = _auth(client, "a@test.com")
    h2 = _auth(client, "b@test.com")

    created = client.post(
        "/memory",
        json={
            "scope_type": "user",
            "category": "style",
            "raw_text": "I prefer pixel art and medium difficulty.",
            "importance": 4,
            "pinned": True,
        },
        headers=h1,
    )
    assert created.status_code == 200
    item = created.json()
    assert item["scope_type"] == "user"
    assert item["pinned"] is True

    assert client.get("/memory", headers=h1).json()["items"][0]["id"] == item["id"]
    assert client.get("/memory", headers=h2).json()["items"] == []

    deleted = client.delete(f"/memory/{item['id']}", headers=h1)
    assert deleted.status_code == 200
    assert client.get("/memory", headers=h1).json()["items"] == []
    deleted_items = client.get("/memory?status=deleted", headers=h1).json()["items"]
    assert deleted_items[0]["id"] == item["id"]


def test_retrieve_memories_prefers_game_scope(db_session_factory):
    from app.models import Game, MemoryItem, MemorySettings, User
    from app.models.common import GameSource, GameStatus
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource, MemoryStatus
    from app.services.memory import retrieve_memories

    db = db_session_factory()
    user = User(email="rank@test.com", password_hash="x", display_name="Rank", avatar_initial="R")
    db.add(user)
    db.flush()
    game = Game(
        author_id=user.id,
        title="G",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
    )
    db.add(game)
    db.flush()
    db.add(MemorySettings(user_id=user.id))
    db.add_all([
        MemoryItem(
            user_id=user.id,
            scope_type=MemoryScope.USER,
            category=MemoryCategory.STYLE,
            raw_text="Prefer pixel art for games.",
            source_type=MemorySource.MANUAL,
            status=MemoryStatus.ACTIVE,
            importance=5,
            confidence=1,
            pinned=True,
        ),
        MemoryItem(
            user_id=user.id,
            scope_type=MemoryScope.GAME,
            scope_id=game.id,
            category=MemoryCategory.CONTROLS,
            raw_text="For this game, jump should feel lighter.",
            source_type=MemorySource.FEEDBACK,
            status=MemoryStatus.ACTIVE,
            importance=4,
            confidence=1,
            pinned=False,
        ),
    ])
    db.commit()

    items = retrieve_memories(
        db,
        user_id=user.id,
        query="make jump lighter",
        game_id=game.id,
        categories=["style", "controls"],
    )
    assert items[0]["scope_type"] == "game"
    assert "jump" in items[0]["raw_text"]
    db.close()


def test_memory_capture_revision_feedback_and_respects_disabled_setting(db_session_factory):
    from app.models import Game, GenerationTask, MemorySettings, User
    from app.models.common import GameSource, GameStatus, TaskStatus
    from app.services.memory import capture_success_memories

    db = db_session_factory()
    user = User(email="capture@test.com", password_hash="x", display_name="Cap", avatar_initial="C")
    db.add(user)
    db.flush()
    game = Game(
        author_id=user.id,
        title="Cap Game",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
    )
    db.add(game)
    db.flush()
    task = GenerationTask(
        user_id=user.id,
        idea="arcade",
        task_kind="revision",
        base_game_id=game.id,
        base_version="v1",
        result_game_id=game.id,
        feedback_text="跳跃要更轻快，但不要明显跳得更高。",
        status=TaskStatus.SUCCEEDED,
    )
    db.add(task)
    db.commit()

    created = capture_success_memories(
        db,
        task_id=task.id,
        state={"task_kind": "revision", "game_id": game.id, "feedback_brief": "Keep jump height while improving feel."},
    )
    db.commit()
    assert len(created) == 1
    assert created[0].scope_type == "game"
    assert created[0].scope_id == game.id
    assert created[0].extracted_text == "Keep jump height while improving feel."

    disabled_user = User(email="disabled@test.com", password_hash="x", display_name="Dis", avatar_initial="D")
    db.add(disabled_user)
    db.flush()
    db.add(MemorySettings(user_id=disabled_user.id, enabled=False))
    disabled_task = GenerationTask(
        user_id=disabled_user.id,
        idea="arcade",
        task_kind="revision",
        base_game_id=game.id,
        base_version="v1",
        feedback_text="make it faster",
        status=TaskStatus.SUCCEEDED,
    )
    db.add(disabled_task)
    db.commit()
    assert capture_success_memories(db, task_id=disabled_task.id, state={"task_kind": "revision", "game_id": game.id}) == []
    db.close()


def test_rrf_rewards_results_found_by_both_rankers():
    from app.services.memory import _rrf_scores

    scores, ranks = _rrf_scores(
        [
            ("lexical", ["both", "lexical-only"], 1.0),
            ("semantic", ["semantic-only", "both"], 1.0),
        ],
        k=60,
    )

    assert scores["both"] > scores["lexical-only"]
    assert scores["both"] > scores["semantic-only"]
    assert ranks["both"] == {"lexical": 1, "semantic": 2}


def test_memory_write_persists_embedding_metadata(db_session_factory, monkeypatch):
    from app.models import User
    from app.models.memory import MemoryCategory, MemoryScope
    from app.services import memory_embeddings
    from app.services.memory import create_memory

    monkeypatch.setattr(memory_embeddings, "embedding_model", lambda: "test-embedding")
    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: [[0.25, 0.75]])
    db = db_session_factory()
    user = User(email="embed@test.com", password_hash="x", display_name="Embed", avatar_initial="E")
    db.add(user)
    db.flush()

    item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.USER,
        scope_id=None,
        category=MemoryCategory.STYLE,
        raw_text="偏好明亮的像素美术",
    )

    assert item.embedding == [0.25, 0.75]
    assert item.embedding_model == "test-embedding"
    assert item.embedding_updated_at is not None
    db.close()


def test_hybrid_retrieval_uses_semantic_rank_and_lazy_backfill(db_session_factory, monkeypatch):
    from app.models import MemoryItem, MemorySettings, User
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource, MemoryStatus
    from app.services import memory_embeddings
    from app.services.memory import retrieve_memories

    monkeypatch.setattr(memory_embeddings, "embedding_model", lambda: "test-embedding")
    monkeypatch.setattr(
        memory_embeddings,
        "embed_texts",
        lambda texts: [[1.0, 0.0], *[[0.0, 1.0] for _ in texts[1:]]],
    )

    db = db_session_factory()
    user = User(email="hybrid@test.com", password_hash="x", display_name="Hybrid", avatar_initial="H")
    db.add(user)
    db.flush()
    db.add(MemorySettings(user_id=user.id))
    semantic = MemoryItem(
        user_id=user.id,
        scope_type=MemoryScope.USER,
        category=MemoryCategory.CONTROLS,
        raw_text="降低重力并缩短起跳前摇",
        source_type=MemorySource.MANUAL,
        status=MemoryStatus.ACTIVE,
        importance=3,
        confidence=1,
        pinned=False,
        embedding=[1.0, 0.0],
        embedding_model="test-embedding",
    )
    lexical_baseline = MemoryItem(
        user_id=user.id,
        scope_type=MemoryScope.USER,
        category=MemoryCategory.STYLE,
        raw_text="像素美术风格",
        source_type=MemorySource.MANUAL,
        status=MemoryStatus.ACTIVE,
        importance=5,
        confidence=1,
        pinned=True,
        embedding=[0.0, 1.0],
        embedding_model="test-embedding",
    )
    stale = MemoryItem(
        user_id=user.id,
        scope_type=MemoryScope.USER,
        category=MemoryCategory.DIFFICULTY,
        raw_text="保持中等难度",
        source_type=MemorySource.MANUAL,
        status=MemoryStatus.ACTIVE,
        importance=2,
        confidence=1,
        pinned=False,
    )
    db.add_all([semantic, lexical_baseline, stale])
    db.commit()

    items = retrieve_memories(db, user_id=user.id, query="让跳跃手感更轻快", limit=3)

    assert items[0]["id"] == semantic.id
    assert items[0]["retrieval"]["strategy"] == "rrf_hybrid"
    assert items[0]["retrieval"]["semantic_rank"] == 1
    assert stale.embedding == [0.0, 1.0]
    assert stale.embedding_model == "test-embedding"
    db.close()


def test_hybrid_retrieval_falls_back_to_lexical(db_session_factory, monkeypatch):
    from app.models import MemoryItem, MemorySettings, User
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource, MemoryStatus
    from app.services import memory_embeddings
    from app.services.memory import retrieve_memories

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user = User(email="fallback@test.com", password_hash="x", display_name="Fallback", avatar_initial="F")
    db.add(user)
    db.flush()
    db.add(MemorySettings(user_id=user.id))
    db.add_all([
        MemoryItem(
            user_id=user.id,
            scope_type=MemoryScope.USER,
            category=MemoryCategory.CONTROLS,
            raw_text="jump should feel lighter",
            source_type=MemorySource.MANUAL,
            status=MemoryStatus.ACTIVE,
            importance=3,
            confidence=1,
            pinned=False,
        ),
        MemoryItem(
            user_id=user.id,
            scope_type=MemoryScope.USER,
            category=MemoryCategory.STYLE,
            raw_text="prefer pixel art",
            source_type=MemorySource.MANUAL,
            status=MemoryStatus.ACTIVE,
            importance=3,
            confidence=1,
            pinned=False,
        ),
    ])
    db.commit()

    items = retrieve_memories(db, user_id=user.id, query="lighter jump", limit=2)

    assert "jump" in items[0]["raw_text"]
    assert items[0]["retrieval"]["strategy"] == "lexical_fallback"
    assert items[0]["retrieval"]["semantic_rank"] is None
    db.close()
