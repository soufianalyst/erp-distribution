"""Pydantic schemas (DTOs) for the cashier module."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CashierAmountCreate(BaseModel):
    # The actual amount handed over/paid out now; may be less than what's owed
    # for a partial settlement — the document only releases (sales: to
    # delivery/pickup) once the full amount has moved, possibly across several
    # movements.
    amount: Decimal = Field(gt=0)


class CashMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    direction: Literal["in", "out"]
    reference_type: Literal["sales_invoice", "purchase_invoice", "expense"]
    reference_id: int
    party_id: int | None
    amount: Decimal
    method: str
    collected_at: datetime


class PendingPayableOut(BaseModel):
    payable_type: Literal["purchase_invoice", "expense"]
    id: int
    date: date_type
    description: str
    payment_method: str
    total: Decimal
    paid_amount: Decimal
    remaining: Decimal


class CashierDailySummaryOut(BaseModel):
    day: date_type
    cashier_id: int
    cashier_name: str
    total_in: Decimal
    total_out: Decimal
    net: Decimal
    cash_in: Decimal
    card_in: Decimal
    cash_out: Decimal
    card_out: Decimal
    movement_count: int
    movements: list[CashMovementOut]
