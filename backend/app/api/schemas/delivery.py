"""Pydantic schemas (DTOs) for the delivery module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.delivery import StopStatus, TripStatus
from app.domain.models.sales import FulfillmentType, SalesPaymentMethod


class TripCreate(BaseModel):
    trip_date: date | None = None
    driver_name: str = Field(min_length=2, max_length=100)
    vehicle: str | None = Field(default=None, max_length=100)
    warehouse_id: int
    notes: str | None = Field(default=None, max_length=300)


class StopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    sequence: int
    status: StopStatus
    notes: str | None
    delivered_at: datetime | None


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trip_date: date
    driver_name: str
    vehicle: str | None
    warehouse_id: int
    status: TripStatus
    notes: str | None
    created_at: datetime
    stops: list[StopOut]


class AddInvoiceRequest(BaseModel):
    invoice_id: int


class StopStatusUpdate(BaseModel):
    status: Literal["delivered", "failed"]
    notes: str | None = Field(default=None, max_length=300)


class PickingLineOut(BaseModel):
    product_id: int
    product_name: str
    base_unit_name: str
    batch_number: str
    quantity: Decimal


class PickingListOut(BaseModel):
    trip: TripOut
    lines: list[PickingLineOut]
    invoice_count: int
    total_quantity: Decimal


class DeliveryItemOut(BaseModel):
    product_name: str
    quantity: Decimal
    unit: str


class DeliveryInvoiceSummary(BaseModel):
    """Invoice view for warehouse/driver staff: goods and destination, never prices."""

    id: int
    invoice_date: date
    customer_name: str
    # NULL when the invoice's items come from more than one warehouse.
    warehouse_id: int | None
    fulfillment: FulfillmentType
    payment_method: SalesPaymentMethod
    picked_up_at: datetime | None
    items: list[DeliveryItemOut]


class PrepLineOut(BaseModel):
    product_name: str
    batch_number: str
    quantity: Decimal
    unit: str
    # Which warehouse to pick this line from — lines are grouped by this for printing.
    warehouse_id: int | None


class InvoicePrepOut(BaseModel):
    """Batch-level preparation sheet for one invoice — items only, never prices."""

    invoice_id: int
    invoice_date: date
    customer_name: str
    warehouse_id: int | None
    fulfillment: FulfillmentType
    lines: list[PrepLineOut]
