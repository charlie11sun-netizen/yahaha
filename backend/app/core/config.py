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
    MEMORY_VECTOR_ENABLED: bool = True
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
    MODEL_PRICING_JSON: str = ""

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
