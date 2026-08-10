"""Customer portal routes — everything a customer can reach, and nothing else.

Two groups live here:

* `/portal/*` — authenticated as a *customer*. Every one of these scopes to
  `current_customer`, taken from the token. None of them accepts a customer id from
  the caller, so there is no identifier to tamper with.
* `/customer-logins/*` — authenticated as *staff*, for opening and withdrawing
  portal access. Guarded by its own permission so a salesman cannot mint a login.

Identity came first and alone, before anything was served through it. Everything a
customer may now do — read their statement and invoices, correct their own contact
details, browse the catalogue, place and withdraw orders — hangs off
`get_current_customer`, the dependency that also refuses anyone still carrying the
office's temporary password.

An order placed here is a request and nothing more: no stock moves, nothing is
reserved, and no price is shown or stored. The office prices it and issues the
invoice through the ordinary sales pipeline.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_customer,
    get_signed_in_customer,
    require_permissions,
)
from app.api.schemas.common import APIResponse
from app.core import rate_limit
from app.api.schemas.portal import (
    CustomerLoginCreateIn,
    CustomerLoginOut,
    CustomerLoginUpdateIn,
    CatalogItemOut,
    InvoiceDetailOut,
    InvoiceSummaryOut,
    PortalCustomerOut,
    PortalLoginIn,
    PortalOrderCancelIn,
    PortalOrderTimelineOut,
    PortalOrderCreateIn,
    PortalOrderOut,
    PortalPasswordChangeIn,
    PortalProfileUpdateIn,
    PortalRefreshIn,
    PortalStatementOut,
    PortalTokenPair,
    StaffOrderInvoiceIn,
    StaffOrderOut,
    StaffOrderRejectIn,
)
from app.api.schemas.sales import SalesInvoiceOut
from app.db.session import get_db
from app.domain.models.sales import Customer, CustomerLogin, CustomerOrderStatus
from app.domain.models.user import User
from app.services.portal.order_timeline import PortalOrderTimelineService
from app.services.portal.portal_auth_service import PortalAuthService
from app.services.portal.portal_data_service import PortalDataService
from app.services.portal.portal_order_service import (
    OrderReviewService,
    PortalOrderService,
)

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
    body: PortalLoginIn, request: Request, db: AsyncSession = Depends(get_db)
) -> APIResponse[PortalTokenPair]:
    """دخول العميل إلى بوابته."""
    # Before the password is even hashed: the per-account lockout cannot see an
    # attacker spreading one password across many shops, and each bcrypt check is
    # real work this box has to do while the warehouse is also using it.
    rate_limit.enforce(request, "portal-login")
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


# --- What the customer may read about their own account ---
# Every one of these takes `get_current_customer`, the strict dependency: a customer
# still on the office's temporary password gets no further than the password screen.
@router.get("/portal/statement", response_model=APIResponse[PortalStatementOut])
async def portal_statement(
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PortalStatementOut]:
    """كشف حساب العميل: الفواتير والمرتجعات والدفعات والرصيد."""
    data = await PortalDataService(db).statement(current_customer.id)
    return APIResponse(data=data)


@router.get("/portal/invoices", response_model=APIResponse[list[InvoiceSummaryOut]])
async def portal_invoices(
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[InvoiceSummaryOut]]:
    """فواتير العميل، الأحدث أولاً."""
    data = await PortalDataService(db).invoices(current_customer.id)
    return APIResponse(data=data)


@router.get(
    "/portal/invoices/{invoice_id}", response_model=APIResponse[InvoiceDetailOut]
)
async def portal_invoice(
    invoice_id: int,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[InvoiceDetailOut]:
    """تفاصيل فاتورة واحدة تخص العميل الحالي."""
    data = await PortalDataService(db).invoice(current_customer.id, invoice_id)
    return APIResponse(data=data)


@router.put("/portal/profile", response_model=APIResponse[PortalCustomerOut])
async def portal_update_profile(
    body: PortalProfileUpdateIn,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PortalCustomerOut]:
    """تعديل رقم الهاتف والعنوان."""
    service = PortalDataService(db)
    customer = await service.update_profile(current_customer.id, body)
    login = (
        await db.execute(
            select(CustomerLogin).where(CustomerLogin.customer_id == customer.id)
        )
    ).scalar_one()
    return APIResponse(
        data=PortalCustomerOut(
            customer_id=customer.id,
            name=customer.name,
            phone=customer.phone,
            address=customer.address,
            must_change_password=login.must_change_password,
        ),
        message="تم تحديث البيانات.",
    )


# --- Ordering ---
@router.get("/portal/catalog", response_model=APIResponse[list[CatalogItemOut]])
async def portal_catalog(
    search: str | None = None,
    limit: int = Query(default=60, ge=1, le=200),
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[CatalogItemOut]]:
    """الأصناف المتاحة للطلب مع مؤشر التوفر — بدون أسعار."""
    data = await PortalOrderService(db).catalog(
        current_customer, search=search, limit=limit
    )
    return APIResponse(data=data)


@router.post(
    "/portal/orders", response_model=APIResponse[PortalOrderOut], status_code=201
)
async def portal_place_order(
    body: PortalOrderCreateIn,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PortalOrderOut]:
    """إرسال طلب شراء للمراجعة من المكتب."""
    order = await PortalOrderService(db).place_order(current_customer.id, body)
    return APIResponse(
        data=order,
        message="تم استلام طلبك، وسيراجعه المكتب ويؤكده لك قريباً.",
    )


@router.get("/portal/orders", response_model=APIResponse[list[PortalOrderOut]])
async def portal_orders(
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[PortalOrderOut]]:
    """طلبات العميل وحالة كل منها."""
    data = await PortalOrderService(db).list_orders(current_customer.id)
    return APIResponse(data=data)


@router.get("/portal/orders/{order_id}", response_model=APIResponse[PortalOrderOut])
async def portal_order(
    order_id: int,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PortalOrderOut]:
    """تفاصيل طلب واحد يخص العميل الحالي."""
    data = await PortalOrderService(db).get_order(current_customer.id, order_id)
    return APIResponse(data=data)


@router.get(
    "/portal/orders/{order_id}/timeline",
    response_model=APIResponse[PortalOrderTimelineOut],
)
async def portal_order_timeline(
    order_id: int,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PortalOrderTimelineOut]:
    """تتبّع الطلب: أين وصل من لحظة إرساله حتى استلامه."""
    order = await PortalOrderService(db).own_order(current_customer.id, order_id)
    timeline = await PortalOrderTimelineService(db).timeline(order)
    return APIResponse(data=PortalOrderTimelineOut.model_validate(timeline))


@router.post(
    "/portal/orders/{order_id}/cancel", response_model=APIResponse[PortalOrderOut]
)
async def portal_cancel_order(
    order_id: int,
    body: PortalOrderCancelIn,
    current_customer: Customer = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[PortalOrderOut]:
    """إلغاء طلب ما زال قيد المراجعة."""
    data = await PortalOrderService(db).cancel_order(
        current_customer.id, order_id, body.reason
    )
    return APIResponse(data=data, message="تم إلغاء الطلب.")


# --- The office reviewing what customers asked for ---
review_orders = Depends(require_permissions("sales.orders_review"))


@router.get("/customer-orders", response_model=APIResponse[list[StaffOrderOut]])
async def list_customer_orders(
    status: Literal["pending", "confirmed", "invoiced", "cancelled"] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.orders_review")),
) -> APIResponse[list[StaffOrderOut]]:
    """طلبات العملاء من البوابة — الأقدم أولاً، ويمكن التصفية بالحالة."""
    data = await OrderReviewService(db).list_orders(
        current_user, CustomerOrderStatus(status) if status else None
    )
    return APIResponse(data=data)


@router.post(
    "/customer-orders/{order_id}/approve", response_model=APIResponse[StaffOrderOut]
)
async def approve_customer_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.orders_review")),
) -> APIResponse[StaffOrderOut]:
    """اعتماد الطلب ليبدأ التجهيز — دون إصدار فاتورة بعد."""
    data = await OrderReviewService(db).approve(order_id, current_user)
    return APIResponse(data=data, message="تم اعتماد الطلب.")


@router.post(
    "/customer-orders/{order_id}/reject", response_model=APIResponse[StaffOrderOut]
)
async def reject_customer_order(
    order_id: int,
    body: StaffOrderRejectIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.orders_review")),
) -> APIResponse[StaffOrderOut]:
    """رفض الطلب مع ذكر السبب — يظهر للعميل في بوابته."""
    data = await OrderReviewService(db).reject(order_id, body.reason, current_user)
    return APIResponse(data=data, message="تم رفض الطلب وإبلاغ العميل بالسبب.")


@router.post(
    "/customer-orders/{order_id}/invoice",
    response_model=APIResponse[SalesInvoiceOut],
    status_code=201,
)
async def invoice_customer_order(
    order_id: int,
    body: StaffOrderInvoiceIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.orders_review")),
) -> APIResponse[SalesInvoiceOut]:
    """تحويل الطلب إلى فاتورة مبيعات عبر المسار المعتاد (خصم FEFO والقيود)."""
    invoice = await OrderReviewService(db).to_invoice(order_id, body, current_user)
    return APIResponse(
        data=SalesInvoiceOut.model_validate(invoice),
        message="تم إصدار الفاتورة وربطها بالطلب.",
    )


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


@router.delete(
    "/customer-logins/{login_id}",
    response_model=APIResponse[None],
    dependencies=[manage_portal_access],
)
async def delete_customer_login(
    login_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[None]:
    """حذف حساب بوابة نهائياً — لا يمسّ العميل ولا فواتيره، فقط طريقة دخوله."""
    await PortalAuthService(db).delete_login(login_id)
    return APIResponse(data=None, message="تم حذف حساب البوابة.")


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
