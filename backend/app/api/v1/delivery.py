"""Delivery endpoints: trips, invoice stops, lifecycle, and picking lists."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.delivery import (
    AddInvoiceRequest,
    DeliveryInvoiceSummary,
    InvoicePrepOut,
    PickingListOut,
    StopStatusUpdate,
    TripCreate,
    TripOut,
)
from app.db.session import get_db
from app.domain.models.delivery import TripStatus
from app.domain.models.user import User
from app.services.delivery.delivery_service import DeliveryService

router = APIRouter(prefix="/delivery", tags=["Delivery"])

# Each operation is gated by a granular permission (roles only supply defaults).
delivery_view = Depends(require_permissions("delivery.view"))
delivery_manage = require_permissions("delivery.manage")
# Drivers hold delivery.deliver: they update stops and close trips, nothing else.
delivery_deliver = require_permissions("delivery.deliver")


@router.get(
    "/invoices",
    response_model=APIResponse[list[DeliveryInvoiceSummary]],
    dependencies=[delivery_view],
)
async def list_delivery_invoices(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[DeliveryInvoiceSummary]]:
    """ملخص الفواتير لموظفي المستودع والسائقين: الأصناف والكميات بدون أسعار."""
    summaries = await DeliveryService(db).list_invoice_summaries()
    return APIResponse(data=summaries)


@router.get(
    "/invoices/{invoice_id}/prep",
    response_model=APIResponse[InvoicePrepOut],
    dependencies=[delivery_view],
)
async def invoice_prep(
    invoice_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[InvoicePrepOut]:
    """قسيمة تجهيز فاتورة: الأصناف والتشغيلات والكميات بدون أسعار."""
    prep = await DeliveryService(db).invoice_prep(invoice_id)
    return APIResponse(data=prep)


@router.post(
    "/trips", response_model=APIResponse[TripOut], status_code=status.HTTP_201_CREATED
)
async def create_trip(
    body: TripCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(delivery_manage),
) -> APIResponse[TripOut]:
    """إنشاء رحلة توزيع جديدة بسائقها ومركبتها ومستودع التحميل."""
    trip = await DeliveryService(db).create_trip(body, created_by=current_user.id)
    return APIResponse(
        data=TripOut.model_validate(trip), message="تم إنشاء الرحلة بنجاح."
    )


@router.get(
    "/trips", response_model=APIResponse[list[TripOut]], dependencies=[delivery_view]
)
async def list_trips(
    status_filter: TripStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[TripOut]]:
    """عرض رحلات التوزيع مع إمكانية التصفية حسب الحالة."""
    trips = await DeliveryService(db).list_trips(status_filter)
    return APIResponse(data=[TripOut.model_validate(t) for t in trips])


@router.get(
    "/trips/{trip_id}",
    response_model=APIResponse[TripOut],
    dependencies=[delivery_view],
)
async def get_trip(
    trip_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[TripOut]:
    """عرض تفاصيل رحلة واحدة بمحطاتها."""
    trip = await DeliveryService(db).get_trip(trip_id)
    return APIResponse(data=TripOut.model_validate(trip))


@router.post(
    "/trips/{trip_id}/invoices",
    response_model=APIResponse[TripOut],
    dependencies=[Depends(delivery_manage)],
)
async def add_invoice(
    trip_id: int, body: AddInvoiceRequest, db: AsyncSession = Depends(get_db)
) -> APIResponse[TripOut]:
    """إضافة فاتورة مبيعات كمحطة توصيل على الرحلة."""
    trip = await DeliveryService(db).add_invoice(trip_id, body.invoice_id)
    return APIResponse(
        data=TripOut.model_validate(trip), message="تمت إضافة الطلبية للرحلة."
    )


@router.delete(
    "/trips/{trip_id}/stops/{stop_id}",
    response_model=APIResponse[TripOut],
    dependencies=[Depends(delivery_manage)],
)
async def remove_stop(
    trip_id: int, stop_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[TripOut]:
    """إزالة طلبية من رحلة قيد التجهيز."""
    trip = await DeliveryService(db).remove_stop(trip_id, stop_id)
    return APIResponse(
        data=TripOut.model_validate(trip), message="تمت إزالة الطلبية من الرحلة."
    )


@router.post(
    "/trips/{trip_id}/dispatch",
    response_model=APIResponse[TripOut],
    dependencies=[Depends(delivery_manage)],
)
async def dispatch_trip(
    trip_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[TripOut]:
    """إطلاق الرحلة بعد اكتمال التحميل — تصبح قيد التوصيل."""
    trip = await DeliveryService(db).dispatch_trip(trip_id)
    return APIResponse(
        data=TripOut.model_validate(trip), message="انطلقت الرحلة بنجاح."
    )


@router.post(
    "/trips/{trip_id}/stops/{stop_id}/status",
    response_model=APIResponse[TripOut],
    dependencies=[Depends(delivery_deliver)],
)
async def update_stop_status(
    trip_id: int,
    stop_id: int,
    body: StopStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TripOut]:
    """تحديث حالة تسليم محطة: تم التسليم أو تعذر التسليم."""
    trip = await DeliveryService(db).update_stop_status(trip_id, stop_id, body)
    return APIResponse(
        data=TripOut.model_validate(trip), message="تم تحديث حالة التسليم."
    )


@router.post(
    "/trips/{trip_id}/complete",
    response_model=APIResponse[TripOut],
    dependencies=[Depends(delivery_deliver)],
)
async def complete_trip(
    trip_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[TripOut]:
    """إنهاء الرحلة بعد حسم جميع الطلبيات."""
    trip = await DeliveryService(db).complete_trip(trip_id)
    return APIResponse(
        data=TripOut.model_validate(trip), message="تم إنهاء الرحلة بنجاح."
    )


@router.get(
    "/trips/{trip_id}/picking-list",
    response_model=APIResponse[PickingListOut],
    dependencies=[delivery_view],
)
async def picking_list(
    trip_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[PickingListOut]:
    """قائمة التجهيز: الكميات المطلوب تحميلها مجمعة حسب الصنف والتشغيلة."""
    result = await DeliveryService(db).picking_list(trip_id)
    return APIResponse(data=result)
