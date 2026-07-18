"""Accounting endpoints: chart of accounts, journal entries, and reports."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.accounting import (
    AccountCreate,
    AccountOut,
    JournalEntryOut,
    ManualEntryCreate,
    TaxSummaryOut,
    TrialBalanceOut,
)
from app.api.schemas.common import APIResponse
from app.db.session import get_db
from app.domain.models.user import User
from app.services.accounting.accounting_service import AccountingService

router = APIRouter(prefix="/accounting", tags=["Accounting"])

# Each operation is gated by a granular permission (roles only supply defaults).
accounting_view = Depends(require_permissions("accounting.view"))
accounting_post = Depends(require_permissions("accounting.manual_entry"))


@router.get(
    "/accounts",
    response_model=APIResponse[list[AccountOut]],
    dependencies=[accounting_view],
)
async def list_accounts(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[AccountOut]]:
    """عرض دليل الحسابات."""
    accounts = await AccountingService(db).list_accounts()
    return APIResponse(data=[AccountOut.model_validate(a) for a in accounts])


@router.post(
    "/accounts",
    response_model=APIResponse[AccountOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[accounting_post],
)
async def create_account(
    body: AccountCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[AccountOut]:
    """إضافة حساب جديد إلى دليل الحسابات."""
    account = await AccountingService(db).create_account(body)
    return APIResponse(
        data=AccountOut.model_validate(account), message="تم إنشاء الحساب بنجاح."
    )


@router.get(
    "/journal-entries",
    response_model=APIResponse[list[JournalEntryOut]],
    dependencies=[accounting_view],
)
async def list_journal_entries(
    reference_type: str | None = Query(default=None, description="نوع المستند المصدر"),
    reference_id: int | None = Query(default=None, description="رقم المستند المصدر"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[JournalEntryOut]]:
    """عرض قيود اليومية، مع إمكانية التصفية حسب المستند المصدر."""
    entries = await AccountingService(db).list_entries(reference_type, reference_id)
    return APIResponse(data=[JournalEntryOut.model_validate(e) for e in entries])


@router.get(
    "/journal-entries/{entry_id}",
    response_model=APIResponse[JournalEntryOut],
    dependencies=[accounting_view],
)
async def get_journal_entry(
    entry_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[JournalEntryOut]:
    """عرض قيد يومية واحد بأطرافه المدينة والدائنة."""
    entry = await AccountingService(db).get_entry(entry_id)
    return APIResponse(data=JournalEntryOut.model_validate(entry))


@router.post(
    "/journal-entries",
    response_model=APIResponse[JournalEntryOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_entry(
    body: ManualEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("accounting.manual_entry")),
) -> APIResponse[JournalEntryOut]:
    """إنشاء قيد يومية يدوي؛ يُرفض أي قيد غير متوازن."""
    entry = await AccountingService(db).create_manual_entry(
        body, created_by=current_user.id
    )
    return APIResponse(
        data=JournalEntryOut.model_validate(entry), message="تم تسجيل القيد بنجاح."
    )


@router.get(
    "/reports/trial-balance",
    response_model=APIResponse[TrialBalanceOut],
    dependencies=[accounting_view],
)
async def trial_balance(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TrialBalanceOut]:
    """ميزان المراجعة: مجاميع الحركة المدينة والدائنة لكل حساب."""
    report = await AccountingService(db).trial_balance()
    return APIResponse(data=report)


@router.get(
    "/reports/tax-summary",
    response_model=APIResponse[TaxSummaryOut],
    dependencies=[accounting_view],
)
async def tax_summary(
    date_from: date | None = Query(default=None, description="بداية الفترة"),
    date_to: date | None = Query(default=None, description="نهاية الفترة"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TaxSummaryOut]:
    """تقرير الضرائب: الضريبة المحصلة على المبيعات مقابل الضريبة المدفوعة في المشتريات."""
    report = await AccountingService(db).tax_summary(date_from, date_to)
    return APIResponse(data=report)
