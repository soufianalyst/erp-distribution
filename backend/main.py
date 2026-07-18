"""Application entry point: FastAPI app factory, startup seeding, and error envelopes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.domain.models.user import User, UserRole
from app.services.accounting.accounting_service import seed_chart_of_accounts

settings = get_settings()


async def seed_first_admin() -> None:
    """Create the initial admin account if the users table is empty."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is None:
            session.add(
                User(
                    username=settings.FIRST_ADMIN_USERNAME,
                    full_name=settings.FIRST_ADMIN_FULL_NAME,
                    hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
                    role=UserRole.ADMIN,
                )
            )
            await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.AUTO_CREATE_TABLES:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    await seed_first_admin()
    async with AsyncSessionLocal() as session:
        await seed_chart_of_accounts(session)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="نظام تخطيط موارد المؤسسات لشركات بيع وتوزيع المواد الغذائية بالجملة",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _envelope(status_code: int, message: str, data: object = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": data, "message": message},
    )


@app.exception_handler(AppException)
async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    return _envelope(exc.status_code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return _envelope(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return _envelope(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "البيانات المدخلة غير صالحة، يرجى التحقق من الحقول.",
        # exc.errors() can embed raw non-JSON types (e.g. Decimal) in the
        # echoed invalid input; jsonable_encoder normalizes them safely.
        data=jsonable_encoder(exc.errors()),
    )


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Health"])
async def health() -> dict[str, object]:
    """فحص جاهزية النظام."""
    return {
        "success": True,
        "data": {"status": "ok"},
        "message": "النظام يعمل بشكل سليم.",
    }
