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
    # What the customer will actually be charged. When it is below the computed
    # gross (goods + tax), the difference is recorded as a discount — this is how
    # the counter rounds 12,005 down to 12,000. Omit to charge the full amount.
    collectable_amount: Decimal | None = Field(default=None, ge=0)


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
    # Granted at issue time by lowering the collectable amount; applied after VAT.
    discount_amount: Decimal
    # What the customer owes: subtotal + vat_amount - discount_amount.
    total: Decimal
    paid_amount: Decimal
    notes: str | None
    created_at: datetime
    # Total credited back via returns; net = total - returned_total.
    returned_total: Decimal = Decimal("0")
    lines: list[SalesLineOut]
    taxes: list[SalesInvoiceTaxOut]


# --- Quotations ---
class QuotationLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_id: int | None = None


class SalesQuotationCreate(BaseModel):
    customer_id: int
    valid_until: date | None = None
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[QuotationLineIn] = Field(min_length=1)


class QuotationConvertIn(BaseModel):
    payment_method: SalesPaymentMethod
    fulfillment: FulfillmentType = FulfillmentType.DELIVERY
    # Manager approval flag: lets an admin exceed the customer's credit limit.
    credit_override: bool = False


class QuotationLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class QuotationTaxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tax_rate_id: int | None
    name: str
    rate: Decimal
    amount: Decimal


class SalesQuotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    salesman_id: int | None
    quote_date: date
    valid_until: date | None
    status: QuotationStatus
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    notes: str | None
    converted_invoice_id: int | None
    created_at: datetime
    lines: list[QuotationLineOut]
    taxes: list[QuotationTaxOut]


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
    # Share of the invoice's discount attributable to the returned goods; it was
    # never charged, so it is withheld from the credit rather than refunded.
    discount_amount: Decimal
    # What the customer is credited: subtotal + vat_amount - discount_amount.
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


# --- Field sync (offline salesman app) ---
class FieldCustomerIn(BaseModel):
    """A shop registered on the round, before the server has ever seen it."""

    client_uuid: str = Field(min_length=8, max_length=36)
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier = PriceTier.WHOLESALE


class FieldDocumentIn(BaseModel):
    """One visit's outcome: goods sold off the van, or an order to fulfil later."""

    client_uuid: str = Field(min_length=8, max_length=36)
    # Exactly one of these identifies the buyer: an existing customer, or one
    # created in this same batch and not yet holding a server id.
    customer_id: int | None = None
    customer_uuid: str | None = None
    kind: Literal["van_sale", "order"]
    payment_method: SalesPaymentMethod = SalesPaymentMethod.CASH
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[SalesLineIn] = Field(min_length=1)
    # Mirrors the counter's rounding-down of the collectable amount.
    collectable_amount: Decimal | None = Field(default=None, ge=0)


class FieldSyncIn(BaseModel):
    """A whole round uploaded at once. Safe to resend: every item is identified
    by its client_uuid, so anything already stored is reported, not repeated."""

    customers: list[FieldCustomerIn] = Field(default_factory=list)
    documents: list[FieldDocumentIn] = Field(default_factory=list)


class FieldSyncItemOut(BaseModel):
    client_uuid: str
    kind: Literal["customer", "van_sale", "order"]
    # created = stored now; duplicate = already stored by an earlier attempt;
    # failed = rejected, with the reason, and the field app keeps it queued.
    status: Literal["created", "duplicate", "failed"]
    server_id: int | None = None
    # The real invoice number, replacing the provisional field reference.
    message: str | None = None


class FieldSyncOut(BaseModel):
    created_count: int
    duplicate_count: int
    failed_count: int
    results: list[FieldSyncItemOut]


class FieldVanStockLineOut(BaseModel):
    product_id: int
    sku: str
    name: str
    base_unit_name: str
    quantity: Decimal


class FieldVanOut(BaseModel):
    """The salesman's own vehicle and what it is currently carrying.

    The field app caches this so it can check quantities while offline.
    """

    warehouse_id: int
    warehouse_name: str
    lines: list[FieldVanStockLineOut]
