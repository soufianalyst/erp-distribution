"""Application-wide settings loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Dev-only fallback (>=32 bytes for HS256). get_settings() refuses to start
# with this value unless DEBUG=true, so production deployments must set a
# real SECRET_KEY in .env.
INSECURE_DEFAULT_SECRET_KEY = "dev-only-secret-key-change-me-in-production-0123456789"

# The password the first admin is seeded with. Published in .env.example and in
# this repository, so it is public knowledge — get_settings() refuses to start on
# it outside debug for the same reason it refuses the default SECRET_KEY. A
# forgotten secret key is a silent weakness; a forgotten admin password is an
# unlocked front door to every screen in the system.
INSECURE_DEFAULT_ADMIN_PASSWORD = "Admin@1234"


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
    FIRST_ADMIN_PASSWORD: str = INSECURE_DEFAULT_ADMIN_PASSWORD
    FIRST_ADMIN_FULL_NAME: str = "مدير النظام"

    # Comma-separated list of allowed CORS origins for the React frontend.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"


@lru_cache
def async_database_url(url: str) -> str:
    """A database URL as SQLAlchemy's async driver needs to see it.

    Managed hosts hand out `postgres://` (Render, Heroku) or `postgresql://`; asyncpg
    only answers to `postgresql+asyncpg://`. Pasting a provider's URL in verbatim is the
    normal thing to do, so the normalisation belongs here rather than in the reader's
    head.

    Written once because it was written twice. The application engine and Alembic each
    carried their own copy and each handled only `postgresql://`, so a `postgres://` URL
    failed in both — with `Can't load plugin: sqlalchemy.dialects:postgres`, which names
    the symptom and not the cause.
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return f"postgresql+asyncpg://{url[len(prefix):]}"
    return url


def get_settings() -> Settings:
    """Load settings once, refusing to start on dev-only defaults outside debug.

    Every check here fails loudly at startup rather than warning, because each one
    guards something whose absence is invisible once the system is running: nobody
    notices a weak signing key, a public admin password, or a schema quietly
    diverging from its migrations until it has already cost something.
    """
    settings = Settings()
    if settings.DEBUG:
        return settings

    problems: list[str] = []
    if settings.SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
        problems.append(
            "SECRET_KEY still has its insecure default value — set a real one "
            "(e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
        )
    if settings.FIRST_ADMIN_PASSWORD == INSECURE_DEFAULT_ADMIN_PASSWORD:
        problems.append(
            "FIRST_ADMIN_PASSWORD is still the documented default, which is public "
            "knowledge — set a real password before the first admin is created."
        )
    if settings.AUTO_CREATE_TABLES:
        # This one is not hypothetical. AUTO_CREATE_TABLES creates *missing*
        # tables and never alters existing ones, so it hides schema drift instead
        # of fixing it: the app starts happily against a database that no
        # migration has ever produced, and the mismatch only surfaces later as a
        # failing insert. Production schema changes go through Alembic.
        problems.append(
            "AUTO_CREATE_TABLES must be false outside debug — it masks schema "
            "drift instead of migrating. Run `alembic upgrade head` instead."
        )
    if problems:
        raise RuntimeError(
            "Refusing to start with DEBUG=false and dev-only settings:\n  - "
            + "\n  - ".join(problems)
        )
    return settings
