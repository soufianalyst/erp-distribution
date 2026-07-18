"""Pydantic schemas (DTOs) for the inventory module."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.inventory import StockAdjustmentReason


# --- Warehouses ---
class WarehouseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    location: str | None = Field(default=None, max_length=200)


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: str | None
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


class StockAdjustmentLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    batch_id: int
    warehouse_id: int
    quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal


class StockAdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reason: StockAdjustmentReason
    total_cost: Decimal
    notes: str | None
    created_at: datetime
    lines: list[StockAdjustmentLineOut]
