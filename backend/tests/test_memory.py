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


def test_profile_extraction_splits_global_and_game_scope(db_session_factory, monkeypatch):
    from app.models import Game, User
    from app.models.common import GameSource, GameStatus
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user = User(email="scope@test.com", password_hash="x", display_name="Scope", avatar_initial="S")
    db.add(user)
    db.flush()
    game = Game(
        author_id=user.id,
        title="Scope Game",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
    )
    db.add(game)
    db.flush()
    item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="以后默认写实风，但这个项目继续用像素风",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )

    profiles = reconcile_memory_item(db, item, game_id=game.id)

    assert len(profiles) == 2
    assert {(profile.scope_type, profile.value_text) for profile in profiles} == {
        (MemoryScope.USER, "realistic"),
        (MemoryScope.GAME, "pixel"),
    }
    assert all(profile.status == "active" for profile in profiles)
    db.close()


def test_profile_explicit_conflict_supersedes_in_same_scope(db_session_factory, monkeypatch):
    from app.models import User
    from app.models.memory import MemoryCategory, MemoryScope, MemoryStatus
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import profile_history, reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user = User(email="conflict@test.com", password_hash="x", display_name="Conflict", avatar_initial="C")
    db.add(user)
    db.flush()
    old_item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.USER,
        scope_id=None,
        category=MemoryCategory.STYLE,
        raw_text="以后默认使用像素风",
    )
    old_profile = reconcile_memory_item(db, old_item)[0]
    new_item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.USER,
        scope_id=None,
        category=MemoryCategory.STYLE,
        raw_text="以后默认不要像素风，改成写实风",
    )
    new_profile = reconcile_memory_item(db, new_item)[0]
    db.flush()

    assert old_profile.status == "superseded"
    assert old_item.status == MemoryStatus.SUPERSEDED
    assert new_profile.status == "active"
    assert new_profile.value_text == "realistic"
    assert new_item.supersedes_id == old_item.id
    assert {version.operation for version in profile_history(db, old_profile.id)} == {"created", "superseded"}
    db.close()


def test_ambiguous_profile_conflict_auto_promotes_after_repeated_support(db_session_factory, monkeypatch):
    from app.models import Game, User
    from app.models.common import GameSource, GameStatus
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import profile_history, reconcile_memory_item, retrieve_profiles

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user = User(email="pending@test.com", password_hash="x", display_name="Pending", avatar_initial="P")
    db.add(user)
    db.flush()
    game = Game(
        author_id=user.id,
        title="Pending Game",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
    )
    db.add(game)
    db.flush()
    old_item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="这个游戏使用像素风",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    old_profile = reconcile_memory_item(db, old_item, game_id=game.id)[0]
    candidate_item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="这个游戏能不能试试写实风",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    candidate = reconcile_memory_item(db, candidate_item, game_id=game.id)[0]
    db.flush()

    assert candidate.status == "candidate"
    assert candidate.conflicts_with_id == old_profile.id
    assert [item["id"] for item in retrieve_profiles(db, user_id=user.id, game_id=game.id)] == [old_profile.id]

    candidate_item_2 = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="Could we use realistic visual style for this game?",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    candidate_2 = reconcile_memory_item(db, candidate_item_2, game_id=game.id)[0]
    assert candidate_2.id == candidate.id
    assert candidate.status == "candidate"
    assert candidate.support_count == 2

    candidate_item_3 = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="Maybe a realistic visual style would fit this game.",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    candidate_3 = reconcile_memory_item(db, candidate_item_3, game_id=game.id)[0]
    db.flush()

    assert candidate_3.id == candidate.id
    assert candidate.status == "active"
    assert candidate.explicitness == "inferred"
    assert candidate.support_count == 3
    assert old_profile.status == "superseded"
    assert [item["id"] for item in retrieve_profiles(db, user_id=user.id, game_id=game.id)] == [candidate.id]
    assert "auto_promoted" in {version.operation for version in profile_history(db, candidate.id)}
    db.close()


