"""The catalogue a customer browses, and the orders they place from it.

An order here is a *request*. It moves no stock, reserves nothing, and carries no
money — the office prices it and turns it into an invoice through the ordinary sales
pipeline, which is where credit limits, FEFO and the ledger already live. Nothing in
this module may become a second way to sell goods.

That also settles what availability can honestly say. Because nothing is reserved,
any number shown to a customer is out of date the moment a van loads, so the
catalogue reports a band instead — see `Availability`.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.portal import (
    Availability,
    CatalogItemOut,
    PortalOrderCreateIn,
    PortalOrderLineOut,
    PortalOrderOut,
)
from app.core.exceptions import AppException
from app.domain.models.inventory import Product, ProductBatch, Warehouse
from app.domain.models.sales import (
    CustomerOrder,
    CustomerOrderLine,
    CustomerOrderStatus,
)
from app.services.inventory.stock_query import sellable

# A customer may have this many requests waiting on the office at once. Not a
# business rule so much as a brake: an ordering form is the one place a stranger with
# a stolen password could generate unbounded work for the sales team.
MAX_OPEN_ORDERS = 20


def _band(on_hand: Decimal, min_stock_level: Decimal) -> Availability:
    """Turn a quantity into something safe to show.

    `min_stock_level` is the product's own reorder threshold — the level at which the
    business already considers itself short. Reusing it means the catalogue says
    "limited" at exactly the point the warehouse would say so, rather than at some
    number invented here.
    """
    if on_hand <= 0:
        return Availability.UNAVAILABLE
    if min_stock_level > 0 and on_hand <= min_stock_level:
        return Availability.LIMITED
    return Availability.AVAILABLE


class PortalOrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _on_hand(self, product_ids: list[int] | None = None) -> dict[int, Decimal]:
        """Sellable quantity per product, across the depots a customer can be served from.

        Vans are excluded. A salesman's vehicle is stock already committed to a round;
        counting it would tell a shop that goods are available when they are halfway
        across the city on someone else's route.
        """
        query = (
            select(ProductBatch.product_id, func.sum(ProductBatch.quantity))
            .join(Warehouse, Warehouse.id == ProductBatch.warehouse_id)
            .where(
                sellable(),
                Warehouse.is_active.is_(True),
                Warehouse.is_vehicle.is_(False),
            )
            .group_by(ProductBatch.product_id)
        )
        if product_ids is not None:
            query = query.where(ProductBatch.product_id.in_(product_ids))
        return {
            product_id: quantity or Decimal("0")
            for product_id, quantity in (await self.session.execute(query)).all()
        }

    async def catalog(self) -> list[CatalogItemOut]:
        """Every active product, with a band instead of a number and no price at all."""
        products = list(
            (
                await self.session.execute(
                    select(Product)
                    .where(Product.is_active.is_(True))
                    .order_by(Product.name)
                )
            )
            .scalars()
            .all()
        )
        on_hand = await self._on_hand([p.id for p in products])
        return [
            CatalogItemOut(
                product_id=product.id,
                name=product.name,
                unit=product.base_unit_name,
                availability=_band(
                    on_hand.get(product.id, Decimal("0")), product.min_stock_level
                ),
            )
            for product in products
        ]

    async def _to_out(self, orders: list[CustomerOrder]) -> list[PortalOrderOut]:
        """Project orders, re-reading availability rather than trusting the request."""
        product_ids = {line.product_id for order in orders for line in order.lines}
        products = {
            p.id: p
            for p in (
                await self.session.execute(
                    select(Product).where(Product.id.in_(product_ids or {0}))
                )
            )
            .scalars()
            .all()
        }
        on_hand = await self._on_hand(list(product_ids) or [0])
        return [
            PortalOrderOut(
                id=order.id,
                order_date=order.order_date,
                status=order.status.value,
                fulfillment=order.fulfillment.value,
                notes=order.notes,
                decision_note=order.decision_note,
                invoice_id=order.invoice_id,
                created_at=order.created_at,
                lines=[
                    PortalOrderLineOut(
                        product_id=line.product_id,
                        product_name=(
                            products[line.product_id].name
                            if line.product_id in products
                            else "—"
                        ),
                        unit=(
                            products[line.product_id].base_unit_name
                            if line.product_id in products
                            else ""
                        ),
                        quantity=line.quantity,
                        availability=_band(
                            on_hand.get(line.product_id, Decimal("0")),
                            (
                                products[line.product_id].min_stock_level
                                if line.product_id in products
                                else Decimal("0")
                            ),
                        ),
                    )
                    for line in order.lines
                ],
            )
            for order in orders
        ]

    async def place_order(
        self, customer_id: int, data: PortalOrderCreateIn
    ) -> PortalOrderOut:
        """File a request for the office to review.

        What this deliberately does *not* do: check the credit limit, or refuse an
        order for goods that are short. Both are the office's judgement — a shop that
        is over its limit may still be allowed to order while they settle up, and a
        short line is something a salesman resolves by ringing them, not something the
        form should silently drop. The order records what was asked for; the invoice
        records what was agreed.
        """
        open_orders = (
            await self.session.execute(
                select(func.count(CustomerOrder.id)).where(
                    CustomerOrder.customer_id == customer_id,
                    CustomerOrder.status == CustomerOrderStatus.PENDING,
                )
            )
        ).scalar_one()
        if open_orders >= MAX_OPEN_ORDERS:
            raise AppException(
                429,
                "لديك طلبات كثيرة قيد المراجعة، يرجى انتظار ردّ المكتب قبل إرسال طلب جديد.",
            )

        # One line per product: two lines for the same item is almost always a
        # double-tap on a phone, and merging them silently would change the quantity
        # the customer thinks they asked for.
        seen: set[int] = set()
        for line in data.lines:
            if line.product_id in seen:
                raise AppException(400, "تكرر الصنف نفسه في الطلب، يرجى دمج الكمية.")
            seen.add(line.product_id)

        products = {
            p.id: p
            for p in (
                await self.session.execute(
                    select(Product).where(Product.id.in_(seen))
                )
            )
            .scalars()
            .all()
        }
        for line in data.lines:
            product = products.get(line.product_id)
            if product is None or not product.is_active:
                raise AppException(400, "أحد الأصناف المطلوبة غير متاح للطلب.")

        order = CustomerOrder(
            customer_id=customer_id,
            order_date=date.today(),
            status=CustomerOrderStatus.PENDING,
            fulfillment=data.fulfillment,
            notes=data.notes,
            lines=[
                CustomerOrderLine(product_id=line.product_id, quantity=line.quantity)
                for line in data.lines
            ],
        )
        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)
        return (await self._to_out([order]))[0]

    async def list_orders(self, customer_id: int) -> list[PortalOrderOut]:
        """This customer's orders, newest first."""
        orders = list(
            (
                await self.session.execute(
                    select(CustomerOrder)
                    .options(selectinload(CustomerOrder.lines))
                    .where(CustomerOrder.customer_id == customer_id)
                    .order_by(CustomerOrder.id.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self._to_out(orders)

    async def _own_order(self, customer_id: int, order_id: int) -> CustomerOrder:
        """Fetch an order by id *and* owner, so there is no check to forget."""
        order = (
            await self.session.execute(
                select(CustomerOrder)
                .options(selectinload(CustomerOrder.lines))
                .where(
                    CustomerOrder.id == order_id,
                    CustomerOrder.customer_id == customer_id,
                )
            )
        ).scalar_one_or_none()
        if order is None:
            raise AppException(404, "الطلب غير موجود.")
        return order

    async def get_order(self, customer_id: int, order_id: int) -> PortalOrderOut:
        order = await self._own_order(customer_id, order_id)
        return (await self._to_out([order]))[0]

    async def cancel_order(
        self, customer_id: int, order_id: int, reason: str | None
    ) -> PortalOrderOut:
        """Withdraw a request the office has not acted on yet.

        Only while pending. Once the office has confirmed it, goods are being picked
        against it and withdrawing is a conversation, not a button.
        """
        order = await self._own_order(customer_id, order_id)
        if order.status != CustomerOrderStatus.PENDING:
            raise AppException(
                400, "لا يمكن إلغاء الطلب بعد أن بدأ المكتب في تجهيزه، يرجى الاتصال بنا."
            )
        order.status = CustomerOrderStatus.CANCELLED
        order.decision_note = reason or "ألغاه العميل."
        order.reviewed_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(order)
        return (await self._to_out([order]))[0]
