"""Chasing the money: who to ring today, what they promised, and who broke it.

The aging report already existed and is a list of facts. This is the list of actions,
and it exists because of what the facts actually say on this database:

* 114,668 sits past ninety days across 189 invoices and 43 customers;
* the 31-60 and 61-90 buckets hold 4,086 *between them*.

Debt here does not age gradually. It is either paid within the month or it is
abandoned, which means the ninety-plus pile is not "slow payers" — it is money nobody
is chasing, and a middle bucket this empty is the signature of a collections process
that does not exist.

Three ideas do the work.

**Rank by what doing nothing costs.** Not by size and not by age, but by both: an old
small debt is a write-off waiting to be admitted, while a large one three weeks past
due is a phone call that still works. The score is the overdue amount weighted by how
long it has sat, so the calls most likely to recover money come first.

**A promise is two fields and a date.** Whether it was *kept* is never stored — it is
read from the payments that did or did not arrive. A stored flag would be a second
opinion about money the ledger has already settled, and the two would disagree the
first time a shop paid cash to a driver.

**Silence is a state.** A customer who has never been contacted and one who was
promised payment yesterday need different actions, so "never chased" is a first-class
answer rather than an empty column.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import has_permission
from app.domain.models.sales import (
    CollectionActivity,
    CollectionOutcome,
    Customer,
    CustomerPayment,
    SalesInvoice,
    SalesPaymentMethod,
)
from app.domain.models.user import User

ZERO = Decimal("0")
TWO_PLACES = Decimal("0.01")

# A promise is judged a few days after the date given. Shops pay on the day they said
# and the receipt is entered the morning after; failing them at midnight would make
# the broken-promise list mostly clerical lag.
PROMISE_GRACE_DAYS = 2

# Debt younger than this is simply trade credit doing its job.
OVERDUE_AFTER_DAYS = 30


@dataclass(frozen=True)
class Promise:
    activity_id: int
    amount: Decimal
    due_on: date
    made_on: date
    paid_since: Decimal
    # open | kept | broken. Derived every time from payments, never stored.
    state: str


@dataclass(frozen=True)
class Debtor:
    customer_id: int
    name: str
    phone: str | None
    salesman_name: str | None
    balance: Decimal
    overdue: Decimal
    oldest_days: int
    invoice_count: int
    buckets: dict[str, Decimal]
    credit_limit: Decimal
    last_contact: datetime | None
    last_outcome: str | None
    promise: Promise | None
    # Overdue amount weighted by age — the cost of leaving it another week.
    priority: Decimal
    reason: str


@dataclass
class CollectionsWorklist:
    total_outstanding: Decimal
    total_overdue: Decimal
    broken_promises: int
    never_contacted: int
    items: list[Debtor] = field(default_factory=list)


class CollectionsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def worklist(self, user: User, min_days: int = OVERDUE_AFTER_DAYS) -> CollectionsWorklist:
        """Everyone worth ringing, worst first.

        Built from three grouped queries rather than a loop over customers. The
        existing aging report runs two queries *per customer* and there are 150 of
        them; that is fine for a report someone opens monthly and wrong for a screen
        meant to be worked every morning.
        """
        today = date.today()
        scoped = self._visible_customers(user)

        rows = (
            await self.session.execute(
                select(
                    SalesInvoice.customer_id,
                    SalesInvoice.invoice_date,
                    (SalesInvoice.total - SalesInvoice.paid_amount).label("owed"),
                )
                .where(SalesInvoice.total > SalesInvoice.paid_amount)
                .where(scoped)
            )
        ).all()

        outstanding: dict[int, Decimal] = {}
        overdue: dict[int, Decimal] = {}
        oldest: dict[int, int] = {}
        counts: dict[int, int] = {}
        buckets: dict[int, dict[str, Decimal]] = {}
        weighted: dict[int, Decimal] = {}

        for customer_id, invoice_date, owed in rows:
            owed = Decimal(str(owed))
            age = (today - invoice_date).days
            outstanding[customer_id] = outstanding.get(customer_id, ZERO) + owed
            counts[customer_id] = counts.get(customer_id, 0) + 1
            oldest[customer_id] = max(oldest.get(customer_id, 0), age)
            bucket = buckets.setdefault(
                customer_id,
                {"current": ZERO, "d31_60": ZERO, "d61_90": ZERO, "d90_plus": ZERO},
            )
            bucket[self._bucket_of(age)] += owed
            if age > min_days:
                overdue[customer_id] = overdue.get(customer_id, ZERO) + owed
                # Weighting by age, not sorting by it: a 40,000 debt at 45 days
                # outranks a 900 one at 400, because the first is still collectable
                # and the second is an admission waiting to be made.
                weighted[customer_id] = weighted.get(customer_id, ZERO) + owed * Decimal(age)

        if not overdue:
            return CollectionsWorklist(
                total_outstanding=sum(outstanding.values(), ZERO).quantize(TWO_PLACES),
                total_overdue=ZERO,
                broken_promises=0,
                never_contacted=0,
            )

        debtor_ids = list(overdue)
        names = await self._customers(debtor_ids)
        contacts = await self._last_contacts(debtor_ids)
        promises = await self._open_promises(debtor_ids, today)

        items: list[Debtor] = []
        for customer_id in debtor_ids:
            customer, salesman = names.get(customer_id, (None, None))
            if customer is None:
                continue
            contact = contacts.get(customer_id)
            promise = promises.get(customer_id)
            items.append(
                Debtor(
                    customer_id=customer_id,
                    name=customer.name,
                    phone=customer.phone,
                    salesman_name=salesman,
                    balance=outstanding[customer_id].quantize(TWO_PLACES),
                    overdue=overdue[customer_id].quantize(TWO_PLACES),
                    oldest_days=oldest[customer_id],
                    invoice_count=counts[customer_id],
                    buckets={k: v.quantize(TWO_PLACES) for k, v in buckets[customer_id].items()},
                    credit_limit=customer.credit_limit,
                    last_contact=contact[0] if contact else None,
                    last_outcome=contact[1] if contact else None,
                    promise=promise,
                    priority=weighted[customer_id].quantize(TWO_PLACES),
                    reason=self._reason(
                        overdue[customer_id], oldest[customer_id], contact, promise
                    ),
                )
            )

        items.sort(key=lambda d: d.priority, reverse=True)
        return CollectionsWorklist(
            total_outstanding=sum(outstanding.values(), ZERO).quantize(TWO_PLACES),
            total_overdue=sum(overdue.values(), ZERO).quantize(TWO_PLACES),
            broken_promises=len([i for i in items if i.promise and i.promise.state == "broken"]),
            never_contacted=len([i for i in items if i.last_contact is None]),
            items=items,
        )

    async def log(
        self,
        customer_id: int,
        outcome: CollectionOutcome,
        user: User,
        promised_amount: Decimal | None = None,
        promised_on: date | None = None,
        note: str | None = None,
    ) -> CollectionActivity:
        """Record a chase. A promise needs both an amount and a date or it is a note."""
        from app.core.exceptions import AppException

        customer = await self.session.get(Customer, customer_id)
        if customer is None:
            raise AppException(404, "العميل غير موجود.")

        if outcome is CollectionOutcome.PROMISED:
            if promised_amount is None or promised_on is None:
                raise AppException(
                    400,
                    "الوعد بالسداد يحتاج مبلغاً وتاريخاً؛ بدونهما لا يمكن معرفة إن "
                    "كان قد أُوفي به.",
                )
            if promised_on < date.today():
                raise AppException(400, "تاريخ الوعد لا يمكن أن يكون في الماضي.")
        else:
            # Silently ignoring them would leave a promise nobody can check against.
            promised_amount, promised_on = None, None

        activity = CollectionActivity(
            customer_id=customer_id,
            outcome=outcome,
            promised_amount=promised_amount,
            promised_on=promised_on,
            note=note,
            created_by=user.id,
        )
        self.session.add(activity)
        await self.session.commit()
        await self.session.refresh(activity)
        return activity

    async def history(self, customer_id: int) -> list[CollectionActivity]:
        result = await self.session.execute(
            select(CollectionActivity)
            .where(CollectionActivity.customer_id == customer_id)
            .order_by(CollectionActivity.created_at.desc())
        )
        return list(result.scalars().all())

    # --- the age gate that the credit limit cannot be ---

    async def overdue_debt_days(self, customer_id: int) -> int:
        """Age of the customer's oldest unpaid invoice, or 0 if they owe nothing."""
        oldest = await self.session.scalar(
            select(func.min(SalesInvoice.invoice_date)).where(
                SalesInvoice.customer_id == customer_id,
                SalesInvoice.total > SalesInvoice.paid_amount,
            )
        )
        return (date.today() - oldest).days if oldest else 0

    # --- internals ---

    @staticmethod
    def _bucket_of(age: int) -> str:
        if age <= 30:
            return "current"
        if age <= 60:
            return "d31_60"
        if age <= 90:
            return "d61_90"
        return "d90_plus"

    @staticmethod
    def _visible_customers(user: User):
        """Salesmen chase their own customers; everyone else sees the whole book.

        Same rule the customer list already applies. A rep handed the full ledger
        would ring shops that are not theirs, which is worse than useless — it is a
        second person calling about a debt somebody else is already arranging.
        """
        if has_permission(user, "sales.all_customers"):
            return SalesInvoice.customer_id.in_(select(Customer.id))
        return SalesInvoice.customer_id.in_(
            select(Customer.id).where(Customer.salesman_id == user.id)
        )

    async def _customers(
        self, ids: list[int]
    ) -> dict[int, tuple[Customer, str | None]]:
        rows = (
            await self.session.execute(
                select(Customer, User.full_name)
                .outerjoin(User, User.id == Customer.salesman_id)
                .where(Customer.id.in_(ids))
            )
        ).all()
        return {customer.id: (customer, salesman) for customer, salesman in rows}

    async def _last_contacts(
        self, ids: list[int]
    ) -> dict[int, tuple[datetime, str]]:
        """The most recent chase per customer."""
        newest = (
            select(
                CollectionActivity.customer_id,
                func.max(CollectionActivity.created_at).label("at"),
            )
            .where(CollectionActivity.customer_id.in_(ids))
            .group_by(CollectionActivity.customer_id)
            .subquery()
        )
        rows = (
            await self.session.execute(
                select(
                    CollectionActivity.customer_id,
                    CollectionActivity.created_at,
                    CollectionActivity.outcome,
                ).join(
                    newest,
                    (CollectionActivity.customer_id == newest.c.customer_id)
                    & (CollectionActivity.created_at == newest.c.at),
                )
            )
        ).all()
        return {cid: (at, outcome.value) for cid, at, outcome in rows}

    async def _open_promises(
        self, ids: list[int], today: date
    ) -> dict[int, Promise]:
        """The latest promise per customer, judged against money actually received."""
        rows = (
            await self.session.execute(
                select(CollectionActivity)
                .where(
                    CollectionActivity.customer_id.in_(ids),
                    CollectionActivity.outcome == CollectionOutcome.PROMISED,
                )
                .order_by(CollectionActivity.created_at.desc())
            )
        ).scalars().all()

        latest: dict[int, CollectionActivity] = {}
        for activity in rows:
            latest.setdefault(activity.customer_id, activity)

        promises: dict[int, Promise] = {}
        for customer_id, activity in latest.items():
            made_on = activity.created_at.date()
            paid = await self.session.scalar(
                select(func.coalesce(func.sum(CustomerPayment.amount), 0)).where(
                    CustomerPayment.customer_id == customer_id,
                    CustomerPayment.payment_date >= made_on,
                )
            )
            paid = Decimal(str(paid or 0))
            amount = activity.promised_amount or ZERO
            if paid >= amount and amount > ZERO:
                state = "kept"
            elif today > activity.promised_on + timedelta(days=PROMISE_GRACE_DAYS):
                state = "broken"
            else:
                state = "open"
            promises[customer_id] = Promise(
                activity_id=activity.id,
                amount=amount,
                due_on=activity.promised_on,
                made_on=made_on,
                paid_since=paid.quantize(TWO_PLACES),
                state=state,
            )
        return promises

    @staticmethod
    def _reason(
        overdue: Decimal,
        oldest_days: int,
        contact: tuple[datetime, str] | None,
        promise: Promise | None,
    ) -> str:
        """Why this shop is on today's list, in one line the caller can read aloud."""
        if promise is not None and promise.state == "broken":
            return (
                f"وعد بسداد {promise.amount} بتاريخ {promise.due_on} ولم يصل المبلغ."
                + (f" المُحصَّل منذ الوعد: {promise.paid_since}." if promise.paid_since else "")
            )
        if promise is not None and promise.state == "open":
            return f"وعد بسداد {promise.amount} بحلول {promise.due_on} — لم يحن موعده بعد."
        if contact is None:
            return (
                f"لم يُتصل به إطلاقاً بشأن {overdue} متأخرة، وأقدم فاتورة عمرها "
                f"{oldest_days} يوماً."
            )
        return (
            f"آخر متابعة بتاريخ {contact[0].date()} ونتيجتها «{contact[1]}»؛ "
            f"لا يزال {overdue} متأخراً."
        )
