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
    StaffOrderInvoiceIn,
    StaffOrderOut,
)
from app.api.schemas.sales import SalesInvoiceCreate, SalesLineIn
from app.core.exceptions import AppException
from app.core.permissions import has_permission
from app.domain.models.inventory import Product, ProductBatch, Warehouse
from app.domain.models.sales import (
    Customer,
    CustomerOrder,
    CustomerOrderLine,
    CustomerOrderStatus,
    SalesInvoice,
    SalesPaymentMethod,
)
from app.domain.models.user import User
from app.services.inventory.stock_query import sellable
from app.services.sales.offer_pricing import active_offers, apply_offer
from app.services.sales.sales_service import SalesService

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

    async def catalog(
        self, customer: Customer, search: str | None = None, limit: int = 60
    ) -> list[CatalogItemOut]:
        """Active products, searched and capped, with a band instead of a number.

        Paged at the database rather than in the browser. A shop opens this on a phone
        over mobile data, and the full range is a thousand rows — sending all of it so
        the client can show sixty is the customer paying for our convenience. Search
        runs here too, so a shop can reach the other nine hundred and forty.
        """
        # Offers are resolved *before* the page is cut, and sorted to the front in
        # SQL. Ordering them first in Python instead let the limit drop them: the
        # first sixty products alphabetically simply did not include the discounted
        # one, so a live markdown was invisible to every shop that did not search for
        # it by name. The offer is the reason the screen is worth opening.
        offers = await active_offers(self.session)
        offered_ids = list(offers)

        query = select(Product).where(Product.is_active.is_(True))
        if search:
            query = query.where(Product.name.ilike(f"%{search.strip()}%"))
        if offered_ids:
            query = query.order_by(
                Product.id.notin_(offered_ids), Product.name
            )
        else:
            query = query.order_by(Product.name)
        products = list(
            (await self.session.execute(query.limit(limit))).scalars().all()
        )
        on_hand = await self._on_hand([p.id for p in products])
        # Only offered lines carry a price, and both numbers are this customer's own:
        # their tier price, and that price discounted. A flat offer price would hand a
        # retail shop the wholesale figure and collapse the ladder.
        items = []
        for product in products:
            offer = offers.get(product.id)
            before = (
                SalesService.tier_price(product, customer.price_tier)
                if offer
                else None
            )
            items.append(
                CatalogItemOut(
                    product_id=product.id,
                    name=product.name,
                    unit=product.base_unit_name,
                    availability=_band(
                        on_hand.get(product.id, Decimal("0")), product.min_stock_level
                    ),
                    price_before=before,
                    price_now=apply_offer(before, offer) if offer else None,
                    discount_percent=offer.discount_percent if offer else None,
                    offer_note=offer.note if offer else None,
                    offer_ends_on=offer.ends_on if offer else None,
                )
            )
        return items

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

    async def own_order(self, customer_id: int, order_id: int):
        """The order row itself, after the ownership check.

        The tracker needs the model, not the output schema — but it must go through
        the same gate, so one customer cannot follow another's order by guessing a
        number.
        """
        return await self._own_order(customer_id, order_id)

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


