from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+psycopg://gameweave:gameweave@localhost:5432/gameweave"
    # 开发兜底建表（create_all 只能补缺表、不能补缺列）。生产 compose 置 false，
    # schema 只走 Alembic，避免掩盖迁移缺口。
    AUTO_CREATE_ALL: bool = True

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT_FAIL_OPEN: bool = False
    WORKER_MAX_MEMORY_PER_CHILD: int = 500_000
    CELERY_VISIBILITY_TIMEOUT: int = 7200
    GENERATION_TASK_SOFT_TIME_LIMIT: int = 3600
    GENERATION_TASK_TIME_LIMIT: int = 3900
    GENERATION_OUTBOX_SCAN_INTERVAL_SECONDS: float = 5.0
    GENERATION_OUTBOX_BATCH_SIZE: int = 100
    GENERATION_LOCK_RETRY_SECONDS: int = 3
    TASK_EVENTS_ENABLED: bool = True
    TASK_EVENTS_HEARTBEAT_SECONDS: float = 15.0

    # Object storage (S3 compatible)
    S3_ENDPOINT: str = "http://localhost:9000"           # 服务端访问 OSS
    S3_PUBLIC_ENDPOINT: str = "http://localhost:9000"    # 浏览器访问 OSS（Play 远端加载）
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "gameweave"
    S3_REGION: str = "us-east-1"

    # Auth (JWT)
    JWT_SECRET: str = "change-me-please-use-a-long-random-string"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080
    AUTH_COOKIE_NAME: str = "gameweave_session"
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    AUTH_COOKIE_DOMAIN: str = ""

    # Model service (OpenAI compatible)
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_NAME: str = "gpt-5.6-sol"
    USE_REAL_MODEL: bool = False
    REAL_MODEL_FALLBACK_ENABLED: bool = False
    MEMORY_VECTOR_ENABLED: bool = True
    OPENAI_MAX_RETRIES: int = 2
    OPENAI_RETRY_BACKOFF_SECONDS: float = 1.5
    MEMORY_EMBEDDING_MODEL: str = "text-embedding-3-small"
    MEMORY_VECTOR_DIMENSIONS: int = 1536
    MEMORY_ANN_CANDIDATES: int = 120
    MEMORY_HNSW_EF_SEARCH: int = 100
    MEMORY_EMBEDDING_API_KEY: str = ""
    MEMORY_EMBEDDING_BASE_URL: str = ""
    MEMORY_EMBEDDING_TIMEOUT: int = 15
    MEMORY_EXTRACTION_MODEL: str = "gpt-5.6-sol"
    MEMORY_EXTRACTION_TIMEOUT: int = 30
    MEMORY_RRF_K: int = 60
    MEMORY_LEXICAL_MIN_SCORE: float = 0.10
    MEMORY_SEMANTIC_MIN_SCORE: float = 0.20
    OPENAI_TIMEOUT: int = 600  # 写整个 game.js 耗时长，给足超时
    # Planning responses are streamed JSON. This is an idle/read timeout, not a
    # total generation deadline: active streams may continue for as long as needed.
    OPENAI_PLANNING_STREAM_IDLE_TIMEOUT: int = 180
    OPENAI_CODE_TIMEOUT: int = 1800
    # Agents SDK tool loops need a shorter idle/read boundary than the broad
    # client timeout. Active streams may run indefinitely; only a model turn
    # that emits no semantic event for this many seconds is retried.
    CODE_AGENT_STREAM_IDLE_TIMEOUT: int = 180
    OPENAI_ALLOW_PARTIAL_CODE_STREAM: bool = True
    OPENAI_PARTIAL_STREAM_MIN_CHARS: int = 2000
    MODEL_PRICING_JSON: str = ""
    # 修复回环内层 Agent（OpenAI Agents SDK 工具循环）。默认关闭：repair 节点沿用
    # "错误塞回 prompt 整体重生成"。开启后 build/revision 修复改为 read/write/run_checks
    # 最小修复 + 自测收敛；gameplay QA 的浏览器运行时报错也先走最小 patch 再回
    # build_validation 门禁。任何失败自动回落旧路径；仅 USE_REAL_MODEL=true 的任务生效。
    CODE_AGENT_ENABLED: bool = False
    # Gameplay-QA repairs routinely need reads + several patches + a check
    # round; 8 turns clipped real repairs mid-flight (observed in traces).
    CODE_AGENT_MAX_TURNS: int = 12
    CODE_AGENT_MODEL: str = ""  # 留空复用 MODEL_NAME
    # Optional Responses API routing key. Leave empty for compatible proxies
    # that reject prompt_cache_key; official OpenAI endpoints may opt in.
    # 非空才会随请求发送 prompt_cache_key。多上游负载均衡的网关靠它做缓存
    # 分片/渠道亲和;不发的话逐轮命中率全看路由运气（2026-07-13 实测:15 轮
    # 整跑仅 48%,单轮在 0%/52%/97% 之间波动）。
    CODE_AGENT_PROMPT_CACHE_KEY_PREFIX: str = "gameweave"
    # Some OpenAI-compatible gateways accept prompt_cache_key but reject the
    # GPT-5.6 prompt_cache_options/breakpoint fields. Keep explicit mode opt-in;
    # the shared >=1024-token planning prefix still caches in implicit mode.
    OPENAI_EXPLICIT_PROMPT_CACHE_ENABLED: bool = False
    # 作者模式：real 任务由 agent 在受限工具循环里逐文件扩展骨架。
    # For Phaser/Vite this agent edits the typed scenes/entities/systems/ui/config
    # tree and must pass TypeScript plus the isolated Vite build before returning.
    CODE_AGENT_AUTHOR_ENABLED: bool = False
    CODE_AGENT_AUTHOR_MAX_TURNS: int = 56
    # Opt-in because this persists complete prompts, model responses, tool
    # arguments/results, generated code, and exception tracebacks.
    CODE_AGENT_DETAILED_LOGGING_ENABLED: bool = False
    CODE_AGENT_TRACE_PAYLOAD_WARN_CHARS: int = Field(default=250_000, ge=1)
    # 0 keeps the complete serialized payload. Positive values opt into a
    # bounded preview for deployments that prefer a hard per-event DB limit.
    CODE_AGENT_TRACE_MAX_PAYLOAD_CHARS: int = Field(default=0, ge=0)
    CODE_AGENT_TRACE_RETENTION_DAYS: int = Field(default=7, ge=1)

    # Opik self-hosted Agent trace export. Keep disabled unless the SDK and
    # endpoint are intentionally configured; PostgreSQL traces remain the
    # local audit source regardless of this setting.
    OPIK_ENABLED: bool = False
    OPIK_URL_OVERRIDE: str = ""
    OPIK_PROJECT_NAME: str = "gameweave-agent"
    OPIK_WORKSPACE: str = "default"
    OPIK_ENVIRONMENT: str = "staging"
    # All newly generated 2D games use modular Phaser 3.90 + TypeScript.
    VITE_BUILD_TIMEOUT_MS: int = 120_000
    SANDBOX_BUILD_TIMEOUT_OVERHEAD_MS: int = 15_000

    # Game asset generation. Each modality is configured independently so an
    # operator may mix providers. "local" produces deterministic placeholders;
    # "openai-compatible" uses the configured /images, /audio, or /videos
    # endpoint. Disabled by default to avoid surprising external spend.
    ASSET_GENERATION_ENABLED: bool = False
    ASSET_GENERATION_FAIL_OPEN: bool = True
    # sheet 最多 ASSET_SHEET_MAX_PAGES(10) 页 + 背景变体(3) + 关键词触发的
    # bgm/动图,给足余量到 20;配额过小会把溢出页图集、场景变体或显式要求的
    # bgm 静默截掉(tileset 不占该配额,走 tilemap 分支)。
    ASSET_GENERATION_MAX_ITEMS: int = 20
    # 同时向图像网关发起的生成调用数。单张 sheet 实测 ~72s(quality=medium),
    # 3 页图集+背景串行要 ~5 分钟;并行 2 路把墙钟时间近似砍半,又不至于
    # 触发网关的并发限流。
    ASSET_GENERATION_CONCURRENCY: int = 2
    # 姿势/技能/敌人动作/道具动画帧扩容后,一局的图集页数上限(每页一次图像
    # 调用,16 格)。这是上限不是目标:排版器按 roster 实际大小开页,普通设计
    # 仍是 2-3 页;两梯队动画帧全开的满编 roster(12 敌人移动+攻击帧、Boss 特技、
    # 6 道具激活帧、玩家 5 技能+跳跃/死亡/胜利 ≈ 75-80 格)也只到第 5 页,10 是
    # "永不截断"的余量。角色帧组永不跨页(Phaser 动画帧必须同纹理)。
    ASSET_SHEET_MAX_PAGES: int = 10
    # 场景背景变体数(1-3):主场景 / 同场景高压(Boss)阶段 / 换区变体,
    # gameplay 代码按阶段切换 Backdrop 制造场景变化。
    ASSET_BACKGROUND_VARIANTS: int = 3
    TILEMAP_GENERATION_ENABLED: bool = True
    # gpt-image 级别的图片生成常见 90-180s；120s 会让客户端先断开、上游报
    # "context canceled"（2026-07-13 实测事故）。给足余量。
    ASSET_PROVIDER_TIMEOUT_SECONDS: int = 300
    ASSET_PROVIDER_MAX_RETRIES: int = 2
    ASSET_PROVIDER_MAX_BYTES: int = 8_000_000
    # Required spritesheet cells are never shipped on an audit failure. The
    # semantic review is opt-in because it sends generated images to the
    # configured vision model; when enabled, review errors are also hard
    # failures and eventually wait for manual recovery.
    ASSET_FRAME_AUDIT_MAX_RETRIES: int = 2
    ASSET_SEMANTIC_REVIEW_ENABLED: bool = False
    ASSET_SEMANTIC_REVIEW_MODEL: str = ""
    ASSET_SEMANTIC_REVIEW_TIMEOUT_SECONDS: int = 120
    ASSET_SEMANTIC_REVIEW_MAX_RETRIES: int = 2
    ASSET_SEMANTIC_REVIEW_MIN_CONFIDENCE: float = Field(default=0.85, ge=0.0, le=1.0)
    # 修复轮图像调用总预算(每张 sheet)与带伤放行的 required 覆盖率底线。
    # 第十二轮(2026-07-19):无预算的修复循环烧了 17 次串行图像调用/36 分钟,
    # 耗尽轮数后仍全任务暂停;现在预算耗尽或失败集不收缩即止损,覆盖率达标
    # 带 regeneration_plan 放行,低于底线才暂停等人工。
    ASSET_REPAIR_MAX_IMAGE_CALLS: int = 8
    ASSET_RELEASE_COVERAGE_FLOOR: float = Field(default=0.8, ge=0.0, le=1.0)
    ASSET_IMAGE_PROVIDER: str = "local"
    ASSET_IMAGE_API_KEY: str = ""
    ASSET_IMAGE_BASE_URL: str = ""
    ASSET_IMAGE_MODEL: str = ""
    # 可选的图像兜底提供商:主提供商重试耗尽后再走一遍(不配置=无兜底,行为
    # 不变)。用于单一网关图像端点半残(如 sheet 类请求恒 502)时保住流水线。
    ASSET_IMAGE_FALLBACK_PROVIDER: str = ""
    ASSET_IMAGE_FALLBACK_API_KEY: str = ""
    ASSET_IMAGE_FALLBACK_BASE_URL: str = ""
    ASSET_IMAGE_FALLBACK_MODEL: str = ""
    # OpenAI's Image API can emit partial-image SSE events. Keep this opt-in:
    # some third-party "compatible" gateways return an empty 200 SSE response.
    ASSET_IMAGE_STREAMING_ENABLED: bool = False
    ASSET_IMAGE_PARTIAL_IMAGES: int = 1
    # background=transparent 参数发送策略。auto=先发送,收到 "transparent
    # background is not supported" 后本进程剥离该参数重试(品红背景色键后处理
    # 天然兜底透明度);never=从不发送,省掉注定失败的首次 400。
    ASSET_IMAGE_NATIVE_TRANSPARENCY: str = "auto"
    ASSET_AUDIO_PROVIDER: str = ""
    ASSET_AUDIO_API_KEY: str = ""
    ASSET_AUDIO_BASE_URL: str = ""
    ASSET_AUDIO_MODEL: str = ""
    ASSET_VIDEO_PROVIDER: str = ""
    ASSET_VIDEO_API_KEY: str = ""
    ASSET_VIDEO_BASE_URL: str = ""
    ASSET_VIDEO_MODEL: str = ""

    # Observability. Empty DSN / OTLP endpoint keeps local development fully
    # offline. LOG_FORMAT=json is intended for production log aggregation.
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    LOG_FORMAT: str = "console"  # console | json
    LOG_LEVEL: str = "INFO"  # DEBUG | INFO | WARNING | ERROR | CRITICAL
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_TRACES_SAMPLE_RATE: float = 1.0

    # OAuth (optional)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    OAUTH_REDIRECT_BASE: str = "http://localhost:8000"
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    # Fixed shared demo identities are unsafe outside an explicit local demo.
    ENABLE_OAUTH_DEMO: bool = False
    # 演示故障注入（prompt 含 force-repair/force-replan 时故意注入违禁 API 触发
    # 修复回环）。仅限本地演示显式开启。
    DEMO_FAULT_INJECTION: bool = False

    # Build-time browser sandbox. Docker compose enables this service and keeps
    # SANDBOX_REQUIRED=true. Bare pytest/local backend runs may leave the URL
    # empty and keep the old V8 precheck as a non-blocking fallback.
    SANDBOX_URL: str = ""
    SANDBOX_REQUIRED: bool = False
    # Asset-heavy Phaser/Vite bundles routinely need 5-10s just to load; a 5s
    # goto timeout produced random frames=0 false failures at the QA gate.
    # 12MB 级素材包在冷启动 Chromium 里解码+首帧可到 15-20s（2026-07-15 实测
    # a5d9791e：QA2 load_ms=18.6s 险过，QA1/QA3 零帧超时被误判成代码缺陷烧掉
    # 整轮重生成）。预算给足，真正的启动挂死仍会在 24s 内暴露。
    SANDBOX_TIMEOUT_MS: int = 24000
    # Must stay above the sandbox runner's own outer headroom (timeout+12s)
    # or the client gives up while the runner is still finishing captures.
    SANDBOX_HTTP_TIMEOUT_OVERHEAD_MS: int = 16_000
    # Screenshot-based visual QA: deterministic blank-screen probe plus a VLM
    # soft gate on the after-input frame. Uses MODEL_NAME unless overridden.
    VISUAL_REVIEW_ENABLED: bool = True
    VISUAL_REVIEW_MODEL: str = ""
    VISUAL_REVIEW_TIMEOUT_SECONDS: int = 90
    MAX_ACTIVE_TASKS_PER_USER: int = 2
    TASK_TOKEN_BUDGET: int = 0
    # LangGraph superstep ceiling per run. The happy path takes ~19 supersteps
    # and a saturated repair/replan budget ~57; langgraph's default of 25 would
    # cut legitimate runs mid-repair. 80 keeps headroom for real work while a
    # runaway build/repair loop still dies with a dedicated RECURSION_LIMIT code.
    GRAPH_RECURSION_LIMIT: int = 80

    # Upload and content moderation hardening. Local/dev stays offline by
    # default: uploads are structurally validated, ClamAV is optional, and text
    # moderation uses the deterministic blocklist.
    UPLOAD_SCAN: str = "off"  # off | clamav
    CLAMD_HOST: str = "clamav"
    CLAMD_PORT: int = 3310
    MODERATION_PROVIDER: str = "blocklist"  # off | blocklist | llm
    MODERATION_MODE: str = "log"  # log | enforce
    MODERATION_CACHE_TTL_SECONDS: int = 24 * 60 * 60

    # Site access gate (front-door password). Empty = disabled (open). When set,
    # every API request must carry a matching X-Gate-Token; shared with the web
    # front-end via the same SITE_PASSWORD env var.
    SITE_PASSWORD: str = ""
    GATE_PUBLIC_BROWSE: bool = False

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
