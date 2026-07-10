"""baseline schema (squashed)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-02

固化基线：把上线前的 0001_initial..0011_memory_pgvector 压缩为一份写死的 DDL。
- 本文件不 import app.models —— 基线必须是历史快照，随模型演进会导致旧迁移不可重放
  （旧 0001 用 Base.metadata.create_all，全新库跑到 0002 即撞列）。
- embedding 维度固化为 1536（与旧 0011 的 DIMENSIONS 一致）；SQLite（开发/测试）落 JSON。
- 在本次 squash 之前建的库：执行 `alembic stamp 0001_baseline --purge`，再 `alembic upgrade head`。
后续 schema 变更请用 `alembic revision --autogenerate -m "..."` 生成增量迁移。
"""
from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _embedding():
    return pgvector.sqlalchemy.vector.VECTOR(dim=1536).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('tags',
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tags_name'), 'tags', ['name'], unique=True)
    op.create_table('users',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('avatar_initial', sa.String(length=4), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('assets',
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('oss_key', sa.String(length=400), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assets_owner_id'), 'assets', ['owner_id'], unique=False)
    op.create_table('follows',
    sa.Column('follower_id', sa.String(length=36), nullable=False),
    sa.Column('following_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['follower_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['following_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('follower_id', 'following_id')
    )
    op.create_table('games',
    sa.Column('author_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('genre', sa.String(length=80), nullable=False),
    sa.Column('cover', sa.String(length=400), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_version', sa.String(length=20), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=True),
    sa.Column('plays_count', sa.BigInteger(), nullable=False),
    sa.Column('likes_count', sa.BigInteger(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_games_author_id'), 'games', ['author_id'], unique=False)
    op.create_index(op.f('ix_games_status'), 'games', ['status'], unique=False)
    op.create_table('memory_entities',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('canonical_name', sa.String(length=240), nullable=False),
    sa.Column('normalized_name', sa.String(length=240), nullable=False),
    sa.Column('embedding', _embedding(), nullable=True),
    sa.Column('embedding_model', sa.String(length=100), nullable=True),
    sa.Column('embedding_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'entity_type', 'normalized_name', name='uq_memory_entity_identity')
    )
    op.create_index('ix_memory_entities_embedding_hnsw', 'memory_entities', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'}, postgresql_where=sa.text('embedding IS NOT NULL'))
    op.create_index(op.f('ix_memory_entities_entity_type'), 'memory_entities', ['entity_type'], unique=False)
    op.create_index(op.f('ix_memory_entities_normalized_name'), 'memory_entities', ['normalized_name'], unique=False)
    op.create_index(op.f('ix_memory_entities_user_id'), 'memory_entities', ['user_id'], unique=False)
    op.create_table('memory_settings',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('allow_cross_game_memory', sa.Boolean(), nullable=False),
    sa.Column('allow_memory_extraction', sa.Boolean(), nullable=False),
    sa.Column('retention_days', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('retention_days IS NULL OR retention_days > 0', name='ck_memory_retention'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('oauth_accounts',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_account_id', sa.String(length=255), nullable=False),
    sa.Column('account_email', sa.String(length=255), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'provider_account_id')
    )
    op.create_index(op.f('ix_oauth_accounts_user_id'), 'oauth_accounts', ['user_id'], unique=False)
    op.create_table('comments',
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_comments_game_id'), 'comments', ['game_id'], unique=False)
    op.create_index(op.f('ix_comments_user_id'), 'comments', ['user_id'], unique=False)
    op.create_table('favorites',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'game_id')
    )
    op.create_table('game_tags',
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('tag_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('game_id', 'tag_id')
    )
    op.create_table('game_versions',
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('manifest_key', sa.String(length=400), nullable=False),
    sa.Column('entry', sa.String(length=120), nullable=False),
    sa.Column('bundle_key', sa.String(length=400), nullable=False),
    sa.Column('cover_key', sa.String(length=400), nullable=True),
    sa.Column('runtime', sa.String(length=40), nullable=False),
    sa.Column('sha256', sa.String(length=80), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('source_task_id', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_game_versions_game_id'), 'game_versions', ['game_id'], unique=False)
    op.create_table('generation_tasks',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('idea', sa.Text(), nullable=False),
    sa.Column('task_kind', sa.String(length=20), server_default='generation', nullable=False),
    sa.Column('base_game_id', sa.String(length=36), nullable=True),
    sa.Column('base_version', sa.String(length=20), nullable=True),
    sa.Column('feedback_text', sa.Text(), nullable=True),
    sa.Column('feedback_brief', sa.Text(), nullable=True),
    sa.Column('dimension', sa.String(length=8), server_default='2d', nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_step', sa.Integer(), nullable=False),
    sa.Column('current_agent', sa.String(length=40), nullable=True),
    sa.Column('result_game_id', sa.String(length=36), nullable=True),
    sa.Column('version_id', sa.String(length=36), nullable=True),
    sa.Column('tokens_used', sa.BigInteger(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('repair_attempts', sa.Integer(), nullable=False),
    sa.Column('max_repair_attempts', sa.Integer(), nullable=False),
    sa.Column('replan_attempts', sa.Integer(), nullable=False),
    sa.Column('max_replan_attempts', sa.Integer(), nullable=False),
    sa.Column('spec_json', sa.Text(), nullable=True),
    sa.Column('design_json', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['base_game_id'], ['games.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['result_game_id'], ['games.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generation_tasks_base_game_id'), 'generation_tasks', ['base_game_id'], unique=False)
    op.create_index(op.f('ix_generation_tasks_status'), 'generation_tasks', ['status'], unique=False)
    op.create_index(op.f('ix_generation_tasks_user_id'), 'generation_tasks', ['user_id'], unique=False)
    op.create_table('likes',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'game_id')
    )
    op.create_table('play_events',
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_play_events_game_id'), 'play_events', ['game_id'], unique=False)
    op.create_table('scores',
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=True),
    sa.Column('player_name', sa.String(length=80), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scores_game_id'), 'scores', ['game_id'], unique=False)
    op.create_table('agent_steps',
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('agent', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('tokens', sa.BigInteger(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['generation_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_steps_task_id'), 'agent_steps', ['task_id'], unique=False)
    op.create_table('memory_items',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('scope_type', sa.String(length=20), nullable=False),
    sa.Column('scope_id', sa.String(length=36), nullable=True),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('extracted_text', sa.Text(), nullable=True),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_task_id', sa.String(length=36), nullable=True),
    sa.Column('source_game_id', sa.String(length=36), nullable=True),
    sa.Column('source_version', sa.String(length=20), nullable=True),
    sa.Column('importance', sa.Integer(), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('pinned', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('supersedes_id', sa.String(length=36), nullable=True),
    sa.Column('embedding', _embedding(), nullable=True),
    sa.Column('embedding_model', sa.String(length=100), nullable=True),
    sa.Column('embedding_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(scope_type = 'user' AND scope_id IS NULL) OR (scope_type IN ('game','task') AND scope_id IS NOT NULL)", name='ck_memory_item_scope_id'),
    sa.CheckConstraint("category IN ('style','mechanics','controls','difficulty','content','constraints','feedback')", name='ck_memory_item_category'),
    sa.CheckConstraint("scope_type IN ('user','game','task')", name='ck_memory_item_scope'),
    sa.CheckConstraint("source_type IN ('idea','feedback','manual','publish','system')", name='ck_memory_item_source'),
    sa.CheckConstraint("status IN ('active','superseded','deleted')", name='ck_memory_item_status'),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name='ck_memory_item_confidence'),
    sa.CheckConstraint('importance BETWEEN 1 AND 5', name='ck_memory_item_importance'),
    sa.ForeignKeyConstraint(['source_game_id'], ['games.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_task_id'], ['generation_tasks.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['memory_items.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memory_items_category'), 'memory_items', ['category'], unique=False)
    op.create_index('ix_memory_items_embedding_hnsw', 'memory_items', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'}, postgresql_where=sa.text('embedding IS NOT NULL'))
    op.create_index(op.f('ix_memory_items_pinned'), 'memory_items', ['pinned'], unique=False)
    op.create_index(op.f('ix_memory_items_scope_id'), 'memory_items', ['scope_id'], unique=False)
    op.create_index(op.f('ix_memory_items_scope_type'), 'memory_items', ['scope_type'], unique=False)
    op.create_index(op.f('ix_memory_items_source_game_id'), 'memory_items', ['source_game_id'], unique=False)
    op.create_index(op.f('ix_memory_items_source_task_id'), 'memory_items', ['source_task_id'], unique=False)
    op.create_index(op.f('ix_memory_items_source_type'), 'memory_items', ['source_type'], unique=False)
    op.create_index(op.f('ix_memory_items_status'), 'memory_items', ['status'], unique=False)
    op.create_index(op.f('ix_memory_items_user_id'), 'memory_items', ['user_id'], unique=False)
    op.create_table('task_assets',
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('asset_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['generation_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'asset_id')
    )
    op.create_table('agent_logs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('step_id', sa.String(length=36), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('line', sa.Text(), nullable=False),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['step_id'], ['agent_steps.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_logs_step_id'), 'agent_logs', ['step_id'], unique=False)
    op.create_table('memory_entity_links',
    sa.Column('entity_id', sa.String(length=36), nullable=False),
    sa.Column('memory_id', sa.String(length=36), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name='ck_memory_entity_link_confidence'),
    sa.ForeignKeyConstraint(['entity_id'], ['memory_entities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['memory_id'], ['memory_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entity_id', 'memory_id', name='uq_memory_entity_link')
    )
    op.create_index(op.f('ix_memory_entity_links_entity_id'), 'memory_entity_links', ['entity_id'], unique=False)
    op.create_index(op.f('ix_memory_entity_links_memory_id'), 'memory_entity_links', ['memory_id'], unique=False)
    op.create_table('memory_profiles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('scope_type', sa.String(length=20), nullable=False),
    sa.Column('scope_id', sa.String(length=36), nullable=True),
    sa.Column('profile_key', sa.String(length=160), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('value_text', sa.Text(), nullable=False),
    sa.Column('summary_text', sa.Text(), nullable=False),
    sa.Column('evidence_span', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('scope_confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('explicitness', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('source_memory_id', sa.String(length=36), nullable=False),
    sa.Column('conflicts_with_id', sa.String(length=36), nullable=True),
    sa.Column('support_count', sa.Integer(), nullable=False),
    sa.Column('utility_score', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('utility_observation_count', sa.Integer(), nullable=False),
    sa.Column('last_supported_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('embedding', _embedding(), nullable=True),
    sa.Column('embedding_model', sa.String(length=100), nullable=True),
    sa.Column('embedding_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(scope_type = 'user' AND scope_id IS NULL) OR (scope_type IN ('game','task') AND scope_id IS NOT NULL)", name='ck_memory_profile_scope_id'),
    sa.CheckConstraint("category IN ('style','mechanics','controls','difficulty','content','constraints','feedback')", name='ck_memory_profile_category'),
    sa.CheckConstraint("explicitness IN ('manual','explicit','inferred')", name='ck_memory_profile_explicitness'),
    sa.CheckConstraint("scope_type IN ('user','game','task')", name='ck_memory_profile_scope'),
    sa.CheckConstraint("status IN ('active','candidate','superseded','deleted')", name='ck_memory_profile_status'),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name='ck_memory_profile_confidence'),
    sa.CheckConstraint('scope_confidence BETWEEN 0 AND 1', name='ck_memory_profile_scope_confidence'),
    sa.CheckConstraint('support_count >= 1', name='ck_memory_profile_support'),
    sa.CheckConstraint('utility_observation_count >= 0', name='ck_memory_profile_utility_observations'),
    sa.CheckConstraint('utility_score BETWEEN 0 AND 1', name='ck_memory_profile_utility'),
    sa.CheckConstraint('version >= 1', name='ck_memory_profile_version'),
    sa.ForeignKeyConstraint(['conflicts_with_id'], ['memory_profiles.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_memory_id'], ['memory_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memory_profiles_category'), 'memory_profiles', ['category'], unique=False)
    op.create_index(op.f('ix_memory_profiles_conflicts_with_id'), 'memory_profiles', ['conflicts_with_id'], unique=False)
    op.create_index('ix_memory_profiles_embedding_hnsw', 'memory_profiles', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'}, postgresql_where=sa.text('embedding IS NOT NULL'))
    op.create_index(op.f('ix_memory_profiles_profile_key'), 'memory_profiles', ['profile_key'], unique=False)
    op.create_index(op.f('ix_memory_profiles_scope_id'), 'memory_profiles', ['scope_id'], unique=False)
    op.create_index(op.f('ix_memory_profiles_scope_type'), 'memory_profiles', ['scope_type'], unique=False)
    op.create_index(op.f('ix_memory_profiles_source_memory_id'), 'memory_profiles', ['source_memory_id'], unique=False)
    op.create_index(op.f('ix_memory_profiles_status'), 'memory_profiles', ['status'], unique=False)
    op.create_index(op.f('ix_memory_profiles_user_id'), 'memory_profiles', ['user_id'], unique=False)
    # 表达式 + 部分唯一索引（autogenerate 无法生成，手工固化）：同 user/scope/key 至多一个 active。
    # 该语法在 PostgreSQL 与 SQLite 上均合法。
    op.execute(
        "CREATE UNIQUE INDEX uq_memory_profile_active_identity ON memory_profiles "
        "(user_id, scope_type, coalesce(scope_id, ''), profile_key) WHERE status = 'active'"
    )
    op.create_table('memory_profile_evidence',
    sa.Column('profile_id', sa.String(length=36), nullable=False),
    sa.Column('memory_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_span', sa.Text(), nullable=False),
    sa.Column('value_text', sa.Text(), nullable=False),
    sa.Column('summary_text', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('scope_confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('explicitness', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("explicitness IN ('manual','explicit','inferred')", name='ck_memory_evidence_explicitness'),
    sa.CheckConstraint('confidence BETWEEN 0 AND 1', name='ck_memory_evidence_confidence'),
    sa.CheckConstraint('scope_confidence BETWEEN 0 AND 1', name='ck_memory_evidence_scope_confidence'),
    sa.ForeignKeyConstraint(['memory_id'], ['memory_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['profile_id'], ['memory_profiles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('profile_id', 'memory_id', name='uq_memory_profile_evidence')
    )
    op.create_index(op.f('ix_memory_profile_evidence_is_active'), 'memory_profile_evidence', ['is_active'], unique=False)
    op.create_index(op.f('ix_memory_profile_evidence_memory_id'), 'memory_profile_evidence', ['memory_id'], unique=False)
    op.create_index(op.f('ix_memory_profile_evidence_profile_id'), 'memory_profile_evidence', ['profile_id'], unique=False)
    op.create_table('memory_profile_versions',
    sa.Column('profile_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('operation', sa.String(length=30), nullable=False),
    sa.Column('snapshot_json', sa.JSON(), nullable=False),
    sa.Column('source_memory_id', sa.String(length=36), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['memory_profiles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_memory_id'], ['memory_items.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memory_profile_versions_operation'), 'memory_profile_versions', ['operation'], unique=False)
    op.create_index(op.f('ix_memory_profile_versions_profile_id'), 'memory_profile_versions', ['profile_id'], unique=False)
    op.create_index(op.f('ix_memory_profile_versions_source_memory_id'), 'memory_profile_versions', ['source_memory_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_memory_profile_versions_source_memory_id'), table_name='memory_profile_versions')
    op.drop_index(op.f('ix_memory_profile_versions_profile_id'), table_name='memory_profile_versions')
    op.drop_index(op.f('ix_memory_profile_versions_operation'), table_name='memory_profile_versions')
    op.drop_table('memory_profile_versions')
    op.drop_index(op.f('ix_memory_profile_evidence_profile_id'), table_name='memory_profile_evidence')
    op.drop_index(op.f('ix_memory_profile_evidence_memory_id'), table_name='memory_profile_evidence')
    op.drop_index(op.f('ix_memory_profile_evidence_is_active'), table_name='memory_profile_evidence')
    op.drop_table('memory_profile_evidence')
    op.execute("DROP INDEX IF EXISTS uq_memory_profile_active_identity")
    op.drop_index(op.f('ix_memory_profiles_user_id'), table_name='memory_profiles')
    op.drop_index(op.f('ix_memory_profiles_status'), table_name='memory_profiles')
    op.drop_index(op.f('ix_memory_profiles_source_memory_id'), table_name='memory_profiles')
    op.drop_index(op.f('ix_memory_profiles_scope_type'), table_name='memory_profiles')
    op.drop_index(op.f('ix_memory_profiles_scope_id'), table_name='memory_profiles')
    op.drop_index(op.f('ix_memory_profiles_profile_key'), table_name='memory_profiles')
    op.drop_index('ix_memory_profiles_embedding_hnsw', table_name='memory_profiles')
    op.drop_index(op.f('ix_memory_profiles_conflicts_with_id'), table_name='memory_profiles')
    op.drop_index(op.f('ix_memory_profiles_category'), table_name='memory_profiles')
    op.drop_table('memory_profiles')
    op.drop_index(op.f('ix_memory_entity_links_memory_id'), table_name='memory_entity_links')
    op.drop_index(op.f('ix_memory_entity_links_entity_id'), table_name='memory_entity_links')
    op.drop_table('memory_entity_links')
    op.drop_index(op.f('ix_agent_logs_step_id'), table_name='agent_logs')
    op.drop_table('agent_logs')
    op.drop_table('task_assets')
    op.drop_index(op.f('ix_memory_items_user_id'), table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_status'), table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_source_type'), table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_source_task_id'), table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_source_game_id'), table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_scope_type'), table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_scope_id'), table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_pinned'), table_name='memory_items')
    op.drop_index('ix_memory_items_embedding_hnsw', table_name='memory_items')
    op.drop_index(op.f('ix_memory_items_category'), table_name='memory_items')
    op.drop_table('memory_items')
    op.drop_index(op.f('ix_agent_steps_task_id'), table_name='agent_steps')
    op.drop_table('agent_steps')
    op.drop_index(op.f('ix_scores_game_id'), table_name='scores')
    op.drop_table('scores')
    op.drop_index(op.f('ix_play_events_game_id'), table_name='play_events')
    op.drop_table('play_events')
    op.drop_table('likes')
    op.drop_index(op.f('ix_generation_tasks_user_id'), table_name='generation_tasks')
    op.drop_index(op.f('ix_generation_tasks_status'), table_name='generation_tasks')
    op.drop_index(op.f('ix_generation_tasks_base_game_id'), table_name='generation_tasks')
    op.drop_table('generation_tasks')
    op.drop_index(op.f('ix_game_versions_game_id'), table_name='game_versions')
    op.drop_table('game_versions')
    op.drop_table('game_tags')
    op.drop_table('favorites')
    op.drop_index(op.f('ix_comments_user_id'), table_name='comments')
    op.drop_index(op.f('ix_comments_game_id'), table_name='comments')
    op.drop_table('comments')
    op.drop_index(op.f('ix_oauth_accounts_user_id'), table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
    op.drop_table('memory_settings')
    op.drop_index(op.f('ix_memory_entities_user_id'), table_name='memory_entities')
    op.drop_index(op.f('ix_memory_entities_normalized_name'), table_name='memory_entities')
    op.drop_index(op.f('ix_memory_entities_entity_type'), table_name='memory_entities')
    op.drop_index('ix_memory_entities_embedding_hnsw', table_name='memory_entities')
    op.drop_table('memory_entities')
    op.drop_index(op.f('ix_games_status'), table_name='games')
    op.drop_index(op.f('ix_games_author_id'), table_name='games')
    op.drop_table('games')
    op.drop_table('follows')
    op.drop_index(op.f('ix_assets_owner_id'), table_name='assets')
    op.drop_table('assets')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_tags_name'), table_name='tags')
    op.drop_table('tags')