class OrderReviewService:
    """The office side of the same orders.

    Kept apart from `PortalOrderService` for the reason the two auth services are
    apart: these methods take a staff `User` and may act on any customer's order,
    and one class holding both would eventually grow a method that forgets which
    kind of caller it has.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.portal = PortalOrderService(session)

    async def _staff_out(self, orders: list[CustomerOrder]) -> list[StaffOrderOut]:
        base = await self.portal._to_out(orders)
        customers = {
            c.id: c.name
            for c in (
                await self.session.execute(
                    select(Customer).where(
                        Customer.id.in_({o.customer_id for o in orders} or {0})
                    )
                )
            )
            .scalars()
            .all()
        }
        return [
            StaffOrderOut(
                **out.model_dump(),
                customer_id=order.customer_id,
                customer_name=customers.get(order.customer_id, "—"),
            )
            for order, out in zip(orders, base)
        ]

    async def list_orders(
        self, user: User, status: CustomerOrderStatus | None = None
    ) -> list[StaffOrderOut]:
        """The review queue, oldest first.

        Oldest first is deliberate: a queue worked newest-first leaves the shop who
        ordered on Sunday still waiting on Thursday.

        Scoped the same way invoices are — a salesman without `sales.all_customers`
        sees only the shops that are his. `create_invoice` would refuse him another
        rep's customer anyway, but a queue that lists orders he cannot act on is
        both noise and a disclosure of who else we sell to.
        """
        query = (
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.lines))
            .order_by(CustomerOrder.id)
        )
        if status is not None:
            query = query.where(CustomerOrder.status == status)
        if not has_permission(user, "sales.all_customers"):
            query = query.where(
                CustomerOrder.customer_id.in_(
                    select(Customer.id).where(Customer.salesman_id == user.id)
                )
            )
        orders = list((await self.session.execute(query)).scalars().all())
        return await self._staff_out(orders)

    async def _get(self, order_id: int, user: User) -> CustomerOrder:
        """Fetch an order this user is allowed to act on.

        The reach check is part of the lookup, so approve/reject/invoice cannot each
        forget it separately — and an order belonging to another rep's customer
        answers 404 rather than 403, for the same reason it does on the portal side.
        """
        query = (
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.lines))
            .where(CustomerOrder.id == order_id)
        )
        if not has_permission(user, "sales.all_customers"):
            query = query.where(
                CustomerOrder.customer_id.in_(
                    select(Customer.id).where(Customer.salesman_id == user.id)
                )
            )
        order = (await self.session.execute(query)).scalar_one_or_none()
        if order is None:
            raise AppException(404, "الطلب غير موجود.")
        return order

    async def approve(self, order_id: int, user: User) -> StaffOrderOut:
        """Accept a request so the warehouse can start picking.

        Separate from invoicing on purpose: the customer gets an answer now, and the
        invoice is raised when the goods are actually gathered and priced.
        """
        order = await self._get(order_id, user)
        if order.status != CustomerOrderStatus.PENDING:
            raise AppException(400, "لا يمكن اعتماد طلب سبق البتّ فيه.")
        order.status = CustomerOrderStatus.CONFIRMED
        order.reviewed_by = user.id
        order.reviewed_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(order)
        return (await self._staff_out([order]))[0]

    async def reject(self, order_id: int, reason: str, user: User) -> StaffOrderOut:
        """Refuse a request, with a reason the customer will read."""
        order = await self._get(order_id, user)
        if order.status in (
            CustomerOrderStatus.INVOICED,
            CustomerOrderStatus.CANCELLED,
        ):
            raise AppException(400, "لا يمكن رفض طلب سبق البتّ فيه.")
        order.status = CustomerOrderStatus.CANCELLED
        order.decision_note = reason
        order.reviewed_by = user.id
        order.reviewed_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(order)
        return (await self._staff_out([order]))[0]

    async def to_invoice(
        self, order_id: int, data: StaffOrderInvoiceIn, user: User
    ) -> SalesInvoice:
        """Turn an order into a real sale, through the ordinary sales pipeline.

        Nothing about invoicing is reimplemented here — FEFO allocation, the credit
        limit, the tax breakdown and the journal entry all belong to
        `SalesService.create_invoice`, and a second path to any of them is how the
        two drift. This method's whole job is to hand the order's lines over and
        record which invoice answered which request.

        Not idempotent by accident: an order already invoiced is refused, so a
        double-click cannot bill a shop twice for one request.
        """
        order = await self._get(order_id, user)
        if order.status == CustomerOrderStatus.INVOICED:
            raise AppException(409, "سبق أن صدرت فاتورة لهذا الطلب.")
        if order.status == CustomerOrderStatus.CANCELLED:
            raise AppException(400, "الطلب ملغى، لا يمكن إصدار فاتورة له.")

        invoice = await SalesService(self.session).create_invoice(
            SalesInvoiceCreate(
                customer_id=order.customer_id,
                payment_method=SalesPaymentMethod(data.payment_method),
                fulfillment=order.fulfillment,
                tax_rate_ids=data.tax_rate_ids,
                notes=data.notes or order.notes,
                credit_override=data.credit_override,
                lines=[
                    SalesLineIn(product_id=line.product_id, quantity=line.quantity)
                    for line in order.lines
                ],
            ),
            user,
            source_warehouse_id=data.warehouse_id,
        )

        order.status = CustomerOrderStatus.INVOICED
        order.invoice_id = invoice.id
        order.reviewed_by = user.id
        order.reviewed_at = datetime.now(timezone.utc)
        await self.session.commit()
        return invoice
