"""ABC / 80-20 analysis: which few things carry the business, and what the rest cost.

The useful part of Pareto is not the headline. Everyone already suspects a handful of
customers matter most. The useful part is the **second** column — what the long tail
consumes while producing almost nothing — because that is the number nobody has, and
it is the one that changes a decision.

Measured on this database, the two halves read very differently:

* **Customers are barely concentrated.** 80% of revenue comes from 80 of 150
  customers, and the largest single account is 2.2% of the total. That is a *finding*,
  not a failure of the report: this book of business has no dependency risk and no
  obvious key-account tier to build. A report that insisted on drawing the famous
  curve here would be inventing a story.
* **Products are brutally concentrated the wrong way round.** 213 products make 80%
  of revenue and hold 11.5M of stock. The other 847 make the remaining 20% — and
  hold 40.0M, which is 78% of everything in the warehouses. 566 of them have never
  sold at all.

So the report is built to state both plainly, including when the classic 80-20 shape
simply is not there. The class thresholds are the standard ones (A to 80% of
cumulative value, B to 95%, C the rest) and a fourth class is added that textbooks
leave out: **D, never sold in the window**. Folding those into C would hide the
single largest pile of money in the business inside a bucket labelled "low value",
when the honest label is "no value, and here is the cost of holding it".

Every figure is a `Decimal`. Shares are percentages rounded to two places rather than
fractions, because they are read by people, not multiplied further.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.inventory import Product, ProductBatch
from app.domain.models.sales import Customer, SalesInvoice, SalesInvoiceLine

TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0")

# The classic cut-offs, on cumulative share of value.
A_THRESHOLD = Decimal("80")
B_THRESHOLD = Decimal("95")

# Headline concentration is reported at these ranks. Three numbers rather than a
# curve, because "the top 5 are 41% of revenue" is a sentence a manager can act on.
TOP_RANKS = (1, 5, 10, 20)


class ParetoDimension(str, Enum):
    CUSTOMERS = "customers"
    PRODUCTS = "products"


class ParetoMeasure(str, Enum):
    REVENUE = "revenue"
    PROFIT = "profit"


@dataclass(frozen=True)
class ParetoItem:
    rank: int
    entity_id: int
    name: str
    code: str | None
    value: Decimal
    share: Decimal
    cumulative_share: Decimal
    abc_class: str
    # Products: stock at cost. Customers: what they currently owe. Both answer
    # "what is this relationship tying up", which is the question a value ranking
    # on its own cannot.
    carrying_value: Decimal
    last_activity: date | None


@dataclass(frozen=True)
class ParetoClass:
    abc_class: str
    label: str
    entities: int
    entity_share: Decimal
    value: Decimal
    value_share: Decimal
    carrying_value: Decimal
    carrying_share: Decimal


@dataclass
class ParetoReport:
    dimension: str
    measure: str
    date_from: date | None
    date_to: date | None
    total_value: Decimal
    total_carrying_value: Decimal
    entity_count: int
    # How many entities it takes to reach 80% of the value, and what fraction of the
    # population that is. When the second number is near 20 the classic rule holds;
    # when it is near 50, this business simply is not concentrated and should not be
    # managed as though it were.
    entities_for_80_percent: int
    share_of_entities_for_80: Decimal
    top_shares: dict[int, Decimal]
    verdict: str
    classes: list[ParetoClass] = field(default_factory=list)
    items: list[ParetoItem] = field(default_factory=list)


CLASS_LABELS = {
    "A": "الفئة أ — تصنع 80% من القيمة",
    "B": "الفئة ب — الـ15% التالية",
    "C": "الفئة ج — آخر 5% من القيمة",
    "D": "الفئة د — لم تُبَع في الفترة",
}


class ParetoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def report(
        self,
        dimension: ParetoDimension = ParetoDimension.PRODUCTS,
        measure: ParetoMeasure = ParetoMeasure.REVENUE,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> ParetoReport:
        values = await self._values(dimension, measure, date_from, date_to)
        carrying = await self._carrying_values(dimension)
        names = await self._names(dimension)
        last_seen = await self._last_activity(dimension, date_from, date_to)

        total_value = sum(values.values(), ZERO)
        ranked = sorted(
            values.items(), key=lambda pair: (-pair[1], names.get(pair[0], ("", ""))[0])
        )

        items: list[ParetoItem] = []
        running = ZERO
        entities_for_80 = 0
        # Classes are assigned by which boundary has been crossed, not by testing the
        # cumulative share against a threshold. The difference is the item that does
        # the crossing: 79 customers reaching 79.5% and the 80th taking it to 80.6%
        # means it takes eighty of them to make 80% — so that eightieth belongs in A
        # and must be counted. Comparing `cumulative <= 80` puts it in B while the
        # headline still counts it, and then class A's size and the headline number
        # disagree by one on every report.
        crossed_80 = False
        crossed_95 = False
        for rank, (entity_id, value) in enumerate(ranked, start=1):
            running += value
            cumulative = self._percent(running, total_value)

            if not crossed_80:
                abc = "A"
                if cumulative >= A_THRESHOLD:
                    crossed_80 = True
                    entities_for_80 = rank
            elif not crossed_95:
                abc = "B"
                crossed_95 = cumulative >= B_THRESHOLD
            else:
                abc = "C"

            name, code = names.get(entity_id, ("—", None))
            items.append(
                ParetoItem(
                    rank=rank,
                    entity_id=entity_id,
                    name=name,
                    code=code,
                    value=value.quantize(TWO_PLACES),
                    share=self._percent(value, total_value),
                    cumulative_share=cumulative,
                    abc_class=abc,
                    carrying_value=carrying.get(entity_id, ZERO).quantize(TWO_PLACES),
                    last_activity=last_seen.get(entity_id),
                )
            )

        # D is everything with stock or a balance but no sales in the window. It has
        # no rank because it has no value to rank on — the point of it is the cost.
        silent = sorted(
            (entity_id for entity_id in carrying if entity_id not in values),
            key=lambda entity_id: -carrying[entity_id],
        )
        for entity_id in silent:
            name, code = names.get(entity_id, ("—", None))
            items.append(
                ParetoItem(
                    rank=0,
                    entity_id=entity_id,
                    name=name,
                    code=code,
                    value=ZERO,
                    share=ZERO,
                    cumulative_share=HUNDRED,
                    abc_class="D",
                    carrying_value=carrying[entity_id].quantize(TWO_PLACES),
                    last_activity=last_seen.get(entity_id),
                )
            )

        # Seeded with ZERO, not bare: an empty report otherwise sums to the integer 0
        # and the next `.quantize` call fails on a fresh install with no sales yet.
        total_carrying = sum((i.carrying_value for i in items), ZERO)
        return ParetoReport(
            dimension=dimension.value,
            measure=measure.value,
            date_from=date_from,
            date_to=date_to,
            total_value=total_value.quantize(TWO_PLACES),
            total_carrying_value=total_carrying.quantize(TWO_PLACES),
            entity_count=len(ranked),
            entities_for_80_percent=entities_for_80,
            share_of_entities_for_80=self._percent(
                Decimal(entities_for_80), Decimal(len(ranked))
            ),
            top_shares=self._top_shares(items, total_value),
            verdict=self._verdict(dimension, items, len(ranked), entities_for_80),
            classes=self._classes(items, total_value, total_carrying),
            items=items,
        )

    # --- value, by dimension and measure ---

    async def _values(
        self,
        dimension: ParetoDimension,
        measure: ParetoMeasure,
        date_from: date | None,
        date_to: date | None,
    ) -> dict[int, Decimal]:
        """What each entity was worth over the window.

        Profit is revenue less the cost recorded on the line at the time of sale, not
        today's cost. A margin recomputed against the current cost would move every
        time a supplier changed a price, and last quarter's profit would quietly
        rewrite itself.
        """
        if measure is ParetoMeasure.REVENUE:
            amount = func.sum(SalesInvoiceLine.line_total)
        else:
            amount = func.sum(
                SalesInvoiceLine.line_total
                - SalesInvoiceLine.quantity
                * func.coalesce(SalesInvoiceLine.unit_cost, 0)
            )

        key = (
            SalesInvoice.customer_id
            if dimension is ParetoDimension.CUSTOMERS
            else SalesInvoiceLine.product_id
        )
        stmt: Select = (
            select(key, amount)
            .select_from(SalesInvoiceLine)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .group_by(key)
        )
        stmt = self._within(stmt, date_from, date_to)

        # A negative total is possible on the profit measure — goods sold below cost.
        # It is dropped from the ranking rather than sorted to the bottom, because a
        # cumulative share built from mixed signs is not a Pareto curve at all: the
        # running total would go down as well as up and the 80% crossing would be
        # meaningless. Losses have their own report.
        return {
            entity_id: Decimal(str(total))
            for entity_id, total in (await self.session.execute(stmt)).all()
            if total is not None and Decimal(str(total)) > ZERO
        }

    async def _carrying_values(self, dimension: ParetoDimension) -> dict[int, Decimal]:
        """What each entity ties up: stock at cost, or an unpaid balance."""
        if dimension is ParetoDimension.PRODUCTS:
            rows = (
                await self.session.execute(
                    select(
                        ProductBatch.product_id,
                        func.sum(
                            ProductBatch.quantity
                            * func.coalesce(ProductBatch.unit_cost, 0)
                        ),
                    )
                    .join(Product, Product.id == ProductBatch.product_id)
                    .where(ProductBatch.quantity > 0, Product.is_active.is_(True))
                    .group_by(ProductBatch.product_id)
                )
            ).all()
        else:
            rows = (
                await self.session.execute(
                    select(
                        SalesInvoice.customer_id,
                        func.sum(SalesInvoice.total - SalesInvoice.paid_amount),
                    )
                    .join(Customer, Customer.id == SalesInvoice.customer_id)
                    .where(
                        SalesInvoice.total > SalesInvoice.paid_amount,
                        Customer.is_active.is_(True),
                    )
                    .group_by(SalesInvoice.customer_id)
                )
            ).all()
        return {
            entity_id: Decimal(str(total or 0))
            for entity_id, total in rows
            if total and Decimal(str(total)) > ZERO
        }

    async def _names(self, dimension: ParetoDimension) -> dict[int, tuple[str, str | None]]:
        if dimension is ParetoDimension.PRODUCTS:
            rows = (
                await self.session.execute(select(Product.id, Product.name, Product.sku))
            ).all()
        else:
            rows = (
                await self.session.execute(
                    select(Customer.id, Customer.name, Customer.phone)
                )
            ).all()
        return {entity_id: (name, code) for entity_id, name, code in rows}

    async def _last_activity(
        self, dimension: ParetoDimension, date_from: date | None, date_to: date | None
    ) -> dict[int, date]:
        """Last invoice date, ignoring the window.

        Deliberately unbounded: on a D-class row the whole question is *how long* it
        has been silent, and a date clipped to the window could only ever say "not in
        the window", which the class already says.
        """
        if dimension is ParetoDimension.CUSTOMERS:
            # No join at all: the invoice already carries the customer, and reaching
            # through the lines would count the same invoice once per line.
            stmt = select(
                SalesInvoice.customer_id, func.max(SalesInvoice.invoice_date)
            ).group_by(SalesInvoice.customer_id)
        else:
            stmt = (
                select(
                    SalesInvoiceLine.product_id, func.max(SalesInvoice.invoice_date)
                )
                .select_from(SalesInvoiceLine)
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
                .group_by(SalesInvoiceLine.product_id)
            )
        rows = (await self.session.execute(stmt)).all()
        return {entity_id: last for entity_id, last in rows if last is not None}

    @staticmethod
    def _within(stmt: Select, date_from: date | None, date_to: date | None) -> Select:
        if date_from is not None:
            stmt = stmt.where(SalesInvoice.invoice_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(SalesInvoice.invoice_date <= date_to)
        return stmt

    # --- shaping ---

    @staticmethod
    def _percent(part: Decimal, whole: Decimal) -> Decimal:
        if whole <= ZERO:
            return ZERO
        return (part / whole * HUNDRED).quantize(TWO_PLACES)

    def _classes(
        self, items: list[ParetoItem], total_value: Decimal, total_carrying: Decimal
    ) -> list[ParetoClass]:
        # Against every entity in the report, silent ones included. Quoting the
        # ranked-only count made class D read as 114% of the population, which is
        # what happens when a share is measured against a denominator that excludes
        # its own numerator.
        population = Decimal(len(items))
        summaries: list[ParetoClass] = []
        for abc in ("A", "B", "C", "D"):
            members = [i for i in items if i.abc_class == abc]
            if not members:
                continue
            value = sum((i.value for i in members), ZERO)
            carrying = sum((i.carrying_value for i in members), ZERO)
            summaries.append(
                ParetoClass(
                    abc_class=abc,
                    label=CLASS_LABELS[abc],
                    entities=len(members),
                    entity_share=self._percent(Decimal(len(members)), population),
                    value=value.quantize(TWO_PLACES),
                    value_share=self._percent(value, total_value),
                    carrying_value=carrying.quantize(TWO_PLACES),
                    carrying_share=self._percent(carrying, total_carrying),
                )
            )
        return summaries

    def _top_shares(
        self, items: list[ParetoItem], total_value: Decimal
    ) -> dict[int, Decimal]:
        ranked = [i for i in items if i.rank > 0]
        shares: dict[int, Decimal] = {}
        for rank in TOP_RANKS:
            if len(ranked) >= rank:
                shares[rank] = self._percent(
                    sum((i.value for i in ranked[:rank]), ZERO), total_value
                )
        return shares

    def _verdict(
        self,
        dimension: ParetoDimension,
        items: list[ParetoItem],
        ranked_count: int,
        entities_for_80: int,
    ) -> str:
        """One sentence in Arabic naming what the numbers actually say.

        Written here rather than in the browser because it is a reading of the data,
        not a layout choice, and because the interesting case is the one a chart
        cannot show: a distribution that is *not* concentrated, where the right
        advice is to stop looking for a key-account tier that does not exist.
        """
        if not ranked_count:
            return "لا توجد مبيعات في هذه الفترة."

        share = self._percent(Decimal(entities_for_80), Decimal(ranked_count))
        subject = "عميلاً" if dimension is ParetoDimension.CUSTOMERS else "صنفاً"
        active = "الذين تعاملوا" if dimension is ParetoDimension.CUSTOMERS else "التي بيعت"
        headline = (
            f"{entities_for_80} {subject} من {ranked_count} {active} في الفترة"
            f" ({share}%) تصنع 80% من القيمة."
        )

        # Two denominators, both honest, and the gap between them is the finding.
        # 213 of the 494 products that sold is 43% and reads as "moderate"; the same
        # 213 out of a catalogue of 1,060 is 20% and is the textbook rule exactly.
        # Quoting only the first hides half the catalogue; only the second flatters.
        population = len(items)
        if population > ranked_count:
            whole = self._percent(Decimal(entities_for_80), Decimal(population))
            headline += (
                f" وهي {whole}% من إجمالي {population} في السجل — والباقي بلا مبيعات"
                " في الفترة."
            )

        if share <= Decimal("30"):
            reading = (
                " تركيز مرتفع يطابق قاعدة 20/80: هذه القائمة القصيرة تستحق معاملة"
                " خاصة، وفقدان أحدها مؤثر فعلاً."
            )
        elif share <= Decimal("45"):
            reading = " تركيز متوسط: هناك نواة واضحة، لكن الاعتماد عليها ليس خطراً."
        else:
            reading = (
                " التوزيع غير مركّز — لا تنطبق قاعدة 20/80 هنا. لا يوجد اعتماد خطر على"
                " قلة، ولا جدوى من بناء طبقة «عملاء رئيسيين» لا وجود لها في الأرقام."
            )

        tail = [i for i in items if i.abc_class in ("C", "D")]
        tail_carrying = sum((i.carrying_value for i in tail), ZERO)
        total_carrying = sum((i.carrying_value for i in items), ZERO)
        if tail_carrying > ZERO and total_carrying > ZERO:
            burden = self._percent(tail_carrying, total_carrying)
            noun = "المخزون" if dimension is ParetoDimension.PRODUCTS else "الذمم"
            reading += (
                f" والأهم: الفئتان ج ود ({len(tail)}) تحتجزان {burden}% من قيمة"
                f" {noun}."
            )
        return headline + reading