def test_memory_profile_api_history_and_user_isolation(client):
    h1 = _auth(client, "profile-a@test.com")
    h2 = _auth(client, "profile-b@test.com")
    created = client.post(
        "/memory",
        json={
            "scope_type": "user",
            "category": "style",
            "raw_text": "I prefer pixel art by default.",
        },
        headers=h1,
    )
    assert created.status_code == 200

    profiles = client.get("/memory/profiles", headers=h1)
    assert profiles.status_code == 200
    profile = profiles.json()["items"][0]
    assert profile["profile_key"] == "visual_style"
    assert profile["status"] == "active"
    assert client.get("/memory/profiles", headers=h2).json()["items"] == []

    corrected = client.patch(
        f"/memory/profiles/{profile['id']}",
        json={"summary_text": "I prefer restrained pixel art by default."},
        headers=h1,
    )
    assert corrected.status_code == 200
    assert corrected.json()["explicitness"] == "manual"
    assert corrected.json()["version"] == 2
    active_evidence = client.get("/memory", headers=h1).json()["items"]
    assert [item["raw_text"] for item in active_evidence] == ["I prefer restrained pixel art by default."]

    history = client.get(f"/memory/profiles/{profile['id']}/history", headers=h1)
    assert history.status_code == 200
    assert [item["operation"] for item in history.json()["items"]] == ["corrected", "created"]
    assert client.get(f"/memory/profiles/{profile['id']}/history", headers=h2).status_code == 404


def test_create_memories_batch_embeds_all_evidence_once(db_session_factory, monkeypatch):
    from app.models import User
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memories_batch

    calls = []

    def fake_embed(texts):
        calls.append(list(texts))
        return [[float(index), 1.0] for index, _ in enumerate(texts)]

    monkeypatch.setattr(memory_embeddings, "embedding_model", lambda: "batch-embedding")
    monkeypatch.setattr(memory_embeddings, "embed_texts", fake_embed)
    db = db_session_factory()
    user = User(email="batch@test.com", password_hash="x", display_name="Batch", avatar_initial="B")
    db.add(user)
    db.flush()

    items = create_memories_batch(
        db,
        user.id,
        [
            {
                "scope_type": MemoryScope.USER,
                "category": MemoryCategory.STYLE,
                "raw_text": "以后默认使用像素风",
                "source_type": MemorySource.FEEDBACK,
            },
            {
                "scope_type": MemoryScope.USER,
                "category": MemoryCategory.DIFFICULTY,
                "raw_text": "以后默认保持中等难度",
                "source_type": MemorySource.FEEDBACK,
            },
        ],
    )

    assert len(calls) == 1
    assert len(calls[0]) == 2
    assert [item.embedding for item in items] == [[0.0, 1.0], [1.0, 1.0]]
    assert all(item.embedding_model == "batch-embedding" for item in items)
    db.close()


