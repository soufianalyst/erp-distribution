"""Pydantic schemas (DTOs) for the accounting module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

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


# --- Tax summary ---
class TaxSummaryRow(BaseModel):
    name: str
    rate: Decimal
    collected: Decimal  # tax on sales invoices (output tax)
    paid: Decimal  # tax on purchase invoices (input tax)
    net: Decimal  # collected - paid; positive means payable to the tax authority


class TaxSummaryOut(BaseModel):
    date_from: date | None
    date_to: date | None
    rows: list[TaxSummaryRow]
    total_collected: Decimal
    total_paid: Decimal
    total_net: Decimal


# --- Income statement (P&L) ---
class IncomeStatementRow(BaseModel):
    account_code: str
    account_name: str
    amount: Decimal


class IncomeStatementOut(BaseModel):
    date_from: date | None
    date_to: date | None
    revenue_rows: list[IncomeStatementRow]
    total_revenue: Decimal
    cogs_rows: list[IncomeStatementRow]
    total_cogs: Decimal
    gross_profit: Decimal
    expense_rows: list[IncomeStatementRow]
    total_expenses: Decimal
    net_profit: Decimal


# --- Balance sheet ---
class BalanceSheetRow(BaseModel):
    account_code: str
    account_name: str
    amount: Decimal


class BalanceSheetOut(BaseModel):
    as_of: date | None
    asset_rows: list[BalanceSheetRow]
    total_assets: Decimal
    liability_rows: list[BalanceSheetRow]
    total_liabilities: Decimal
    equity_rows: list[BalanceSheetRow]
    # Cumulative net income folded into equity — this system has no
    # period-end closing entries, so it must be added for the sheet to balance.
    retained_earnings: Decimal
    total_equity: Decimal
    total_liabilities_and_equity: Decimal
    is_balanced: bool


# --- Bank reconciliation ---
class BankStatementLineCreate(BaseModel):
    line_date: date
    description: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(gt=0)
    direction: Literal["in", "out"]
    notes: str | None = Field(default=None, max_length=300)


class MatchRequest(BaseModel):
    journal_item_id: int


class JournalItemSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    description: str
    debit: Decimal
    credit: Decimal


class BankStatementLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_date: date
    description: str
    amount: Decimal
    direction: Literal["in", "out"]
    matched_journal_item_id: int | None
    matched_journal_item: JournalItemSummaryOut | None
    matched_at: datetime | None
    notes: str | None
    created_at: datetime


class UnmatchedJournalItemOut(BaseModel):
    id: int
    entry_id: int
    entry_date: date
    description: str
    debit: Decimal
    credit: Decimal


class BankReconciliationSummaryOut(BaseModel):
    date_from: date | None
    date_to: date | None
    total_lines: int
    matched_count: int
    unmatched_count: int
    total_in: Decimal
    total_out: Decimal
    unmatched_book_entries: int
