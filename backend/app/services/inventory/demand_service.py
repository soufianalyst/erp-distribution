"""How fast a product sells, how sure we are, and how long it keeps.

One definition, because "demand" is about to be asked for by the reorder point, the
suggested order quantity and the expiry cap, and three slightly different answers
would be three slightly different reorder points.

The confidence tier is the honest part. Measured over a year on the seeded database,
16 products have 24 or more sale-days, 29 have 12–23, 7 have 4–11 and **439 sold on
one to three days**. A mean and a standard deviation taken from three sale-days is
noise wearing the clothes of arithmetic, and a reorder point built on it would be
worse than the number a buyer typed — because it would look calculated. So a product
only gets a computed point when there is something to compute from, and otherwise
says so and stands aside.
"""

from dataclasses import dataclass
from statistics import median
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.inventory import Product, ProductBatch
from app.domain.models.purchases import PurchaseInvoice, PurchaseInvoiceLine, Supplier
from app.domain.models.sales import SalesInvoice, SalesInvoiceLine

THREE_PLACES = Decimal("0.001")
ZERO = Decimal("0")

# A year. Shorter windows look tempting — recent demand is more relevant — but with
# demand this lumpy a 90-day window leaves only three products with enough
# sale-days to measure, and everything else falls back. A year trades some
# freshness for the ability to say anything at all.
WINDOW_DAYS = 365

# Sale-days needed before a rate is treated as measured rather than guessed. Eight
# is roughly "sold on average twice a month" — below that a single unusual order
# moves the rate more than the underlying trade does.
MIN_SALE_DAYS = 8


class DemandConfidence(str, Enum):
    MEASURED = "measured"  # enough sale-days to compute a rate
    SPARSE = "sparse"  # sells, but too rarely to estimate
    NONE = "none"  # no sales in the window at all


@dataclass(frozen=True)
class Demand:
    product_id: int
    # Units of the base unit sold per calendar day, averaged across the window
    # including days with no sales — which is what a reorder point needs, since
    # stock drains on the quiet days too.
    daily_rate: Decimal
    sale_days: int
    total_quantity: Decimal
    confidence: DemandConfidence
    # Typical days between a batch arriving and its expiry date, from purchase
    # history. None when this product has never been received with both dates.
    shelf_life_days: int | None

    # Lead time that applies to this product: its most recent supplier's, or the
    # company default.
    lead_time_days: int
    supplier_name: str | None

    @property
    def is_measured(self) -> bool:
        """Whether this rate may be projected forward at all.

        A rate exists for anything that sold once; it is only *usable* when there
        were enough separate sale-days behind it to be a pattern rather than an
        anecdote. Callers that skip this check get a number, which is worse than
        getting nothing, because a number gets acted on.
        """
        return self.confidence is DemandConfidence.MEASURED and self.daily_rate > ZERO

    def confident_projection(self, days: int) -> Decimal:
        """Units that will move in `days`, or nothing if the rate is not trustworthy.

        For decisions that commit to something. A markdown sets a price the customer
        is charged, so a rate from three sale-days must project to zero rather than
        to a plausible-looking number: better to call the whole batch surplus and be
        told to phone a customer than to discount on the strength of an anecdote.
        """
        if not self.is_measured or days <= 0:
            return ZERO
        return self.daily_rate * Decimal(days)

    def nominal_projection(self, days: int) -> Decimal:
        """Units that will move in `days` at whatever rate exists, thin or not.

        For advisory screens. The expiry worklist earns its keep by *not* listing
        stock that will clear on its own, and on this catalogue 439 of 1,060 products
        sold on three days or fewer in a year — gate those to zero and the list
        becomes the wall of noise it was built to replace.

        Two named methods rather than one with a flag, because the rate underneath is
        the thing that must never diverge, while this choice is a real editorial
        difference between a price commitment and a suggestion. Naming both makes a
        call site declare which it is instead of doing its own multiplication.
        """
        if days <= 0:
            return ZERO
        return self.daily_rate * Decimal(days)


