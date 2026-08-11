"""What to do with stock that is heading for its expiry date, and what it is worth.

Measured on the seeded database: 51.5M of stock at cost against 3.16M of annual
revenue — sixteen years of cover — with 24.4M expiring inside sixty days and not a
single expiry write-off yet recorded. The markdown machinery has been used three
times. The loss is real and it is happening off the books.

This turns that into a decision list. Every batch lands in exactly one of four
buckets, and the honest part is that only one of them is a pricing problem:

  **leave**      sells fast enough to clear on its own — do nothing
  **markdown**   sells, but not fast enough; a discount can close the gap
  **push**       barely sells, yet specific shops have bought it before; this is a
                 phone call, not a price
  **write_off**  never sold, no buyer on record. No discount reaches zero demand.
                 Recognise the loss and stop reordering.

The fourth bucket is where most of the money is, and refusing to dress it up as a
pricing opportunity is the most useful thing here. A markdown engine that quietly
proposed 50% off nine hundred dead lines would look industrious and change nothing.

**The discount stages itself.** There is no ladder of "10% at 30 days, 25% at 14".
The depth falls out of the arithmetic: clearing the stock needs a rate of
`quantity ÷ days left`, and as the date approaches that required rate climbs, so the
discount deepens on its own, recomputed every time the plan is opened. A ladder would
be a second, wronger model of the same thing.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.inventory import Product, ProductBatch, Warehouse
from app.domain.models.sales import Customer, SalesInvoice, SalesInvoiceLine
from app.services.inventory.demand_service import DemandConfidence, DemandService
from app.services.inventory.elasticity import Elasticity, ElasticityService
from app.services.sales.offer_pricing import active_offers

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")

# Recent demand, not a year of it. Whether this stock moves *now* is the question;
# a brisk spring must not vouch for a dead autumn.
DEMAND_WINDOW_DAYS = 90

# Until enough discounts have been run to measure it. -1.5 is a middling grocery
# figure: a 20% cut buys roughly a third more units. Labelled "assumed" everywhere
# it is used, and replaced by the real number the moment there is one.
ASSUMED_ELASTICITY = Decimal("-1.5")

# Below this the paperwork costs more than the margin saved.
MIN_USEFUL_DISCOUNT = Decimal("5")

# How many past buyers to name on a "push" row.
MAX_BUYERS = 4


@dataclass(frozen=True)
class Buyer:
    customer_id: int
    name: str
    phone: str | None
    last_bought: date
    units: Decimal


@dataclass(frozen=True)
class Proposal:
    batch_id: int
    product_id: int
    sku: str
    name: str
    batch_number: str
    warehouse_name: str
    expiry_date: date
    days_left: int
    quantity: Decimal
    unit_cost: Decimal | None
    stock_value: Decimal
    daily_rate: Decimal
    # Units that will still be on the shelf on the expiry date at the current rate.
    surplus: Decimal
    surplus_value: Decimal
    action: str  # leave | markdown | push | write_off
    discount_percent: Decimal | None
    price_before: Decimal | None
    price_now: Decimal | None
    # Cash this recovers if the plan works, against losing the surplus entirely.
    recovery_value: Decimal
    reason: str
    buyers: list[Buyer]
    # The discount already running on this product, if one is. A batch under a live
    # offer stays on the list — the stock is still at risk and the manager still
    # needs to see it — but it must not invite a second tick, because the depth
    # below was computed from a sales rate the running discount is already changing.
    active_offer_percent: Decimal | None = None


@dataclass
class MarkdownPlan:
    horizon_days: int
    elasticity: Elasticity
    stock_at_risk: Decimal
    surplus_value: Decimal
    recoverable_value: Decimal
    write_off_value: Decimal
    items: list[Proposal]


class MarkdownService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def plan(
        self, horizon_days: int = 60, max_discount: Decimal = Decimal("50")
    ) -> MarkdownPlan:
        today = date.today()
        rows = (
            await self.session.execute(
                select(ProductBatch, Product, Warehouse)
                .join(Product, Product.id == ProductBatch.product_id)
                .join(Warehouse, Warehouse.id == ProductBatch.warehouse_id)
                .where(
                    ProductBatch.quantity > 0,
                    ProductBatch.expiry_date > today,
                    ProductBatch.expiry_date <= today + _days(horizon_days),
                    Product.is_active.is_(True),
                )
                .order_by(ProductBatch.expiry_date)
            )
        ).all()
        if not rows:
            return MarkdownPlan(
                horizon_days=horizon_days,
                elasticity=await ElasticityService(self.session).measure(
                    ASSUMED_ELASTICITY
                ),
                stock_at_risk=ZERO,
                surplus_value=ZERO,
                recoverable_value=ZERO,
                write_off_value=ZERO,
                items=[],
            )

        product_ids = list({batch.product_id for batch, _, _ in rows})
        demand = await DemandService(self.session).for_products(
            product_ids, default_lead_time_days=7, window_days=DEMAND_WINDOW_DAYS
        )
        elasticity = await ElasticityService(self.session).measure(ASSUMED_ELASTICITY)
        buyers = await self._buyers(product_ids)
        live = await active_offers(self.session, product_ids, on=today)

        items = [
            self._propose(
                batch, product, warehouse, today,
                demand[batch.product_id], elasticity, max_discount,
                buyers.get(batch.product_id, []),
                live.get(batch.product_id),
            )
            for batch, product, warehouse in rows
        ]
        # Worst first: the money you are about to lose, not the number of units.
        items.sort(key=lambda i: i.surplus_value, reverse=True)

        return MarkdownPlan(
            horizon_days=horizon_days,
            elasticity=elasticity,
            stock_at_risk=_sum(i.stock_value for i in items),
            surplus_value=_sum(i.surplus_value for i in items),
            recoverable_value=_sum(i.recovery_value for i in items),
            write_off_value=_sum(
                i.surplus_value for i in items if i.action == "write_off"
            ),
            items=items,
        )

    def _propose(
        self, batch, product, warehouse, today, demand,
        elasticity: Elasticity, max_discount: Decimal, buyers: list[Buyer],
        live_offer=None,
    ) -> Proposal:
        days_left = (batch.expiry_date - today).days
        quantity = Decimal(str(batch.quantity))
        cost = Decimal(str(batch.unit_cost)) if batch.unit_cost is not None else None
        stock_value = quantity * (cost or ZERO)

        measured = demand.confidence is DemandConfidence.MEASURED and demand.daily_rate > 0
        sellable = demand.daily_rate * Decimal(days_left) if measured else ZERO
        surplus = max(quantity - sellable, ZERO)
        surplus_value = (surplus * (cost or ZERO)).quantize(TWO_PLACES)

        base = self._make(
            batch, product, warehouse, days_left, quantity, cost, stock_value,
            demand, surplus, surplus_value,
            live_offer.discount_percent if live_offer is not None else None,
        )

        if measured and surplus <= 0:
            return base(
                action="leave",
                reason=(
                    f"يبيع {demand.daily_rate} يومياً — سينفد قبل انتهاء صلاحيته "
                    f"بعد {days_left} يوم."
                ),
            )

        if measured:
            discount = self._discount_to_clear(
                quantity, demand.daily_rate, days_left, elasticity.value, max_discount
            )
            if discount < MIN_USEFUL_DISCOUNT:
                return base(
                    action="leave",
                    reason="الفائض ضئيل — لا يستحق خصماً.",
                )
            before = Decimal(str(product.wholesale_price))
            now = (before * (Decimal("100") - discount) / Decimal("100")).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            return base(
                action="markdown",
                discount_percent=discount,
                price_before=before,
                price_now=now,
                # What the discounted sale brings in, versus nothing if it expires.
                recovery_value=(surplus * now).quantize(TWO_PLACES),
                reason=(
                    f"يبيع {demand.daily_rate} يومياً، ويحتاج "
                    f"{(quantity / Decimal(days_left)).quantize(Decimal('0.01'))} يومياً "
                    f"ليُصرَّف خلال {days_left} يوم — خصم {discount}% يغطي الفارق"
                    f"{' (مرونة مقاسة)' if elasticity.source == 'measured' else ' (مرونة مفترضة)'}."
                ),
            )

        if buyers:
            return base(
                action="push",
                buyers=buyers,
                # Selling it at the ordinary price is the whole value here; the
                # problem is reach, not price.
                recovery_value=(
                    quantity * Decimal(str(product.wholesale_price))
                ).quantize(TWO_PLACES),
                reason=(
                    f"لا توجد مبيعات منتظمة، لكن {len(buyers)} من العملاء اشتروه من قبل "
                    "— اتصل بهم؛ المشكلة في الوصول وليست في السعر."
                ),
            )

        return base(
            action="write_off",
            reason=(
                "لم يُبَع نهائياً ولا يوجد مشترٍ سابق — لا يوجد خصم يصل بطلب معدوم "
                "إلى مشترٍ. اعترف بالخسارة الآن وأوقف إعادة طلبه."
            ),
        )

    @staticmethod
    def _discount_to_clear(
        quantity: Decimal, rate: Decimal, days_left: int,
        elasticity: Decimal, max_discount: Decimal,
    ) -> Decimal:
        """The price cut whose demand lift would just clear the batch in time.

        Constant-elasticity: Q₂/Q₁ = (P₂/P₁)^e, so the price ratio needed for an
        uplift U is U^(1/e). Capped, because a computed 90% is the model telling you
        this batch cannot be saved by pricing — not an instruction to give it away.
        """
        if days_left <= 0 or rate <= 0 or elasticity >= 0:
            return max_discount
        needed_rate = quantity / Decimal(days_left)
        uplift = needed_rate / rate
        if uplift <= 1:
            return ZERO
        price_ratio = Decimal(str(float(uplift) ** (1 / float(elasticity))))
        discount = (Decimal("1") - price_ratio) * Decimal("100")
        return min(max(discount, ZERO), max_discount).quantize(TWO_PLACES)

    @staticmethod
    def _make(batch, product, warehouse, days_left, quantity, cost, stock_value,
              demand, surplus, surplus_value, active_offer_percent):
        """Curried constructor, so each branch states only what it decides."""

        def build(**overrides) -> Proposal:
            return Proposal(
                batch_id=batch.id,
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                batch_number=batch.batch_number,
                warehouse_name=warehouse.name,
                expiry_date=batch.expiry_date,
                days_left=days_left,
                quantity=quantity,
                unit_cost=cost,
                stock_value=stock_value.quantize(TWO_PLACES),
                daily_rate=demand.daily_rate,
                surplus=surplus.quantize(Decimal("0.001")),
                surplus_value=surplus_value,
                discount_percent=overrides.pop("discount_percent", None),
                price_before=overrides.pop("price_before", None),
                price_now=overrides.pop("price_now", None),
                recovery_value=overrides.pop("recovery_value", ZERO),
                buyers=overrides.pop("buyers", []),
                active_offer_percent=active_offer_percent,
                **overrides,
            )

        return build

    async def _buyers(self, product_ids: list[int]) -> dict[int, list[Buyer]]:
        """Who has actually bought each product, biggest and most recent first.

        Nothing here invents a prospect. A shop that bought it once is a real lead;
        a shop that looks similar on paper is a guess.
        """
        rows = (
            await self.session.execute(
                select(
                    SalesInvoiceLine.product_id,
                    Customer.id,
                    Customer.name,
                    Customer.phone,
                    func.max(SalesInvoice.invoice_date),
                    func.sum(SalesInvoiceLine.quantity),
                )
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
                .join(Customer, Customer.id == SalesInvoice.customer_id)
                .where(
                    SalesInvoiceLine.product_id.in_(product_ids),
                    Customer.is_active.is_(True),
                )
                .group_by(
                    SalesInvoiceLine.product_id, Customer.id, Customer.name, Customer.phone
                )
            )
        ).all()

        grouped: dict[int, list[Buyer]] = {}
        for product_id, customer_id, name, phone, last, units in rows:
            grouped.setdefault(product_id, []).append(
                Buyer(
                    customer_id=customer_id,
                    name=name,
                    phone=phone,
                    last_bought=last,
                    units=Decimal(str(units)),
                )
            )
        for product_id, entries in grouped.items():
            entries.sort(key=lambda b: (b.last_bought, b.units), reverse=True)
            grouped[product_id] = entries[:MAX_BUYERS]
        return grouped

    async def apply(
        self, batch_ids: list[int], user_id: int | None,
        horizon_days: int = 60, max_discount: Decimal = Decimal("50"),
    ) -> tuple[int, int, list[str]]:
        """Turn chosen proposals into real offers.

        The plan is recomputed here rather than trusting numbers the browser sent
        back. A discount is a price the customer will be charged — `create_invoice`
        reads the same offers — so the depth must be decided by this service against
        the stock as it stands now, not by whatever a stale screen believed ten
        minutes ago.

        Only `markdown` rows can be applied. A "push" needs a phone call and a
        "write_off" needs an accountant; silently discounting either would be the
        engine pretending it had solved something.
        """
        from app.domain.models.inventory import ProductOffer

        plan = await self.plan(horizon_days=horizon_days, max_discount=max_discount)
        by_batch = {item.batch_id: item for item in plan.items}

        created = 0
        notes: list[str] = []
        # One offer per product, not per batch: an offer is a price on a product, and
        # two batches of the same thing cannot carry different prices at once.
        seen_products: set[int] = set()

        for batch_id in batch_ids:
            item = by_batch.get(batch_id)
            if item is None:
                notes.append(f"التشغيلة {batch_id} لم تعد في الخطة — ربما نفدت أو انتهت.")
                continue
            if item.action != "markdown":
                notes.append(
                    f"{item.sku}: لا ينطبق عليه خصم ({item.action}) — {item.reason}"
                )
                continue
            if item.product_id in seen_products:
                notes.append(f"{item.sku}: عرض واحد لكل صنف؛ تم تجاهل تشغيلة مكررة.")
                continue

            live = await active_offers(self.session, [item.product_id])
            if item.product_id in live:
                notes.append(f"{item.sku}: يوجد عرض ساري بالفعل على هذا الصنف.")
                continue

            self.session.add(
                ProductOffer(
                    product_id=item.product_id,
                    discount_percent=item.discount_percent,
                    starts_on=date.today(),
                    # Ends with the stock it exists to clear: an offer outliving its
                    # batch discounts fresh goods that never needed it.
                    ends_on=item.expiry_date,
                    note=(
                        f"تصريف تشغيلة {item.batch_number} قبل "
                        f"{item.expiry_date} — مقترح آلي"
                    ),
                    created_by=user_id,
                )
            )
            seen_products.add(item.product_id)
            created += 1

        await self.session.commit()
        return created, len(batch_ids) - created, notes


def _days(count: int):
    from datetime import timedelta

    return timedelta(days=count)


def _sum(values) -> Decimal:
    return sum(values, ZERO).quantize(TWO_PLACES)
