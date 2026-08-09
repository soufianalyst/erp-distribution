"""Turning the expiry alert into a list of things to do.

`AnalyticsService.expiry_risk` already answers "what is about to expire". A manager
reading it still has the two hard questions in front of them: *will it sell anyway*,
and *who do I ring*. This answers both, so the list can be worked from the top down
instead of stared at.

Two ideas do the work.

**Surplus, not stock.** Two hundred units expiring in thirty days is not a problem if
the product moves ten a day — it will be gone with a week to spare. The same two
hundred is a write-off if it moves one a day. So the number that matters is the part
that will *not* sell at the current rate, and everything is ranked on that.

**Who buys it.** Nothing here invents a customer. It reads who has actually bought
this product before, most recent and largest first, because those are the calls most
likely to land.

The output is deliberately advice, not action: nothing is reserved, discounted or
sent. A manager decides, and the ordinary sales pipeline does the selling.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.analytics import (
    ExpiryWorklistItemOut,
    ExpiryWorklistOut,
    SuggestedBuyerOut,
)
from app.domain.models.inventory import Product, ProductBatch, Warehouse
from app.domain.models.sales import Customer, SalesInvoice, SalesInvoiceLine
from app.services.inventory.stock_query import sellable

TWO_PLACES = Decimal("0.01")

# How far back to measure how fast something sells. Long enough to survive a quiet
# fortnight, short enough that last season's demand does not vouch for this one.
#
# The rate divides by the whole window, which understates anything that only started
# selling recently: a line launched last week reads as slow, and may be flagged when
# it is in fact accelerating. That is the conservative direction — it over-warns
# rather than under-warns — and dividing by "days since first sale" instead would let
# a single day's burst imply a rate the product has never sustained. Worth revisiting
# once there is enough real history to tell the two apart.
VELOCITY_WINDOW_DAYS = 90

# How many past buyers to name per product. A list of thirty is not a call list.
MAX_SUGGESTED_BUYERS = 5


class ExpiryWorklistService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _daily_rate(self, product_ids: list[int]) -> dict[int, Decimal]:
        """Units sold per day per product over the recent window.

        Returns nothing for a product that has not sold, and the caller treats that
        as a rate of zero — which is the conservative reading: with no evidence it
        moves, assume none of it will.
        """
        if not product_ids:
            return {}
        since = date.today() - timedelta(days=VELOCITY_WINDOW_DAYS)
        rows = (
            await self.session.execute(
                select(
                    SalesInvoiceLine.product_id,
                    func.sum(SalesInvoiceLine.quantity),
                )
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
                .where(
                    SalesInvoiceLine.product_id.in_(product_ids),
                    SalesInvoice.invoice_date >= since,
                )
                .group_by(SalesInvoiceLine.product_id)
            )
        ).all()
        return {
            product_id: (Decimal(str(total)) / Decimal(VELOCITY_WINDOW_DAYS))
            for product_id, total in rows
            if total
        }

    async def _buyers(self, product_ids: list[int]) -> dict[int, list[SuggestedBuyerOut]]:
        """Customers who have actually bought each product, best prospects first.

        Ranked by how much they have taken and how recently. No modelling: a shop
        that bought forty cases last month is a better call than one that took two a
        year ago, and that ordering is the whole of the intelligence needed here.
        """
        if not product_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    SalesInvoiceLine.product_id,
                    Customer.id,
                    Customer.name,
                    Customer.phone,
                    func.sum(SalesInvoiceLine.quantity).label("total_quantity"),
                    func.max(SalesInvoice.invoice_date).label("last_bought"),
                )
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
                .join(Customer, Customer.id == SalesInvoice.customer_id)
                .where(
                    SalesInvoiceLine.product_id.in_(product_ids),
                    Customer.is_active.is_(True),
                )
                .group_by(SalesInvoiceLine.product_id, Customer.id, Customer.name, Customer.phone)
                .order_by(
                    SalesInvoiceLine.product_id,
                    func.max(SalesInvoice.invoice_date).desc(),
                    func.sum(SalesInvoiceLine.quantity).desc(),
                )
            )
        ).all()

        buyers: dict[int, list[SuggestedBuyerOut]] = {}
        for product_id, customer_id, name, phone, total_quantity, last_bought in rows:
            bucket = buyers.setdefault(product_id, [])
            if len(bucket) >= MAX_SUGGESTED_BUYERS:
                continue
            bucket.append(
                SuggestedBuyerOut(
                    customer_id=customer_id,
                    customer_name=name,
                    phone=phone,
                    total_quantity=Decimal(str(total_quantity)),
                    last_bought=last_bought,
                )
            )
        return buyers

    def _at_risk_batches(self, horizon_days: int) -> Select:
        today = date.today()
        return (
            select(ProductBatch, Product, Warehouse.name)
            .join(Product, Product.id == ProductBatch.product_id)
            .join(Warehouse, Warehouse.id == ProductBatch.warehouse_id)
            .where(
                # `sellable()` excludes anything already expired: that is a write-off,
                # not a selling opportunity, and mixing the two would let a growing
                # pile of dead stock inflate a list meant to prompt phone calls.
                sellable(),
                ProductBatch.expiry_date <= today + timedelta(days=horizon_days),
                Warehouse.is_active.is_(True),
            )
        )

    async def worklist(self, horizon_days: int = 60) -> ExpiryWorklistOut:
        """What is about to expire, what of it will not sell, and who to call.

        Grouped by product rather than by batch: three batches of the same yoghurt
        expiring in the same fortnight are one phone call, not three, and ranking
        batches separately would push that call down the list three times over.
        """
        today = date.today()
        rows = (await self.session.execute(self._at_risk_batches(horizon_days))).all()

        grouped: dict[int, dict] = {}
        for batch, product, warehouse_name in rows:
            entry = grouped.setdefault(
                product.id,
                {
                    "product": product,
                    "quantity": Decimal("0"),
                    "value": Decimal("0"),
                    "earliest": batch.expiry_date,
                    "warehouses": set(),
                    "batches": 0,
                },
            )
            unit_cost = batch.unit_cost or Decimal("0")
            entry["quantity"] += batch.quantity
            entry["value"] += batch.quantity * unit_cost
            entry["earliest"] = min(entry["earliest"], batch.expiry_date)
            entry["warehouses"].add(warehouse_name)
            entry["batches"] += 1

        product_ids = list(grouped)
        rates = await self._daily_rate(product_ids)
        buyers = await self._buyers(product_ids)

        items: list[ExpiryWorklistItemOut] = []
        for product_id, entry in grouped.items():
            days_remaining = (entry["earliest"] - today).days
            rate = rates.get(product_id, Decimal("0"))
            will_sell = rate * Decimal(max(days_remaining, 0))
            surplus = max(entry["quantity"] - will_sell, Decimal("0"))

            unit_value = (
                entry["value"] / entry["quantity"] if entry["quantity"] else Decimal("0")
            )
            surplus_value = (surplus * unit_value).quantize(TWO_PLACES)

            # Cost of doing nothing, per day of runway left. A large sum with a month
            # to arrange something ranks below a smaller one that must move this week.
            urgency = surplus_value / Decimal(max(days_remaining, 1))

            items.append(
                ExpiryWorklistItemOut(
                    product_id=product_id,
                    product_name=entry["product"].name,
                    unit=entry["product"].base_unit_name,
                    batches=entry["batches"],
                    warehouses=sorted(entry["warehouses"]),
                    earliest_expiry=entry["earliest"],
                    days_remaining=days_remaining,
                    quantity_at_risk=entry["quantity"],
                    daily_sales_rate=rate.quantize(Decimal("0.001")),
                    projected_sales=will_sell.quantize(Decimal("0.001")),
                    surplus_quantity=surplus.quantize(Decimal("0.001")),
                    surplus_value=surplus_value,
                    urgency=urgency.quantize(TWO_PLACES),
                    has_sales_history=product_id in rates,
                    suggested_buyers=buyers.get(product_id, []),
                )
            )

        # Only what will not clear on its own is worth a manager's attention; the rest
        # is noise that trains people to ignore the screen.
        at_risk = [i for i in items if i.surplus_quantity > 0]

        # Split, because the two halves need different actions and the dead half is
        # both larger and louder — everything that never sold scores maximum surplus,
        # so mixed together it buries every call worth making.
        selling = sorted(
            (i for i in at_risk if i.has_sales_history),
            key=lambda i: i.urgency,
            reverse=True,
        )
        dead = sorted(
            (i for i in at_risk if not i.has_sales_history),
            key=lambda i: i.urgency,
            reverse=True,
        )

        return ExpiryWorklistOut(
            horizon_days=horizon_days,
            velocity_window_days=VELOCITY_WINDOW_DAYS,
            total_products=len(selling),
            total_surplus_value=sum(
                (i.surplus_value for i in selling), Decimal("0")
            ).quantize(TWO_PLACES),
            items=selling,
            dead_stock=dead,
            dead_stock_value=sum(
                (i.surplus_value for i in dead), Decimal("0")
            ).quantize(TWO_PLACES),
        )
