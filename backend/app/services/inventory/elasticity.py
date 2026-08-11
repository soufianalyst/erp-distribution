"""How much a discount actually lifts demand, learned from discounts already run.

Every markdown is an experiment nobody wrote down. A product was 12.00, it went to
9.60, and either it flew off the shelf or it did not. That answer is the difference
between a discount that clears the stock and one that gives away margin on goods
that would have sold anyway — and it is sitting in the invoice lines already.

The measure is the textbook one, price elasticity of demand:

    elasticity = ln(units after ÷ units before) ÷ ln(price after ÷ price before)

which comes out negative, because cutting the price raises the quantity. Around
-0.5 means "barely responds, discounting is mostly a gift"; around -2.5 means "very
responsive, a modest cut clears the shelf".

The single most important behaviour here is refusing to answer. Two offers is not
evidence, and an elasticity computed from one quiet fortnight would set the discount
depth for the whole catalogue. When there is not enough history this returns nothing
and the caller falls back to a stated assumption that it labels as an assumption.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.inventory import ProductOffer
from app.domain.models.sales import SalesInvoice, SalesInvoiceLine

# Offers shorter than this are noise: a two-day markdown over a weekend measures the
# weekend, not the price.
MIN_OFFER_DAYS = 5

# Below this many observations the median is one opinion wearing a lab coat.
MIN_OBSERVATIONS = 5

# Elasticities outside this range are almost always a coincidence — a product that
# happened to get a large order the week of the offer — rather than a price effect.
SANE_RANGE = (Decimal("-6"), Decimal("-0.1"))


@dataclass(frozen=True)
class Elasticity:
    value: Decimal
    # "measured" once there is real history; "assumed" until then. Carried all the
    # way to the screen, because a buyer deserves to know whether the number that
    # set a 40% discount was learned or guessed.
    source: str
    observations: int


class ElasticityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def measure(self, default: Decimal) -> Elasticity:
        """One elasticity for the business, from every offer worth measuring.

        Company-wide rather than per product: with a handful of offers there is
        nowhere near enough to split by product, and a per-product number computed
        from one observation would be worse than a shared one computed from twenty.
        Per-category is the natural next step once the history exists.
        """
        offers = (
            await self.session.execute(
                select(ProductOffer).order_by(ProductOffer.id)
            )
        ).scalars().all()

        observations: list[Decimal] = []
        for offer in offers:
            reading = await self._observe(offer)
            if reading is not None:
                observations.append(reading)

        if len(observations) < MIN_OBSERVATIONS:
            return Elasticity(
                value=default, source="assumed", observations=len(observations)
            )

        observations.sort()
        middle = len(observations) // 2
        median = (
            observations[middle]
            if len(observations) % 2
            else (observations[middle - 1] + observations[middle]) / 2
        )
        return Elasticity(
            value=median.quantize(Decimal("0.01")),
            source="measured",
            observations=len(observations),
        )

    async def _observe(self, offer: ProductOffer) -> Decimal | None:
        """One offer's elasticity, or nothing if it cannot be read honestly."""
        length = (offer.ends_on - offer.starts_on).days + 1
        if length < MIN_OFFER_DAYS or offer.discount_percent <= 0:
            return None

        during = await self._units(offer.product_id, offer.starts_on, offer.ends_on)
        before_end = offer.starts_on - timedelta(days=1)
        before = await self._units(
            offer.product_id, before_end - timedelta(days=length - 1), before_end
        )
        # A product that sold nothing either side tells us nothing; one that sold
        # nothing before and something during implies infinite elasticity, which is
        # an artefact of a zero, not a discovery about pricing.
        if before <= 0 or during <= 0:
            return None

        # Equal-length windows, so raw units compare directly without a rate.
        quantity_ratio = float(during) / float(before)
        price_ratio = 1 - float(offer.discount_percent) / 100
        if price_ratio <= 0 or quantity_ratio <= 0 or price_ratio == 1:
            return None

        value = Decimal(str(math.log(quantity_ratio) / math.log(price_ratio)))
        low, high = SANE_RANGE
        return value if low <= value <= high else None

    async def _units(self, product_id: int, start: date, end: date) -> Decimal:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(SalesInvoiceLine.quantity), 0))
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .where(
                SalesInvoiceLine.product_id == product_id,
                SalesInvoice.invoice_date >= start,
                SalesInvoice.invoice_date <= end,
            )
        )
        return Decimal(str(total or 0))
