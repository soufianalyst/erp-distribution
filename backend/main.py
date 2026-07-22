"""Application entry point: FastAPI app factory, startup seeding, and error envelopes."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core import audit_listeners  # noqa: F401 -- import registers the session hooks
from app.core.audit_context import current_user_id
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.security import decode_token, hash_password
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.domain.models.user import User, UserRole
from app.services.accounting.accounting_service import seed_chart_of_accounts

settings = get_settings()

logging.basicConfig(level=logging.INFO if settings.DEBUG else logging.WARNING)
logger = logging.getLogger("app")


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
    # Interactive docs leak schema/route details; only expose them in dev.
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    # The frontend authenticates with a Bearer token (see services/api.js), never
    # cookies, so credentialed CORS requests are not needed.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def populate_audit_user_context(request: Request, call_next):
    """Best-effort: decode the bearer token so the audit-log listeners can
    attribute changes to a user. Never blocks the request — actual auth
    enforcement stays with the route-level permission dependencies."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = decode_token(auth_header[7:], expected_type="access")
            current_user_id.set(int(payload["sub"]))
        except Exception:
            pass
    return await call_next(request)


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


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler so unexpected errors get the same response envelope
    (and never leak a stack trace) instead of Starlette's default 500 page."""
    logger.exception("Unhandled exception", exc_info=exc)
    return _envelope(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "حدث خطأ غير متوقع في الخادم، يرجى المحاولة لاحقاً.",
    )


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# Serve the built React frontend.
frontend_dist = Path(__file__).resolve().parent / "frontend" / "dist"


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str = "") -> JSONResponse:
    """Serve the React SPA for non-API routes, or health check for root."""
    if not full_path:
        return JSONResponse(
            status_code=200,
            content={"success": True, "data": {"status": "ok"}, "message": "النظام يعمل بشكل سليم."},
        )
    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"success": False, "data": None, "message": "غير موجود"})
    if frontend_dist.is_dir():
        file_path = frontend_dist / full_path
        if file_path.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(str(file_path))
        index = frontend_dist / "index.html"
        if index.exists():
            from fastapi.responses import HTMLResponse
            return HTMLResponse(content=index.read_text(encoding="utf-8"), status_code=200)
    return JSONResponse(status_code=404, content={"success": False, "data": None, "message": "غير موجود"})
