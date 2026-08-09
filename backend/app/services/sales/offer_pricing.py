"""What a customer actually pays today, offers included.

Kept in one place because the number has to be identical in three: the price the
portal shows a shop, the price the office sees while deciding, and the price the
invoice charges. The moment a customer is shown "was 12.00, now 9.60" that is a
promise, and a promise kept only by the display is how you quote one number and bill
another.

So the offer is applied inside price resolution rather than passed in by the caller.
A caller who forgets is not possible; there is nothing to forget.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.inventory import ProductOffer

TWO_PLACES = Decimal("0.01")


async def active_offers(
    session: AsyncSession, product_ids: list[int] | None = None, on: date | None = None
) -> dict[int, ProductOffer]:
    """The live offer per product, best discount winning where several overlap.

    Overlapping offers are allowed rather than refused — a category-wide markdown and
    a clearance on one line are both legitimate, and refusing the second would make
    the office undo the first. When they collide the customer gets the better of the
    two, which is the only choice that cannot be argued with afterwards.
    """
    today = on or date.today()
    query = select(ProductOffer).where(
        ProductOffer.is_active.is_(True),
        ProductOffer.starts_on <= today,
        ProductOffer.ends_on >= today,
    )
    if product_ids is not None:
        if not product_ids:
            return {}
        query = query.where(ProductOffer.product_id.in_(product_ids))

    best: dict[int, ProductOffer] = {}
    for offer in (await session.execute(query)).scalars().all():
        current = best.get(offer.product_id)
        if current is None or offer.discount_percent > current.discount_percent:
            best[offer.product_id] = offer
    return best


def apply_offer(base_price: Decimal, offer: ProductOffer | None) -> Decimal:
    """The discounted price, rounded to the currency.

    Rounded here, once, rather than left for each caller: the portal rounding to two
    places while the invoice rounds at the line total is exactly how a customer ends
    up disputing a fils, and being right.
    """
    if offer is None:
        return base_price
    factor = (Decimal("100") - offer.discount_percent) / Decimal("100")
    return (base_price * factor).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
