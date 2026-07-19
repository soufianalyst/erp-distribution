"""Pydantic schemas (DTOs) for the sales module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.sales import (
    FulfillmentType,
    PriceTier,
    ReturnReason,
    SalesPaymentMethod,
)


# --- Customers ---
class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier = PriceTier.WHOLESALE
    credit_limit: Decimal = Field(default=Decimal("0"), ge=0)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)
    salesman_id: int | None = None


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0)
    salesman_id: int | None = None
    is_active: bool | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str | None
    address: str | None
    price_tier: PriceTier
    credit_limit: Decimal
    opening_balance: Decimal
    salesman_id: int | None
    is_active: bool


# --- Sales invoices ---
class SalesLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    # Optional alternative unit; when omitted the quantity is in the base unit.
    unit_id: int | None = None


class SalesInvoiceCreate(BaseModel):
    customer_id: int
    payment_method: SalesPaymentMethod
    # Warehouse pickup (استلام من المستودع) or driver delivery (توصيل).
    fulfillment: FulfillmentType = FulfillmentType.DELIVERY
    # Which configured taxes to apply (see /settings/tax-rates); empty = tax-free.
    # Several may be selected at once (e.g. VAT + a local municipality tax).
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[SalesLineIn] = Field(min_length=1)
    # Manager approval flag: lets an admin exceed the customer's credit limit.
    credit_override: bool = False


class SalesLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    batch_id: int
    batch_number: str
    # Warehouse this line was picked from — drives print grouping by warehouse.
    warehouse_id: int | None
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class SalesInvoiceTaxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tax_rate_id: int | None
    name: str
    rate: Decimal
    amount: Decimal


class SalesInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    salesman_id: int | None
    # Set only when every line shares one warehouse; NULL for mixed-warehouse invoices.
    warehouse_id: int | None
    invoice_date: date
    payment_method: SalesPaymentMethod
    fulfillment: FulfillmentType
    picked_up_at: datetime | None
    # NULL for cash/card invoices awaiting cashier collection; credit invoices are
    # confirmed immediately since they're settled later through the customer's account.
    payment_confirmed_at: datetime | None
    subtotal: Decimal
    # Sum of all applied taxes' amounts (see `taxes` for the per-tax breakdown).
    vat_amount: Decimal
    total: Decimal
    paid_amount: Decimal
    notes: str | None
    created_at: datetime
    # Total credited back via returns; net = total - returned_total.
    returned_total: Decimal = Decimal("0")
    lines: list[SalesLineOut]
    taxes: list[SalesInvoiceTaxOut]


# --- Returns ---
class ReturnLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_id: int | None = None


class SalesReturnCreate(BaseModel):
    invoice_id: int
    reason: ReturnReason
    notes: str | None = Field(default=None, max_length=300)
    lines: list[ReturnLineIn] = Field(min_length=1)


class ReturnLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    batch_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class SalesReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    customer_id: int
    reason: ReturnReason
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    notes: str | None
    created_at: datetime
    lines: list[ReturnLineOut]


# --- Customer payments & statement ---
class CustomerPaymentCreate(BaseModel):
    customer_id: int
    amount: Decimal = Field(gt=0)
    payment_date: date | None = None
    method: Literal["cash", "bank", "cheque"] = "cash"
    reference: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=300)


class CustomerPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    amount: Decimal
    payment_date: date
    method: str
    reference: str | None
    notes: str | None


class CustomerStatementOut(BaseModel):
    customer: CustomerOut
    opening_balance: Decimal
    total_invoices: Decimal
    total_returns: Decimal
    total_paid: Decimal
    # What the customer still owes us.
    balance: Decimal
    invoices: list[SalesInvoiceOut]
    returns: list[SalesReturnOut]
    payments: list[CustomerPaymentOut]


# --- Salesman commissions ---
class CommissionRow(BaseModel):
    salesman_id: int
    salesman_name: str
    total_sales: Decimal
    total_returns: Decimal
    # total_sales - total_returns, both excluding VAT.
    net_sales: Decimal
    commission_rate: Decimal
    commission_amount: Decimal


class CommissionReportOut(BaseModel):
    date_from: date | None
    date_to: date | None
    rows: list[CommissionRow]
    total_commission: Decimal
