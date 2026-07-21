"""Expense entities: payable notes for utilities, supplies, etc."""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExpenseCategory(str, enum.Enum):
    UTILITIES = "utilities"  # فواتير مرافق
    FOOD = "food"  # طعام
    WATER = "water"  # مياه شرب
    RENT = "rent"  # إيجار
    SALARIES = "salaries"  # رواتب
    TRANSPORT = "transport"  # نقل ومواصلات
    MAINTENANCE = "maintenance"  # صيانة
    OFFICE = "office"  # مكتبية
    OTHER = "other"  # أخرى


class ExpensePaymentMethod(str, enum.Enum):
    CASH = "cash"  # نقدي — يمر عبر الصندوق
    CREDIT = "credit"  # آجل — يضاف للمدفوعات المستحقة


class Expense(Base):
    """سند مصروف — a payable note tracked through the cashier for cash/card payments."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[ExpenseCategory] = mapped_column(
        Enum(ExpenseCategory, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    payee_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    expense_date: Mapped[date] = mapped_column(nullable=False)
    payment_method: Mapped[ExpensePaymentMethod] = mapped_column(
        Enum(ExpensePaymentMethod, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
