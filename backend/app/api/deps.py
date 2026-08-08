"""Shared FastAPI dependencies: current user resolution and role-based guards."""

from collections.abc import Awaitable, Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import has_permission
from sqlalchemy import select

from app.core.security import decode_token
from app.db.session import get_db
from app.domain.models.sales import Customer, CustomerLogin
from app.domain.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the bearer token to an active user, or reject the request."""
    if credentials is None:
        raise AppException(401, "يجب تسجيل الدخول للوصول إلى هذه الخدمة.")
    # `expected_realm` is what stops a customer's token from being read as a staff
    # one. Both realms number their subjects from 1, so without it customer 7 would
    # resolve to user 7 — and inherit whatever role that employee holds.
    payload = decode_token(
        credentials.credentials, expected_type="access", expected_realm="staff"
    )
    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AppException(401, "الحساب غير موجود أو معطل.")
    return user


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[User]]:
    """Dependency factory: allow only users whose role is in `roles`."""

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        """Allow the request through only for one of the listed roles."""
        if current_user.role not in roles:
            raise AppException(403, "ليس لديك الصلاحية اللازمة للقيام بهذه العملية.")
        return current_user

    return checker


def require_permissions(*permissions: str) -> Callable[..., Awaitable[User]]:
    """Dependency factory: allow only users holding ALL of the given permissions."""

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        """Allow the request through only when the user holds every permission."""
        if not all(has_permission(current_user, p) for p in permissions):
            raise AppException(403, "ليس لديك الصلاحية اللازمة للقيام بهذه العملية.")
        return current_user

    return checker


async def get_signed_in_customer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Customer:
    """Resolve a portal bearer token to the customer it belongs to.

    The mirror of `get_current_user`, and separate from it for the same reason the
    tables are separate: one function that returned "a principal" would sooner or
    later be trusted by a route that meant the other kind.

    Everything the portal serves is scoped by the customer this returns. No portal
    route takes a customer id from the caller — there is nothing to tamper with.

    This one accepts a customer who is still on the temporary password the office
    handed them, so use it only for the two routes that have to work in that state:
    reading who you are, and changing the password. Everything else takes
    `get_current_customer`.
    """
    if credentials is None:
        raise AppException(401, "يجب تسجيل الدخول للوصول إلى هذه الخدمة.")
    payload = decode_token(
        credentials.credentials, expected_type="access", expected_realm="customer"
    )
    customer = await db.get(Customer, int(payload["sub"]))
    if customer is None or not customer.is_active:
        raise AppException(401, "الحساب غير موجود أو موقوف.")

    # The customer may exist while their way in has been withdrawn. Checked on every
    # request rather than only at sign-in, so revoking access takes effect at once
    # instead of whenever the access token happens to expire.
    login = (
        await db.execute(
            select(CustomerLogin).where(CustomerLogin.customer_id == customer.id)
        )
    ).scalar_one_or_none()
    if login is None or not login.is_active:
        raise AppException(401, "الحساب غير موجود أو موقوف.")
    return customer


async def get_current_customer(
    customer: Customer = Depends(get_signed_in_customer),
    db: AsyncSession = Depends(get_db),
) -> Customer:
    """The customer, with the forced password change already behind them.

    The strict one, and the one every portal route serving actual data must use. The
    office hands out a temporary password by phone, which means for a while it exists
    in a WhatsApp message and in someone's memory. Refusing the rest of the portal
    until it is replaced keeps that window to the password screen alone.

    Enforced here rather than in each route so a route added later inherits it by
    default — the name to reach for is this one, and the permissive
    `get_signed_in_customer` has to be asked for deliberately.
    """
    login = (
        await db.execute(
            select(CustomerLogin).where(CustomerLogin.customer_id == customer.id)
        )
    ).scalar_one_or_none()
    if login is not None and login.must_change_password:
        raise AppException(403, "يلزم تغيير كلمة المرور المؤقتة قبل متابعة الاستخدام.")
    return customer
