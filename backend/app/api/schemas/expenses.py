"""Pydantic schemas (DTOs) for the expenses module."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.expenses import ExpenseCategory, ExpensePaymentMethod


class ExpenseIn(BaseModel):
    category: ExpenseCategory
    payee_name: str = Field(max_length=150)
    description: str | None = Field(default=None, max_length=300)
    amount: Decimal = Field(gt=0)
    expense_date: date
    payment_method: ExpensePaymentMethod
    account_code: str = Field(max_length=20, description="Account code in chart of accounts")
    reference_no: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=300)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: ExpenseCategory
    payee_name: str
    description: str | None
    amount: Decimal
    expense_date: date
    payment_method: ExpensePaymentMethod
    paid_amount: Decimal
    account_code: str
    reference_no: str | None
    notes: str | None
    created_by: int | None
    created_at: datetime
