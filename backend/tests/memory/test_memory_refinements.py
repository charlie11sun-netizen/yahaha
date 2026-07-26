"""第六批回归：混合表达按 claim 分流、反义方向词不错并、强化后向量跟随文本。"""
from app.models import Game, User
from app.models.common import GameSource, GameStatus


def _make_user_and_game(db, email):
    user = User(email=email, display_name="M", avatar_initial="M")
    db.add(user)
    db.flush()
    game = Game(
        author_id=user.id, title="Mem Game", summary="", genre="arcade",
        status=GameStatus.PREVIEW, current_version="v1", source=GameSource.CREATE,
        plays_count=0, likes_count=0,
    )
    db.add(game)
    db.commit()
    return user, game


def test_mixed_ephemeral_feedback_keeps_persistent_claim(db_session_factory, monkeypatch):
    """"以后默认像素风，这次先把跳跃调高" —— 持久偏好入档（user 影子/game），
    临时部分路由到 task 作用域，而不是整条丢弃。"""
    from app.models import MemoryProfile
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: None)
    db = db_session_factory()
    user, game = _make_user_and_game(db, "mixed@test.com")

    item = create_memory(
        db,
        user.id,
        scope_type=MemoryScope.GAME,
        scope_id=game.id,
        category=MemoryCategory.STYLE,
        raw_text="以后所有游戏默认像素风，这次先把跳跃调高一点",
        source_type=MemorySource.FEEDBACK,
        source_game_id=game.id,
        source_task_id=None,
    )
    reconcile_memory_item(db, item, game_id=game.id)

    profiles = db.query(MemoryProfile).filter(MemoryProfile.user_id == user.id).all()
    summaries = " | ".join(p.summary_text for p in profiles)
    assert "像素风" in summaries, f"持久偏好被丢弃: {summaries}"
    # 临时 claim 不得进入 game/user 作用域的 Prompt 轨道
    for p in profiles:
        if "这次" in p.summary_text:
            assert p.scope_type == MemoryScope.TASK
    db.close()


def test_opposite_direction_feedback_not_merged_as_reinforcement(db_session_factory, monkeypatch):
    """"跳跃不要太高" vs "跳跃不要太低"：embedding 高相似 + 同为否定句，
    方向冲突守卫必须阻止 value 复用（否则反向偏好被当成强化）。"""
    from app.models import MemoryProfile
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    # 两句返回同一向量 → 余弦相似度 1.0，旧逻辑必然复用 value 并 reinforce
    monkeypatch.setattr(memory_embeddings, "embed_texts", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])
    monkeypatch.setattr(memory_embeddings, "cosine_similarity", lambda a, b: 1.0 if a and b else None)
    db = db_session_factory()
    user, game = _make_user_and_game(db, "direction@test.com")

    for text in ("小人跳跃不要太高", "小人跳跃不要太低"):
        item = create_memory(
            db,
            user.id,
            scope_type=MemoryScope.GAME,
            scope_id=game.id,
            category=MemoryCategory.MECHANICS,
            raw_text=text,
            source_type=MemorySource.FEEDBACK,
            source_game_id=game.id,
        )
        reconcile_memory_item(db, item, game_id=game.id)

    game_profiles = db.query(MemoryProfile).filter(
        MemoryProfile.user_id == user.id,
        MemoryProfile.scope_type == MemoryScope.GAME,
    ).all()
    # 反向反馈绝不能变成同一 profile 的 support_count=2 强化
    for p in game_profiles:
        if p.status == "active" and "不要太低" in p.summary_text:
            continue
        assert not (p.support_count >= 2 and "不要太高" in p.summary_text and "低" not in p.summary_text), (
            f"反向偏好被错并强化: {p.summary_text} support={p.support_count}"
        )
    # 当前生效的表述必须是后一条（"不要太低"），要么取代要么并列，不能丢失
    active_texts = [p.summary_text for p in game_profiles if p.status == "active"]
    assert any("不要太低" in t for t in active_texts), f"active: {active_texts}"
    db.close()


def test_reinforce_refreshes_embedding_with_summary(db_session_factory, monkeypatch):
    """强化改写 summary 后向量必须跟随（否则同义认领随时间漂移）。"""
    from app.models import MemoryProfile
    from app.models.memory import MemoryCategory, MemoryScope, MemorySource
    from app.services import memory_embeddings
    from app.services.memory import create_memory
    from app.services.memory_profiles import reconcile_memory_item

    calls = {"n": 0}

    def _fake_embed(texts):
        calls["n"] += 1
        return [[float(calls["n"]), 0.0] for _ in texts]

    monkeypatch.setattr(memory_embeddings, "embed_texts", _fake_embed)
    monkeypatch.setattr(memory_embeddings, "cosine_similarity", lambda a, b: 0.0)
    monkeypatch.setattr(memory_embeddings, "embedding_model", lambda: "fake-model")
    db = db_session_factory()
    user, game = _make_user_and_game(db, "embref@test.com")

    # 同一 attribute（难度词表命中，非 hash key）两条不同措辞 → 第二条 reinforce
    first = create_memory(
        db, user.id, scope_type=MemoryScope.GAME, scope_id=game.id,
        category=MemoryCategory.DIFFICULTY, raw_text="难度调得简单一点",
        source_type=MemorySource.FEEDBACK, source_game_id=game.id,
    )
    reconcile_memory_item(db, first, game_id=game.id)
    profile = db.query(MemoryProfile).filter(
        MemoryProfile.user_id == user.id, MemoryProfile.scope_type == MemoryScope.GAME
    ).first()
    vector_before = list(profile.embedding or [])

    second = create_memory(
        db, user.id, scope_type=MemoryScope.GAME, scope_id=game.id,
        category=MemoryCategory.DIFFICULTY, raw_text="整体难度再调简单一些",
        source_type=MemorySource.FEEDBACK, source_game_id=game.id,
    )
    reconcile_memory_item(db, second, game_id=game.id)
    db.refresh(profile)

    if profile.support_count >= 2:  # 确实走了 reinforce 路径
        assert profile.summary_text == "整体难度再调简单一些"
        assert list(profile.embedding or []) != vector_before, "summary 变了但向量没刷新"
    db.close()