def test_success_memory_batch_uses_small_model_with_profiles_and_user_messages(
    db_session_factory, monkeypatch
):
    import json
    from datetime import datetime, timedelta, timezone

    from app.agents import llm
    from app.core.config import settings
    from app.models import Game, GenerationTask, MemoryEntityLink, MemoryProfile, User
    from app.models.common import GameSource, GameStatus, TaskStatus
    from app.models.memory import MemoryCategory, MemoryScope
    from app.services import memory_embeddings
    from app.services.memory import capture_success_memories, create_memory
    from app.services.memory_profiles import reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_MODEL", "small-memory-model")
    calls = []

    def fake_chat(system, user, **kwargs):
        payload = json.loads(user)
        calls.append((system, payload, kwargs))
        evidence = payload["current_evidence"][0]
        return json.dumps(
            {
                "claims": [
                    {
                        "source_memory_id": evidence["source_memory_id"],
                        "decision": "active",
                        "profile_key": "jump_feel",
                        "category": "controls",
                        "value_text": "lighter",
                        "summary_text": "跳跃应更轻快但不明显增加高度",
                        "evidence_span": "跳跃要更轻快，但不要明显跳得更高。",
                        "suggested_scope": "game",
                        "explicitness": "explicit",
                        "confidence": 0.9,
                        "entities": [{"type": "control", "name": "跳跃"}],
                    }
                ]
            },
            ensure_ascii=False,
        ), 42

    monkeypatch.setattr(llm, "chat", fake_chat)
    db = db_session_factory()
    user = User(email="context@test.com", password_hash="x", display_name="Context", avatar_initial="C")
    db.add(user)
    db.flush()
    game = Game(
        author_id=user.id,
        title="Context Game",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v2",
    )
    db.add(game)
    db.flush()
    source = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="这个游戏保持像素风",
        source_game_id=game.id,
    )
    reconcile_memory_item(db, source, game_id=game.id)
    started = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    prior = GenerationTask(
        user_id=user.id,
        idea="arcade",
        task_kind="revision",
        base_game_id=game.id,
        base_version="v1",
        feedback_text="上一版把角色移动调快一点。",
        status=TaskStatus.SUCCEEDED,
        result_game_id=game.id,
        created_at=started,
    )
    current = GenerationTask(
        user_id=user.id,
        idea="arcade",
        task_kind="revision",
        base_game_id=game.id,
        base_version="v2",
        feedback_text="跳跃要更轻快，但不要明显跳得更高。",
        status=TaskStatus.SUCCEEDED,
        result_game_id=game.id,
        created_at=started + timedelta(minutes=1),
    )
    db.add_all([prior, current])
    db.commit()

    created = capture_success_memories(
        db,
        task_id=current.id,
        state={"task_kind": "revision", "game_id": game.id},
    )
    db.commit()

    assert len(created) == 1
    assert len(calls) == 1
    _, payload, kwargs = calls[0]
    assert kwargs["model"] == "small-memory-model"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert payload["known_profiles"][0]["profile_key"] == "visual_style"
    assert payload["known_profiles"][0]["status"] == "active"
    assert [message["content"] for message in payload["recent_user_messages"]] == [
        "上一版把角色移动调快一点。",
        "跳跃要更轻快，但不要明显跳得更高。",
    ]
    assert all(set(message) == {"content", "version", "created_at"} for message in payload["recent_user_messages"])
    assert "assistant" not in json.dumps(payload, ensure_ascii=False).lower()
    jump_profiles = db.query(MemoryProfile).filter(MemoryProfile.profile_key == "jump_feel").all()
    # The direct claim stays game-scoped; a background user-scope candidate
    # accumulates cross-game evidence without entering prompts.
    assert {(profile.scope_type, profile.status) for profile in jump_profiles} == {
        ("game", "active"),
        ("user", "candidate"),
    }
    assert db.query(MemoryEntityLink).filter(MemoryEntityLink.memory_id == created[0].id).count() == 1
    db.close()


def test_entity_ranking_adds_third_rrf_signal(db_session_factory, monkeypatch):
    from app.models import MemoryEntity, MemoryEntityLink, MemorySettings, User
    from app.models.memory import MemoryCategory, MemoryScope
    from app.services import memory_embeddings
    from app.services.memory import create_memory, retrieve_memories

    monkeypatch.setattr(memory_embeddings, "embedding_model", lambda: "test-embedding")
    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    db = db_session_factory()
    user = User(email="entity@test.com", password_hash="x", display_name="Entity", avatar_initial="E")
    db.add(user)
    db.flush()
    db.add(MemorySettings(user_id=user.id))
    item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.USER,
        scope_id=None,
        category=MemoryCategory.MECHANICS,
        raw_text="保留通过门户瞬移的核心机制",
    )
    entity = MemoryEntity(
        user_id=user.id,
        entity_type="mechanic",
        canonical_name="跃迁门",
        normalized_name="跃迁门",
        embedding=[1.0, 0.0],
        embedding_model="test-embedding",
    )
    db.add(entity)
    db.flush()
    db.add(MemoryEntityLink(entity_id=entity.id, memory_id=item.id, confidence=1.0, source="claim"))
    db.commit()

    results = retrieve_memories(db, user_id=user.id, query="跃迁门", limit=1)

    assert results[0]["id"] == item.id
    assert results[0]["retrieval"]["entity_rank"] == 1
    assert results[0]["retrieval"]["strategy"] == "rrf_hybrid_entity"
    db.close()


def _make_user_and_game(db, email, title="G"):
    from app.models import Game, User
    from app.models.common import GameSource, GameStatus

    user = User(email=email, password_hash="x", display_name="U", avatar_initial="U")
    db.add(user)
    db.flush()
    game = Game(
        author_id=user.id,
        title=title,
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
    )
    db.add(game)
    db.flush()
    return user, game


