"""Accounting business logic: chart of accounts, double-entry journal, trial balance."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.accounting import (
    AccountCreate,
    BalanceSheetOut,
    BalanceSheetRow,
    IncomeStatementOut,
    IncomeStatementRow,
    ManualEntryCreate,
    TaxSummaryOut,
    TaxSummaryRow,
    TrialBalanceOut,
    TrialBalanceRow,
)
from app.api.schemas.pagination import PageParams, paginate
from app.core import business_day
from app.core.exceptions import AppException
from app.domain.models.accounting import Account, AccountType, JournalEntry, JournalItem
from app.domain.models.purchases import PurchaseInvoice, PurchaseInvoiceTax
from app.domain.models.sales import SalesInvoice, SalesInvoiceTax, SalesReturn
from app.services.sales.returns_query import posted

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
# Contra-revenue: discounts granted on invoices (including rounding down the
# collectable amount). Debiting a revenue-type account reduces net revenue,
# which is exactly how the income statement should treat a discount given.
SALES_DISCOUNT = "4030"
COGS = "5010"
GENERAL_EXPENSES = "5020"
DAMAGE_LOSS = "5030"
# Physical-count differences. Typed EXPENSE so a shortfall (debit) is a cost;
# a surplus credits it, which nets the cost down — the same account carries both
# directions because they are two outcomes of the same reconciliation.
STOCKTAKE_VARIANCE = "5040"

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
    (SALES_DISCOUNT, "خصم مسموح به", AccountType.REVENUE),
    (COGS, "تكلفة البضاعة المباعة", AccountType.EXPENSE),
    (GENERAL_EXPENSES, "مصاريف تشغيلية عامة", AccountType.EXPENSE),
    (DAMAGE_LOSS, "خسائر التالف والمرتجعات", AccountType.EXPENSE),
    (STOCKTAKE_VARIANCE, "فروقات الجرد (عجز وزيادة)", AccountType.EXPENSE),
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
        """Look up a ledger account by its code, or raise a 404."""
        result = await self.session.execute(select(Account).where(Account.code == code))
        account = result.scalar_one_or_none()
        if account is None:
            raise AppException(404, f"الحساب رقم ({code}) غير موجود في دليل الحسابات.")
        return account

    async def create_account(self, data: AccountCreate) -> Account:
        """Add an account to the chart of accounts; codes are unique."""
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
        """The whole chart of accounts, in code order."""
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
        """Post a hand-written journal entry, balanced and committed as one unit."""
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
        """Fetch a journal entry with its items and their accounts, or raise a 404."""
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
        page: PageParams | None = None,
        search: str | None = None,
    ) -> tuple[list[JournalEntry], int]:
        """Journal entries, newest first, optionally filtered by what produced them.

        Returns the page and the total. The ledger is the fastest-growing table in the
        system — every invoice, payment, return and expense posts one — so this is the
        one list that must never be fetched whole.

        `search` has to run in SQL for the same reason. Filtering in the browser once
        meant searching every entry, which was correct; filtering the browser's copy
        of one page would search fifteen rows out of thousands and look identical.
        """
        stmt = (
            select(JournalEntry)
            .options(selectinload(JournalEntry.items).selectinload(JournalItem.account))
            .order_by(JournalEntry.id.desc())
        )
        if reference_type is not None:
            stmt = stmt.where(JournalEntry.reference_type == reference_type)
        if reference_id is not None:
            stmt = stmt.where(JournalEntry.reference_id == reference_id)
        if search and search.strip():
            # Description and date only. `reference_type` is deliberately excluded:
            # it holds English snake_case the screen never shows — an accountant sees
            # "فاتورة شراء", not "purchase_invoice" — and the descriptions already
            # carry the document type in Arabic ("فاتورة شراء رقم 66 من المورد"). So
            # searching what is displayed finds what is displayed.
            #
            # `ilike` rather than `like` because Arabic has no case to fold but the
            # descriptions mix in Latin supplier codes, and someone typing "sc"
            # should still find "(SC شركة التوريد الوطنية)".
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                JournalEntry.description.ilike(term)
                | func.cast(JournalEntry.entry_date, String).ilike(term)
            )
        return await paginate(self.session, stmt, page or PageParams())

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

        # Credit notes reduce the tax owed, and this report used to ignore them
        # entirely. Sell 1,000 with 160 of VAT, take the whole lot back, and it still
        # showed 160 collected — so the company would file and pay tax on sales that
        # no longer existed. The journal entry was always right; the report simply
        # read from a different place than the ledger, which is how the two came to
        # disagree.
        #
        # A return stores one combined `vat_amount` rather than a row per rate, so it
        # is allocated across the invoice's own tax rows in proportion to what each
        # one charged. That keeps the credit against the same rate that collected it —
        # which matters as soon as an invoice carries VAT plus a local tax, because
        # the two are declared separately.
        returns_stmt = (
            select(
                SalesInvoiceTax.name,
                SalesInvoiceTax.rate,
                SalesInvoiceTax.amount,
                SalesInvoice.vat_amount,
                SalesReturn.vat_amount,
            )
            .join(SalesReturn, SalesReturn.invoice_id == SalesInvoiceTax.invoice_id)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceTax.invoice_id)
            .where(SalesReturn.vat_amount > 0, posted())
        )
        # Dated by the *return*, not the invoice: a credit note issued in March
        # against a January sale belongs to March's declaration.
        # Windowed on the company's local day: a credit note raised just after local
        # midnight on the 1st belongs to this declaration, not the previous one.
        from app.services.settings.settings_service import SettingsService

        company = await SettingsService(self.session).get_company_settings()
        returns_from, returns_to = business_day.utc_window(
            date_from, date_to, company.timezone
        )
        if returns_from is not None:
            returns_stmt = returns_stmt.where(SalesReturn.created_at >= returns_from)
        if returns_to is not None:
            returns_stmt = returns_stmt.where(SalesReturn.created_at < returns_to)
        credited: dict[tuple[str, Decimal], Decimal] = {}
        for name, rate, tax_amount, invoice_vat, return_vat in (
            await self.session.execute(returns_stmt)
        ).all():
            invoice_vat = Decimal(str(invoice_vat))
            if invoice_vat <= 0:
                continue
            share = (Decimal(str(tax_amount)) / invoice_vat) * Decimal(str(return_vat))
            key = (name, Decimal(str(rate)))
            credited[key] = credited.get(key, Decimal("0")) + share.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        collected = {
            (name, Decimal(str(rate))): Decimal(str(amount))
            - credited.get((name, Decimal(str(rate))), Decimal("0"))
            for name, rate, amount in sales_result.all()
        }
        # A rate that only ever appeared on a credit note in this period still owes a
        # (negative) line, or the declaration silently omits it.
        for key, amount in credited.items():
            collected.setdefault(key, -amount)
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

    async def income_statement(
        self, date_from: date | None, date_to: date | None
    ) -> IncomeStatementOut:
        """قائمة الدخل: الإيرادات - تكلفة البضاعة المباعة - المصاريف = صافي الربح."""
        stmt = (
            select(
                Account.code,
                Account.name,
                Account.type,
                func.coalesce(func.sum(JournalItem.debit), 0),
                func.coalesce(func.sum(JournalItem.credit), 0),
            )
            .join(JournalItem, JournalItem.account_id == Account.id)
            .join(JournalEntry, JournalItem.entry_id == JournalEntry.id)
            .where(Account.type.in_([AccountType.REVENUE, AccountType.EXPENSE]))
            .group_by(Account.code, Account.name, Account.type)
            .order_by(Account.code)
        )
        if date_from is not None:
            stmt = stmt.where(JournalEntry.entry_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(JournalEntry.entry_date <= date_to)
        result = await self.session.execute(stmt)

        revenue_rows: list[IncomeStatementRow] = []
        cogs_rows: list[IncomeStatementRow] = []
        expense_rows: list[IncomeStatementRow] = []
        total_revenue = Decimal("0")
        total_cogs = Decimal("0")
        total_expenses = Decimal("0")

        for code, name, account_type, debit, credit in result.all():
            debit = Decimal(str(debit))
            credit = Decimal(str(credit))
            if account_type == AccountType.REVENUE:
                # Revenue accounts normally carry a credit balance.
                amount = credit - debit
                revenue_rows.append(
                    IncomeStatementRow(account_code=code, account_name=name, amount=amount)
                )
                total_revenue += amount
            elif code == COGS:
                amount = debit - credit
                cogs_rows.append(
                    IncomeStatementRow(account_code=code, account_name=name, amount=amount)
                )
                total_cogs += amount
            else:
                # Expense accounts normally carry a debit balance.
                amount = debit - credit
                expense_rows.append(
                    IncomeStatementRow(account_code=code, account_name=name, amount=amount)
                )
                total_expenses += amount

        gross_profit = total_revenue - total_cogs
        return IncomeStatementOut(
            date_from=date_from,
            date_to=date_to,
            revenue_rows=revenue_rows,
            total_revenue=total_revenue,
            cogs_rows=cogs_rows,
            total_cogs=total_cogs,
            gross_profit=gross_profit,
            expense_rows=expense_rows,
            total_expenses=total_expenses,
            net_profit=gross_profit - total_expenses,
        )

    async def balance_sheet(self, as_of: date | None = None) -> BalanceSheetOut:
        """الميزانية العمومية: الأصول = الالتزامات + حقوق الملكية.

        This system has no period-end closing entries (revenue/expense accounts
        just accumulate), so cumulative net income up to `as_of` is folded into
        equity as retained earnings — otherwise the sheet would never balance.
        """
        stmt = (
            select(
                Account.code,
                Account.name,
                Account.type,
                func.coalesce(func.sum(JournalItem.debit), 0),
                func.coalesce(func.sum(JournalItem.credit), 0),
            )
            .join(JournalItem, JournalItem.account_id == Account.id)
            .join(JournalEntry, JournalItem.entry_id == JournalEntry.id)
            .where(
                Account.type.in_(
                    [AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY]
                )
            )
            .group_by(Account.code, Account.name, Account.type)
            .order_by(Account.code)
        )
        if as_of is not None:
            stmt = stmt.where(JournalEntry.entry_date <= as_of)
        result = await self.session.execute(stmt)

        asset_rows: list[BalanceSheetRow] = []
        liability_rows: list[BalanceSheetRow] = []
        equity_rows: list[BalanceSheetRow] = []
        total_assets = Decimal("0")
        total_liabilities = Decimal("0")
        total_equity = Decimal("0")

        for code, name, account_type, debit, credit in result.all():
            debit = Decimal(str(debit))
            credit = Decimal(str(credit))
            if account_type == AccountType.ASSET:
                amount = debit - credit
                asset_rows.append(
                    BalanceSheetRow(account_code=code, account_name=name, amount=amount)
                )
                total_assets += amount
            elif account_type == AccountType.LIABILITY:
                amount = credit - debit
                liability_rows.append(
                    BalanceSheetRow(account_code=code, account_name=name, amount=amount)
                )
                total_liabilities += amount
            else:  # EQUITY
                amount = credit - debit
                equity_rows.append(
                    BalanceSheetRow(account_code=code, account_name=name, amount=amount)
                )
                total_equity += amount

        retained_earnings = (
            await self.income_statement(date_from=None, date_to=as_of)
        ).net_profit
        total_equity_with_earnings = total_equity + retained_earnings
        total_liabilities_and_equity = total_liabilities + total_equity_with_earnings

        return BalanceSheetOut(
            as_of=as_of,
            asset_rows=asset_rows,
            total_assets=total_assets,
            liability_rows=liability_rows,
            total_liabilities=total_liabilities,
            equity_rows=equity_rows,
            retained_earnings=retained_earnings,
            total_equity=total_equity_with_earnings,
            total_liabilities_and_equity=total_liabilities_and_equity,
            is_balanced=total_assets == total_liabilities_and_equity,
        )
