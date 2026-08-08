"""Schemas for the customer portal — the first surface outside the company.

Kept in their own module and never sharing a class with the internal API. Reuse is
how a field leaks: an internal schema gains `unit_cost` one day for a staff screen,
and it appears in a customer's response the same afternoon with nobody noticing.
Every portal response is written out explicitly here, field by field.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PortalLoginIn(BaseModel):
    login_id: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class PortalCustomerOut(BaseModel):
    """Who the portal thinks you are.

    No credit limit, no price tier, no salesman — none of it is the customer's
    business and all of it says something about how we treat them commercially.
    """

    model_config = ConfigDict(from_attributes=True)

    customer_id: int
    name: str
    phone: str | None
    address: str | None
    must_change_password: bool


class PortalTokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    customer: PortalCustomerOut


class PortalRefreshIn(BaseModel):
    refresh_token: str


class PortalPasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class PortalProfileUpdateIn(BaseModel):
    """The two things a customer may correct about themselves.

    Not the name — that is what the invoices and the ledger are filed under — and
    certainly not the credit limit or the salesman.
    """

    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)


# --- Past business: the customer's own invoices ---
# These carry money, unlike everything on the ordering side. What a customer was
# charged is theirs to see; what we pay for the goods is not, and `unit_cost` sits
# on the same row as `unit_price` in the model. Hence spelling the fields out.
#
# The `Invoice` prefix is what exempts them from the schema guard in
# test_portal_identity.py — an exemption by deliberate naming rather than accident.
class InvoiceLineOut(BaseModel):
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class InvoiceTaxOut(BaseModel):
    name: str
    rate: Decimal
    amount: Decimal


class InvoiceSummaryOut(BaseModel):
    id: int
    invoice_date: date
    total: Decimal
    paid_amount: Decimal
    # What is still owed on this invoice — the number a customer actually looks for.
    amount_due: Decimal
    payment_method: str
    is_settled: bool


class InvoiceDetailOut(InvoiceSummaryOut):
    subtotal: Decimal
    discount_amount: Decimal
    vat_amount: Decimal
    lines: list[InvoiceLineOut]
    taxes: list[InvoiceTaxOut]


class PortalReturnOut(BaseModel):
    id: int
    invoice_id: int | None
    date: datetime
    total: Decimal
    reason: str | None


class PortalPaymentOut(BaseModel):
    id: int
    payment_date: date
    amount: Decimal
    method: str
    reference: str | None


class PortalStatementOut(BaseModel):
    """The same movements the office sees, minus how we rate the customer."""

    opening_balance: Decimal
    total_invoices: Decimal
    total_returns: Decimal
    total_paid: Decimal
    # Positive means the customer owes us.
    balance: Decimal
    invoices: list[InvoiceSummaryOut]
    returns: list[PortalReturnOut]
    payments: list[PortalPaymentOut]


# --- Ordering: the catalogue and the request ---
class Availability(str, Enum):
    """How much to say about stock.

    A number would be a promise. Between the moment a shop reads it and the moment
    the office prices their order, a van can empty the shelf — and a customer who was
    shown "47 cartons" and receives 12 has been misled by us, not by circumstance. A
    band says the true thing: worth ordering, or not.
    """

    AVAILABLE = "available"  # متوفر
    LIMITED = "limited"  # كمية محدودة
    UNAVAILABLE = "unavailable"  # غير متوفر


class CatalogItemOut(BaseModel):
    """A line in the customer's catalogue. Note what is absent: every price.

    The product carries three of them — wholesale, half-wholesale, retail — and which
    one applies to this shop is a commercial decision the office makes when it prices
    the order. Showing any of them here would either be wrong or would disclose the
    tier.
    """

    product_id: int
    name: str
    unit: str
    availability: Availability


class PortalOrderLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)


class PortalOrderCreateIn(BaseModel):
    lines: list[PortalOrderLineIn] = Field(min_length=1)
    fulfillment: Literal["pickup", "delivery"] = "delivery"
    notes: str | None = Field(default=None, max_length=300)


class PortalOrderLineOut(BaseModel):
    product_id: int
    product_name: str
    unit: str
    quantity: Decimal
    # Re-checked when the order is read, not frozen at the time it was placed: what
    # matters to a waiting customer is whether it can be filled now.
    availability: Availability


class PortalOrderOut(BaseModel):
    id: int
    order_date: date
    status: Literal["pending", "confirmed", "invoiced", "cancelled"]
    fulfillment: Literal["pickup", "delivery"]
    notes: str | None
    decision_note: str | None
    # Set once the office has issued the invoice, so the customer can open it.
    invoice_id: int | None
    created_at: datetime
    lines: list[PortalOrderLineOut]


class PortalOrderCancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


# --- Office side: reviewing what customers have asked for ---
class StaffOrderOut(PortalOrderOut):
    """The same order, plus who sent it. Still no money: it has none until invoiced."""

    customer_id: int
    customer_name: str


class StaffOrderRejectIn(BaseModel):
    # Shown to the customer in their portal, so it is written for them.
    reason: str = Field(min_length=1, max_length=300)


class StaffOrderInvoiceIn(BaseModel):
    """What the office decides that the customer could not.

    Everything commercial about the sale is settled here rather than at order time:
    which taxes apply, how it is being paid, and — through `credit_override` — whether
    a customer over their limit is allowed through this once.
    """

    payment_method: Literal["cash", "card", "credit"]
    tax_rate_ids: list[int] = Field(default_factory=list)
    warehouse_id: int | None = None
    credit_override: bool = False
    notes: str | None = Field(default=None, max_length=300)


# --- Office side: managing who can get in ---
class CustomerLoginCreateIn(BaseModel):
    customer_id: int
    login_id: str = Field(min_length=3, max_length=120)
    # The office reads this out to the customer. There is no mail or SMS gateway
    # configured, so a self-service invite link would silently never arrive.
    temporary_password: str = Field(min_length=8, max_length=200)


class CustomerLoginOut(BaseModel):
    """What staff see about a portal account. Never the hash, not even truncated."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str | None = None
    login_id: str
    is_active: bool
    must_change_password: bool
    is_locked: bool = False
    last_login_at: datetime | None
    created_at: datetime


class CustomerLoginUpdateIn(BaseModel):
    is_active: bool | None = None
    # Setting a new temporary password also clears any lockout and forces a change
    # at next sign-in — the whole point of the office resetting it.
    temporary_password: str | None = Field(default=None, min_length=8, max_length=200)
