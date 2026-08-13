"""Shapes the data-import screen speaks in."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class ImportErrorOut(BaseModel):
    """One reason the file was refused, addressed to whoever must fix the spreadsheet.

    `row` is the number Excel shows in its gutter, not a zero-based index — an error
    the user cannot navigate to is barely an error report at all.
    """

    sheet: str
    sheet_title: str
    row: int | None = None
    column: str | None = None
    message: str


class SheetResultOut(BaseModel):
    sheet: str
    title: str
    rows: int


class ReconciliationRowOut(BaseModel):
    """One party's balance, as this system computes it against what the old one said.

    Renamed from `customer_name` when suppliers joined the import: a supplier balance
    that silently fails to reconcile is exactly the class of error this table exists
    to catch, and leaving it customer-only would have made the guide's promise —
    "the same rule applies to suppliers" — untrue.
    """

    party_kind: Literal["customer", "supplier"]
    party_name: str
    expected_balance: Decimal
    actual_balance: Decimal
    # Positive means this system thinks they owe more than the legacy figure.
    difference: Decimal
    matches: bool


class ImportReportOut(BaseModel):
    # False both for a dry run and for a rejected file — `error_count` separates them.
    applied: bool
    sheets: list[SheetResultOut]
    error_count: int
    # Capped list; `error_count` is the true total.
    errors: list[ImportErrorOut]
    reconciliation: list[ReconciliationRowOut]
    reconciliation_mismatches: int
    message: str


class ImportSheetInfoOut(BaseModel):
    """What the screen shows about a sheet before anything is uploaded."""

    name: str
    title: str
    purpose: str
    columns: list["ImportColumnInfoOut"]


class ImportColumnInfoOut(BaseModel):
    name: str
    label: str
    kind: str
    required: bool
    choices: list[str]
    note: str


class ImportGuideOut(BaseModel):
    rules: list[str]
    sheets: list[ImportSheetInfoOut]
