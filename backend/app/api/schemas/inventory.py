"""Pydantic schemas (DTOs) for the inventory module."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.inventory import (
    AdjustmentStatus,
    StockAdjustmentReason,
    StocktakeStatus,
)


# --- Warehouses ---
class WarehouseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    # A vehicle carries stock on a sales round rather than standing still; the
    # salesman it is assigned to sells from it in the field app.
    is_vehicle: bool = False
    assigned_to_id: int | None = None


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    is_vehicle: bool | None = None
    # Explicit null unassigns the vehicle; omitting the field leaves it alone.
    assigned_to_id: int | None = None
    is_active: bool | None = None


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str | None
    is_vehicle: bool
    assigned_to_id: int | None
    # Resolved so the list can name the driver without a second call.
    assigned_to_name: str | None
    is_active: bool


# --- Products & units ---
class ProductUnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    factor: Decimal = Field(gt=0, description="عدد الوحدات الأساسية في هذه الوحدة")


class ProductUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    factor: Decimal


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    barcode: str | None = Field(default=None, min_length=1, max_length=50)
    name: str = Field(min_length=2, max_length=150)
    base_unit_name: str = Field(min_length=1, max_length=30)
    wholesale_price: Decimal = Field(ge=0)
    half_wholesale_price: Decimal = Field(ge=0)
    retail_price: Decimal = Field(ge=0)
    min_stock_level: Decimal = Field(default=Decimal("0"), ge=0)
    # Home warehouse for sales — every item belongs to exactly one.
    warehouse_id: int
    units: list[ProductUnitIn] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    barcode: str | None = Field(default=None, min_length=1, max_length=50)
    wholesale_price: Decimal | None = Field(default=None, ge=0)
    half_wholesale_price: Decimal | None = Field(default=None, ge=0)
    retail_price: Decimal | None = Field(default=None, ge=0)
    min_stock_level: Decimal | None = Field(default=None, ge=0)
    warehouse_id: int | None = None
    is_active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    barcode: str | None
    name: str
    base_unit_name: str
    wholesale_price: Decimal
    half_wholesale_price: Decimal
    retail_price: Decimal
    min_stock_level: Decimal
    warehouse_id: int | None
    is_active: bool
    units: list[ProductUnitOut]


# --- Stock operations ---
class StockReceiveRequest(BaseModel):
    product_id: int
    warehouse_id: int
    batch_number: str = Field(min_length=1, max_length=50)
    expiry_date: date
    quantity: Decimal = Field(gt=0)
    # Optional alternative unit; when omitted the quantity is in the base unit.
    unit_id: int | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0)


class StockTransferRequest(BaseModel):
    product_id: int
    from_warehouse_id: int
    to_warehouse_id: int
    quantity: Decimal = Field(gt=0)
    unit_id: int | None = None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    warehouse_id: int
    batch_number: str
    expiry_date: date
    quantity: Decimal
    unit_cost: Decimal | None
    received_at: datetime


class TransferLineOut(BaseModel):
    batch_number: str
    expiry_date: date
    quantity: Decimal


class StockLevelOut(BaseModel):
    product_id: int
    product_name: str
    base_unit_name: str
    warehouse_id: int
    warehouse_name: str
    total_quantity: Decimal


class NearExpiryOut(BaseModel):
    batch_id: int
    product_id: int
    product_name: str
    warehouse_id: int
    warehouse_name: str
    batch_number: str
    expiry_date: date
    quantity: Decimal
    days_remaining: int


# --- Stock adjustments (write-offs) ---
class StockAdjustmentLineIn(BaseModel):
    batch_id: int
    quantity: Decimal = Field(gt=0)
    unit_id: int | None = None


class StockAdjustmentCreate(BaseModel):
    reason: StockAdjustmentReason
    notes: str | None = Field(default=None, max_length=300)
    lines: list[StockAdjustmentLineIn] = Field(min_length=1)


class StockAdjustmentCancel(BaseModel):
    # Why the write-off is being cancelled; kept on the record for audit.
    cancel_reason: str | None = Field(default=None, max_length=300)


class StockAdjustmentLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    base_unit_name: str
    batch_id: int
    batch_number: str
    expiry_date: date
    warehouse_id: int
    warehouse_name: str
    quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal


class StockAdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reason: StockAdjustmentReason
    status: AdjustmentStatus
    total_quantity: Decimal
    total_cost: Decimal
    # False when no line's batch carried a purchase cost — total_cost is then 0
    # because the cost is unknown, not because the loss was worthless.
    cost_known: bool
    notes: str | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    lines: list[StockAdjustmentLineOut]


# --- Stocktakes (physical counts) ---
class StocktakeCreate(BaseModel):
    """Opens a count for one warehouse, snapshotting what the books expect."""

    warehouse_id: int
    count_date: date | None = None
    notes: str | None = Field(default=None, max_length=300)


class StocktakeCountIn(BaseModel):
    """One counted line. Zero is a valid count — the shelf was empty."""

    line_id: int
    counted_quantity: Decimal = Field(ge=0)


class StocktakeCountsIn(BaseModel):
    """Counts can be saved in batches as the aisles are walked."""

    counts: list[StocktakeCountIn] = Field(min_length=1)


class StocktakeCancelIn(BaseModel):
    cancel_reason: str | None = Field(default=None, max_length=300)


class StocktakeLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    sku: str
    base_unit_name: str
    batch_id: int
    batch_number: str
    expiry_date: date
    expected_quantity: Decimal
    # NULL until this batch has been counted.
    counted_quantity: Decimal | None
    # Counted minus expected: negative is a shortfall, positive a surplus.
    variance: Decimal
    unit_cost: Decimal
    variance_value: Decimal


class StocktakeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    warehouse_name: str
    count_date: date
    status: StocktakeStatus
    notes: str | None
    # Net value of the differences: positive = surplus, negative = shortfall.
    # Only meaningful once posted.
    net_value: Decimal
    line_count: int
    counted_line_count: int
    variance_line_count: int
    posted_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    lines: list[StocktakeLineOut]
