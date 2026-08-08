"""Customer portal routes — everything a customer can reach, and nothing else.

Two groups live here:

* `/portal/*` — authenticated as a *customer*. Every one of these scopes to
  `current_customer`, taken from the token. None of them accepts a customer id from
  the caller, so there is no identifier to tamper with.
* `/customer-logins/*` — authenticated as *staff*, for opening and withdrawing
  portal access. Guarded by its own permission so a salesman cannot mint a login.

Phase 0 deliberately stops at identity. There is no statement, no invoice and no
ordering here yet: the isolation has to be right before anything is served through
it.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_signed_in_customer, require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.portal import (
    CustomerLoginCreateIn,
    CustomerLoginOut,
    CustomerLoginUpdateIn,
    PortalCustomerOut,
    PortalLoginIn,
    PortalPasswordChangeIn,
    PortalRefreshIn,
    PortalTokenPair,
)
from app.db.session import get_db
from app.domain.models.sales import Customer, CustomerLogin
from app.domain.models.user import User
from app.services.portal.portal_auth_service import PortalAuthService

router = APIRouter(tags=["portal"])

manage_portal_access = Depends(require_permissions("customers.portal_access"))


def _login_out(login: CustomerLogin) -> CustomerLoginOut:
    return CustomerLoginOut(
        id=login.id,
        customer_id=login.customer_id,
        customer_name=login.customer.name if login.customer else None,
        login_id=login.login_id,
        is_active=login.is_active,
        must_change_password=login.must_change_password,
        # Asked of the service rather than recomputed here: "still locked?" is a
        # question with one right answer, and the second copy is the one that rots.
        is_locked=PortalAuthService._is_locked(login),
        last_login_at=login.last_login_at,
        created_at=login.created_at,
    )


# --- The customer's own session ---
@router.post("/portal/auth/login", response_model=APIResponse[PortalTokenPair])
async def portal_login(
    body: PortalLoginIn, db: AsyncSession = Depends(get_db)
) -> APIResponse[PortalTokenPair]:
    """دخول العميل إلى بوابته."""
    tokens = await PortalAuthService(db).authenticate(body.login_id, body.password)
    return APIResponse(data=tokens, message="أهلاً بك.")


@router.post("/portal/auth/refresh", response_model=APIResponse[PortalTokenPair])
async def portal_refresh(
    body: PortalRefreshIn, db: AsyncSession = Depends(get_db)
) -> APIResponse[PortalTokenPair]:
    """تجديد جلسة العميل."""
    tokens = await PortalAuthService(db).refresh(body.refresh_token)
    return APIResponse(data=tokens)


@router.get("/portal/me", response_model=APIResponse[PortalCustomerOut])
async def portal_me(
    current_customer: Customer = Depends(get_signed_in_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PortalCustomerOut]:
    """بيانات العميل الحالي كما تراها البوابة."""
    from sqlalchemy import select

    login = (
        await db.execute(
            select(CustomerLogin).where(CustomerLogin.customer_id == current_customer.id)
        )
    ).scalar_one()
    return APIResponse(
        data=PortalCustomerOut(
            customer_id=current_customer.id,
            name=current_customer.name,
            phone=current_customer.phone,
            address=current_customer.address,
            must_change_password=login.must_change_password,
        )
    )


@router.post("/portal/auth/change-password", response_model=APIResponse[None])
async def portal_change_password(
    body: PortalPasswordChangeIn,
    current_customer: Customer = Depends(get_signed_in_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[None]:
    """تغيير كلمة المرور — إلزامي بعد أول دخول بكلمة مؤقتة."""
    await PortalAuthService(db).change_password(
        current_customer.id, body.current_password, body.new_password
    )
    return APIResponse(data=None, message="تم تغيير كلمة المرور.")


# --- The office managing who can get in ---
@router.get(
    "/customer-logins",
    response_model=APIResponse[list[CustomerLoginOut]],
    dependencies=[manage_portal_access],
)
async def list_customer_logins(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[CustomerLoginOut]]:
    """حسابات العملاء على البوابة وحالة كل منها."""
    logins = await PortalAuthService(db).list_logins()
    return APIResponse(data=[_login_out(login) for login in logins])


@router.post(
    "/customer-logins",
    response_model=APIResponse[CustomerLoginOut],
    status_code=201,
)
async def create_customer_login(
    body: CustomerLoginCreateIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("customers.portal_access")),
) -> APIResponse[CustomerLoginOut]:
    """فتح حساب بوابة لعميل بكلمة مرور مؤقتة يسلّمها المكتب."""
    login = await PortalAuthService(db).create_login(body, current_user.id)
    return APIResponse(
        data=_login_out(login),
        message="تم فتح الحساب. سلّم العميل كلمة المرور المؤقتة؛ سيُطلب منه تغييرها.",
    )


@router.put(
    "/customer-logins/{login_id}",
    response_model=APIResponse[CustomerLoginOut],
    dependencies=[manage_portal_access],
)
async def update_customer_login(
    login_id: int,
    body: CustomerLoginUpdateIn,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[CustomerLoginOut]:
    """إيقاف حساب أو إعادة تفعيله أو إعطاؤه كلمة مرور مؤقتة جديدة."""
    login = await PortalAuthService(db).update_login(login_id, body)
    return APIResponse(data=_login_out(login), message="تم تحديث الحساب.")
