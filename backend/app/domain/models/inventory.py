"""Inventory entities: warehouses, products, units of measure, and expiry-tracked batches."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # Smallest sellable unit (e.g. "حبة"); all stored quantities are in this unit.
    base_unit_name: Mapped[str] = mapped_column(String(30), nullable=False)
    wholesale_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    half_wholesale_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    retail_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_stock_level: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )
    # Home warehouse for sales: FEFO allocation and invoice printing use this automatically.
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    units: Mapped[list["ProductUnit"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    warehouse: Mapped["Warehouse | None"] = relationship()


class ProductUnit(Base):
    """Alternative unit of measure with a fixed conversion factor to the base unit."""

    __tablename__ = "product_units"
    __table_args__ = (
        UniqueConstraint("product_id", "name", name="uq_product_unit_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    # Base units contained in one of this unit (e.g. carton factor 12 = 12 pieces).
    factor: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

    product: Mapped[Product] = relationship(back_populates="units")


class ProductBatch(Base):
    """A received lot of a product; batch number and expiry date are always mandatory."""

    __tablename__ = "product_batches"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "warehouse_id", "batch_number", name="uq_batch_per_warehouse"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False, index=True
    )
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Quantity on hand, always in the product's base unit.
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )
    # Purchase cost per base unit (filled by the purchases module later).
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped[Product] = relationship()
    warehouse: Mapped[Warehouse] = relationship()
