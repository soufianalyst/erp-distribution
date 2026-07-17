"""Application-wide settings loaded from environment variables / .env file."""

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "ERP Distribution Platform"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/erp"
    # Dev convenience only — production schema changes must go through Alembic.
    AUTO_CREATE_TABLES: bool = True

    # Security / JWT
    # Dev-only fallback (>=32 bytes for HS256); always override via .env in production.
    SECRET_KEY: str = "dev-only-secret-key-change-me-in-production-0123456789"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # VAT rate applied on sales invoices (e.g. 0.16 = 16%).
    VAT_RATE: Decimal = Decimal("0.16")

    # First admin account, seeded on startup when the users table is empty.
    FIRST_ADMIN_USERNAME: str = "admin"
    FIRST_ADMIN_PASSWORD: str = "Admin@1234"
    FIRST_ADMIN_FULL_NAME: str = "مدير النظام"

    # Comma-separated list of allowed CORS origins for the React frontend.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
