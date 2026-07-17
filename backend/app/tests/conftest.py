"""Test fixtures: in-memory SQLite database and an HTTP client wired to the app."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.domain.models.user import User, UserRole
from app.services.accounting.accounting_service import seed_chart_of_accounts
from main import app

TEST_ADMIN_PASSWORD = "Admin@Test1234"
TEST_SALES_PASSWORD = "Sales@Test1234"
TEST_STORE_PASSWORD = "Store@Test1234"
TEST_ACCOUNTANT_PASSWORD = "Acct@Test1234"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    # StaticPool keeps a single in-memory SQLite connection alive across sessions.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        session.add_all(
            [
                User(
                    username="admin",
                    full_name="مدير النظام",
                    hashed_password=hash_password(TEST_ADMIN_PASSWORD),
                    role=UserRole.ADMIN,
                ),
                User(
                    username="salesman",
                    full_name="مندوب المبيعات",
                    hashed_password=hash_password(TEST_SALES_PASSWORD),
                    role=UserRole.SALES,
                ),
                User(
                    username="storekeeper",
                    full_name="أمين المستودع",
                    hashed_password=hash_password(TEST_STORE_PASSWORD),
                    role=UserRole.STOREKEEPER,
                ),
                User(
                    username="accountant",
                    full_name="المحاسب",
                    hashed_password=hash_password(TEST_ACCOUNTANT_PASSWORD),
                    role=UserRole.ACCOUNTANT,
                ),
                User(
                    username="disabled_user",
                    full_name="حساب معطل",
                    hashed_password=hash_password(TEST_SALES_PASSWORD),
                    role=UserRole.SALES,
                    is_active=False,
                ),
            ]
        )
        await session.commit()
        await seed_chart_of_accounts(session)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as override_session:
            yield override_session

    app.dependency_overrides[get_db] = override_get_db
    async with session_factory() as session:
        yield session
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    # ASGITransport does not trigger lifespan, so no real Postgres is needed in tests.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


async def login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    """Log in and return an Authorization header for subsequent requests."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}
