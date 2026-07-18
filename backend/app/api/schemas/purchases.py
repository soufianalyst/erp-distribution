"""Pydantic schemas (DTOs) for the purchases module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.purchases import PurchasePaymentMethod


# --- Suppliers ---
class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str | None
    address: str | None
    opening_balance: Decimal
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
    total_paid: Decimal
    # What we still owe the supplier.
    balance: Decimal
    invoices: list[PurchaseInvoiceOut]
    payments: list[SupplierPaymentOut]
