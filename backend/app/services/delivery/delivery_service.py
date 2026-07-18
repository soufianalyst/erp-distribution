"""Delivery business logic: trips, invoice stops, lifecycle, and picking lists."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.delivery import (
    DeliveryInvoiceSummary,
    DeliveryItemOut,
    InvoicePrepOut,
    PrepLineOut,
    PickingLineOut,
    PickingListOut,
    StopStatusUpdate,
    TripCreate,
    TripOut,
)
from app.core.exceptions import AppException
from app.domain.models.delivery import (
    DeliveryStop,
    DeliveryTrip,
    StopStatus,
    TripStatus,
)
from app.domain.models.inventory import Product
from app.domain.models.sales import (
    Customer,
    FulfillmentType,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPaymentMethod,
)
from app.services.inventory.stock_service import StockService


class DeliveryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stock = StockService(session)

    async def list_invoice_summaries(self) -> list[DeliveryInvoiceSummary]:
        """Price-free invoice list for delivery staff: items, quantities, destination.

        Cash/card invoices stay hidden here until the cashier confirms payment;
        credit invoices are visible immediately (settled later via accounts).
        """
        result = await self.session.execute(
            select(SalesInvoice, Customer.name)
            .join(Customer, SalesInvoice.customer_id == Customer.id)
            .where(
                or_(
                    SalesInvoice.payment_method == SalesPaymentMethod.CREDIT,
                    SalesInvoice.payment_confirmed_at.isnot(None),
                )
            )
            .order_by(SalesInvoice.id.desc())
        )
        rows = result.all()
        invoice_ids = [invoice.id for invoice, _ in rows]

        items_map: dict[int, list[DeliveryItemOut]] = {}
        if invoice_ids:
            lines = await self.session.execute(
                select(
                    SalesInvoiceLine.invoice_id,
                    Product.name,
                    Product.base_unit_name,
                    func.sum(SalesInvoiceLine.quantity),
                )
                .join(Product, SalesInvoiceLine.product_id == Product.id)
                .where(SalesInvoiceLine.invoice_id.in_(invoice_ids))
                .group_by(
                    SalesInvoiceLine.invoice_id, Product.name, Product.base_unit_name
                )
            )
            for invoice_id, name, unit, quantity in lines.all():
                items_map.setdefault(invoice_id, []).append(
                    DeliveryItemOut(
                        product_name=name, quantity=Decimal(str(quantity)), unit=unit
                    )
                )

        return [
            DeliveryInvoiceSummary(
                id=invoice.id,
                invoice_date=invoice.invoice_date,
                customer_name=customer_name,
                warehouse_id=invoice.warehouse_id,
                fulfillment=invoice.fulfillment,
                payment_method=invoice.payment_method,
                picked_up_at=invoice.picked_up_at,
                items=items_map.get(invoice.id, []),
            )
            for invoice, customer_name in rows
        ]

    async def invoice_prep(self, invoice_id: int) -> InvoicePrepOut:
        """Batch-level prep sheet so staff pick the exact FEFO batches — no prices."""
        result = await self.session.execute(
            select(SalesInvoice, Customer.name)
            .join(Customer, SalesInvoice.customer_id == Customer.id)
            .where(SalesInvoice.id == invoice_id)
        )
        row = result.first()
        if row is None:
            raise AppException(404, "فاتورة المبيعات غير موجودة.")
        invoice, customer_name = row

        lines_result = await self.session.execute(
            select(
                Product.name,
                SalesInvoiceLine.batch_number,
                func.sum(SalesInvoiceLine.quantity),
                Product.base_unit_name,
                SalesInvoiceLine.warehouse_id,
            )
            .join(Product, SalesInvoiceLine.product_id == Product.id)
            .where(SalesInvoiceLine.invoice_id == invoice_id)
            .group_by(
                Product.name,
                SalesInvoiceLine.batch_number,
                Product.base_unit_name,
                SalesInvoiceLine.warehouse_id,
            )
            .order_by(
                SalesInvoiceLine.warehouse_id,
                Product.name,
                SalesInvoiceLine.batch_number,
            )
        )
        lines = [
            PrepLineOut(
                product_name=name,
                batch_number=batch_number,
                quantity=Decimal(str(quantity)),
                unit=unit,
                warehouse_id=warehouse_id,
            )
            for name, batch_number, quantity, unit, warehouse_id in lines_result.all()
        ]
        return InvoicePrepOut(
            invoice_id=invoice.id,
            invoice_date=invoice.invoice_date,
            customer_name=customer_name,
            warehouse_id=invoice.warehouse_id,
            fulfillment=invoice.fulfillment,
            lines=lines,
        )

    async def get_trip(self, trip_id: int) -> DeliveryTrip:
        result = await self.session.execute(
            select(DeliveryTrip)
            .options(selectinload(DeliveryTrip.stops))
            .where(DeliveryTrip.id == trip_id)
        )
        trip = result.scalar_one_or_none()
        if trip is None:
            raise AppException(404, "رحلة التوزيع غير موجودة.")
        return trip

    async def create_trip(
        self, data: TripCreate, created_by: int | None = None
    ) -> DeliveryTrip:
        await self.stock.get_active_warehouse(data.warehouse_id)
        trip = DeliveryTrip(
            trip_date=data.trip_date or date.today(),
            driver_name=data.driver_name,
            vehicle=data.vehicle,
            warehouse_id=data.warehouse_id,
            notes=data.notes,
            created_by=created_by,
        )
        self.session.add(trip)
        await self.session.commit()
        return await self.get_trip(trip.id)

    async def list_trips(self, status: TripStatus | None = None) -> list[DeliveryTrip]:
        stmt = (
            select(DeliveryTrip)
            .options(selectinload(DeliveryTrip.stops))
            .order_by(DeliveryTrip.id.desc())
        )
        if status is not None:
            stmt = stmt.where(DeliveryTrip.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_invoice(self, trip_id: int, invoice_id: int) -> DeliveryTrip:
        """Attach a posted sales invoice as the next stop on a planned trip."""
        trip = await self.get_trip(trip_id)
        if trip.status != TripStatus.PLANNED:
            raise AppException(400, "لا يمكن تعديل طلبيات رحلة بعد انطلاقها.")

        invoice = await self.session.get(SalesInvoice, invoice_id)
        if invoice is None:
            raise AppException(404, "فاتورة المبيعات غير موجودة.")
        if invoice.warehouse_id is None:
            raise AppException(
                400,
                "الفاتورة تحتوي على أصناف من أكثر من مستودع ولا يمكن إضافتها "
                "لرحلة توزيع واحدة.",
            )
        if invoice.warehouse_id != trip.warehouse_id:
            raise AppException(400, "الفاتورة صادرة من مستودع مختلف عن مستودع الرحلة.")
        if invoice.fulfillment == FulfillmentType.PICKUP:
            raise AppException(
                400, "هذه الفاتورة استلام من المستودع ولا تُضاف لرحلات التوصيل."
            )
        if (
            invoice.payment_method != SalesPaymentMethod.CREDIT
            and invoice.payment_confirmed_at is None
        ):
            raise AppException(
                400,
                "لم يتم تحصيل قيمة الفاتورة من الصندوق بعد؛ لا يمكن إضافتها لرحلة توزيع.",
            )

        # An invoice may ride on at most one trip that is not completed yet.
        active = await self.session.execute(
            select(func.count())
            .select_from(DeliveryStop)
            .join(DeliveryTrip, DeliveryStop.trip_id == DeliveryTrip.id)
            .where(
                DeliveryStop.invoice_id == invoice_id,
                DeliveryTrip.status != TripStatus.COMPLETED,
            )
        )
        if active.scalar_one() > 0:
            raise AppException(409, "هذه الفاتورة مرتبطة برحلة توزيع نشطة من قبل.")

        trip.stops.append(
            DeliveryStop(invoice_id=invoice_id, sequence=len(trip.stops) + 1)
        )
        await self.session.commit()
        return await self.get_trip(trip_id)

    async def remove_stop(self, trip_id: int, stop_id: int) -> DeliveryTrip:
        trip = await self.get_trip(trip_id)
        if trip.status != TripStatus.PLANNED:
            raise AppException(400, "لا يمكن تعديل طلبيات رحلة بعد انطلاقها.")
        stop = next((s for s in trip.stops if s.id == stop_id), None)
        if stop is None:
            raise AppException(404, "المحطة غير موجودة في هذه الرحلة.")
        trip.stops.remove(stop)
        # Keep the visiting order gapless for the driver sheet.
        for index, remaining in enumerate(trip.stops, start=1):
            remaining.sequence = index
        await self.session.commit()
        return await self.get_trip(trip_id)

    async def dispatch_trip(self, trip_id: int) -> DeliveryTrip:
        trip = await self.get_trip(trip_id)
        if trip.status != TripStatus.PLANNED:
            raise AppException(400, "الرحلة ليست في مرحلة التجهيز.")
        if not trip.stops:
            raise AppException(400, "لا يمكن إطلاق رحلة بدون طلبيات.")
        trip.status = TripStatus.IN_TRANSIT
        await self.session.commit()
        return await self.get_trip(trip_id)

    async def update_stop_status(
        self, trip_id: int, stop_id: int, data: StopStatusUpdate
    ) -> DeliveryTrip:
        trip = await self.get_trip(trip_id)
        if trip.status != TripStatus.IN_TRANSIT:
            raise AppException(400, "تحديث حالة التسليم متاح فقط أثناء الرحلة.")
        stop = next((s for s in trip.stops if s.id == stop_id), None)
        if stop is None:
            raise AppException(404, "المحطة غير موجودة في هذه الرحلة.")
        stop.status = StopStatus(data.status)
        stop.notes = data.notes
        stop.delivered_at = datetime.now(timezone.utc)
        await self.session.commit()
        return await self.get_trip(trip_id)

    async def complete_trip(self, trip_id: int) -> DeliveryTrip:
        trip = await self.get_trip(trip_id)
        if trip.status != TripStatus.IN_TRANSIT:
            raise AppException(400, "الرحلة ليست قيد التوصيل.")
        if any(stop.status == StopStatus.PENDING for stop in trip.stops):
            raise AppException(400, "لا يمكن إنهاء الرحلة وبعض الطلبيات لم تُحسم بعد.")
        trip.status = TripStatus.COMPLETED
        await self.session.commit()
        return await self.get_trip(trip_id)

    async def picking_list(self, trip_id: int) -> PickingListOut:
        """قائمة التجهيز: goods to load, aggregated by product and batch (FEFO-faithful)."""
        trip = await self.get_trip(trip_id)
        invoice_ids = [stop.invoice_id for stop in trip.stops]

        lines: list[PickingLineOut] = []
        total = Decimal("0")
        if invoice_ids:
            result = await self.session.execute(
                select(
                    Product.id,
                    Product.name,
                    Product.base_unit_name,
                    SalesInvoiceLine.batch_number,
                    func.sum(SalesInvoiceLine.quantity),
                )
                .join(Product, SalesInvoiceLine.product_id == Product.id)
                .where(SalesInvoiceLine.invoice_id.in_(invoice_ids))
                .group_by(
                    Product.id,
                    Product.name,
                    Product.base_unit_name,
                    SalesInvoiceLine.batch_number,
                )
                .order_by(Product.name, SalesInvoiceLine.batch_number)
            )
            for product_id, name, unit, batch_number, quantity in result.all():
                quantity = Decimal(str(quantity))
                lines.append(
                    PickingLineOut(
                        product_id=product_id,
                        product_name=name,
                        base_unit_name=unit,
                        batch_number=batch_number,
                        quantity=quantity,
                    )
                )
                total += quantity

        return PickingListOut(
            trip=TripOut.model_validate(trip),
            lines=lines,
            invoice_count=len(invoice_ids),
            total_quantity=total,
        )