def test_rephrased_free_form_claim_reinforces_existing_profile(db_session_factory, monkeypatch):
    """词表外偏好换一种说法时，通过向量认领同一个 profile_key 并强化，而不是新建孤立档案。"""
    from app.models import MemoryProfile
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embedding_model", lambda: "test-embedding")
    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: [[1.0, 0.0] for _ in texts])
    db = db_session_factory()
    user, game = _make_user_and_game(db, "adopt@test.com")

    first = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="多加故障闪烁的特效",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    first_profiles = reconcile_memory_item(db, first, game_id=game.id)
    game_profile = next(profile for profile in first_profiles if profile.scope_type == "game")
    assert game_profile.status == "active"
    assert game_profile.embedding == [1.0, 0.0]

    rephrased = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="画面里要有更多glitch闪烁效果",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    second_profiles = reconcile_memory_item(db, rephrased, game_id=game.id)

    assert game_profile.id in {profile.id for profile in second_profiles}
    assert game_profile.support_count == 2
    # Rephrasing must not mint a second key: still one game profile + its user shadow candidate.
    keys = {profile.profile_key for profile in db.query(MemoryProfile).filter(MemoryProfile.user_id == user.id)}
    assert keys == {game_profile.profile_key}
    db.close()


def test_rephrased_claim_without_embeddings_keeps_hash_fallback(db_session_factory, monkeypatch):
    from app.models import MemoryProfile
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user, game = _make_user_and_game(db, "hash-fallback@test.com")
    for raw_text in ("多加故障闪烁的特效", "画面里要有更多glitch闪烁效果"):
        item = create_memory(
            db,
            user.id,
            scope_type=MemoryScope.GAME,
            scope_id=game.id,
            category=MemoryCategory.STYLE,
            raw_text=raw_text,
            source_type=MemorySource.FEEDBACK,
            source_game_id=game.id,
        )
        reconcile_memory_item(db, item, game_id=game.id)

    game_keys = [
        profile.profile_key
        for profile in db.query(MemoryProfile).filter(
            MemoryProfile.user_id == user.id, MemoryProfile.scope_type == "game"
        )
    ]
    # Without a vector service the pre-existing behavior is preserved: two separate hash keys.
    assert len(game_keys) == 2
    assert len(set(game_keys)) == 2
    db.close()


def test_llm_low_confidence_claim_lands_as_candidate(db_session_factory, monkeypatch):
    """LLM 可以下调置信度，让拿不准的 claim 走 candidate 轨道而不是被规则抬回 active。"""
    import json

    from app.agents import llm
    from app.core.config import settings
    from app.models import GenerationTask, MemoryProfile
    from app.models.common import TaskStatus
    from app.services import memory_embeddings
    from app.services.memory import capture_success_memories

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_MODEL", "small-memory-model")

    def fake_chat(system, user_payload, **kwargs):
        payload = json.loads(user_payload)
        evidence = payload["current_evidence"][0]
        return json.dumps(
            {
                "claims": [
                    {
                        "source_memory_id": evidence["source_memory_id"],
                        "decision": "active",
                        "profile_key": "art_direction",
                        "category": "style",
                        "value_text": "glitch",
                        "summary_text": "画面往故障艺术方向调整",
                        "evidence_span": evidence["raw_text"],
                        "suggested_scope": "game",
                        "explicitness": "explicit",
                        "confidence": 0.2,
                    }
                ]
            },
            ensure_ascii=False,
        ), 7

    monkeypatch.setattr(llm, "chat", fake_chat)
    db = db_session_factory()
    user, game = _make_user_and_game(db, "lowconf@test.com")
    task = GenerationTask(
        user_id=user.id,
        idea="arcade",
        task_kind="revision",
        base_game_id=game.id,
        base_version="v1",
        result_game_id=game.id,
        feedback_text="画面往故障艺术方向改",
        status=TaskStatus.SUCCEEDED,
    )
    db.add(task)
    db.commit()

    capture_success_memories(db, task_id=task.id, state={"task_kind": "revision", "game_id": game.id})
    db.flush()

    profile = (
        db.query(MemoryProfile)
        .filter(MemoryProfile.profile_key == "art_direction", MemoryProfile.scope_type == "game")
        .one()
    )
    assert profile.status == "candidate"
    assert float(profile.confidence) == 0.30
    db.close()


