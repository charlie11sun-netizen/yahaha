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
    WORKER_MAX_MEMORY_PER_CHILD: int = 500_000
    CELERY_VISIBILITY_TIMEOUT: int = 7200
    GENERATION_TASK_SOFT_TIME_LIMIT: int = 3600
    GENERATION_TASK_TIME_LIMIT: int = 3900

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

    # Model service (OpenAI compatible)
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_NAME: str = "gpt-5.5"
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
    MEMORY_EXTRACTION_MODEL: str = "gpt-4.1-mini"
    MEMORY_EXTRACTION_TIMEOUT: int = 30
    MEMORY_RRF_K: int = 60
    MEMORY_LEXICAL_MIN_SCORE: float = 0.10
    MEMORY_SEMANTIC_MIN_SCORE: float = 0.20
    OPENAI_TIMEOUT: int = 600  # 写整个 game.js 耗时长，给足超时
    OPENAI_CODE_TIMEOUT: int = 1800
    OPENAI_ALLOW_PARTIAL_CODE_STREAM: bool = True
    OPENAI_PARTIAL_STREAM_MIN_CHARS: int = 2000
    MODEL_PRICING_JSON: str = ""
    # 修复回环内层 Agent（OpenAI Agents SDK 工具循环）。默认关闭：repair 节点沿用
    # "错误塞回 prompt 整体重生成"。开启后 build/revision 修复改为 read/write/run_checks
    # 最小修复 + 自测收敛；gameplay QA 的浏览器运行时报错也先走最小 patch 再回
    # build_validation 门禁。任何失败自动回落旧路径；仅 USE_REAL_MODEL=true 的任务生效。
    CODE_AGENT_ENABLED: bool = False
    CODE_AGENT_MAX_TURNS: int = 8
    CODE_AGENT_MODEL: str = ""  # 留空复用 MODEL_NAME
    # 作者模式试点（2D）：real 任务由 agent 在工具循环里从骨架逐文件写出游戏，
    # 文件结构自定（write_file / V4A Add File，平铺 .js/.css，配额见 validation）。
    # 每轮一个小 patch，绕开单请求超时墙；agent 不可用/产出过短自动回落单次整包
    # 生成。产物仍过 build_validation / gameplay QA 门禁。
    CODE_AGENT_AUTHOR_ENABLED: bool = False
    CODE_AGENT_AUTHOR_MAX_TURNS: int = 32
    # 2D 生成运行时试点：true 时 real 模式的 2D 代码生成改用自托管 Phaser 4
    # （vendor/phaser.min.js，全局 Phaser，与 3D three.min.js 同模式随包发布）。
    # 模板兜底仍是 Canvas；模型失败/过短的回退逻辑不变。默认关闭灰度。
    PHASER_2D_ENABLED: bool = False

    # Observability. Empty DSN / OTLP endpoint keeps local development fully
    # offline. LOG_FORMAT=json is intended for production log aggregation.
    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "development"
    LOG_FORMAT: str = "console"  # console | json
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
    SANDBOX_TIMEOUT_MS: int = 5000
    SANDBOX_HTTP_TIMEOUT_OVERHEAD_MS: int = 10_000
    MAX_ACTIVE_TASKS_PER_USER: int = 2
    TASK_TOKEN_BUDGET: int = 0

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
