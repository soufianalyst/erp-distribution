"""Analytics/dashboard endpoints: RFM, trends, waste, credit risk, delivery, reps."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.analytics import (
    ARAgingRowOut,
    CreditRiskCustomerOut,
    CustomerRFMOut,
    DamageReportOut,
    DiscountReportOut,
    DashboardSummaryOut,
    DriverPerformanceOut,
    ExpiryRiskOut,
    ExpiryWorklistOut,
    FulfillmentSummaryOut,
    LapsingReportOut,
    PriceTierRevenueOut,
    ProductRFMOut,
    RepPerformanceOut,
    ReturnsTrendPointOut,
    SalesTrendPointOut,
    TurnoverOut,
    WarehouseRevenueOut,
)
from app.api.schemas.common import APIResponse
from app.db.session import get_db
from app.services.analytics.analytics_service import AnalyticsService
from app.services.analytics.expiry_worklist_service import ExpiryWorklistService
from app.services.analytics.lapsing_service import LapsingService

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
    dependencies=[Depends(require_permissions("analytics.view"))],
)


@router.get("/summary", response_model=APIResponse[DashboardSummaryOut])
async def summary(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DashboardSummaryOut]:
    """مؤشرات الأداء الرئيسية للوحة التحليلات (آخر 12 شهراً)."""
    return APIResponse(data=await AnalyticsService(db).dashboard_summary())


@router.get("/customers/rfm", response_model=APIResponse[list[CustomerRFMOut]])
async def customer_rfm(
    product_id: int | None = Query(
        default=None, description="حصر التحليل بصنف واحد؛ اتركه فارغاً لكل الأصناف"
    ),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[CustomerRFMOut]]:
    """تحليل RFM للعملاء: الحداثة، التكرار، والقيمة النقدية مع تصنيف الشرائح.

    عند تحديد صنف، تُحسب المؤشرات الثلاثة على مشتريات ذلك الصنف وحده، ويبقى
    العملاء الذين لم يشتروه في القائمة بقيمة صفر — فتصبح قائمة استهداف.
    """
    return APIResponse(data=await AnalyticsService(db).customer_rfm(product_id))


@router.get("/products/rfm", response_model=APIResponse[list[ProductRFMOut]])
async def product_rfm(
    customer_id: int | None = Query(
        default=None, description="حصر التحليل بعميل واحد؛ اتركه فارغاً لكل العملاء"
    ),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ProductRFMOut]]:
    """تحليل RFM للأصناف مع الربط بالمخزون الحالي وأقرب تاريخ انتهاء صلاحية.

    عند تحديد عميل، تُحسب المبيعات والهامش لذلك العميل وحده، ويبقى المخزون
    وأقرب صلاحية على مستوى الشركة لأنهما وصف للرفّ لا للعميل.
    """
    return APIResponse(data=await AnalyticsService(db).product_rfm(customer_id))


@router.get("/sales/trend", response_model=APIResponse[list[SalesTrendPointOut]])
async def sales_trend(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[SalesTrendPointOut]]:
    """اتجاه المبيعات الشهري: الإيرادات، الضريبة، الهامش، ونقدي مقابل آجل."""
    return APIResponse(data=await AnalyticsService(db).sales_trend())


@router.get(
    "/sales/by-warehouse", response_model=APIResponse[list[WarehouseRevenueOut]]
)
async def sales_by_warehouse(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[WarehouseRevenueOut]]:
    """توزيع الإيرادات حسب المستودع."""
    return APIResponse(data=await AnalyticsService(db).revenue_by_warehouse())


@router.get(
    "/sales/by-price-tier", response_model=APIResponse[list[PriceTierRevenueOut]]
)
async def sales_by_price_tier(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[PriceTierRevenueOut]]:
    """توزيع الإيرادات حسب فئة السعر (جملة/نصف جملة/تجزئة)."""
    return APIResponse(data=await AnalyticsService(db).revenue_by_price_tier())


@router.get("/returns/trend", response_model=APIResponse[list[ReturnsTrendPointOut]])
async def returns_trend(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ReturnsTrendPointOut]]:
    """اتجاه نسبة المرتجعات الشهرية مصنفة حسب صالح لإعادة البيع أو تالف."""
    return APIResponse(data=await AnalyticsService(db).returns_trend())


@router.get("/customers/lapsing", response_model=APIResponse[LapsingReportOut])
async def lapsing_customers(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[LapsingReportOut]:
    """عملاء توقفوا عن الطلب بمقياس وتيرتهم هم، مرتّبين بما هو على المحك.

    ليست عتبة موحّدة: العميل الذي يطلب مرتين أسبوعياً يُعدّ متأخراً بعد أسبوعين،
    والذي يطلب كل شهرين لا يُعدّ كذلك إلا بعد ستة.
    """
    return APIResponse(data=await LapsingService(db).lapsing())


@router.get("/inventory/expiry-risk", response_model=APIResponse[list[ExpiryRiskOut]])
async def expiry_risk(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ExpiryRiskOut]]:
    """التشغيلات القريبة من انتهاء الصلاحية خلال 30 يوماً وقيمتها المعرضة للخطر."""
    return APIResponse(data=await AnalyticsService(db).expiry_risk(days=30))


@router.get("/inventory/turnover", response_model=APIResponse[list[TurnoverOut]])
async def turnover(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[TurnoverOut]]:
    """معدل دوران المخزون لكل صنف (تكلفة المبيعات ÷ قيمة المخزون الحالي)."""
    return APIResponse(data=await AnalyticsService(db).turnover())


@router.get("/credit/aging", response_model=APIResponse[list[ARAgingRowOut]])
async def ar_aging(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ARAgingRowOut]]:
    """أعمار ذمم العملاء المدينة موزعة على شرائح زمنية."""
    return APIResponse(data=await AnalyticsService(db).ar_aging())


@router.get("/credit/at-risk", response_model=APIResponse[list[CreditRiskCustomerOut]])
async def credit_risk(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[CreditRiskCustomerOut]]:
    """العملاء الأعلى استغلالاً لحدهم الائتماني."""
    return APIResponse(data=await AnalyticsService(db).credit_risk())


@router.get(
    "/delivery/fulfillment", response_model=APIResponse[list[FulfillmentSummaryOut]]
)
async def fulfillment_summary(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[FulfillmentSummaryOut]]:
    """ملخص التوصيل مقابل الاستلام من المستودع ونسب الإنجاز."""
    return APIResponse(data=await AnalyticsService(db).fulfillment_summary())


@router.get("/delivery/drivers", response_model=APIResponse[list[DriverPerformanceOut]])
async def driver_performance(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[DriverPerformanceOut]]:
    """أداء السائقين: عدد الرحلات ونسبة فشل التسليم."""
    return APIResponse(data=await AnalyticsService(db).driver_performance())


@router.get("/reps/performance", response_model=APIResponse[list[RepPerformanceOut]])
async def rep_performance(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[RepPerformanceOut]]:
    """أداء مناديب المبيعات: الإيرادات، متوسط الفاتورة، ونسبة المرتجعات."""
    return APIResponse(data=await AnalyticsService(db).rep_performance())


@router.get(
    "/inventory/expiry-worklist", response_model=APIResponse[ExpiryWorklistOut]
)
async def expiry_worklist(
    horizon_days: int = Query(default=60, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[ExpiryWorklistOut]:
    """ما سينتهي قريباً ولن يُباع بالوتيرة الحالية، ومن يُتصل به لتصريفه.

    ليس تنبيهاً بل قائمة عمل: الترتيب بحسب قيمة الفائض على أيام المهلة المتبقية.
    """
    data = await ExpiryWorklistService(db).worklist(horizon_days=horizon_days)
    return APIResponse(data=data)


@router.get("/inventory/damage-report", response_model=APIResponse[DamageReportOut])
async def damage_report(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DamageReportOut]:
    """تقرير التالف/الهالك لفترة محددة، موزعاً حسب السبب وحسب الصنف."""
    return APIResponse(
        data=await AnalyticsService(db).damage_report(date_from, date_to)
    )


@router.get("/sales/discount-report", response_model=APIResponse[DiscountReportOut])
async def discount_report(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[DiscountReportOut]:
    """تقرير الخصومات الممنوحة على الفواتير لفترة محددة، حسب العميل والمندوب."""
    return APIResponse(
        data=await AnalyticsService(db).discount_report(date_from, date_to)
    )
