"""Application-wide settings loaded from environment variables."""

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

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/erp"
    AUTO_CREATE_TABLES: bool = False

    SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    VAT_RATE: Decimal = Decimal("0.16")

    FIRST_ADMIN_USERNAME: str = "admin"
    FIRST_ADMIN_PASSWORD: str = ""
    FIRST_ADMIN_FULL_NAME: str = "مدير النظام"

    CORS_ORIGINS: str = ""


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Render provides postgresql:// — app needs postgresql+asyncpg://.
    if s.DATABASE_URL.startswith("postgresql://"):
        s.DATABASE_URL = s.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not s.SECRET_KEY:
        s.SECRET_KEY = secrets.token_hex(32)
    return s
