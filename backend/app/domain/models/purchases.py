"""Purchasing entities: suppliers, purchase invoices with lines, and supplier payments."""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PurchasePaymentMethod(str, enum.Enum):
    CASH = "cash"  # نقدي — يُسدد من الصندوق
    CARD = "card"  # بطاقة — يُسدد من الصندوق
    CREDIT = "credit"  # آجل — يضاف إلى رصيد المورد


class PurchaseReturnReason(str, enum.Enum):
    """Record-keeping only — unlike sales returns, the goods always leave the
    warehouse back to the supplier regardless of reason."""

    DEFECTIVE = "defective"  # تالف / معيب
    WRONG_ITEM = "wrong_item"  # صنف خاطئ
    EXCESS = "excess"  # فائض عن الحاجة
    OTHER = "other"  # أخرى


class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"  # مسودة — قيد التحضير، لم تُرسل للمورد بعد
    SENT = "sent"  # مرسل للمورد — بانتظار التوريد
    PARTIALLY_RECEIVED = "partially_received"  # مستلم جزئياً
    RECEIVED = "received"  # مستلم بالكامل
    CANCELLED = "cancelled"  # ملغى


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(200))
    # Balance owed to the supplier before this system went live.
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # Days between placing an order with this supplier and the goods arriving.
    # NULL falls back to the company default. Kept per supplier because in food
    # distribution the spread is the whole point: a local dairy delivers tomorrow
    # and imported rice takes a month, and one averaged figure would order the
    # dairy far too early and the rice far too late.
    lead_time_days: Mapped[int | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PurchaseOrder(Base):
    """طلب شراء — what we intend to buy from a supplier, before anything arrives.

    Carries no stock or accounting effect on its own. Goods enter the warehouse
    only when a delivery is received, which raises a normal purchase invoice.
    A single order may be received over several deliveries.
    """

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    # Where the goods are expected to land; each receipt can override it.
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        Enum(PurchaseOrderStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT,
        server_default=PurchaseOrderStatus.DRAFT.value,
    )
    # Expected value at the prices agreed when ordering; the actual cost is
    # whatever the receipts end up recording.
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    # Deliveries raised against this order. Viewonly because the link is owned by
    # the invoice side (purchase_invoices.purchase_order_id) — an order never
    # creates or detaches invoices by itself.
    received_invoices: Mapped[list["PurchaseInvoice"]] = relationship(
        "PurchaseInvoice", viewonly=True, order_by="PurchaseInvoice.id"
    )

    @property
    def is_fully_received(self) -> bool:
        """True once every line has been delivered in full."""
        return all(line.received_quantity >= line.quantity for line in self.lines)

    @property
    def received_invoice_ids(self) -> list[int]:
        """Invoices raised by receiving deliveries against this order."""
        return [invoice.id for invoice in self.received_invoices]


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    # Ordered amount in the product's base unit, at the expected cost per base
    # unit. Batch number and expiry are unknown until the goods actually arrive,
    # so they live on the receipt, not here.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0"), server_default="0"
    )
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")

    @property
    def outstanding_quantity(self) -> Decimal:
        """Still to be delivered on this line."""
        return max(self.quantity - self.received_quantity, Decimal("0"))


class PurchaseInvoice(Base):
    __tablename__ = "purchase_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    # The supplier's own paper invoice reference, if any.
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(50))
    # Set when this invoice came from receiving a purchase order, so an order
    # can show every delivery raised against it.
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=True, index=True
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[PurchasePaymentMethod] = mapped_column(
        Enum(PurchasePaymentMethod, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    vat_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # Cashier gate: cash/card invoices sit here until the cashier actually pays
    # the supplier out of the register; credit invoices are confirmed immediately
    # (settled later via the existing supplier-statement/payment flow).
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # Reference from the system this was migrated from; unique so a repeated
    # import is refused instead of billing the supplier twice. Mirrors
    # SalesInvoice.legacy_ref.
    legacy_ref: Mapped[str | None] = mapped_column(
        String(60), unique=True, nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["PurchaseInvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    taxes: Mapped[list["PurchaseInvoiceTax"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class PurchaseInvoiceLine(Base):
    __tablename__ = "purchase_invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("product_batches.id"), nullable=False
    )
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Stored in the product's base unit with the cost per base unit.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    invoice: Mapped[PurchaseInvoice] = relationship(back_populates="lines")


class PurchaseInvoiceTax(Base):
    """One applied tax on a purchase invoice — an invoice may carry several at once.

    Name/rate/amount are snapshotted at invoice time so an invoice keeps showing
    exactly what was charged even if the TaxRate is later edited or deleted.
    """

    __tablename__ = "purchase_invoice_taxes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tax_rate_id: Mapped[int | None] = mapped_column(
        ForeignKey("tax_rates.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    invoice: Mapped[PurchaseInvoice] = relationship(back_populates="taxes")


class PurchaseReturn(Base):
    """مرتجع مشتريات — goods sent back to the supplier; always leaves the warehouse."""

    __tablename__ = "purchase_returns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_invoices.id"), nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    reason: Mapped[PurchaseReturnReason] = mapped_column(
        Enum(PurchaseReturnReason, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    lines: Mapped[list["PurchaseReturnLine"]] = relationship(
        back_populates="purchase_return", cascade="all, delete-orphan"
    )


class PurchaseReturnLine(Base):
    __tablename__ = "purchase_return_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_returns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("product_batches.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    purchase_return: Mapped[PurchaseReturn] = relationship(back_populates="lines")


class SupplierPayment(Base):
    """سند صرف — a payment made to a supplier against outstanding balance."""

    __tablename__ = "supplier_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(50))
    # Reference from the system this was migrated from; unique so a repeated
    # import is refused instead of billing the supplier twice. Mirrors
    # SalesInvoice.legacy_ref.
    legacy_ref: Mapped[str | None] = mapped_column(
        String(60), unique=True, nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    supplier: Mapped[Supplier] = relationship()
