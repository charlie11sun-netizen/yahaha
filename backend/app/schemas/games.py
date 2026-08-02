"""游戏域:卡片/详情/版本/互动(评论·点赞·收藏·排行)/manifest。"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GameUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ScoreIn(BaseModel):
    points: int = Field(ge=0, le=100_000_000)
    player_name: str | None = Field(default=None, max_length=80)


class GameCardOut(BaseModel):
    id: str
    title: str
    summary: str
    genre: str
    cover: str | None = None
    version: str
    source: str
    from_create: bool
    status: str
    author: str
    author_init: str
    author_id: str
    tags: list[str]
    plays: int
    plays_str: str
    likes: int
    likes_str: str
    published_at: str | None = None
    date: str
    manifest_url: str
    oss_path: str
    remixed_from_game_id: str | None = None
    remixed_from_version: str | None = None


class RemixedFromOut(BaseModel):
    id: str
    title: str
    author: str
    version: str | None = None


class GameDetailOut(GameCardOut):
    prompt: str | None = None
    bundle_url: str
    liked: bool | None = None
    favorited: bool | None = None
    remixed_from: RemixedFromOut | None = None
    remix_count: int | None = None


class GameListOut(BaseModel):
    items: list[GameCardOut]
    total: int
    has_more: bool


class GameCollectionOut(BaseModel):
    items: list[GameCardOut]
    total: int | None = None
    has_more: bool | None = None


class GameStatsOut(BaseModel):
    game_count: int
    total_plays: int


class TagsOut(BaseModel):
    tags: list[str]


class GameVersionOut(BaseModel):
    version: str
    created_at: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    is_current: bool


class GameVersionListOut(BaseModel):
    items: list[GameVersionOut]


class PlayOut(BaseModel):
    plays: int
    plays_str: str
    counted: bool


class LikeOut(BaseModel):
    liked: bool
    likes: int


class FavoriteOut(BaseModel):
    favorited: bool


class CommentOut(BaseModel):
    id: str
    body: str
    created_at: str | None = None
    ago: str
    author: str
    author_init: str
    author_id: str


class CommentListOut(BaseModel):
    items: list[CommentOut]


class ScoreOut(BaseModel):
    rank: int | None = None
    name: str
    points: int
    ago: str


class LeaderboardOut(BaseModel):
    items: list[ScoreOut]


class GameManifestFileOut(BaseModel):
    path: str
    url: str | None = None
    sha256: str | None = None


class GameManifestOut(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: str | None = None
    game_id: str | None = None
    version_id: str | None = None
    title: str | None = None
    entry: str | None = None
    entry_url: str | None = None
    runtime: str | None = None
    sha256: str | None = None
    size: int | None = None
    files: list[GameManifestFileOut] | None = None
    assets: list[dict[str, Any]] | None = None
    permissions: dict[str, Any] | None = None
    source: str | None = Field(default=None, alias="_source")
    url: str | None = Field(default=None, alias="_url")
