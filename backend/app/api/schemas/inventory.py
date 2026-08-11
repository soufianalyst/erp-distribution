"""Pydantic schemas (DTOs) for the inventory module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

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


class ProductOfferCreate(BaseModel):
    product_id: int
    discount_percent: Decimal = Field(gt=0, lt=100)
    starts_on: date
    ends_on: date
    note: str | None = Field(default=None, max_length=200)


class ProductOfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str | None = None
    discount_percent: Decimal
    starts_on: date
    ends_on: date
    note: str | None
    is_active: bool
    # Whether it applies today — a window can be set for next week, or be over.
    is_live: bool = False
    # What the discount does to the wholesale margin, so the office is never
    # discounting below cost by accident. Selling under cost can still beat a
    # write-off; it should just be a decision rather than a surprise.
    wholesale_price: Decimal | None = None
    offer_price: Decimal | None = None
    unit_cost: Decimal | None = None
    below_cost: bool = False


# --- Markdown plan ---
class MarkdownBuyerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: int
    name: str
    phone: str | None
    last_bought: date
    units: Decimal


class MarkdownProposalOut(BaseModel):
    """One batch, and the single thing worth doing about it."""

    model_config = ConfigDict(from_attributes=True)

    batch_id: int
    product_id: int
    sku: str
    name: str
    batch_number: str
    warehouse_name: str
    expiry_date: date
    days_left: int
    quantity: Decimal
    unit_cost: Decimal | None
    stock_value: Decimal
    daily_rate: Decimal
    # Units still on the shelf on the expiry date at the current rate of sale.
    surplus: Decimal
    surplus_value: Decimal
    # leave = clears on its own · markdown = a discount closes the gap ·
    # push = has past buyers, so it is a call not a price ·
    # write_off = no demand and no buyer; no discount reaches zero.
    action: Literal["leave", "markdown", "push", "write_off"]
    discount_percent: Decimal | None
    price_before: Decimal | None
    price_now: Decimal | None
    recovery_value: Decimal
    reason: str
    buyers: list[MarkdownBuyerOut]
    active_offer_percent: Decimal | None


class MarkdownPlanOut(BaseModel):
    horizon_days: int
    # The elasticity behind every proposed depth, and whether it was learned from
    # past discounts or assumed. A buyer deserves to know which.
    elasticity: Decimal
    elasticity_source: Literal["measured", "assumed"]
    elasticity_observations: int
    stock_at_risk: Decimal
    surplus_value: Decimal
    recoverable_value: Decimal
    write_off_value: Decimal
    items: list[MarkdownProposalOut]


class MarkdownApplyIn(BaseModel):
    """Turn chosen proposals into real offers.

    Batch ids rather than a blanket "apply everything": the plan is advice, and a
    human decides which lines they are willing to discount. Sending the ids back
    also means a plan read ten minutes ago cannot silently discount a batch that
    has since sold out.
    """

    batch_ids: list[int] = Field(min_length=1, max_length=200)


class MarkdownApplyOut(BaseModel):
    created: int
    skipped: int
    # Why each skipped batch was skipped, so nothing disappears without a word.
    notes: list[str]
