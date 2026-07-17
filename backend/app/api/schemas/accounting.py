"""Pydantic schemas (DTOs) for the accounting module."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models.accounting import AccountType


# --- Accounts ---
class AccountCreate(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[0-9]+$")
    name: str = Field(min_length=2, max_length=150)
    type: AccountType


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    type: AccountType
    is_system: bool
    is_active: bool


# --- Journal entries ---
class JournalItemIn(BaseModel):
    account_code: str
    debit: Decimal = Field(default=Decimal("0"), ge=0)
    credit: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def one_side_only(self) -> "JournalItemIn":
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("كل سطر يجب أن يكون مديناً أو دائناً وليس كليهما.")
        return self


class ManualEntryCreate(BaseModel):
    entry_date: date | None = None
    description: str = Field(min_length=3, max_length=300)
    items: list[JournalItemIn] = Field(min_length=2)


class JournalItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account: AccountOut
    debit: Decimal
    credit: Decimal


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    description: str
    reference_type: str | None
    reference_id: int | None
    created_at: datetime
    items: list[JournalItemOut]


# --- Trial balance ---
class TrialBalanceRow(BaseModel):
    account_code: str
    account_name: str
    account_type: AccountType
    total_debit: Decimal
    total_credit: Decimal
    balance: Decimal


class TrialBalanceOut(BaseModel):
    rows: list[TrialBalanceRow]
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool
