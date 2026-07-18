"""Pydantic schemas (DTOs) for the expenses module."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.expenses import ExpensePaymentMethod


# --- Categories ---
class ExpenseCategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    is_active: bool = True


class ExpenseCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    is_active: bool | None = None


class ExpenseCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool


# --- Expenses ---
class ExpenseCreate(BaseModel):
    category_id: int
    description: str = Field(min_length=2, max_length=300)
    amount: Decimal = Field(gt=0)
    payment_method: ExpensePaymentMethod
    notes: str | None = Field(default=None, max_length=300)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    description: str
    amount: Decimal
    payment_method: ExpensePaymentMethod
    paid_amount: Decimal
    payment_confirmed_at: datetime | None
    notes: str | None
    created_at: datetime
