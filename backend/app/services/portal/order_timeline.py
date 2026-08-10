"""Where a shop's order has got to, written for the shop.

An order and the invoice that answers it are one journey to a customer and two
records to us. Until the office prices it there is no invoice at all; afterwards,
"where is my order" is really a question about the invoice — is it on a van, is it
waiting on the counter. So this stitches the two halves together and presents one
line.

The invoice half deliberately reuses `InvoiceTimelineService` rather than
recomputing it. Two places deciding whether goods are on the road is two answers,
and the one the customer sees would be the one nobody checks.

What is *not* reused is the wording or the fields. Staff steps say things like
"لن تخرج البضاعة قبل التحصيل" and name trip numbers — internal operational facts
that mean nothing to a shop and disclose how we run. Every portal step below is
written out here explicitly, which is the same rule the portal schemas follow.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.sales import (
    CustomerOrder,
    CustomerOrderStatus,
    FulfillmentType,
    SalesInvoice,
)
from app.services.sales.invoice_timeline_service import InvoiceTimelineService


@dataclass
class PortalStep:
    key: str
    label: str
    state: str  # done | current | pending | failed
    at: datetime | None = None
    detail: str | None = None


@dataclass
class PortalTimeline:
    order_id: int
    status_label: str
    fulfillment: str
    expected: date | None = None
    steps: list[PortalStep] = field(default_factory=list)


class PortalOrderTimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def timeline(self, order: CustomerOrder) -> PortalTimeline:
        steps: list[PortalStep] = [
            PortalStep(
                key="placed",
                label="استلمنا طلبك",
                state="done",
                at=order.created_at,
                detail=f"رقم الطلب {order.id} بتاريخ {order.order_date}",
            )
        ]

        if order.status is CustomerOrderStatus.CANCELLED:
            # A refused order stops here and says why, in the words the office wrote
            # for the customer. Continuing the line would imply goods are coming.
            steps.append(
                PortalStep(
                    key="cancelled",
                    label="أُلغي الطلب",
                    state="failed",
                    at=order.reviewed_at,
                    detail=order.decision_note or "أُلغي هذا الطلب.",
                )
            )
            return PortalTimeline(
                order_id=order.id,
                status_label="أُلغي الطلب",
                fulfillment=order.fulfillment.value,
                steps=steps,
            )

        reviewed = order.status in (
            CustomerOrderStatus.CONFIRMED,
            CustomerOrderStatus.INVOICED,
        )
        steps.append(
            PortalStep(
                key="confirmed",
                label="تمت الموافقة على الطلب" if reviewed else "بانتظار مراجعة المكتب",
                state="done" if reviewed else "current",
                at=order.reviewed_at if reviewed else None,
                detail=(
                    "يجري تجهيز طلبك"
                    if reviewed
                    else "سنراجع الأصناف والكميات ونؤكد لك الطلب"
                ),
            )
        )

        invoiced = order.status is CustomerOrderStatus.INVOICED and order.invoice_id
        steps.append(
            PortalStep(
                key="prepared",
                label="جُهّز الطلب" if invoiced else "التجهيز",
                state="done" if invoiced else "pending",
                detail="تم تجهيز البضاعة وإصدار الفاتورة" if invoiced else None,
            )
        )

        steps.extend(await self._handover(order, invoiced))
        self._mark_current(steps)

        expected, status = await self._heading(order, invoiced, steps)
        return PortalTimeline(
            order_id=order.id,
            status_label=status,
            fulfillment=order.fulfillment.value,
            expected=expected,
            steps=steps,
        )

    async def _handover(
        self, order: CustomerOrder, invoiced: bool
    ) -> list[PortalStep]:
        """The last stretch, which differs by how the goods reach the shop."""
        pickup = order.fulfillment is FulfillmentType.PICKUP

        if not invoiced:
            return [
                PortalStep(
                    key="ready",
                    label="جاهز للاستلام" if pickup else "في الطريق إليك",
                    state="pending",
                ),
                PortalStep(key="completed", label="اكتمل الطلب", state="pending"),
            ]

        invoice = await self.session.get(SalesInvoice, order.invoice_id)
        states = {
            step["key"]: step
            for step in (await InvoiceTimelineService(self.session).timeline(invoice))[
                "steps"
            ]
        }

        if pickup:
            handed = states.get("handover", {}).get("state") == "done"
            return [
                PortalStep(
                    key="ready",
                    label="جاهز للاستلام" if not handed else "كان جاهزاً للاستلام",
                    state="done",
                    detail="يمكنك استلام البضاعة من المستودع",
                ),
                PortalStep(
                    key="completed",
                    label="تم الاستلام" if handed else "بانتظار استلامك",
                    state="done" if handed else "pending",
                    at=invoice.picked_up_at,
                ),
            ]

        transit = states.get("transit", {})
        delivered = states.get("delivered", {}).get("state") == "done"
        if transit.get("state") == "failed":
            return [
                PortalStep(
                    key="ready",
                    label="تعذّر التوصيل",
                    state="failed",
                    detail=(
                        "لم نتمكن من التسليم؛ سنتواصل معك لإعادة الجدولة."
                    ),
                ),
                PortalStep(key="completed", label="اكتمل الطلب", state="pending"),
            ]

        on_road = transit.get("state") == "done"
        return [
            PortalStep(
                key="ready",
                label="في الطريق إليك" if on_road else "بانتظار خروج المندوب",
                state="done" if on_road else "pending",
                # The driver's name, and nothing about which round they are on:
                # that is our routing, not the customer's business.
                detail=transit.get("detail") if on_road else None,
            ),
            PortalStep(
                key="completed",
                label="تم التسليم" if delivered else "اكتمل الطلب",
                state="done" if delivered else "pending",
            ),
        ]

    async def _heading(
        self, order: CustomerOrder, invoiced: bool, steps: list[PortalStep]
    ) -> tuple[date | None, str]:
        expected = None
        if invoiced and order.fulfillment is FulfillmentType.DELIVERY:
            invoice = await self.session.get(SalesInvoice, order.invoice_id)
            expected = (await InvoiceTimelineService(self.session).timeline(invoice))[
                "expected"
            ]
        for step in steps:
            if step.state in ("failed", "current"):
                return expected, step.label
        return expected, steps[-1].label

    @staticmethod
    def _mark_current(steps: list[PortalStep]) -> None:
        if any(step.state == "failed" for step in steps):
            return
        for step in steps:
            if step.state == "pending":
                step.state = "current"
                return
