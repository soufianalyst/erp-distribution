"""Async database engine and session dependency (FastAPI DI)."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# Render provides postgresql:// — force asyncpg driver.
_db_url = settings.DATABASE_URL
if _db_url and _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
# asyncpg uses ssl=, not sslmode= (Supabase requires SSL for external connections).
if "sslmode=" in _db_url:
    _db_url = _db_url.replace("sslmode=require", "ssl=require")

# Serverless-friendly: small pool (Supabase free tier allows ~60 connections).
engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=600,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a database session per request; FastAPI closes it automatically."""
    async with AsyncSessionLocal() as session:
        yield session
