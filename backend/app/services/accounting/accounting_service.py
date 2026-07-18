"""Accounting business logic: chart of accounts, double-entry journal, trial balance."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.accounting import (
    AccountCreate,
    ManualEntryCreate,
    TaxSummaryOut,
    TaxSummaryRow,
    TrialBalanceOut,
    TrialBalanceRow,
)
from app.core.exceptions import AppException
from app.domain.models.accounting import Account, AccountType, JournalEntry, JournalItem
from app.domain.models.purchases import PurchaseInvoice, PurchaseInvoiceTax
from app.domain.models.sales import SalesInvoice, SalesInvoiceTax

# System account codes used by automatic postings.
CASH = "1010"
BANK = "1015"
ACCOUNTS_RECEIVABLE = "1020"
INVENTORY = "1030"
ACCOUNTS_PAYABLE = "2010"
VAT = "2020"
CAPITAL = "3010"
SALES_REVENUE = "4010"
SALES_RETURNS = "4020"
COGS = "5010"
GENERAL_EXPENSES = "5020"
DAMAGE_LOSS = "5030"

DEFAULT_ACCOUNTS: list[tuple[str, str, AccountType]] = [
    (CASH, "الصندوق", AccountType.ASSET),
    (BANK, "البنك", AccountType.ASSET),
    (ACCOUNTS_RECEIVABLE, "ذمم العملاء", AccountType.ASSET),
    (INVENTORY, "المخزون", AccountType.ASSET),
    (ACCOUNTS_PAYABLE, "ذمم دائنة", AccountType.LIABILITY),
    (VAT, "الضريبة المحصلة على المبيعات", AccountType.LIABILITY),
    (CAPITAL, "رأس المال", AccountType.EQUITY),
    (SALES_REVENUE, "إيرادات المبيعات", AccountType.REVENUE),
    (SALES_RETURNS, "مرتجعات المبيعات", AccountType.REVENUE),
    (COGS, "تكلفة البضاعة المباعة", AccountType.EXPENSE),
    (GENERAL_EXPENSES, "مصاريف تشغيلية عامة", AccountType.EXPENSE),
    (DAMAGE_LOSS, "خسائر التالف والمرتجعات", AccountType.EXPENSE),
]


def cash_or_bank(method: str) -> str:
    """Route a payment method to the cash box or the bank account."""
    return CASH if method == "cash" else BANK


async def seed_chart_of_accounts(session: AsyncSession) -> None:
    """Insert any missing system accounts; safe to run on every startup."""
    existing = await session.execute(select(Account.code))
    existing_codes = {code for (code,) in existing.all()}
    for code, name, account_type in DEFAULT_ACCOUNTS:
        if code not in existing_codes:
            session.add(
                Account(code=code, name=name, type=account_type, is_system=True)
            )
    await session.commit()


class AccountingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Accounts ---
    async def get_account_by_code(self, code: str) -> Account:
        result = await self.session.execute(select(Account).where(Account.code == code))
        account = result.scalar_one_or_none()
        if account is None:
            raise AppException(404, f"الحساب رقم ({code}) غير موجود في دليل الحسابات.")
        return account

    async def create_account(self, data: AccountCreate) -> Account:
        result = await self.session.execute(
            select(Account).where(Account.code == data.code)
        )
        if result.scalar_one_or_none() is not None:
            raise AppException(409, "يوجد حساب بهذا الرقم من قبل.")
        account = Account(code=data.code, name=data.name, type=data.type)
        self.session.add(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def list_accounts(self) -> list[Account]:
        result = await self.session.execute(select(Account).order_by(Account.code))
        return list(result.scalars().all())

    # --- Journal ---
    async def add_entry_no_commit(
        self,
        entry_date: date,
        description: str,
        items: list[tuple[str, Decimal, Decimal]],
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: int | None = None,
    ) -> JournalEntry:
        """Build a balanced journal entry WITHOUT committing — callers own the transaction.

        `items` is a list of (account_code, debit, credit); zero-amount rows are dropped.
        """
        non_zero = [(code, d, c) for code, d, c in items if d > 0 or c > 0]
        if len(non_zero) < 2:
            raise AppException(400, "القيد المحاسبي يجب أن يحتوي على طرفين على الأقل.")

        total_debit = sum((d for _, d, _ in non_zero), Decimal("0"))
        total_credit = sum((c for _, _, c in non_zero), Decimal("0"))
        if total_debit != total_credit:
            raise AppException(
                400,
                f"القيد غير متوازن: مجموع المدين ({total_debit}) لا يساوي مجموع الدائن ({total_credit}).",
            )

        entry = JournalEntry(
            entry_date=entry_date,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )
        for code, debit, credit in non_zero:
            account = await self.get_account_by_code(code)
            entry.items.append(
                JournalItem(account_id=account.id, debit=debit, credit=credit)
            )
        self.session.add(entry)
        return entry

    async def create_manual_entry(
        self, data: ManualEntryCreate, created_by: int | None = None
    ) -> JournalEntry:
        entry = await self.add_entry_no_commit(
            entry_date=data.entry_date or date.today(),
            description=data.description,
            items=[(i.account_code, i.debit, i.credit) for i in data.items],
            reference_type="manual",
            created_by=created_by,
        )
        await self.session.commit()
        return await self.get_entry(entry.id)

    async def get_entry(self, entry_id: int) -> JournalEntry:
        result = await self.session.execute(
            select(JournalEntry)
            .options(selectinload(JournalEntry.items).selectinload(JournalItem.account))
            .where(JournalEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            raise AppException(404, "القيد المحاسبي غير موجود.")
        return entry

    async def list_entries(
        self,
        reference_type: str | None = None,
        reference_id: int | None = None,
    ) -> list[JournalEntry]:
        stmt = (
            select(JournalEntry)
            .options(selectinload(JournalEntry.items).selectinload(JournalItem.account))
            .order_by(JournalEntry.id.desc())
        )
        if reference_type is not None:
            stmt = stmt.where(JournalEntry.reference_type == reference_type)
        if reference_id is not None:
            stmt = stmt.where(JournalEntry.reference_id == reference_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Reports ---
    async def trial_balance(self) -> TrialBalanceOut:
        """ميزان المراجعة: aggregate debit/credit per account; must always balance."""
        result = await self.session.execute(
            select(
                Account.code,
                Account.name,
                Account.type,
                func.coalesce(func.sum(JournalItem.debit), 0),
                func.coalesce(func.sum(JournalItem.credit), 0),
            )
            .join(JournalItem, JournalItem.account_id == Account.id)
            .group_by(Account.code, Account.name, Account.type)
            .order_by(Account.code)
        )

        rows: list[TrialBalanceRow] = []
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for code, name, account_type, debit, credit in result.all():
            debit = Decimal(str(debit))
            credit = Decimal(str(credit))
            rows.append(
                TrialBalanceRow(
                    account_code=code,
                    account_name=name,
                    account_type=account_type,
                    total_debit=debit,
                    total_credit=credit,
                    balance=debit - credit,
                )
            )
            total_debit += debit
            total_credit += credit

        return TrialBalanceOut(
            rows=rows,
            total_debit=total_debit,
            total_credit=total_credit,
            is_balanced=total_debit == total_credit,
        )

    async def tax_summary(
        self, date_from: date | None, date_to: date | None
    ) -> TaxSummaryOut:
        """تقرير الضرائب: مقارنة الضريبة المحصلة على المبيعات بالضريبة المدفوعة في المشتريات لكل نوع ضريبة."""

        sales_stmt = (
            select(
                SalesInvoiceTax.name,
                SalesInvoiceTax.rate,
                func.coalesce(func.sum(SalesInvoiceTax.amount), 0),
            )
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceTax.invoice_id)
            .group_by(SalesInvoiceTax.name, SalesInvoiceTax.rate)
        )
        if date_from is not None:
            sales_stmt = sales_stmt.where(SalesInvoice.invoice_date >= date_from)
        if date_to is not None:
            sales_stmt = sales_stmt.where(SalesInvoice.invoice_date <= date_to)
        sales_result = await self.session.execute(sales_stmt)

        purchases_stmt = (
            select(
                PurchaseInvoiceTax.name,
                PurchaseInvoiceTax.rate,
                func.coalesce(func.sum(PurchaseInvoiceTax.amount), 0),
            )
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceTax.invoice_id)
            .group_by(PurchaseInvoiceTax.name, PurchaseInvoiceTax.rate)
        )
        if date_from is not None:
            purchases_stmt = purchases_stmt.where(
                PurchaseInvoice.invoice_date >= date_from
            )
        if date_to is not None:
            purchases_stmt = purchases_stmt.where(
                PurchaseInvoice.invoice_date <= date_to
            )
        purchases_result = await self.session.execute(purchases_stmt)

        collected = {
            (name, Decimal(str(rate))): Decimal(str(amount))
            for name, rate, amount in sales_result.all()
        }
        paid = {
            (name, Decimal(str(rate))): Decimal(str(amount))
            for name, rate, amount in purchases_result.all()
        }

        rows: list[TaxSummaryRow] = []
        total_collected = Decimal("0")
        total_paid = Decimal("0")
        for name, rate in sorted(set(collected) | set(paid)):
            c = collected.get((name, rate), Decimal("0"))
            p = paid.get((name, rate), Decimal("0"))
            rows.append(TaxSummaryRow(name=name, rate=rate, collected=c, paid=p, net=c - p))
            total_collected += c
            total_paid += p

        return TaxSummaryOut(
            date_from=date_from,
            date_to=date_to,
            rows=rows,
            total_collected=total_collected,
            total_paid=total_paid,
            total_net=total_collected - total_paid,
        )
