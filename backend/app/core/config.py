"""Application-wide settings loaded from environment variables / .env file."""

import secrets
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
    DEBUG: bool = False

    # Database — must be set in .env for production.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/erp"
    # Production: schema changes ONLY via Alembic migrations.
    AUTO_CREATE_TABLES: bool = False

    # Security / JWT — SECRET_KEY is mandatory in production.
    SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # VAT rate applied on sales invoices (e.g. 0.16 = 16%).
    VAT_RATE: Decimal = Decimal("0.16")

    # First admin account — seeded on startup when users table is empty.
    FIRST_ADMIN_USERNAME: str = "admin"
    FIRST_ADMIN_PASSWORD: str = ""
    FIRST_ADMIN_FULL_NAME: str = "مدير النظام"

    # Comma-separated list of allowed CORS origins.
    CORS_ORIGINS: str = ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Render / Supabase provide postgresql:// — asyncpg needs +asyncpg.
    if settings.DATABASE_URL.startswith("postgresql://"):
        settings.DATABASE_URL = settings.DATABASE_URL.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
    # Generate a random SECRET_KEY if not provided (dev convenience).
    if not settings.SECRET_KEY:
        settings.SECRET_KEY = secrets.token_hex(32)
    return settings
