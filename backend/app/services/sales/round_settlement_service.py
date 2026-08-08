"""Closing a salesman's day: what went out, what sold, what came back.

A van leaves loaded and returns with cash, an emptier hold, and a stack of
invoices. Each of those was already tracked — the load-out is a transfer, the
sales are invoices, the cash is collected by the cashier, the leftover stock is a
stocktake — but nothing said whether a given round was *closed*. A salesman could
keep a day's takings in his pocket indefinitely and no screen would notice.

This service is that missing close. Two boundaries shape it, and both exist to
stop the ledger drifting:

**It never posts money.** Van cash already passes the cashier gate on each
invoice, and the cashier's collection is the one place a cash movement is
written. Settling therefore *requires* the round's cash to be collected already
and records what it found — it does not move a riyal itself. Posting here would
double-count every round.

**It never adjusts stock.** Posting a stocktake already applies differences per
batch and nets one entry against 5040. Settlement links to that count instead of
repeating it, because two code paths adjusting the same batches is exactly how
inventory and the ledger come apart.

So what does it actually enforce? One hard gate and one soft one:

* **Cash outstanding blocks the close, with no override.** Cash is not a
  judgement — it was handed over or it was not.
* **A stock difference does not block, but can never pass silently.** It needs a
  written reason always, and a supervisor's permission once it exceeds the
  configured limit. Blocking on variance instead would be worse than useless: the
  round could not close, tomorrow's round could not open (one open round per van),
  and the pressure would land on whoever counts — producing tidy books and untrue
  shelves.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.sales import (
    RoundInvoiceOut,
    RoundPositionOut,
    RoundSettlementOpenIn,
    RoundSettlementSettleIn,
    RoundVanSettleIn,
)
from app.core import arabic
from app.services.sales.returns_query import returned_totals
from app.core.exceptions import AppException
from app.core.permissions import has_permission
from app.domain.models.cashier import CashMovement
from app.domain.models.inventory import Stocktake, StocktakeLine, StocktakeStatus, Warehouse
from app.domain.models.sales import (
    Customer,
    RoundSettlement,
    RoundSettlementStatus,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPaymentMethod,
)
from app.domain.models.settings import CompanySettings
from app.domain.models.user import User, UserRole

# Cash and card both have to reach the drawer by the end of the day. Credit is the
# customer's debt, chased through their account — never the salesman's pocket.
DRAWER_METHODS = (SalesPaymentMethod.CASH, SalesPaymentMethod.CARD)


class RoundSettlementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Lookups ---
    async def _get_van(self, warehouse_id: int) -> Warehouse:
        warehouse = await self.session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise AppException(404, "المستودع غير موجود.")
        if not warehouse.is_vehicle:
            raise AppException(
                400,
                f"({warehouse.name}) مستودع ثابت لا مركبة؛ "
                "التسوية تخصّ جولات المناديب فقط.",
            )
        if warehouse.assigned_to_id is None:
            raise AppException(
                400,
                f"المركبة ({warehouse.name}) غير مسندة لمندوب؛ "
                "أسندها من صفحة المستودعات أولاً.",
            )
        return warehouse

    async def get_settlement(self, settlement_id: int) -> RoundSettlement:
        settlement = await self.session.get(RoundSettlement, settlement_id)
        if settlement is None:
            raise AppException(404, "التسوية غير موجودة.")
        return settlement

    async def _open_for_van(self, warehouse_id: int) -> RoundSettlement | None:
        result = await self.session.execute(
            select(RoundSettlement).where(
                RoundSettlement.warehouse_id == warehouse_id,
                RoundSettlement.status == RoundSettlementStatus.OPEN,
            )
        )
        return result.scalar_one_or_none()

    async def _variance_limit(self) -> Decimal:
        settings = await self.session.get(CompanySettings, 1)
        return settings.round_variance_approval_limit if settings else Decimal("0")

    # --- The round's live position ---
    async def _round_invoices(
        self, warehouse_id: int, salesman_id: int, round_date: date
    ) -> list[SalesInvoice]:
        """Invoices sold off this van by this salesman on this date.

        The van is matched through the *lines*, because that is where the source
        warehouse is recorded per batch. `SalesInvoice.warehouse_id` is only set
        when every line agrees on one warehouse, so relying on it would silently
        drop any invoice that mixed the van with another source.
        """
        stmt = (
            select(SalesInvoice)
            .join(SalesInvoiceLine, SalesInvoiceLine.invoice_id == SalesInvoice.id)
            .where(
                SalesInvoiceLine.warehouse_id == warehouse_id,
                SalesInvoice.salesman_id == salesman_id,
                SalesInvoice.invoice_date == round_date,
            )
            .distinct()
            .order_by(SalesInvoice.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _collected_for(self, invoice_ids: list[int]) -> dict[int, Decimal]:
        """How much the cashier has taken in against each invoice.

        Read from cash movements rather than the invoice's own paid_amount so the
        settlement reflects what actually reached the drawer, which is the thing
        being reconciled.
        """
        if not invoice_ids:
            return {}
        stmt = (
            select(CashMovement.reference_id, func.coalesce(func.sum(CashMovement.amount), 0))
            .where(
                CashMovement.direction == "in",
                CashMovement.reference_type == "sales_invoice",
                CashMovement.reference_id.in_(invoice_ids),
            )
            .group_by(CashMovement.reference_id)
        )
        return {
            ref: Decimal(str(total))
            for ref, total in (await self.session.execute(stmt)).all()
        }

    async def _posted_count_for(self, warehouse_id: int, on: date) -> int | None:
        """The van's most recent posted count for that day, if one exists."""
        result = await self.session.execute(
            select(Stocktake.id)
            .where(
                Stocktake.warehouse_id == warehouse_id,
                Stocktake.count_date == on,
                Stocktake.status == StocktakeStatus.POSTED,
            )
            .order_by(Stocktake.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _stocktake_variance(
        self, stocktake_id: int | None
    ) -> tuple[Decimal, Decimal]:
        """Returns (value of the differences, net difference in units).

        Both are needed, and conflating them was a real mistake worth recording:
        `variance_value` is the difference *priced at the batch's cost*, and it is
        zero whenever that cost is unknown. Gating only on the value therefore let
        a van come back short of goods that had no cost recorded — a real
        shortfall — and close in complete silence.

        So the quantity flag decides whether an explanation is demanded, and the
        value decides whether a supervisor must approve it.
        """
        if stocktake_id is None:
            return Decimal("0"), Decimal("0")
        stocktake = await self.session.get(Stocktake, stocktake_id)
        if stocktake is None:
            raise AppException(404, "الجرد المرتبط غير موجود.")
        if stocktake.status != StocktakeStatus.POSTED:
            raise AppException(
                400,
                "لا يمكن ربط جرد لم يُرحَّل بعد؛ رحّل الجرد أولاً ثم أعد التسوية.",
            )
        lines = (
            await self.session.execute(
                select(StocktakeLine).where(StocktakeLine.stocktake_id == stocktake_id)
            )
        ).scalars().all()
        value = sum((line.variance_value for line in lines), Decimal("0"))
        qty = sum((line.variance for line in lines), Decimal("0"))
        return value, qty

    async def position(
        self, warehouse_id: int, round_date: date | None = None
    ) -> RoundPositionOut:
        """What the settlement screen shows before anyone signs anything."""
        van = await self._get_van(warehouse_id)
        open_round = await self._open_for_van(warehouse_id)
        on = round_date or (open_round.round_date if open_round else date.today())

        # An open round is the authority on whose round it is, not the van's
        # current assignee. Reassigning a vehicle while a round is open would
        # otherwise hide that round's own sales — the position would query the new
        # salesman, find nothing, and happily close a day showing zero.
        salesman_id = open_round.salesman_id if open_round else van.assigned_to_id
        salesman = await self.session.get(User, salesman_id)

        invoices = await self._round_invoices(warehouse_id, salesman_id, on)
        collected = await self._collected_for([i.id for i in invoices])

        totals = {m: Decimal("0") for m in SalesPaymentMethod}
        drawer_due = Decimal("0")
        drawer_in = Decimal("0")
        rows: list[RoundInvoiceOut] = []

        # Net of credit notes, or the round can never close. The cashier correctly
        # collects total-minus-returns, while this computed what was owed from the
        # gross totals — so a van sale that was partly returned left the round showing
        # cash outstanding that nobody owes, blocking the close permanently, with the
        # cashier unable to collect it either because their own gate refuses money
        # that is not due. The same missing term as the cashier bug, in a second place
        # that recalculated the figure instead of asking for it.
        credited = await returned_totals(self.session, [i.id for i in invoices])

        for invoice in invoices:
            back = credited.get(invoice.id, Decimal("0"))
            net_total = invoice.total - back
            totals[invoice.payment_method] += net_total
            got = collected.get(invoice.id, Decimal("0"))
            customer = await self.session.get(Customer, invoice.customer_id)
            if invoice.payment_method in DRAWER_METHODS:
                drawer_due += net_total
                drawer_in += got
                outstanding = net_total - got
            else:
                # Credit sales are not the salesman's to hand over tonight.
                outstanding = Decimal("0")
            rows.append(
                RoundInvoiceOut(
                    id=invoice.id,
                    customer_name=customer.name if customer else "—",
                    payment_method=invoice.payment_method,
                    total=net_total,
                    collected=got,
                    outstanding=outstanding,
                    is_collected=outstanding <= 0,
                )
            )

        outstanding_total = drawer_due - drawer_in

        # Prefer a count deliberately linked to the round; otherwise adopt the van's
        # own posted count for the day. Without this the screen showed no variance
        # until someone had already linked a stocktake by hand — so a storekeeper
        # who counted the van correctly would still see a clean, balanced round and
        # sign it off, which defeats the point of the check.
        stocktake_id = open_round.stocktake_id if open_round else None
        if stocktake_id is None:
            stocktake_id = await self._posted_count_for(van.id, on)
        variance, variance_qty = await self._stocktake_variance(stocktake_id)
        limit = await self._variance_limit()

        blockers: list[str] = []
        # Only the things `settle` actually refuses belong here. A missing open
        # round was listed until closing in one step became possible; leaving it
        # would have made the screen refuse a close the API performs happily. The
        # rule this list has to keep: blockers mirror the service's gates exactly,
        # because a screen that disagrees with its API is worse than no screen.
        if outstanding_total > 0:
            uncollected = sum(1 for r in rows if not r.is_collected)
            blockers.append(
                f"مبلغ {outstanding_total} لم يُحصَّل في الصندوق بعد "
                f"({arabic.invoices(uncollected)})."
            )

        return RoundPositionOut(
            warehouse_id=van.id,
            warehouse_name=van.name,
            # Reported as the same salesman the figures were computed for, so the
            # screen can never name one person while totalling another's sales.
            salesman_id=salesman_id,
            salesman_name=salesman.full_name if salesman else "—",
            round_date=on,
            invoice_count=len(invoices),
            cash_sales_total=totals[SalesPaymentMethod.CASH],
            card_sales_total=totals[SalesPaymentMethod.CARD],
            credit_sales_total=totals[SalesPaymentMethod.CREDIT],
            total_sales=sum(totals.values(), Decimal("0")),
            cash_collected_total=drawer_in,
            cash_outstanding_total=outstanding_total,
            stocktake_id=stocktake_id,
            stock_variance_value=variance,
            stock_variance_qty=variance_qty,
            has_stock_variance=variance_qty != 0,
            variance_needs_approval=abs(variance) > limit,
            variance_approval_limit=limit,
            can_settle=not blockers,
            blockers=blockers,
            invoices=rows,
        )

    # --- Lifecycle ---
    async def list_settlements(
        self,
        warehouse_id: int | None = None,
        salesman_id: int | None = None,
        status: RoundSettlementStatus | None = None,
    ) -> list[RoundSettlement]:
        stmt = select(RoundSettlement).order_by(
            RoundSettlement.round_date.desc(), RoundSettlement.id.desc()
        )
        if warehouse_id is not None:
            stmt = stmt.where(RoundSettlement.warehouse_id == warehouse_id)
        if salesman_id is not None:
            stmt = stmt.where(RoundSettlement.salesman_id == salesman_id)
        if status is not None:
            stmt = stmt.where(RoundSettlement.status == status)
        return list((await self.session.execute(stmt)).scalars().all())

    async def open_round(
        self, data: RoundSettlementOpenIn, user: User
    ) -> RoundSettlement:
        """Start a round for a van. One at a time, enforced here and in the index."""
        van = await self._get_van(data.warehouse_id)
        existing = await self._open_for_van(van.id)
        if existing is not None:
            raise AppException(
                400,
                f"للمركبة ({van.name}) جولة مفتوحة بتاريخ {existing.round_date} — "
                "سوّها أو ألغِها قبل فتح جولة جديدة.",
            )
        settlement = RoundSettlement(
            warehouse_id=van.id,
            salesman_id=van.assigned_to_id,
            round_date=data.round_date or date.today(),
            status=RoundSettlementStatus.OPEN,
            notes=data.notes,
            opened_by=user.id,
        )
        self.session.add(settlement)
        await self.session.commit()
        await self.session.refresh(settlement)
        return settlement

    async def settle(
        self, settlement_id: int, data: RoundSettlementSettleIn, user: User
    ) -> RoundSettlement:
        """Close the round, snapshotting the figures that were true at sign-off."""
        settlement = await self.get_settlement(settlement_id)
        if settlement.status != RoundSettlementStatus.OPEN:
            raise AppException(
                400,
                "لا يمكن تسوية جولة غير مفتوحة "
                f"(حالتها الآن: {settlement.status.value}).",
            )

        if data.stocktake_id is not None:
            settlement.stocktake_id = data.stocktake_id

        position = await self.position(settlement.warehouse_id, settlement.round_date)

        # The hard gate: money first, no exceptions and no override permission.
        if position.cash_outstanding_total > 0:
            raise AppException(
                400,
                f"لا يمكن إقفال الجولة ومبلغ {position.cash_outstanding_total} "
                "لم يُحصَّل بعد؛ حصّل الفواتير من الصندوق أولاً.",
            )

        # The soft gate: a difference may pass, but never silently. Keyed on the
        # *quantity* differing, not its value — an unvalued shortfall is still a
        # shortfall (see _stocktake_variance).
        variance = position.stock_variance_value
        if position.has_stock_variance:
            if not (data.notes or "").strip():
                amount = f"بقيمة {variance}" if variance else "غير مُقيَّم"
                raise AppException(
                    400,
                    f"الجولة بها فرق مخزون ({amount})؛ "
                    "اكتب سبب الفرق قبل الإقفال.",
                )
            if position.variance_needs_approval and not has_permission(
                user, "sales.round_settle_variance"
            ):
                raise AppException(
                    403,
                    f"فرق المخزون ({variance}) يتجاوز حدّ الإقرار "
                    f"({position.variance_approval_limit})؛ "
                    "يلزم إقرار مدير أو محاسب.",
                )

        settlement.invoice_count = position.invoice_count
        settlement.cash_sales_total = position.cash_sales_total
        settlement.card_sales_total = position.card_sales_total
        settlement.credit_sales_total = position.credit_sales_total
        settlement.cash_collected_total = position.cash_collected_total
        settlement.cash_outstanding_total = position.cash_outstanding_total
        settlement.stock_variance_value = variance
        settlement.stock_variance_qty = position.stock_variance_qty
        # Record the count the figures came from, including one adopted
        # automatically, so the signed round points at its evidence.
        settlement.stocktake_id = position.stocktake_id
        if data.notes is not None:
            settlement.notes = data.notes
        settlement.status = RoundSettlementStatus.SETTLED
        settlement.settled_at = datetime.now(timezone.utc)
        settlement.settled_by = user.id

        await self.session.commit()
        await self.session.refresh(settlement)
        return settlement

    async def settle_van(
        self, data: RoundVanSettleIn, user: User
    ) -> RoundSettlement:
        """Close a van's day, opening the round first if nobody opened one.

        The common path: the storekeeper takes the van back, counts it, and signs
        off. Requiring a separate open beforehand would only add a step that can be
        forgotten — and a forgotten open means a day's sales sitting unsettled for
        no reason a user could see.
        """
        van = await self._get_van(data.warehouse_id)
        settlement = await self._open_for_van(van.id)
        if settlement is None:
            settlement = await self.open_round(
                RoundSettlementOpenIn(
                    warehouse_id=van.id, round_date=data.round_date, notes=data.notes
                ),
                user,
            )
        return await self.settle(
            settlement.id,
            RoundSettlementSettleIn(stocktake_id=data.stocktake_id, notes=data.notes),
            user,
        )

    async def cancel(self, settlement_id: int, user: User) -> RoundSettlement:
        """Abandon an open round. A settled one is a signed record and stays."""
        settlement = await self.get_settlement(settlement_id)
        if settlement.status != RoundSettlementStatus.OPEN:
            raise AppException(
                400, "لا يمكن إلغاء جولة مسوّاة أو ملغاة من قبل."
            )
        settlement.status = RoundSettlementStatus.CANCELLED
        settlement.cancelled_at = datetime.now(timezone.utc)
        settlement.cancelled_by = user.id
        await self.session.commit()
        await self.session.refresh(settlement)
        return settlement

    async def unsettled_rounds(self) -> list[dict]:
        """Vans that sold today but have no settled round — fuel for the alerts centre.

        Reported per van rather than per invoice: the thing needing action is a
        round, and listing twelve invoices for one van would bury the signal.
        """
        today = date.today()
        vans = (
            await self.session.execute(
                select(Warehouse).where(
                    Warehouse.is_vehicle == True,  # noqa: E712 — SQL, not Python truthiness
                    Warehouse.is_active == True,  # noqa: E712
                    Warehouse.assigned_to_id.isnot(None),
                )
            )
        ).scalars().all()

        pending: list[dict] = []
        for van in vans:
            invoices = await self._round_invoices(van.id, van.assigned_to_id, today)
            if not invoices:
                continue
            settled = await self.session.execute(
                select(func.count())
                .select_from(RoundSettlement)
                .where(
                    RoundSettlement.warehouse_id == van.id,
                    RoundSettlement.round_date == today,
                    RoundSettlement.status == RoundSettlementStatus.SETTLED,
                )
            )
            if settled.scalar_one():
                continue
            collected = await self._collected_for([i.id for i in invoices])
            outstanding = sum(
                (
                    i.total - collected.get(i.id, Decimal("0"))
                    for i in invoices
                    if i.payment_method in DRAWER_METHODS
                ),
                Decimal("0"),
            )
            salesman = await self.session.get(User, van.assigned_to_id)
            pending.append(
                {
                    "warehouse_id": van.id,
                    "warehouse_name": van.name,
                    "salesman_name": salesman.full_name if salesman else "—",
                    "invoice_count": len(invoices),
                    "cash_outstanding": outstanding,
                }
            )
        return pending
