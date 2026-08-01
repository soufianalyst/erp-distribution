"""Inventory entities: warehouses, products, units of measure, and expiry-tracked batches."""

import enum
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StockAdjustmentReason(str, enum.Enum):
    EXPIRED = "expired"  # منتهي الصلاحية
    DAMAGED = "damaged"  # تالف
    SPOILED = "spoiled"  # فاسد
    COUNT_SHORTFALL = "count_shortfall"  # نقص عند الجرد
    OTHER = "other"  # أخرى


class AdjustmentStatus(str, enum.Enum):
    POSTED = "posted"  # مُثبّت — البضاعة خرجت من المخزون
    CANCELLED = "cancelled"  # ملغى — أُعيدت الكمية للمخزون وعُكس القيد


class StocktakeStatus(str, enum.Enum):
    COUNTING = "counting"  # قيد الجرد — تُدخل الكميات الفعلية، لا أثر بعد
    POSTED = "posted"  # مُثبّت — سُوّيت الفروقات على المخزون والقيود
    CANCELLED = "cancelled"  # ملغى — أُهمل الجرد دون أي تسوية


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
    # For barcode-scanner lookup; optional since not every product carries one.
    barcode: Mapped[str | None] = mapped_column(
        String(50), unique=True, index=True, nullable=True
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


class StockAdjustment(Base):
    """تعديل/إتلاف مخزون — write-off outside any sale or purchase return.

    Decrease-only: goods are always removed from stock (damaged, expired,
    spoiled, or a physical-count shortfall); one classification per document,
    mirroring sales/purchase returns.
    """

    __tablename__ = "stock_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reason: Mapped[StockAdjustmentReason] = mapped_column(
        Enum(StockAdjustmentReason, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # A write-off entered by mistake is cancelled, never deleted: the goods go back
    # to their batch, the journal entry is reversed, and the record stays on file.
    status: Mapped[AdjustmentStatus] = mapped_column(
        Enum(AdjustmentStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AdjustmentStatus.POSTED,
        server_default=AdjustmentStatus.POSTED.value,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    lines: Mapped[list["StockAdjustmentLine"]] = relationship(
        back_populates="adjustment", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> Decimal:
        """Total base-unit quantity written off across all lines."""
        return sum((line.quantity for line in self.lines), Decimal("0"))

    @property
    def cost_known(self) -> bool:
        """False when no line had a purchase cost on its batch, so `total_cost`
        is 0 because the cost is unknown — not because nothing of value was lost.
        """
        return any(line.unit_cost > 0 for line in self.lines)


class StockAdjustmentLine(Base):
    __tablename__ = "stock_adjustment_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    adjustment_id: Mapped[int] = mapped_column(
        ForeignKey("stock_adjustments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("product_batches.id"), nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    # Snapshot of the batch's cost per base unit; 0 when the batch has none
    # (e.g. stock received directly without a purchase invoice).
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    adjustment: Mapped[StockAdjustment] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    batch: Mapped[ProductBatch] = relationship()
    warehouse: Mapped[Warehouse] = relationship()

    # Read-through labels so the log and the printed report are self-describing
    # without the caller having to join products/batches/warehouses itself.
    @property
    def product_name(self) -> str:
        return self.product.name

    @property
    def base_unit_name(self) -> str:
        return self.product.base_unit_name

    @property
    def batch_number(self) -> str:
        return self.batch.batch_number

    @property
    def expiry_date(self) -> date:
        return self.batch.expiry_date

    @property
    def warehouse_name(self) -> str:
        return self.warehouse.name


class Stocktake(Base):
    """جرد مخزون — a physical count of one warehouse, reconciled against the books.

    Unlike a StockAdjustment (a decrease-only write-off with a known cause), a
    count discovers differences in *both* directions: shelves hold less than the
    system says (shrinkage, unrecorded damage, miscounts on receipt) or more
    (goods received but not entered, earlier over-issues). Opening a session
    snapshots what the system expects per batch; posting settles the differences
    against stock and the ledger in one transaction.
    """

    __tablename__ = "stocktakes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False, index=True
    )
    count_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[StocktakeStatus] = mapped_column(
        Enum(StocktakeStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=StocktakeStatus.COUNTING,
        server_default=StocktakeStatus.COUNTING.value,
    )
    notes: Mapped[str | None] = mapped_column(String(300))
    # Net value of the settled differences: positive = surplus found, negative =
    # shortfall. Only meaningful once posted.
    net_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    warehouse: Mapped[Warehouse] = relationship()
    lines: Mapped[list["StocktakeLine"]] = relationship(
        back_populates="stocktake", cascade="all, delete-orphan"
    )

    @property
    def warehouse_name(self) -> str:
        return self.warehouse.name

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def counted_line_count(self) -> int:
        """Lines the counter has actually entered a figure for."""
        return sum(1 for line in self.lines if line.counted_quantity is not None)

    @property
    def variance_line_count(self) -> int:
        """Counted lines that disagree with the books — the ones worth reviewing."""
        return sum(1 for line in self.lines if line.variance != Decimal("0"))


class StocktakeLine(Base):
    """One batch on a count sheet: what the books expect against what was found."""

    __tablename__ = "stocktake_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stocktake_id: Mapped[int] = mapped_column(
        ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("product_batches.id"), nullable=False
    )
    # Snapshotted so the sheet still reads correctly if the batch is edited later.
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # What the system held when the session was opened, in the base unit.
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    # NULL until someone counts this batch; 0 is a real count, not "not counted".
    counted_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    # Snapshot of the batch's cost per base unit; 0 when the batch has none.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    stocktake: Mapped[Stocktake] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    batch: Mapped[ProductBatch] = relationship()

    @property
    def variance(self) -> Decimal:
        """Found minus expected: negative is a shortfall, positive a surplus.

        Zero while uncounted, so an unvisited line never looks like a shortfall.
        """
        if self.counted_quantity is None:
            return Decimal("0")
        return self.counted_quantity - self.expected_quantity

    @property
    def variance_value(self) -> Decimal:
        """The variance valued at the batch's cost; 0 when the cost is unknown."""
        value = (self.variance * self.unit_cost).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        # A shortfall on a costless batch would otherwise render as "-0.00".
        return Decimal("0.00") if value == 0 else value

    # Read-through labels so the count sheet is self-describing. Batch number and
    # expiry are columns here rather than read-throughs: they are snapshotted so
    # the sheet still reads correctly if the batch is edited after counting.
    @property
    def product_name(self) -> str:
        return self.product.name

    @property
    def sku(self) -> str:
        return self.product.sku

    @property
    def base_unit_name(self) -> str:
        return self.product.base_unit_name
