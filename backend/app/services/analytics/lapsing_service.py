"""Shops that have gone quiet, judged against their own rhythm.

A fixed rule — "no order in 30 days" — is wrong in both directions at once. It never
fires for the hotel that orders quarterly, and it fires far too late for the grocery
that orders twice a week and has now been silent a fortnight. By the time a single
threshold catches the second one, they are buying from someone else.

So each customer is measured against the gap *they* normally leave between orders.
Silence of three times their own median is the signal, whatever their normal is.

Nothing here is a prediction. It is arithmetic on their order dates, which is the
right tool: with 150 customers a model would be fitting noise, and a rep who is told
"this shop is 4× overdue and worth 12,000 a quarter" does not need a probability to
know what to do.
"""

from datetime import date
from decimal import Decimal
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.analytics import LapsingCustomerOut, LapsingReportOut
from app.domain.models.sales import Customer, SalesInvoice
from app.domain.models.user import User

TWO_PLACES = Decimal("0.01")

# Two gaps is the minimum from which "normally" means anything; below that a single
# unusual week would set the whole expectation.
MIN_ORDERS = 3

# Three of their own cycles. Two fires on a shop that simply skipped a delivery; four
# is usually a customer already lost. Three is late enough to be real and early enough
# to be worth a phone call.
OVERDUE_MULTIPLE = Decimal("3")

# A floor, because a customer whose median gap is a day would otherwise be "3× overdue"
# by Thursday. Nobody is lost after three days.
MIN_SILENT_DAYS = 7


class LapsingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lapsing(self, limit: int = 100) -> LapsingReportOut:
        """Active customers who have stopped ordering at their own usual rate."""
        today = date.today()

        rows = (
            await self.session.execute(
                select(
                    Customer.id,
                    Customer.name,
                    Customer.phone,
                    User.full_name,
                    SalesInvoice.invoice_date,
                    SalesInvoice.total,
                )
                .join(SalesInvoice, SalesInvoice.customer_id == Customer.id)
                .outerjoin(User, User.id == Customer.salesman_id)
                .where(Customer.is_active.is_(True))
                .order_by(Customer.id, SalesInvoice.invoice_date)
            )
        ).all()

        history: dict[int, dict] = {}
        for customer_id, name, phone, salesman, invoice_date, total in rows:
            entry = history.setdefault(
                customer_id,
                {"name": name, "phone": phone, "salesman": salesman,
                 "dates": [], "total": Decimal("0")},
            )
            entry["dates"].append(invoice_date)
            entry["total"] += total

        items: list[LapsingCustomerOut] = []
        for customer_id, entry in history.items():
            dates = entry["dates"]
            if len(dates) < MIN_ORDERS:
                continue

            gaps = [
                (later - earlier).days
                for earlier, later in zip(dates, dates[1:])
                if (later - earlier).days > 0
            ]
            if not gaps:
                continue

            # Median rather than mean: one holiday shutdown should not redefine what
            # normal looks like for the rest of the year.
            usual_gap = Decimal(str(median(gaps)))
            silent_days = (today - dates[-1]).days
            if silent_days < MIN_SILENT_DAYS:
                continue

            overdue = Decimal(silent_days) / usual_gap
            if overdue < OVERDUE_MULTIPLE:
                continue

            # Value per day of relationship, annualised — so a big customer of two
            # months outranks a small one of two years, which is the right way round
            # when deciding who to ring first.
            active_days = max((dates[-1] - dates[0]).days, 1)
            annual_value = (entry["total"] / Decimal(active_days)) * Decimal("365")

            items.append(
                LapsingCustomerOut(
                    customer_id=customer_id,
                    customer_name=entry["name"],
                    phone=entry["phone"],
                    salesman_name=entry["salesman"],
                    last_order=dates[-1],
                    silent_days=silent_days,
                    usual_gap_days=usual_gap.quantize(Decimal("0.1")),
                    overdue_multiple=overdue.quantize(Decimal("0.1")),
                    orders_count=len(dates),
                    lifetime_value=entry["total"].quantize(TWO_PLACES),
                    annual_value=annual_value.quantize(TWO_PLACES),
                )
            )

        # Ranked by what is at stake, not by who is latest: a shop worth 200 a year
        # being 10× overdue matters less than one worth 90,000 being 3× overdue.
        items.sort(key=lambda i: i.annual_value, reverse=True)
        capped = items[:limit]

        return LapsingReportOut(
            overdue_multiple=OVERDUE_MULTIPLE,
            total_customers=len(items),
            annual_value_at_risk=sum(
                (i.annual_value for i in items), Decimal("0")
            ).quantize(TWO_PLACES),
            items=capped,
        )
