"""Pydantic schemas (DTOs) for the sales module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.sales import (
    FulfillmentType,
    PriceTier,
    QuotationStatus,
    ReturnReason,
    SalesPaymentMethod,
)


# --- Tax Types ---
class TaxTypeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    rate: Decimal = Field(ge=0, le=1)
    is_active: bool = True
    accounting_code: str = Field(min_length=2, max_length=20)


class TaxTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    rate: Decimal | None = Field(default=None, ge=0, le=1)
    is_active: bool | None = None
    accounting_code: str | None = Field(default=None, min_length=2, max_length=20)


class TaxTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rate: Decimal
    is_active: bool
    accounting_code: str
    created_at: datetime


class TaxLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tax_type_id: int
    rate_at_time: Decimal
    amount: Decimal
    tax_type: TaxTypeOut | None = None


# --- Customers ---
class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier = PriceTier.WHOLESALE
    credit_limit: Decimal = Field(default=Decimal("0"), ge=0)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)
    salesman_id: int | None = None
    tax_exempt: bool = False


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0)
    salesman_id: int | None = None
    tax_exempt: bool | None = None
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
    tax_exempt: bool
    is_active: bool


# --- Sales invoices ---
class SalesLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    # Optional alternative unit; when omitted the quantity is in the base unit.
    unit_id: int | None = None


class SalesInvoiceCreate(BaseModel):
    customer_id: int
    warehouse_id: int | None = None
    payment_method: SalesPaymentMethod
    # Warehouse pickup (استلام من المستودع) or driver delivery (توصيل).
    fulfillment: FulfillmentType = FulfillmentType.DELIVERY
    # List of tax type IDs to apply; empty = no tax.
    tax_type_ids: list[int] = []
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
    warehouse_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class SalesInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    salesman_id: int | None
    warehouse_id: int | None
    invoice_date: date
    payment_method: SalesPaymentMethod
    fulfillment: FulfillmentType
    picked_up_at: datetime | None
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    paid_amount: Decimal
    notes: str | None
    created_at: datetime
    # Total credited back via returns; net = total - returned_total.
    returned_total: Decimal = Decimal("0")
    lines: list[SalesLineOut]
    tax_lines: list[TaxLineOut] = []


# --- Cashier ---
class CashierInvoiceSummary(BaseModel):
    """Pending item view for the cashier: receivable (sales) or payable (purchase/expense)."""

    model_config = ConfigDict(from_attributes=True)

    type: str  # "sales", "purchase", or "expense"
    type_label: str  # Arabic label
    account_label: str  # "ذمم العملاء" or "ذمم الموردين"
    id: int
    date: str
    party_name: str
    payment_method: str
    total: Decimal
    paid_amount: Decimal
    remaining: Decimal


class PaymentIn(BaseModel):
    """Amount entered by the cashier when collecting payment."""

    reference_type: str = Field(description="نوع المصدر: sales, purchase, expense")
    reference_id: int = Field(gt=0, description="رقم الفاتورة أو المصروف")
    amount: float = Field(gt=0, description="المبلغ المحصّل")


class DailyPaymentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference_type: str
    reference_id: int
    amount: Decimal
    payment_method: str


class DailySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: str
    grand_total: Decimal
    total_count: int
    by_method: dict[str, Decimal]
    by_type: dict[str, dict]
    payments: list[DailyPaymentDetail]


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
    tax_lines: list[TaxLineOut] = []


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


# --- Quotations ---
class QuotationLineIn(BaseModel):
    product_id: int
    product_name: str = Field(max_length=200)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    unit_id: int | None = None


class QuotationCreate(BaseModel):
    customer_id: int
    warehouse_id: int
    valid_until: date | None = None
    notes: str | None = Field(default=None, max_length=300)
    tax_type_ids: list[int] = []
    lines: list[QuotationLineIn] = Field(min_length=1)


class QuotationLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class QuotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    salesman_id: int | None
    warehouse_id: int
    quotation_date: date
    valid_until: date | None
    status: QuotationStatus
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    notes: str | None
    created_at: datetime
    converted_invoice_id: int | None
    lines: list[QuotationLineOut]
    tax_lines: list[TaxLineOut] = []
