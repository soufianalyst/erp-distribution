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

    # Database — reads DATABASE_URL env var; falls back to Supabase production DB.
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:Wazvu3-ruwzej-wajsop"
        "@db.bquxudmlyldlgbjfbmrr.supabase.co:5432/postgres"
    )
    # Production: schema changes ONLY via Alembic migrations.
    AUTO_CREATE_TABLES: bool = False
    # Seed admin + chart of accounts on startup (disable in serverless after first run).
    SEED_ON_STARTUP: bool = False

    # Security / JWT — SECRET_KEY is mandatory in production.
    SECRET_KEY: str = "erp-prod-2026-xK9mPq3vLz7wRt5nBj8cFd2gHs4yUe0a"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # VAT rate applied on sales invoices (e.g. 0.16 = 16%).
    VAT_RATE: Decimal = Decimal("0.16")

    # First admin account — seeded on startup when users table is empty.
    FIRST_ADMIN_USERNAME: str = "admin"
    FIRST_ADMIN_PASSWORD: str = "Adm1n@Erp2026!"
    FIRST_ADMIN_FULL_NAME: str = "مدير النظام"

    # Comma-separated list of allowed CORS origins.
    CORS_ORIGINS: str = "*"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Generate a random SECRET_KEY if not provided (dev convenience).
    if not settings.SECRET_KEY:
        settings.SECRET_KEY = secrets.token_hex(32)
    return settings
