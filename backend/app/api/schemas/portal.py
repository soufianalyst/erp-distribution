"""Pydantic schemas (DTOs) for the customer portal and portal orders.

Everything order-related is quantity-only by design: no price field exists in
this schema. Statement and invoice outputs reuse the sales module's DTOs
because those carry the customer's *own* financial data.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models.sales import CustomerOrderStatus, FulfillmentType


# --- Portal accounts (staff-facing: binding a customer to a login) ---
class PortalAccountCreate(BaseModel):
    """Create or replace the portal login bound to one customer."""

    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=72)


class PortalAccountUpdate(BaseModel):
    """Reset a portal account's password or toggle it active."""

    password: str | None = Field(default=None, min_length=8, max_length=72)
    is_active: bool | None = None


# --- Catalog: stock is identity, never a price ---
class CatalogItemOut(BaseModel):
    """One product at one warehouse: quantity only, no cost data whatsoever."""

    product_id: int
    product_name: str
    sku: str
    base_unit_name: str
    # NULL for a product that has no stock anywhere — it is listed greyed out
    # with a zero quantity so customers see it exists but is unavailable.
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    available_quantity: Decimal
    # Out-of-stock products are still listed (greyed out) so customers see that
    # the product exists rather than suspecting it vanished from the catalog.
    in_stock: bool


# --- Orders ---
class PortalLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)


class PortalOrderCreate(BaseModel):
    lines: list[PortalLineIn] = Field(min_length=1)
    # How the customer wants the goods: warehouse pickup or driver delivery.
    fulfillment: FulfillmentType = FulfillmentType.DELIVERY
    # NULL lets the sales team decide the warehouse at confirmation time.
    warehouse_id: int | None = None
    notes: str | None = Field(default=None, max_length=300)


class PortalOrderCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class PortalOrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str | None = None
    quantity: Decimal


class PortalOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    # Hydrated for the staff confirmation queue only (customer sees their own name).
    customer_name: str | None = None
    order_date: date
    status: CustomerOrderStatus
    fulfillment: FulfillmentType
    warehouse_id: int | None
    warehouse_name: str | None = None
    converted_invoice_id: int | None
    notes: str | None
    cancel_reason: str | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    total_quantity: Decimal = Decimal("0")
    lines: list[PortalOrderLineOut]

    @model_validator(mode="after")
    def _compute_total_quantity(self) -> "PortalOrderOut":
        # The CustomerOrder model's total_quantity is a read-only property; the
        # DTO owns its own value by summing the (already hydrated) lines.
        self.total_quantity = sum(
            (line.quantity for line in self.lines), Decimal("0")
        )
        return self


# --- Staff side ---
class PortalOrderConfirm(BaseModel):
    """Confirmation choices made by the sales team when converting an order."""

    # Payment method is decided at confirmation time, mirroring the quotation flow.
    payment_method: Literal["cash", "card", "credit"] = "credit"
    # Manager approval flag: lets an admin exceed the customer's credit limit.
    credit_override: bool = False


class PortalOrderLineBrief(BaseModel):
    """A pending order line for the staff list: product + quantity, no price."""

    product_id: int
    product_name: str
    quantity: Decimal


class PortalPendingOrderOut(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    order_date: date
    fulfillment: FulfillmentType
    warehouse_name: str | None
    notes: str | None
    total_quantity: Decimal
    lines: list[PortalOrderLineBrief]