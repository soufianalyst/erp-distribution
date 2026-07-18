"""Expenses business logic: configurable categories and payable expense notes.

Business rule: every expense is cash or card (never credit) and always posts as
a payable at creation — it only counts as settled once the cashier disburses it
in full (see CashierService.pay_expense).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.expenses import (
    ExpenseCategoryCreate,
    ExpenseCategoryUpdate,
    ExpenseCreate,
)
from app.core.exceptions import AppException
from app.domain.models.expenses import Expense, ExpenseCategory
from app.domain.models.user import User
from app.services.accounting.accounting_service import (
    ACCOUNTS_PAYABLE,
    GENERAL_EXPENSES,
    AccountingService,
)


class ExpenseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounting = AccountingService(session)

    # --- Categories ---
    async def get_category(self, category_id: int) -> ExpenseCategory:
        category = await self.session.get(ExpenseCategory, category_id)
        if category is None:
            raise AppException(404, "تصنيف المصاريف غير موجود.")
        return category

    async def list_categories(self, active_only: bool = False) -> list[ExpenseCategory]:
        stmt = select(ExpenseCategory).order_by(ExpenseCategory.id)
        if active_only:
            stmt = stmt.where(ExpenseCategory.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_category(self, data: ExpenseCategoryCreate) -> ExpenseCategory:
        existing = await self.session.execute(
            select(ExpenseCategory).where(ExpenseCategory.name == data.name)
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(409, "يوجد تصنيف بهذا الاسم من قبل.")
        category = ExpenseCategory(name=data.name, is_active=data.is_active)
        self.session.add(category)
        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def update_category(
        self, category_id: int, data: ExpenseCategoryUpdate
    ) -> ExpenseCategory:
        category = await self.get_category(category_id)
        if data.name is not None:
            category.name = data.name
        if data.is_active is not None:
            category.is_active = data.is_active
        await self.session.commit()
        await self.session.refresh(category)
        return category

    # --- Expenses ---
    async def get_expense(self, expense_id: int) -> Expense:
        expense = await self.session.get(Expense, expense_id)
        if expense is None:
            raise AppException(404, "المصروف غير موجود.")
        return expense

    async def list_expenses(self, category_id: int | None = None) -> list[Expense]:
        stmt = select(Expense).order_by(Expense.id.desc())
        if category_id is not None:
            stmt = stmt.where(Expense.category_id == category_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_expense(self, data: ExpenseCreate, user: User) -> Expense:
        """Post an expense as a payable — Dr Expense, Cr Accounts Payable.

        It always starts unpaid and awaits the cashier (see CashierService).
        """
        category = await self.get_category(data.category_id)
        if not category.is_active:
            raise AppException(400, "هذا التصنيف موقوف ولا يمكن تسجيل مصروف عليه.")

        expense = Expense(
            category_id=category.id,
            description=data.description,
            amount=data.amount,
            payment_method=data.payment_method,
            paid_amount=Decimal("0"),
            payment_confirmed_at=None,
            notes=data.notes,
            created_by=user.id,
        )
        self.session.add(expense)
        await self.session.flush()

        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"مصروف رقم {expense.id} — {category.name}: {data.description}",
            items=[
                (GENERAL_EXPENSES, data.amount, Decimal("0")),
                (ACCOUNTS_PAYABLE, Decimal("0"), data.amount),
            ],
            reference_type="expense",
            reference_id=expense.id,
            created_by=user.id,
        )

        await self.session.commit()
        await self.session.refresh(expense)
        return expense
