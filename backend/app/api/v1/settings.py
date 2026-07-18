"""Settings endpoints: configurable tax rates and company identity."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.settings import (
    CompanySettingsOut,
    CompanySettingsUpdate,
    TaxRateCreate,
    TaxRateOut,
    TaxRateUpdate,
)
from app.db.session import get_db
from app.services.settings.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["Settings"])

settings_view = Depends(require_permissions("settings.view"))
settings_manage = Depends(require_permissions("settings.manage"))


@router.get(
    "/tax-rates",
    response_model=APIResponse[list[TaxRateOut]],
    dependencies=[settings_view],
)
async def list_tax_rates(
    active_only: bool = False, db: AsyncSession = Depends(get_db)
) -> APIResponse[list[TaxRateOut]]:
    """عرض قائمة الضرائب المعرّفة (مع خيار الأنواع المفعّلة فقط)."""
    tax_rates = await SettingsService(db).list_tax_rates(active_only)
    return APIResponse(data=[TaxRateOut.model_validate(t) for t in tax_rates])


@router.post(
    "/tax-rates",
    response_model=APIResponse[TaxRateOut],
    status_code=201,
    dependencies=[settings_manage],
)
async def create_tax_rate(
    body: TaxRateCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[TaxRateOut]:
    """إضافة نوع ضريبة جديد (مثال: ضريبة قيمة مضافة، ضريبة مبيعات، GST)."""
    tax_rate = await SettingsService(db).create_tax_rate(body)
    return APIResponse(
        data=TaxRateOut.model_validate(tax_rate), message="تم إضافة الضريبة بنجاح."
    )


@router.patch(
    "/tax-rates/{tax_rate_id}",
    response_model=APIResponse[TaxRateOut],
    dependencies=[settings_manage],
)
async def update_tax_rate(
    tax_rate_id: int, body: TaxRateUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[TaxRateOut]:
    """تعديل ضريبة موجودة (النسبة، التفعيل، أو جعلها الافتراضية)."""
    tax_rate = await SettingsService(db).update_tax_rate(tax_rate_id, body)
    return APIResponse(
        data=TaxRateOut.model_validate(tax_rate), message="تم تحديث الضريبة بنجاح."
    )


@router.delete(
    "/tax-rates/{tax_rate_id}",
    response_model=APIResponse[None],
    dependencies=[settings_manage],
)
async def delete_tax_rate(
    tax_rate_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[None]:
    """حذف ضريبة معرّفة؛ الفواتير السابقة تحتفظ بقيمتها المطبّقة وقت الإصدار."""
    await SettingsService(db).delete_tax_rate(tax_rate_id)
    return APIResponse(data=None, message="تم حذف الضريبة بنجاح.")


@router.get(
    "/company",
    response_model=APIResponse[CompanySettingsOut],
    dependencies=[settings_view],
)
async def get_company_settings(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[CompanySettingsOut]:
    """عرض بيانات الشركة المستخدمة في رأس المستندات المطبوعة."""
    company = await SettingsService(db).get_company_settings()
    return APIResponse(data=CompanySettingsOut.model_validate(company))


@router.put(
    "/company",
    response_model=APIResponse[CompanySettingsOut],
    dependencies=[settings_manage],
)
async def update_company_settings(
    body: CompanySettingsUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[CompanySettingsOut]:
    """تحديث بيانات الشركة (الاسم، العنوان، الهاتف، الرقم الضريبي، العملة)."""
    company = await SettingsService(db).update_company_settings(body)
    return APIResponse(
        data=CompanySettingsOut.model_validate(company),
        message="تم تحديث بيانات الشركة بنجاح.",
    )
