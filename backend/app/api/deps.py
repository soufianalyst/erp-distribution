"""Shared FastAPI dependencies: current user resolution and role-based guards."""

from collections.abc import Awaitable, Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import has_permission
from app.core.security import decode_token
from app.db.session import get_db
from app.domain.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise AppException(401, "يجب تسجيل الدخول للوصول إلى هذه الخدمة.")
    payload = decode_token(credentials.credentials, expected_type="access")
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AppException(401, "الحساب غير موجود أو معطل.")
    return user


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[User]]:
    """Dependency factory: allow only users whose role is in `roles`."""

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise AppException(403, "ليس لديك الصلاحية اللازمة للقيام بهذه العملية.")
        return current_user

    return checker


def require_permissions(*permissions: str) -> Callable[..., Awaitable[User]]:
    """Dependency factory: allow only users holding ALL of the given permissions."""

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if not all(has_permission(current_user, p) for p in permissions):
            raise AppException(403, "ليس لديك الصلاحية اللازمة للقيام بهذه العملية.")
        return current_user

    return checker
