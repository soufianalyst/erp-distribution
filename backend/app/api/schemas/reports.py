"""Pydantic schemas (DTOs) for the reports module."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class SalesMonthKPI(BaseModel):
    count: int
    revenue: Decimal
    collected: Decimal
    prev_count: int
    prev_revenue: Decimal


class PurchasesMonthKPI(BaseModel):
    count: int
    total: Decimal


class ReturnsMonthKPI(BaseModel):
    count: int
    total: Decimal


class DashboardData(BaseModel):
    sales_this_month: SalesMonthKPI
    purchases_this_month: PurchasesMonthKPI
    returns_this_month: ReturnsMonthKPI
    outstanding_receivables: Decimal
    low_stock_count: int
    total_products: int


class TopProductRow(BaseModel):
    product_id: int
    product_name: str
    sku: str
    base_unit_name: str
    total_quantity: Decimal
    total_revenue: Decimal


class SalesmanPerfRow(BaseModel):
    salesman_id: int
    salesman_name: str
    invoice_count: int
    total_revenue: Decimal
    collected: Decimal


class DamageRow(BaseModel):
    product_id: int
    product_name: str
    sku: str
    batch_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    reason: str
    created_at: datetime | None = None


# --- Tax report ---


class TaxByTypeRow(BaseModel):
    tax_type_id: int
    tax_type_name: str
    rate: Decimal
    accounting_code: str
    collected: Decimal
    returned: Decimal
    net_collected: Decimal


class TaxReportOut(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    total_collected: Decimal
    total_returned: Decimal
    net_collected: Decimal
    total_paid_on_purchases: Decimal
    net_tax_payable: Decimal
    by_tax_type: list[TaxByTypeRow]


# --- Income statement ---
class IncomeStatementLine(BaseModel):
    account_code: str
    account_name: str
    balance: Decimal


class IncomeStatementOut(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    gross_sales: Decimal
    sales_returns: Decimal
    net_sales: Decimal
    cogs: Decimal
    gross_profit: Decimal
    expenses: list[IncomeStatementLine]
    total_expenses: Decimal
    net_profit: Decimal


# --- Balance sheet ---
class BalanceSheetLine(BaseModel):
    account_code: str
    account_name: str
    balance: Decimal


class BalanceSheetSection(BaseModel):
    title: str
    items: list[BalanceSheetLine]
    total: Decimal


class BalanceSheetOut(BaseModel):
    as_of_date: str
    assets: BalanceSheetSection
    liabilities: BalanceSheetSection
    equity: BalanceSheetSection
    total_liabilities_and_equity: Decimal
