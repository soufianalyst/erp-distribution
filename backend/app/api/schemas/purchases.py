"""Pydantic schemas (DTOs) for the purchases module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.purchases import (
    PurchaseOrderStatus,
    PurchasePaymentMethod,
    PurchaseReturnReason,
)


# --- Suppliers ---
class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)
    # Days from order to delivery. Empty falls back to the company default.
    lead_time_days: int | None = Field(default=None, ge=1, le=180)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    lead_time_days: int | None = Field(default=None, ge=1, le=180)
    is_active: bool | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str | None
    address: str | None
    opening_balance: Decimal
    lead_time_days: int | None
    is_active: bool


# --- Purchase invoices ---
class PurchaseLineIn(BaseModel):
    product_id: int
    batch_number: str = Field(min_length=1, max_length=50)
    expiry_date: date
    quantity: Decimal = Field(gt=0)
    # Optional alternative unit; unit_cost is per the unit actually used.
    unit_id: int | None = None
    unit_cost: Decimal = Field(ge=0)


class PurchaseInvoiceCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    payment_method: PurchasePaymentMethod
    supplier_invoice_number: str | None = Field(default=None, max_length=50)
    invoice_date: date | None = None
    shipping_cost: Decimal = Field(default=Decimal("0"), ge=0)
    # Which configured taxes to apply (see /settings/tax-rates); empty = tax-free.
    # Several may be selected at once (e.g. VAT + a local tax).
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[PurchaseLineIn] = Field(min_length=1)


class PurchaseLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    # Named on the line, so no consumer needs the product catalogue to read it.
    product_name: str
    batch_id: int
    batch_number: str
    expiry_date: date
    quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal


class PurchaseInvoiceTaxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tax_rate_id: int | None
    name: str
    rate: Decimal
    amount: Decimal


class PurchaseInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    warehouse_id: int
    supplier_invoice_number: str | None
    invoice_date: date
    payment_method: PurchasePaymentMethod
    subtotal: Decimal
    shipping_cost: Decimal
    # Sum of all applied taxes' amounts (see `taxes` for the per-tax breakdown).
    vat_amount: Decimal
    total: Decimal
    paid_amount: Decimal
    # NULL for cash/card invoices awaiting cashier disbursement; credit invoices
    # are confirmed immediately since they settle later via the supplier account.
    payment_confirmed_at: datetime | None
    notes: str | None
    created_at: datetime
    lines: list[PurchaseLineOut]
    taxes: list[PurchaseInvoiceTaxOut]


# --- Purchase orders ---
class PurchaseOrderLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    # Optional alternative unit; unit_cost is per the unit actually used.
    unit_id: int | None = None
    unit_cost: Decimal = Field(ge=0)


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    expected_date: date | None = None
    notes: str | None = Field(default=None, max_length=300)
    lines: list[PurchaseOrderLineIn] = Field(min_length=1)


class PurchaseOrderUpdate(BaseModel):
    """Only a draft can be edited; sending or receiving freezes the order."""

    supplier_id: int
    warehouse_id: int
    expected_date: date | None = None
    notes: str | None = Field(default=None, max_length=300)
    lines: list[PurchaseOrderLineIn] = Field(min_length=1)


class PurchaseOrderCancelIn(BaseModel):
    cancel_reason: str | None = Field(default=None, max_length=300)


class PurchaseReceiptLineIn(BaseModel):
    """One delivered line. Batch and expiry are only known now, on arrival.

    Quantity and cost are in the product's base unit, matching how the order
    line stores them — no unit conversion happens on receipt.
    """

    order_line_id: int
    quantity: Decimal = Field(gt=0)
    batch_number: str = Field(min_length=1, max_length=50)
    expiry_date: date
    # Actual cost if it differs from what was ordered; omit to keep the ordered cost.
    unit_cost: Decimal | None = Field(default=None, ge=0)


class PurchaseOrderReceiveIn(BaseModel):
    """Receiving a delivery raises a normal purchase invoice for what arrived."""

    payment_method: PurchasePaymentMethod
    # Defaults to the order's warehouse when omitted.
    warehouse_id: int | None = None
    supplier_invoice_number: str | None = Field(default=None, max_length=50)
    invoice_date: date | None = None
    shipping_cost: Decimal = Field(default=Decimal("0"), ge=0)
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[PurchaseReceiptLineIn] = Field(min_length=1)


class PurchaseOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    # Named on the line, so no consumer needs the product catalogue to read it.
    product_name: str
    # All quantities are in the product's base unit.
    quantity: Decimal
    received_quantity: Decimal
    # Still to be delivered: quantity - received_quantity.
    outstanding_quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    warehouse_id: int
    order_date: date
    expected_date: date | None
    status: PurchaseOrderStatus
    # Expected value at the ordered prices; receipts record the actual cost.
    subtotal: Decimal
    notes: str | None
    sent_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    lines: list[PurchaseOrderLineOut]
    # Invoice ids raised by receiving deliveries against this order.
    received_invoice_ids: list[int] = Field(default_factory=list)


class ReorderSuggestionOut(BaseModel):
    """A product worth reordering: out of stock, or at/below its minimum level."""

    product_id: int
    sku: str
    name: str
    base_unit_name: str
    current_stock: Decimal
    min_stock_level: Decimal
    # How far below the minimum it sits; 0 when exactly at the threshold.
    shortfall: Decimal
    out_of_stock: bool
    # Most recent purchase cost seen for this product, to pre-fill an order line.
    last_unit_cost: Decimal | None

    # --- Why this product is on the list, and what to do about it ---
    # The level at which it should be reordered. Computed from demand where there is
    # enough history; the hand-entered `min_stock_level` otherwise.
    reorder_point: Decimal
    # How much to order: enough to last until the next review, trimmed to what will
    # sell before it expires.
    suggested_quantity: Decimal
    # False means `reorder_point` is the typed minimum standing in for a calculation
    # that could not honestly be made.
    computed: bool
    # Arabic one-liner explaining the figures, shown beside them. A suggestion a
    # buyer cannot interrogate is one they learn to ignore.
    basis: str
    capped_by_expiry: bool
    daily_rate: Decimal
    lead_time_days: int


# --- Purchase returns ---
class PurchaseReturnLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_id: int | None = None


class PurchaseReturnCreate(BaseModel):
    invoice_id: int
    reason: PurchaseReturnReason
    notes: str | None = Field(default=None, max_length=300)
    lines: list[PurchaseReturnLineIn] = Field(min_length=1)


class PurchaseReturnLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    # Named on the line, so no consumer needs the product catalogue to read it.
    product_name: str
    batch_id: int
    quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal


class PurchaseReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    supplier_id: int
    reason: PurchaseReturnReason
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    notes: str | None
    created_at: datetime
    lines: list[PurchaseReturnLineOut]


# --- Supplier payments & statement ---
class SupplierPaymentCreate(BaseModel):
    supplier_id: int
    amount: Decimal = Field(gt=0)
    payment_date: date | None = None
    method: Literal["cash", "bank", "cheque"] = "cash"
    reference: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=300)


class SupplierPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    amount: Decimal
    payment_date: date
    method: str
    reference: str | None
    notes: str | None


class SupplierStatementOut(BaseModel):
    supplier: SupplierOut
    opening_balance: Decimal
    total_invoices: Decimal
    total_returns: Decimal
    total_paid: Decimal
    # What we still owe the supplier.
    balance: Decimal
    invoices: list[PurchaseInvoiceOut]
    returns: list[PurchaseReturnOut]
    payments: list[SupplierPaymentOut]
