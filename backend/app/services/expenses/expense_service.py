"""Expense business logic: CRUD for payable notes."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.domain.models.accounting import Account, AccountType, JournalEntry
from app.domain.models.expenses import (
    Expense,
    ExpensePaymentMethod,
)
from app.services.accounting.accounting_service import (
    ACCOUNTS_PAYABLE,
    CASH,
    AccountingService,
    cash_or_bank,
)

# Default expense accounts seeded on startup.
EXPENSE_ACCOUNTS: list[tuple[str, str]] = [
    ("5100", "فواتير المرافق"),
    ("5200", "طعام"),
    ("5300", "مياه شرب"),
    ("5400", "إيجار"),
    ("5500", "رواتب"),
    ("5600", "نقل ومواصلات"),
    ("5700", "صيانة"),
    ("5800", "مكتبية"),
    ("5900", "مصاريف أخرى"),
]


async def seed_expense_accounts(session: AsyncSession) -> None:
    """Insert missing default expense accounts into the chart of accounts."""
    existing = await session.execute(select(Account.code))
    existing_codes = {code for (code,) in existing.all()}
    for code, name in EXPENSE_ACCOUNTS:
        if code not in existing_codes:
            session.add(
                Account(code=code, name=name, type=AccountType.EXPENSE, is_system=True)
            )
    await session.commit()


class ExpenseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounting = AccountingService(session)

    async def list_expenses(self) -> list[Expense]:
        result = await self.session.execute(
            select(Expense).order_by(Expense.id.desc())
        )
        return list(result.scalars().all())

    async def get_expense(self, expense_id: int) -> Expense:
        expense = await self.session.get(Expense, expense_id)
        if expense is None:
            raise AppException(404, "سند المصروف غير موجود.")
        return expense

    async def create_expense(
        self, data: dict, user_id: int | None = None
    ) -> Expense:
        """Create a payable note. Cash expenses route through the cashier."""
        # Validate account exists.
        account = await self.session.execute(
            select(Account).where(Account.code == data["account_code"])
        )
        if account.scalar_one_or_none() is None:
            raise AppException(
                400,
                f"حساب رقم {data['account_code']} غير موجود في دليل الحسابات."
            )

        expense = Expense(
            category=data["category"],
            payee_name=data["payee_name"],
            description=data.get("description"),
            amount=data["amount"],
            expense_date=data["expense_date"],
            payment_method=data["payment_method"],
            paid_amount=Decimal("0"),
            account_code=data["account_code"],
            reference_no=data.get("reference_no"),
            notes=data.get("notes"),
            created_by=user_id,
        )
        self.session.add(expense)
        await self.session.flush()

        # Journal entry: Debit expense account, Credit accounts payable (cash expenses
        # settled later by cashier; credit expenses go straight to payable).
        credit_account = ACCOUNTS_PAYABLE
        await self.accounting.add_entry_no_commit(
            entry_date=data["expense_date"],
            description=f"سند مصروف ({data['payee_name']})",
            items=[
                (data["account_code"], data["amount"], Decimal("0")),
                (credit_account, Decimal("0"), data["amount"]),
            ],
            reference_type="expense",
            reference_id=expense.id,
            created_by=user_id,
        )

        await self.session.commit()
        await self.session.refresh(expense)
        return expense

    async def update_expense(
        self, expense_id: int, data: dict, user_id: int | None = None
    ) -> Expense:
        """Edit an unpaid expense."""
        expense = await self.get_expense(expense_id)
        if expense.paid_amount > 0:
            raise AppException(400, "لا يمكن تعديل مصروف تم تحصيل جزئي أو كلي.")

        # Validate account exists.
        account = await self.session.execute(
            select(Account).where(Account.code == data["account_code"])
        )
        if account.scalar_one_or_none() is None:
            raise AppException(
                400,
                f"حساب رقم {data['account_code']} غير موجود في دليل الحسابات."
            )

        # Remove old journal entries.
        old_entries = await self.session.execute(
            select(JournalEntry).where(
                JournalEntry.reference_type == "expense",
                JournalEntry.reference_id == expense_id,
            )
        )
        for entry in old_entries.scalars().all():
            await self.session.delete(entry)

        expense.category = data["category"]
        expense.payee_name = data["payee_name"]
        expense.description = data.get("description")
        expense.amount = data["amount"]
        expense.expense_date = data["expense_date"]
        expense.payment_method = data["payment_method"]
        expense.account_code = data["account_code"]
        expense.reference_no = data.get("reference_no")
        expense.notes = data.get("notes")

        # Re-post journal entry.
        credit_account = ACCOUNTS_PAYABLE
        await self.accounting.add_entry_no_commit(
            entry_date=data["expense_date"],
            description=f"سند مصروف ({data['payee_name']})",
            items=[
                (data["account_code"], data["amount"], Decimal("0")),
                (credit_account, Decimal("0"), data["amount"]),
            ],
            reference_type="expense",
            reference_id=expense.id,
            created_by=user_id,
        )

        await self.session.commit()
        await self.session.refresh(expense)
        return expense

    async def delete_expense(self, expense_id: int) -> None:
        """Delete an unpaid expense and reverse journal entries."""
        expense = await self.get_expense(expense_id)
        if expense.paid_amount > 0:
            raise AppException(400, "لا يمكن حذف مصروف تم تحصيل جزئي أو كلي.")

        old_entries = await self.session.execute(
            select(JournalEntry).where(
                JournalEntry.reference_type == "expense",
                JournalEntry.reference_id == expense_id,
            )
        )
        for entry in old_entries.scalars().all():
            await self.session.delete(entry)
        await self.session.delete(expense)
        await self.session.commit()