class DemandService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def for_products(
        self,
        product_ids: list[int] | None = None,
        *,
        default_lead_time_days: int,
        on: date | None = None,
        window_days: int = WINDOW_DAYS,
    ) -> dict[int, Demand]:
        """Demand for every product, or just the ones asked for.

        Built as one pass over three aggregate queries rather than per product: the
        reorder screen asks about the whole catalogue, and a query per product would
        be a thousand round trips to answer one question.
        """
        today = on or date.today()
        # The window is a parameter because the right length depends on the
        # question. A reorder point wants a year: it is a standing policy and
        # benefits from every scrap of signal. An expiry decision wants a quarter,
        # because what matters is whether this stock moves *now*, and a brisk
        # spring should not vouch for a dead autumn. Same definition, one knob —
        # two separately-written rate calculations would drift within a month.
        window_start = today - timedelta(days=window_days)

        sold = await self._sales(product_ids, window_start, today)
        shelf_lives = await self._shelf_lives(product_ids)
        suppliers = await self._last_supplier(product_ids)
        lead_times = await self._supplier_lead_times()

        ids = product_ids
        if ids is None:
            ids = list(
                (await self.session.execute(select(Product.id))).scalars()
            )

        demand: dict[int, Demand] = {}
        for product_id in ids:
            sale_days, quantity = sold.get(product_id, (0, ZERO))
            if sale_days == 0:
                confidence = DemandConfidence.NONE
            elif sale_days < MIN_SALE_DAYS:
                confidence = DemandConfidence.SPARSE
            else:
                confidence = DemandConfidence.MEASURED

            supplier_id, supplier_name = suppliers.get(product_id, (None, None))
            lead_time = lead_times.get(supplier_id) if supplier_id else None

            demand[product_id] = Demand(
                product_id=product_id,
                daily_rate=(quantity / Decimal(window_days)).quantize(THREE_PLACES),
                sale_days=sale_days,
                total_quantity=quantity,
                confidence=confidence,
                shelf_life_days=shelf_lives.get(product_id),
                lead_time_days=lead_time or default_lead_time_days,
                supplier_name=supplier_name,
            )
        return demand

    async def _sales(
        self, product_ids: list[int] | None, start: date, end: date
    ) -> dict[int, tuple[int, Decimal]]:
        """Sale-days and total quantity per product across the window.

        Distinct invoice *dates*, not invoice count: three invoices on one morning
        are one day of trade, and counting them as three would treat a single busy
        Tuesday as a pattern.
        """
        stmt = (
            select(
                SalesInvoiceLine.product_id,
                func.count(func.distinct(SalesInvoice.invoice_date)),
                func.coalesce(func.sum(SalesInvoiceLine.quantity), 0),
            )
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .where(
                SalesInvoice.invoice_date >= start,
                SalesInvoice.invoice_date <= end,
            )
            .group_by(SalesInvoiceLine.product_id)
        )
        if product_ids is not None:
            stmt = stmt.where(SalesInvoiceLine.product_id.in_(product_ids))
        return {
            pid: (int(days), Decimal(str(qty)))
            for pid, days, qty in (await self.session.execute(stmt)).all()
        }

    async def _shelf_lives(self, product_ids: list[int] | None) -> dict[int, int]:
        """Median days from receipt to expiry, per product.

        The median rather than the mean, because one batch received near the end of
        its life would otherwise drag the figure down and cap every future order far
        below what the goods can actually take.
        """
        stmt = select(ProductBatch.product_id, ProductBatch.received_at, ProductBatch.expiry_date)
        if product_ids is not None:
            stmt = stmt.where(ProductBatch.product_id.in_(product_ids))

        spans: dict[int, list[int]] = {}
        for product_id, received_at, expiry in (
            await self.session.execute(stmt)
        ).all():
            if received_at is None or expiry is None:
                continue
            days = (expiry - received_at.date()).days
            if days > 0:
                spans.setdefault(product_id, []).append(days)

        return {pid: int(median(values)) for pid, values in spans.items() if values}

    async def _last_supplier(
        self, product_ids: list[int] | None
    ) -> dict[int, tuple[int, str]]:
        """Who we bought each product from most recently.

        There is no preferred-supplier field, so the last one to sell it to us is
        the best available guess at whose lead time applies.
        """
        stmt = (
            select(
                PurchaseInvoiceLine.product_id,
                PurchaseInvoice.supplier_id,
                Supplier.name,
                PurchaseInvoice.id,
            )
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.invoice_id)
            .join(Supplier, Supplier.id == PurchaseInvoice.supplier_id)
            .order_by(PurchaseInvoiceLine.product_id, PurchaseInvoice.id.desc())
        )
        if product_ids is not None:
            stmt = stmt.where(PurchaseInvoiceLine.product_id.in_(product_ids))

        latest: dict[int, tuple[int, str]] = {}
        for product_id, supplier_id, name, _ in (
            await self.session.execute(stmt)
        ).all():
            # Ordered newest first, so the first row seen per product is the latest.
            latest.setdefault(product_id, (supplier_id, name))
        return latest

    async def _supplier_lead_times(self) -> dict[int, int]:
        """Suppliers who have stated their own lead time; the rest use the default."""
        return {
            supplier_id: lead
            for supplier_id, lead in (
                await self.session.execute(
                    select(Supplier.id, Supplier.lead_time_days).where(
                        Supplier.lead_time_days.is_not(None)
                    )
                )
            ).all()
        }


def rounded_units(value: Decimal) -> Decimal:
    """Whole base units — you cannot order two thirds of a sack."""
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
