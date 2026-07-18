"""Cashier endpoints: pending invoices/payables and cash movements (in and out)."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.cashier import (
    CashierAmountCreate,
    CashierDailySummaryOut,
    PendingPayableOut,
)
from app.api.schemas.common import APIResponse
from app.api.schemas.expenses import ExpenseOut
from app.api.schemas.purchases import PurchaseInvoiceOut
from app.api.schemas.sales import SalesInvoiceOut
from app.db.session import get_db
from app.domain.models.user import User
from app.services.cashier.cashier_service import CashierService

router = APIRouter(prefix="/cashier", tags=["Cashier"])

cashier_view = Depends(require_permissions("cashier.view"))


# --- Money in: sales collections ---
@router.get(
    "/invoices",
    response_model=APIResponse[list[SalesInvoiceOut]],
    dependencies=[cashier_view],
)
async def list_pending_invoices(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[SalesInvoiceOut]]:
    """الفواتير النقدية/بالبطاقة بانتظار التحصيل عند الصندوق."""
    invoices = await CashierService(db).list_pending_invoices()
    return APIResponse(data=[SalesInvoiceOut.model_validate(i) for i in invoices])


@router.post(
    "/invoices/{invoice_id}/collect",
    response_model=APIResponse[SalesInvoiceOut],
)
async def collect_payment(
    invoice_id: int,
    body: CashierAmountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("cashier.collect")),
) -> APIResponse[SalesInvoiceOut]:
    """تسجيل تحصيل نقدي أو بالبطاقة (كامل أو جزئي)؛ تُحرَّر الفاتورة لفريق التوزيع
    عند اكتمال تحصيل كامل قيمتها فقط."""
    invoice = await CashierService(db).collect_payment(
        invoice_id, body.amount, current_user
    )
    message = (
        "تم تحصيل قيمة الفاتورة بالكامل وتحريرها لفريق التوزيع."
        if invoice.payment_confirmed_at is not None
        else "تم تسجيل تحصيل جزئي؛ الفاتورة ما زالت بانتظار استكمال التحصيل."
    )
    return APIResponse(data=SalesInvoiceOut.model_validate(invoice), message=message)


# --- Money out: purchase invoices & expenses ---
@router.get(
    "/payables",
    response_model=APIResponse[list[PendingPayableOut]],
    dependencies=[cashier_view],
)
async def list_pending_payables(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[PendingPayableOut]]:
    """فواتير الشراء والمصاريف النقدية/بالبطاقة بانتظار السداد من الصندوق."""
    payables = await CashierService(db).list_pending_payables()
    return APIResponse(data=payables)


@router.post(
    "/purchases/{invoice_id}/pay",
    response_model=APIResponse[PurchaseInvoiceOut],
)
async def pay_purchase_invoice(
    invoice_id: int,
    body: CashierAmountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("cashier.pay")),
) -> APIResponse[PurchaseInvoiceOut]:
    """سداد فاتورة شراء نقداً أو بالبطاقة (كامل أو جزئي) من الصندوق."""
    invoice = await CashierService(db).pay_purchase_invoice(
        invoice_id, body.amount, current_user
    )
    message = (
        "تم سداد قيمة فاتورة الشراء بالكامل."
        if invoice.payment_confirmed_at is not None
        else "تم تسجيل سداد جزئي؛ الفاتورة ما زالت بانتظار استكمال السداد."
    )
    return APIResponse(data=PurchaseInvoiceOut.model_validate(invoice), message=message)


@router.post(
    "/expenses/{expense_id}/pay",
    response_model=APIResponse[ExpenseOut],
)
async def pay_expense(
    expense_id: int,
    body: CashierAmountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("cashier.pay")),
) -> APIResponse[ExpenseOut]:
    """سداد مصروف نقداً أو بالبطاقة (كامل أو جزئي) من الصندوق."""
    expense = await CashierService(db).pay_expense(expense_id, body.amount, current_user)
    message = (
        "تم سداد قيمة المصروف بالكامل."
        if expense.payment_confirmed_at is not None
        else "تم تسجيل سداد جزئي؛ المصروف ما زال بانتظار استكمال السداد."
    )
    return APIResponse(data=ExpenseOut.model_validate(expense), message=message)


# --- Daily summary ---
@router.get(
    "/daily-summary",
    response_model=APIResponse[CashierDailySummaryOut],
)
async def daily_summary(
    day: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("cashier.view")),
) -> APIResponse[CashierDailySummaryOut]:
    """ملخص ما تم تحصيله وصرفه اليوم (أو يوم محدد) لمساعدة أمين الصندوق على تقفيل يومه."""
    summary = await CashierService(db).daily_summary(current_user, day)
    return APIResponse(data=summary)
