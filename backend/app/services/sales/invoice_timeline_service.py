"""Where an invoice has got to, as a sequence of steps a customer would recognise.

The stages are not decorative — each one is a real gate in this system, and getting
them wrong would show a shop a picture that contradicts what the warehouse is doing.

An invoice branches twice. It is either collected at the counter or delivered on a
round, which changes the last steps entirely. And it is either cash or card, which
waits for the cashier to take the money before the goods may move, or on account,
which is cleared to move immediately and settled later against the customer's
balance. Four paths, and the tracker has to tell the truth on all of them.

Failure is a state too. A delivery attempt that could not be made is not "still on
the way"; it stops the line in red, because a shop told "in transit" about a parcel
sitting back at the depot will ring up angry, and rightly.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.delivery import DeliveryStop, DeliveryTrip, StopStatus, TripStatus
from app.domain.models.sales import (
    Customer,
    FulfillmentType,
    SalesInvoice,
    SalesPaymentMethod,
    SalesReturn,
)
from app.services.sales.returns_query import posted

StepState = Literal["done", "current", "pending", "failed"]

ZERO = Decimal("0")


@dataclass
class Step:
    key: str
    label: str
    state: StepState
    # When it happened; None for anything not yet reached.
    at: datetime | None = None
    # A second line under the label — the driver's name, the amount still owed.
    detail: str | None = None


class InvoiceTimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def timeline(self, invoice: SalesInvoice) -> dict:
        """The whole card: the heading facts and the ordered steps."""
        customer = await self.session.get(Customer, invoice.customer_id)
        stop, trip = await self._delivery(invoice.id)
        returned = await self._returned_total(invoice.id)

        steps = [self._raised(invoice)]
        steps.append(self._payment(invoice, returned))
        if invoice.fulfillment is FulfillmentType.PICKUP:
            steps.append(self._pickup(invoice, steps[-1]))
        else:
            steps.extend(self._delivery_steps(invoice, stop, trip, steps[-1]))

        # Exactly one step is "current": the first that is not finished. Anything
        # after a failure stays pending rather than current — the journey is not
        # advancing, it is stuck.
        self._mark_current(steps)

        return {
            "invoice_id": invoice.id,
            "reference": f"INV-{invoice.id:05d}",
            "customer_name": customer.name if customer else "",
            "fulfillment": invoice.fulfillment.value,
            "shipped_via": self._shipped_via(invoice, trip),
            "status_label": self._status_label(steps),
            "expected": self._expected(invoice, trip),
            "total": invoice.total,
            "amount_due": (invoice.total - returned - invoice.paid_amount),
            "returned_total": returned,
            "steps": [step.__dict__ for step in steps],
        }

    # --- The steps ---
    @staticmethod
    def _raised(invoice: SalesInvoice) -> Step:
        return Step(
            key="raised",
            label="صدرت الفاتورة",
            state="done",
            at=invoice.created_at,
            detail=f"بتاريخ {invoice.invoice_date}",
        )

    @staticmethod
    def _payment(invoice: SalesInvoice, returned: Decimal) -> Step:
        """The cashier gate, or the account.

        Two genuinely different things wearing one step. A cash sale is not released
        until the till has the money; a credit sale is released at once and chased
        later. Showing both as "paid" would tell a credit customer their debt was
        settled.
        """
        due = invoice.total - returned - invoice.paid_amount
        if invoice.payment_method is SalesPaymentMethod.CREDIT:
            settled = due <= ZERO
            return Step(
                key="payment",
                label="على الحساب" if not settled else "سُدّدت",
                state="done",
                at=invoice.payment_confirmed_at,
                detail=(
                    "لا يوجد رصيد مستحق على هذه الفاتورة"
                    if settled
                    else f"المتبقي على الحساب: {due}"
                ),
            )
        if invoice.payment_confirmed_at is not None:
            return Step(
                key="payment",
                label="تم التحصيل",
                state="done",
                at=invoice.payment_confirmed_at,
                detail="استلم الصندوق قيمة الفاتورة",
            )
        return Step(
            key="payment",
            label="بانتظار التحصيل",
            state="pending",
            detail=f"المطلوب تحصيله: {due} — لن تخرج البضاعة قبل ذلك",
        )

    @staticmethod
    def _pickup(invoice: SalesInvoice, payment: Step) -> Step:
        if invoice.picked_up_at is not None:
            return Step(
                key="handover",
                label="تم الاستلام",
                state="done",
                at=invoice.picked_up_at,
                detail="سلّم المستودع البضاعة للعميل",
            )
        return Step(
            key="handover",
            label="بانتظار الاستلام من المستودع",
            state="pending",
            detail=(
                None
                if payment.state == "done"
                else "يبدأ بعد تحصيل قيمة الفاتورة"
            ),
        )

    @staticmethod
    def _delivery_steps(
        invoice: SalesInvoice,
        stop: DeliveryStop | None,
        trip: DeliveryTrip | None,
        payment: Step,
    ) -> list[Step]:
        """Scheduled, on the road, delivered — three states a customer feels
        differently about, so they are three steps rather than one "shipping"."""
        if stop is None or trip is None:
            return [
                Step(
                    key="scheduled",
                    label="بانتظار الجدولة في رحلة",
                    state="pending",
                    detail=(
                        None
                        if payment.state == "done"
                        else "تُجدول بعد تحصيل قيمة الفاتورة"
                    ),
                ),
                Step(key="transit", label="قيد التوصيل", state="pending"),
                Step(key="delivered", label="تم التسليم", state="pending"),
            ]

        driver = f"السائق: {trip.driver_name}"
        scheduled = Step(
            key="scheduled",
            label="مجدولة في رحلة",
            state="done",
            at=trip.created_at,
            detail=f"رحلة رقم {trip.id} بتاريخ {trip.trip_date} — {driver}",
        )

        if stop.status is StopStatus.FAILED:
            return [
                scheduled,
                Step(
                    key="transit",
                    label="تعذّر التسليم",
                    state="failed",
                    at=stop.delivered_at,
                    detail=stop.notes or "لم يتم التسليم — يحتاج إعادة جدولة",
                ),
                Step(key="delivered", label="تم التسليم", state="pending"),
            ]

        in_transit = trip.status in (TripStatus.IN_TRANSIT, TripStatus.COMPLETED)
        transit = Step(
            key="transit",
            label="قيد التوصيل" if in_transit else "بانتظار انطلاق الرحلة",
            state="done" if in_transit else "pending",
            at=trip.created_at if in_transit else None,
            detail=driver if in_transit else None,
        )

        delivered = (
            Step(
                key="delivered",
                label="تم التسليم",
                state="done",
                at=stop.delivered_at,
                detail="استلم العميل البضاعة",
            )
            if stop.status is StopStatus.DELIVERED
            else Step(key="delivered", label="تم التسليم", state="pending")
        )
        return [scheduled, transit, delivered]

    @staticmethod
    def _mark_current(steps: list[Step]) -> None:
        """Promote the first unfinished step to "current", unless we are stuck."""
        if any(step.state == "failed" for step in steps):
            return
        for step in steps:
            if step.state == "pending":
                step.state = "current"
                return

    # --- Heading facts ---
    @staticmethod
    def _shipped_via(invoice: SalesInvoice, trip: DeliveryTrip | None) -> str:
        if invoice.fulfillment is FulfillmentType.PICKUP:
            return "استلام من المستودع"
        if trip is None:
            return "توصيل — لم تُجدول بعد"
        return trip.vehicle or trip.driver_name

    @staticmethod
    def _status_label(steps: list[Step]) -> str:
        for step in steps:
            if step.state in ("failed", "current"):
                return step.label
        return steps[-1].label  # everything done

    @staticmethod
    def _expected(invoice: SalesInvoice, trip: DeliveryTrip | None) -> date | None:
        if invoice.fulfillment is FulfillmentType.PICKUP:
            return None
        return trip.trip_date if trip else None

    # --- Lookups ---
    async def _delivery(
        self, invoice_id: int
    ) -> tuple[DeliveryStop | None, DeliveryTrip | None]:
        """The most recent stop for this invoice, and its trip.

        Most recent rather than the only one: a failed delivery is rescheduled onto
        a later trip, and the tracker must show where the goods are now, not the
        first attempt.
        """
        row = (
            await self.session.execute(
                select(DeliveryStop)
                .options(selectinload(DeliveryStop.trip))
                .where(DeliveryStop.invoice_id == invoice_id)
                .order_by(DeliveryStop.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return (row, row.trip) if row else (None, None)

    async def _returned_total(self, invoice_id: int) -> Decimal:
        """Credit notes against this invoice, so "still owed" is the real figure."""
        rows = (
            await self.session.execute(
                select(SalesReturn.total).where(
                    SalesReturn.invoice_id == invoice_id, posted()
                )
            )
        ).scalars()
        return sum(rows, ZERO)
