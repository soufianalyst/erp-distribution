"""Cashier endpoints: receivables, payables, polymorphic payments, daily summary."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.sales import (
    CashierInvoiceSummary,
    DailySummaryOut,
    DailyPaymentDetail,
    PaymentIn,
)
from app.db.session import get_db
from app.domain.models.user import User
from app.services.cashier.cashier_service import CashierService

router = APIRouter(prefix="/cashier", tags=["Cashier"])

pending_view = Depends(require_permissions("cashier.view"))
receive_payment_perm = Depends(require_permissions("cashier.receive_payment"))


@router.get(
    "/receivables",
    response_model=APIResponse[list[CashierInvoiceSummary]],
    dependencies=[pending_view],
)
async def list_receivables(db: AsyncSession = Depends(get_db)):
    """فواتير المبيعات المعلقة — ذمم العملاء (المبالغ المستحقة علينا)."""
    items = await CashierService(db).list_pending_receivables()
    data = [
        CashierInvoiceSummary(
            type=item["type"],
            type_label=item["type_label"],
            account_label=item["account_label"],
            id=item["id"],
            date=item["date"],
            party_name=item["party_name"],
            payment_method=item["payment_method"],
            total=item["total"],
            paid_amount=item["paid_amount"],
            remaining=item["remaining"],
        )
        for item in items
    ]
    return APIResponse(data=data)


@router.get(
    "/payables",
    response_model=APIResponse[list[CashierInvoiceSummary]],
    dependencies=[pending_view],
)
async def list_payables(db: AsyncSession = Depends(get_db)):
    """فواتير المشتريات والمصروفات المعلقة — ذمم الموردين والمصروفات (المبالغ المستحقة منا)."""
    items = await CashierService(db).list_pending_payables()
    data = [
        CashierInvoiceSummary(
            type=item["type"],
            type_label=item["type_label"],
            account_label=item["account_label"],
            id=item["id"],
            date=item["date"],
            party_name=item["party_name"],
            payment_method=item["payment_method"],
            total=item["total"],
            paid_amount=item["paid_amount"],
            remaining=item["remaining"],
        )
        for item in items
    ]
    return APIResponse(data=data)


@router.post(
    "/pay",
    response_model=APIResponse[dict],
    dependencies=[receive_payment_perm],
)
async def receive_payment(
    body: PaymentIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("cashier.receive_payment")),
):
    """تسجيل تحصيل دفعة (كاملة أو جزئية) لأي فاتورة أو مصروف معلق."""
    result = await CashierService(db).receive_payment(
        body.reference_type,
        body.reference_id,
        Decimal(str(body.amount)),
        current_user.id,
    )
    return APIResponse(data=result, message="تم تسجيل التحصيل بنجاح.")


@router.get(
    "/daily-summary",
    response_model=APIResponse[DailySummaryOut],
    dependencies=[pending_view],
)
async def daily_summary(db: AsyncSession = Depends(get_db)):
    """ملخص تحصيلات الصندوق ليوم اليوم — لتسوية نهاية اليوم."""
    summary = await CashierService(db).daily_summary()
    return APIResponse(data=DailySummaryOut(**summary))
