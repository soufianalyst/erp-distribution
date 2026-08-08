"""Customer portal endpoints.

Every endpoint resolves the authenticated customer from the signed-in user's
link (users.customer_id) — never from a client-supplied id — so one portal
account cannot reach another customer's data. Staff-side order confirmation
shares the `customers.manage` permission that already gates customers.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.portal import (
    CatalogItemOut,
    PortalAccountCreate,
    PortalAccountUpdate,
    PortalOrderCancel,
    PortalOrderConfirm,
    PortalOrderCreate,
    PortalOrderOut,
)
from app.api.schemas.sales import CustomerStatementOut, SalesInvoiceOut
from app.core.exceptions import AppException
from app.db.session import get_db
from app.domain.models.user import User
from app.services.portal.account_service import PortalAccountService
from app.services.portal.portal_service import PortalService
from app.services.sales.sales_service import SalesService

router = APIRouter(prefix="/portal", tags=["Customer Portal"])

customer_manage = require_permissions("customers.manage")


# --- Staff: portal accounts (admin creates the customer's login) -------------
@router.get("/accounts/{customer_id}", dependencies=[Depends(customer_manage)])
async def get_portal_account(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """حالة حساب البوابة المرتبط بالعميل (إن وُجد)."""
    account = await PortalAccountService(db).get(customer_id)
    return APIResponse(data=account)


@router.post(
    "/accounts/{customer_id}",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(customer_manage)],
)
async def create_portal_account(
    customer_id: int,
    body: PortalAccountCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """إنشاء أو استبدال حساب بوابة العملاء لعميل معين."""
    account = await PortalAccountService(db).create(customer_id, body)
    return APIResponse(data=account, message="تم إنشاء حساب البوابة للعميل.")


@router.patch(
    "/accounts/{customer_id}", dependencies=[Depends(customer_manage)]
)
async def update_portal_account(
    customer_id: int,
    body: PortalAccountUpdate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """تغيير كلمة مرور حساب البوابة أو تفعيله/تعطيله."""
    account = await PortalAccountService(db).update(customer_id, body)
    return APIResponse(data=account, message="تم تحديث حساب البوابة.")


# --- Customer: catalog, statement, invoices (scoped to the linked customer) --
@router.get("/catalog", response_model=APIResponse[list[CatalogItemOut]])
async def portal_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[list[CatalogItemOut]]:
    """دليل الأصناف مع الأرصدة الكمية فقط — بلا أي أسعار."""
    items = await PortalService(db).catalog(user=current_user)
    return APIResponse(data=items)


@router.get("/statement", response_model=APIResponse[CustomerStatementOut])
async def portal_statement(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[CustomerStatementOut]:
    """كشف حساب العميل: الفواتير، المرتجعات، المقبوضات، والرصيد."""
    service = PortalService(db)
    customer = await service.linked_customer(user=current_user)
    statement = await SalesService(db).portal_statement(customer.id)
    return APIResponse(data=statement)


@router.get("/invoices", response_model=APIResponse[list[SalesInvoiceOut]])
async def portal_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[list[SalesInvoiceOut]]:
    """فواتير العميل، الأحدث أولاً."""
    service = PortalService(db)
    customer = await service.linked_customer(user=current_user)
    invoices = await SalesService(db).invoices_for_customer(customer.id)
    return APIResponse(data=[SalesInvoiceOut.model_validate(i) for i in invoices])


@router.get("/invoices/{invoice_id}", response_model=APIResponse[SalesInvoiceOut])
async def portal_invoice_detail(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[SalesInvoiceOut]:
    """تفاصيل فاتورة تخص العميل المسجل فقط."""
    service = PortalService(db)
    customer = await service.linked_customer(user=current_user)
    invoice = await SalesService(db).get_invoice(invoice_id)
    if invoice.customer_id != customer.id:
        raise AppException(404, "الفاتورة غير موجودة.")
    return APIResponse(data=SalesInvoiceOut.model_validate(invoice))


# --- Customer: orders --------------------------------------------------------
@router.post(
    "/orders",
    response_model=APIResponse[PortalOrderOut],
    status_code=status.HTTP_201_CREATED,
)
async def portal_place_order(
    body: PortalOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[PortalOrderOut]:
    """تقديم طلب شراء — كميات فقط، بلا أسعار."""
    order = await PortalService(db).place_order(user=current_user, data=body)
    return APIResponse(
        data=PortalOrderOut.model_validate(order), message="تم استلام طلبك بنجاح."
    )


@router.get("/orders", response_model=APIResponse[list[PortalOrderOut]])
async def portal_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[list[PortalOrderOut]]:
    """طلبات العميل، الأحدث أولاً."""
    orders = await PortalService(db).list_orders(user=current_user)
    return APIResponse(data=[PortalOrderOut.model_validate(o) for o in orders])


@router.post(
    "/orders/{order_id}/cancel", response_model=APIResponse[PortalOrderOut]
)
async def cancel_portal_order(
    order_id: int,
    body: PortalOrderCancel,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[PortalOrderOut]:
    """إلغاء طلب لا يزال في حالة الانتظار."""
    order = await PortalService(db).cancel_order(
        order_id=order_id, user=current_user, reason=body.reason
    )
    return APIResponse(
        data=PortalOrderOut.model_validate(order), message="تم إلغاء الطلب."
    )


# --- Staff: confirmation queue -----------------------------------------------
@router.get("/orders/pending", response_model=APIResponse[list[PortalOrderOut]])
async def pending_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(customer_manage),
) -> APIResponse[list[PortalOrderOut]]:
    """طلبات العملاء في انتظار تأكيد فريق المبيعات."""
    orders = await PortalService(db).staff_list_pending(user=current_user)
    return APIResponse(data=[PortalOrderOut.model_validate(o) for o in orders])


@router.post(
    "/orders/{order_id}/confirm", response_model=APIResponse[PortalOrderOut]
)
async def confirm_order(
    order_id: int,
    body: PortalOrderConfirm,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(customer_manage),
) -> APIResponse[PortalOrderOut]:
    """تحويل طلب العميل إلى فاتورة مبيعات رسمية (مسار FEFO/ائتمان/محاسبة)."""
    order = await PortalService(db).staff_confirm(
        order_id=order_id,
        payment_method=body.payment_method,
        credit_override=body.credit_override,
        user=current_user,
    )
    return APIResponse(
        data=PortalOrderOut.model_validate(order),
        message="تم تحويل الطلب إلى فاتورة مبيعات بنجاح.",
    )