from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+psycopg://playforge:playforge@localhost:5432/playforge"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # Object storage (S3 compatible)
    S3_ENDPOINT: str = "http://localhost:9000"           # 服务端访问 OSS
    S3_PUBLIC_ENDPOINT: str = "http://localhost:9000"    # 浏览器访问 OSS（Play 远端加载）
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "playforge"
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

    # OAuth (optional)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    OAUTH_REDIRECT_BASE: str = "http://localhost:8000"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
