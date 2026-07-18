"""Bank reconciliation: match manually-entered bank statement lines against the
book's own journal items posted to the bank account (1015)."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.accounting import (
    BankReconciliationSummaryOut,
    BankStatementLineCreate,
    JournalItemSummaryOut,
    UnmatchedJournalItemOut,
)
from app.core.exceptions import AppException
from app.domain.models.accounting import BankStatementLine, JournalEntry, JournalItem
from app.services.accounting.accounting_service import BANK, AccountingService


class BankReconciliationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _bank_account_id(self) -> int:
        account = await AccountingService(self.session).get_account_by_code(BANK)
        return account.id

    async def create_line(
        self, data: BankStatementLineCreate, created_by: int | None = None
    ) -> dict:
        line = BankStatementLine(
            line_date=data.line_date,
            description=data.description,
            amount=data.amount,
            direction=data.direction,
            notes=data.notes,
            created_by=created_by,
        )
        self.session.add(line)
        await self.session.commit()
        return await self.line_out_data(await self.get_line(line.id))

    async def get_line(self, line_id: int) -> BankStatementLine:
        result = await self.session.execute(
            select(BankStatementLine)
            .options(
                selectinload(BankStatementLine.matched_journal_item).selectinload(
                    JournalItem.entry
                )
            )
            .where(BankStatementLine.id == line_id)
        )
        line = result.scalar_one_or_none()
        if line is None:
            raise AppException(404, "بند كشف الحساب غير موجود.")
        return line

    async def line_out_data(self, line: BankStatementLine) -> dict:
        matched = None
        if line.matched_journal_item is not None:
            item = line.matched_journal_item
            matched = JournalItemSummaryOut(
                id=item.id,
                entry_date=item.entry.entry_date,
                description=item.entry.description,
                debit=item.debit,
                credit=item.credit,
            )
        return {
            "id": line.id,
            "line_date": line.line_date,
            "description": line.description,
            "amount": line.amount,
            "direction": line.direction,
            "matched_journal_item_id": line.matched_journal_item_id,
            "matched_journal_item": matched,
            "matched_at": line.matched_at,
            "notes": line.notes,
            "created_at": line.created_at,
        }

    async def list_lines(
        self,
        is_reconciled: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        stmt = (
            select(BankStatementLine)
            .options(
                selectinload(BankStatementLine.matched_journal_item).selectinload(
                    JournalItem.entry
                )
            )
            .order_by(BankStatementLine.line_date.desc(), BankStatementLine.id.desc())
        )
        if is_reconciled is not None:
            if is_reconciled:
                stmt = stmt.where(BankStatementLine.matched_journal_item_id.is_not(None))
            else:
                stmt = stmt.where(BankStatementLine.matched_journal_item_id.is_(None))
        if date_from is not None:
            stmt = stmt.where(BankStatementLine.line_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(BankStatementLine.line_date <= date_to)
        result = await self.session.execute(stmt)
        lines = list(result.scalars().all())
        return [await self.line_out_data(line) for line in lines]

    async def list_unmatched_journal_items(self) -> list[UnmatchedJournalItemOut]:
        bank_account_id = await self._bank_account_id()
        matched_subquery = select(BankStatementLine.matched_journal_item_id).where(
            BankStatementLine.matched_journal_item_id.is_not(None)
        )
        result = await self.session.execute(
            select(JournalItem, JournalEntry.entry_date, JournalEntry.description)
            .join(JournalEntry, JournalItem.entry_id == JournalEntry.id)
            .where(
                JournalItem.account_id == bank_account_id,
                JournalItem.id.not_in(matched_subquery),
            )
            .order_by(JournalEntry.entry_date.desc(), JournalItem.id.desc())
        )
        return [
            UnmatchedJournalItemOut(
                id=item.id,
                entry_id=item.entry_id,
                entry_date=entry_date,
                description=description,
                debit=item.debit,
                credit=item.credit,
            )
            for item, entry_date, description in result.all()
        ]

    async def match(
        self, line_id: int, journal_item_id: int, matched_by: int | None
    ) -> dict:
        line = await self.get_line(line_id)
        if line.matched_journal_item_id is not None:
            raise AppException(400, "هذا البند مطابق بالفعل.")

        item = await self.session.get(JournalItem, journal_item_id)
        if item is None:
            raise AppException(404, "حركة دفتر الأستاذ غير موجودة.")

        bank_account_id = await self._bank_account_id()
        if item.account_id != bank_account_id:
            raise AppException(400, "هذه الحركة ليست على حساب البنك.")

        existing = await self.session.execute(
            select(BankStatementLine).where(
                BankStatementLine.matched_journal_item_id == journal_item_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(400, "هذه الحركة مطابقة ببند آخر بالفعل.")

        # A bank deposit (inflow) increases the bank balance -> a debit;
        # a withdrawal (outflow) decreases it -> a credit.
        expected_side = "in" if item.debit > 0 else "out"
        if expected_side != line.direction:
            raise AppException(
                400,
                "اتجاه الحركة لا يتطابق مع بند كشف الحساب "
                f"(الحركة {'وارد' if expected_side == 'in' else 'صادر'} في دفتر الأستاذ).",
            )

        line.matched_journal_item_id = journal_item_id
        line.matched_at = datetime.now(timezone.utc)
        line.matched_by = matched_by
        await self.session.commit()
        # expire_on_commit=False means the (previously-None) matched_journal_item
        # relationship stays cached stale unless explicitly expired here.
        self.session.expire(line, ["matched_journal_item"])
        return await self.line_out_data(await self.get_line(line_id))

    async def unmatch(self, line_id: int) -> dict:
        line = await self.get_line(line_id)
        if line.matched_journal_item_id is None:
            raise AppException(400, "هذا البند غير مطابق أصلاً.")
        line.matched_journal_item_id = None
        line.matched_at = None
        line.matched_by = None
        await self.session.commit()
        self.session.expire(line, ["matched_journal_item"])
        return await self.line_out_data(await self.get_line(line_id))

    async def summary(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> BankReconciliationSummaryOut:
        stmt = select(BankStatementLine)
        if date_from is not None:
            stmt = stmt.where(BankStatementLine.line_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(BankStatementLine.line_date <= date_to)
        result = await self.session.execute(stmt)
        lines = list(result.scalars().all())

        matched_count = sum(1 for line in lines if line.matched_journal_item_id is not None)
        total_in = sum(
            (line.amount for line in lines if line.direction == "in"), Decimal("0")
        )
        total_out = sum(
            (line.amount for line in lines if line.direction == "out"), Decimal("0")
        )
        unmatched_book_entries = len(await self.list_unmatched_journal_items())

        return BankReconciliationSummaryOut(
            date_from=date_from,
            date_to=date_to,
            total_lines=len(lines),
            matched_count=matched_count,
            unmatched_count=len(lines) - matched_count,
            total_in=total_in,
            total_out=total_out,
            unmatched_book_entries=unmatched_book_entries,
        )
