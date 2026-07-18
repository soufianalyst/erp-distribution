"""Application-wide settings loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Dev-only fallback (>=32 bytes for HS256). get_settings() refuses to start
# with this value unless DEBUG=true, so production deployments must set a
# real SECRET_KEY in .env.
INSECURE_DEFAULT_SECRET_KEY = "dev-only-secret-key-change-me-in-production-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "ERP Distribution Platform"
    API_V1_PREFIX: str = "/api/v1"
    # Also gates dev-only behavior: interactive API docs and the insecure
    # default SECRET_KEY are only allowed while DEBUG=true.
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/erp"
    # Dev convenience only — production schema changes must go through Alembic.
    AUTO_CREATE_TABLES: bool = False

    # Security / JWT
    SECRET_KEY: str = INSECURE_DEFAULT_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # First admin account, seeded on startup when the users table is empty.
    FIRST_ADMIN_USERNAME: str = "admin"
    FIRST_ADMIN_PASSWORD: str = "Admin@1234"
    FIRST_ADMIN_FULL_NAME: str = "مدير النظام"

    # Comma-separated list of allowed CORS origins for the React frontend.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.DEBUG and settings.SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY still has its insecure default value. Set a real "
            "SECRET_KEY in .env before running with DEBUG=false."
        )
    return settings