def test_user_shadow_candidate_promotes_across_distinct_games(db_session_factory, monkeypatch):
    """同一偏好在两个不同游戏中出现后，用户级影子 candidate 自动晋升为 active。"""
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item, retrieve_profiles

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user, game_a = _make_user_and_game(db, "cross-game@test.com", title="Game A")
    from app.models import Game
    from app.models.common import GameSource, GameStatus

    game_b = Game(
        author_id=user.id,
        title="Game B",
        summary="",
        genre="ARCADE",
        cover="",
        source=GameSource.CREATE,
        status=GameStatus.PREVIEW,
        current_version="v1",
    )
    db.add(game_b)
    db.flush()

    item_a = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game_a.id,
        category=MemoryCategory.DIFFICULTY,
        raw_text="太难了，调得简单一点",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game_a.id,
    )
    profiles_a = reconcile_memory_item(db, item_a, game_id=game_a.id)
    shadow = next(profile for profile in profiles_a if profile.scope_type == "user")
    assert shadow.status == "candidate"
    assert shadow.value_text == "easy"

    item_b = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game_b.id,
        category=MemoryCategory.DIFFICULTY,
        raw_text="太难了，调得简单一点",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game_b.id,
    )
    reconcile_memory_item(db, item_b, game_id=game_b.id)
    db.flush()

    assert shadow.status == "active"
    assert shadow.support_count == 2
    active_user_profiles = retrieve_profiles(db, user_id=user.id)
    assert shadow.id in {profile["id"] for profile in active_user_profiles}
    db.close()


def test_user_shadow_candidate_stays_candidate_within_one_game(db_session_factory, monkeypatch):
    """同一句话在同一个游戏里重复三次不构成跨游戏证据，用户级 candidate 不晋升。"""
    from app.models import MemoryProfile
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user, game = _make_user_and_game(db, "same-game@test.com")

    for _ in range(3):
        item = create_memory(
            db,
            user.id,
            scope_type=MemoryScope.GAME,
            scope_id=game.id,
            category=MemoryCategory.DIFFICULTY,
            raw_text="太难了，调得简单一点",
            source_type=MemorySource.FEEDBACK,
            source_game_id=game.id,
        )
        reconcile_memory_item(db, item, game_id=game.id)

    shadow = (
        db.query(MemoryProfile)
        .filter(MemoryProfile.user_id == user.id, MemoryProfile.scope_type == "user")
        .one()
    )
    assert shadow.status == "candidate"
    assert shadow.support_count == 3
    db.close()


def test_explicitly_game_scoped_feedback_creates_no_user_shadow(db_session_factory, monkeypatch):
    from app.models import MemoryProfile
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user, game = _make_user_and_game(db, "pinned-scope@test.com")

    item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.DIFFICULTY,
        raw_text="这个游戏太难了，调得简单一点",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    reconcile_memory_item(db, item, game_id=game.id)

    user_profiles = (
        db.query(MemoryProfile)
        .filter(MemoryProfile.user_id == user.id, MemoryProfile.scope_type == "user")
        .count()
    )
    assert user_profiles == 0
    db.close()


def test_extraction_context_includes_candidate_profiles(db_session_factory, monkeypatch):
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import _profiles_for_extraction_context, reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user, game = _make_user_and_game(db, "context-cand@test.com")
    active_item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="这个游戏使用像素风",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    reconcile_memory_item(db, active_item, game_id=game.id)
    hedged_item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="这个游戏能不能试试写实风",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
    )
    reconcile_memory_item(db, hedged_item, game_id=game.id)

    rows = _profiles_for_extraction_context(db, user_id=user.id, game_id=game.id, task_id=None)
    statuses = {(row["value_text"], row["status"]) for row in rows}
    assert ("pixel", "active") in statuses
    assert ("realistic", "candidate") in statuses
    db.close()
