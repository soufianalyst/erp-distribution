"""Creating and withdrawing the markdowns customers see.

The office half of `offer_pricing`, which is the read half. Everything here is about
making the decision an informed one: a discount is set against a product whose cost
is known, so the screen can say what it does to the margin before anyone commits.

Selling below cost is allowed. For food approaching its date it is often the right
call — recovering sixty per cent of cost beats recovering none — but it is flagged
rather than silently permitted, because the same number typed by mistake is a loss
nobody notices until the month closes.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.inventory import ProductOfferCreate, ProductOfferOut
from app.core.exceptions import AppException
from app.domain.models.inventory import Product, ProductBatch, ProductOffer
from app.services.sales.offer_pricing import apply_offer


class OfferService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _average_cost(self, product_id: int) -> Decimal | None:
        """Cost per unit across stock still held, weighted by quantity.

        The batch average rather than the newest cost: what matters when deciding a
        markdown is what the goods on the shelf actually cost, not what the next
        delivery will.
        """
        row = (
            await self.session.execute(
                select(
                    func.sum(ProductBatch.quantity * ProductBatch.unit_cost),
                    func.sum(ProductBatch.quantity),
                ).where(
                    ProductBatch.product_id == product_id,
                    ProductBatch.quantity > 0,
                    ProductBatch.unit_cost.is_not(None),
                )
            )
        ).one()
        value, quantity = row
        if not quantity:
            return None
        return Decimal(str(value)) / Decimal(str(quantity))

    async def _to_out(self, offer: ProductOffer, today: date) -> ProductOfferOut:
        product = offer.product
        unit_cost = await self._average_cost(offer.product_id)
        offer_price = apply_offer(product.wholesale_price, offer)
        return ProductOfferOut(
            id=offer.id,
            product_id=offer.product_id,
            product_name=product.name,
            discount_percent=offer.discount_percent,
            starts_on=offer.starts_on,
            ends_on=offer.ends_on,
            note=offer.note,
            is_active=offer.is_active,
            is_live=(
                offer.is_active and offer.starts_on <= today <= offer.ends_on
            ),
            wholesale_price=product.wholesale_price,
            offer_price=offer_price,
            unit_cost=unit_cost,
            below_cost=unit_cost is not None and offer_price < unit_cost,
        )

    async def create(
        self, data: ProductOfferCreate, created_by: int | None
    ) -> ProductOfferOut:
        product = await self.session.get(Product, data.product_id)
        if product is None:
            raise AppException(404, "الصنف غير موجود.")
        if not product.is_active:
            raise AppException(400, "لا يمكن إنشاء عرض على صنف موقوف.")
        if data.ends_on < data.starts_on:
            raise AppException(400, "تاريخ نهاية العرض قبل بدايته.")
        # A window that has already closed would be accepted by the database and then
        # do nothing, which looks identical to a broken feature.
        if data.ends_on < date.today():
            raise AppException(400, "انتهى تاريخ العرض قبل إنشائه.")

        offer = ProductOffer(
            product_id=data.product_id,
            discount_percent=data.discount_percent,
            starts_on=data.starts_on,
            ends_on=data.ends_on,
            note=data.note,
            created_by=created_by,
        )
        self.session.add(offer)
        await self.session.commit()
        await self.session.refresh(offer, attribute_names=["product"])
        return await self._to_out(offer, date.today())

    async def end(self, offer_id: int) -> ProductOfferOut:
        """Stop an offer now, without deleting it.

        Deactivated rather than removed: invoices raised while it ran were priced by
        it, and a discount that vanishes leaves a line nobody can explain.
        """
        offer = await self.session.get(
            ProductOffer, offer_id, options=[selectinload(ProductOffer.product)]
        )
        if offer is None:
            raise AppException(404, "العرض غير موجود.")
        offer.is_active = False
        await self.session.commit()
        await self.session.refresh(offer, attribute_names=["product"])
        return await self._to_out(offer, date.today())

    async def list_offers(self, include_ended: bool = False) -> list[ProductOfferOut]:
        query = (
            select(ProductOffer)
            .options(selectinload(ProductOffer.product))
            .order_by(ProductOffer.ends_on.desc())
        )
        if not include_ended:
            query = query.where(
                ProductOffer.is_active.is_(True),
                ProductOffer.ends_on >= date.today(),
            )
        offers = list((await self.session.execute(query)).scalars().all())
        today = date.today()
        return [await self._to_out(offer, today) for offer in offers]
