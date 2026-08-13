"""المواد المقننة — the register of regulated goods, per customer.

Regulated stock is sold and charged on the ordinary sales invoice like anything else.
What the business additionally has to keep is a record of *which client took which of
those goods*, so a monthly declaration can be produced from it. That record is what
this builds, and the most important thing about it is everything it does not do: it
posts nothing to the ledger, moves no stock, creates no receivable and cannot become an
invoice. All of that happened once, on the real invoice.

**The register owns no figures.** A row is a pointer to a `SalesInvoiceLine`, and every
quantity, price and total on screen is read through to the line. That is a deliberate
choice with one consequence worth stating plainly: correct a quantity on the invoice,
cancel the invoice, or take goods back, and the register changes with it, because there
is only one copy of the number and the invoice owns it.

The alternative — copying quantities in at tagging time — produces a register that is
right on the day it is written and quietly wrong afterwards. For a document handed to an
authority, that is the worst failure available, so it is not offered as an option.

Returns are netted the same way, live, from the return lines that reference the same
product on the same invoice. A shop that took ten sacks and sent two back received
eight, and eight is what the declaration has to say.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.domain.models.sales import (
    Customer,
    RationedLine,
    RationedRecord,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
)
from app.domain.models.user import User
from app.services.sales.returns_query import posted

ZERO = Decimal("0")
TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")


@dataclass(frozen=True)
class RationedEntry:
    """One regulated line as it stands right now, not as it stood when tagged."""

    line_id: int
    invoice_id: int
    invoice_reference: str
    invoice_date: date
    product_id: int
    product_name: str
    unit_name: str
    quantity: Decimal
    # Quantity already sent back on a posted credit note, so the declaration can show
    # what the shop actually kept.
    returned_quantity: Decimal
    net_quantity: Decimal
    unit_price: Decimal
    net_total: Decimal
    added_at: datetime


@dataclass
class RationedRegister:
    record_id: int
    customer_id: int
    customer_name: str
    customer_phone: str | None
    opened_at: datetime
    closed_at: datetime | None
    closed_by_name: str | None
    notes: str | None
    is_open: bool
    line_count: int
    total_quantity: Decimal
    total_value: Decimal
    entries: list[RationedEntry] = field(default_factory=list)


class RationedService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- tagging ---

    async def tag_lines(
        self, line_ids: list[int], user: User | None = None
    ) -> int:
        """File invoice lines under their customer's open register.

        Called from invoice creation, and safe to call again: a line already filed is
        skipped rather than duplicated. That matters because the unique constraint on
        `sales_invoice_line_id` would otherwise abort a whole invoice over a repeated
        tag, and losing a real sale to protect a record would be the wrong way round.

        Lines belonging to different customers are filed under different registers in
        one call — an invoice only ever has one customer, but nothing here needs to
        assume that.
        """
        if not line_ids:
            return 0

        rows = (
            await self.session.execute(
                select(SalesInvoiceLine.id, SalesInvoice.customer_id)
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
                .where(SalesInvoiceLine.id.in_(line_ids))
            )
        ).all()
        already = set(
            (
                await self.session.execute(
                    select(RationedLine.sales_invoice_line_id).where(
                        RationedLine.sales_invoice_line_id.in_(line_ids)
                    )
                )
            ).scalars()
        )

        added = 0
        registers: dict[int, RationedRecord] = {}
        for line_id, customer_id in rows:
            if line_id in already:
                continue
            record = registers.get(customer_id)
            if record is None:
                record = await self._open_record(customer_id)
                registers[customer_id] = record
            self.session.add(
                RationedLine(
                    record_id=record.id,
                    sales_invoice_line_id=line_id,
                    added_by=user.id if user else None,
                )
            )
            added += 1
        await self.session.flush()
        return added

    async def untag(self, line_id: int) -> None:
        """Take a line off the open register.

        Only an open one: a closed register has been printed and declared, and quietly
        removing a line from it would leave the paper and the system disagreeing about
        something an authority has already been told.
        """
        entry = (
            await self.session.execute(
                select(RationedLine)
                .options(selectinload(RationedLine.record))
                .where(RationedLine.sales_invoice_line_id == line_id)
            )
        ).scalar_one_or_none()
        if entry is None:
            raise AppException(404, "هذا السطر غير مسجَّل في المواد المقننة.")
        if entry.record.closed_at is not None:
            raise AppException(
                400,
                "السجل مقفل؛ لا يمكن حذف سطر منه. افتح سجلاً جديداً أو صحّح الفاتورة "
                "نفسها.",
            )
        await self.session.delete(entry)
        await self.session.commit()

    # --- reading ---

    async def register_for(self, customer_id: int) -> RationedRegister:
        """The customer's current register, created empty if they have none yet."""
        record = await self._open_record(customer_id)
        await self.session.commit()
        return await self.load(record.id)

    async def load(self, record_id: int) -> RationedRegister:
        record = (
            await self.session.execute(
                select(RationedRecord)
                .options(selectinload(RationedRecord.customer))
                .where(RationedRecord.id == record_id)
            )
        ).scalar_one_or_none()
        if record is None:
            raise AppException(404, "السجل غير موجود.")

        closer = None
        if record.closed_by is not None:
            closer = await self.session.get(User, record.closed_by)

        entries = await self._entries(record_id)
        return RationedRegister(
            record_id=record.id,
            customer_id=record.customer_id,
            customer_name=record.customer.name,
            customer_phone=record.customer.phone,
            opened_at=record.opened_at,
            closed_at=record.closed_at,
            closed_by_name=closer.full_name if closer else None,
            notes=record.notes,
            is_open=record.closed_at is None,
            line_count=len(entries),
            total_quantity=sum(
                (e.net_quantity for e in entries), ZERO
            ).quantize(THREE_PLACES),
            total_value=sum((e.net_total for e in entries), ZERO).quantize(TWO_PLACES),
            entries=entries,
        )

    async def history(self, customer_id: int) -> list[RationedRecord]:
        """Closed registers, newest first — the declarations already issued."""
        result = await self.session.execute(
            select(RationedRecord)
            .where(
                RationedRecord.customer_id == customer_id,
                RationedRecord.closed_at.is_not(None),
            )
            .order_by(RationedRecord.closed_at.desc())
        )
        return list(result.scalars().all())

    # --- closing ---

    async def close(
        self, record_id: int, user: User, notes: str | None = None
    ) -> tuple[RationedRegister, int]:
        """Close this register and open the customer's next one.

        Returns the closed register and the id of the fresh one, because the screen
        needs both: what was just finalised, and what is now accumulating.

        An empty register is refused. Closing nothing produces a declaration with no
        lines, which is not a record of anything and would sit in the history looking
        like a month in which the customer took no regulated goods.
        """
        record = await self.session.get(RationedRecord, record_id)
        if record is None:
            raise AppException(404, "السجل غير موجود.")
        if record.closed_at is not None:
            raise AppException(400, "هذا السجل مقفل من قبل.")

        count = await self.session.scalar(
            select(func.count())
            .select_from(RationedLine)
            .where(RationedLine.record_id == record_id)
        )
        if not count:
            raise AppException(
                400, "لا يمكن إقفال سجل فارغ؛ لا توجد مواد مقننة مسجَّلة فيه."
            )

        record.closed_at = datetime.now(timezone.utc)
        record.closed_by = user.id
        if notes is not None:
            record.notes = notes
        # Flush before opening the next one: the partial unique index allows a single
        # open register per customer, so the close has to be visible first.
        await self.session.flush()

        successor = await self._open_record(record.customer_id)
        await self.session.commit()
        return await self.load(record_id), successor.id

    # --- internals ---

    async def _open_record(self, customer_id: int) -> RationedRecord:
        """The customer's open register, created if there is none.

        Not `get_or_create` by name, because the uniqueness that matters is enforced by
        a partial index in the database rather than by this check — two concurrent
        invoices for one customer would otherwise both find nothing and both insert.
        """
        customer = await self.session.get(Customer, customer_id)
        if customer is None:
            raise AppException(404, "العميل غير موجود.")

        record = (
            await self.session.execute(
                select(RationedRecord).where(
                    RationedRecord.customer_id == customer_id,
                    RationedRecord.closed_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if record is not None:
            return record

        record = RationedRecord(customer_id=customer_id)
        self.session.add(record)
        await self.session.flush()
        return record

    async def _entries(self, record_id: int) -> list[RationedEntry]:
        """Every filed line, read through to the invoice as it stands now."""
        rows = (
            await self.session.execute(
                select(RationedLine, SalesInvoiceLine, SalesInvoice)
                .join(
                    SalesInvoiceLine,
                    SalesInvoiceLine.id == RationedLine.sales_invoice_line_id,
                )
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
                .where(RationedLine.record_id == record_id)
                .order_by(SalesInvoice.invoice_date, SalesInvoice.id, SalesInvoiceLine.id)
            )
        ).all()
        if not rows:
            return []

        returned = await self._returned_quantities(
            {(invoice.id, line.product_id) for _, line, invoice in rows}
        )

        entries: list[RationedEntry] = []
        for tag, line, invoice in rows:
            # Returns are recorded per product per invoice, not per batch line, so a
            # product split across batches has its credit apportioned by share of the
            # quantity sold. Assigning the whole return to the first line would make
            # one row negative and another overstated while the total stayed right.
            sold_for_product = sum(
                Decimal(str(other.quantity))
                for _, other, other_invoice in rows
                if other_invoice.id == invoice.id and other.product_id == line.product_id
            )
            credited = returned.get((invoice.id, line.product_id), ZERO)
            share = (
                (Decimal(str(line.quantity)) / sold_for_product)
                if sold_for_product > 0
                else ZERO
            )
            mine = (credited * share).quantize(THREE_PLACES)
            net = max(Decimal(str(line.quantity)) - mine, ZERO)
            entries.append(
                RationedEntry(
                    line_id=line.id,
                    invoice_id=invoice.id,
                    invoice_reference=str(invoice.id),
                    invoice_date=invoice.invoice_date,
                    product_id=line.product_id,
                    product_name=line.product_name,
                    unit_name=line.unit_name,
                    quantity=Decimal(str(line.quantity)),
                    returned_quantity=mine,
                    net_quantity=net,
                    unit_price=Decimal(str(line.unit_price)),
                    net_total=(net * Decimal(str(line.unit_price))).quantize(TWO_PLACES),
                    added_at=tag.added_at,
                )
            )
        return entries

    async def _returned_quantities(
        self, keys: set[tuple[int, int]]
    ) -> dict[tuple[int, int], Decimal]:
        """Posted credit-note quantities per (invoice, product).

        `posted()` is the shared definition of a return that counts — a cancelled
        credit note must not reduce the declaration, and re-deciding that here would
        be a second opinion about it.
        """
        if not keys:
            return {}
        invoice_ids = {invoice_id for invoice_id, _ in keys}
        rows = (
            await self.session.execute(
                select(
                    SalesReturn.invoice_id,
                    SalesReturnLine.product_id,
                    func.sum(SalesReturnLine.quantity),
                )
                .join(SalesReturn, SalesReturn.id == SalesReturnLine.return_id)
                .where(SalesReturn.invoice_id.in_(invoice_ids), posted())
                .group_by(SalesReturn.invoice_id, SalesReturnLine.product_id)
            )
        ).all()
        return {
            (invoice_id, product_id): Decimal(str(total or 0))
            for invoice_id, product_id, total in rows
            if (invoice_id, product_id) in keys
        }
