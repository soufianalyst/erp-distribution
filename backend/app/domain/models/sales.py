"""Sales entities: customers, FEFO-allocated sales invoices, returns, and receipts."""

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


class PriceTier(str, enum.Enum):
    WHOLESALE = "wholesale"  # جملة
    HALF_WHOLESALE = "half_wholesale"  # نصف جملة
    RETAIL = "retail"  # تجزئة


class SalesPaymentMethod(str, enum.Enum):
    CASH = "cash"  # نقدي
    CREDIT = "credit"  # آجل — يخضع للحد الائتماني


class FulfillmentType(str, enum.Enum):
    PICKUP = "pickup"  # استلام من المستودع (عند محلنا)
    DELIVERY = "delivery"  # توصيل إلى العميل عبر رحلات التوزيع


class ReturnReason(str, enum.Enum):
    RESELLABLE = "resellable"  # صالح لإعادة البيع — يعود للمخزون
    DAMAGED_CUSTOMER = "damaged_customer"  # تالف بسبب العميل
    DAMAGED_TRANSPORT = "damaged_transport"  # تالف بسبب النقل


class TaxType(Base):
    """نوع ضريبة — configurable tax types (VAT, Municipal, etc.)."""

    __tablename__ = "tax_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    accounting_code: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(200))
    price_tier: Mapped[PriceTier] = mapped_column(
        Enum(PriceTier, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PriceTier.WHOLESALE,
    )
    # Maximum outstanding credit; exceeding it requires manager approval.
    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # The sales representative responsible for this customer.
    salesman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    # Exempt from all taxes (ex: government entities, export).
    tax_exempt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesInvoice(Base):
    __tablename__ = "sales_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    salesman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id"), nullable=True
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[SalesPaymentMethod] = mapped_column(
        Enum(SalesPaymentMethod, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # How the customer receives the goods: warehouse pickup or driver delivery.
    fulfillment: Mapped[FulfillmentType] = mapped_column(
        Enum(FulfillmentType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=FulfillmentType.DELIVERY,
        server_default=FulfillmentType.DELIVERY.value,
    )
    # Set when a pickup invoice is handed over at the counter.
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["SalesInvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    tax_lines: Mapped[list["InvoiceTaxLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class SalesInvoiceLine(Base):
    """One FEFO allocation: an input line may split into several lines, one per batch."""

    __tablename__ = "sales_invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("product_batches.id"), nullable=False
    )
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    # Base-unit quantity, sell price per base unit, and cost snapshot for profit reports.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")


class InvoiceTaxLine(Base):
    """سطر ضريبة الفاتورة — each tax applied to an invoice."""

    __tablename__ = "invoice_tax_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tax_type_id: Mapped[int] = mapped_column(
        ForeignKey("tax_types.id"), nullable=False
    )
    # Snapshot of rate at time of invoice (tax rates may change later).
    rate_at_time: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    invoice: Mapped[SalesInvoice] = relationship(back_populates="tax_lines")
    tax_type: Mapped["TaxType"] = relationship()


class SalesReturn(Base):
    """مرتجع مبيعات — one classification per document; mixed reasons need separate documents."""

    __tablename__ = "sales_returns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sales_invoices.id"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    reason: Mapped[ReturnReason] = mapped_column(
        Enum(ReturnReason, values_callable=lambda e: [m.value for m in e]),
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

    lines: Mapped[list["SalesReturnLine"]] = relationship(
        back_populates="sales_return", cascade="all, delete-orphan"
    )
    tax_lines: Mapped[list["ReturnTaxLine"]] = relationship(
        back_populates="sales_return", cascade="all, delete-orphan"
    )


class SalesReturnLine(Base):
    __tablename__ = "sales_return_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("product_batches.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    sales_return: Mapped[SalesReturn] = relationship(back_populates="lines")


class ReturnTaxLine(Base):
    """سطر ضريبة المرتجع — each tax applied to a sales return."""

    __tablename__ = "return_tax_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("sales_returns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tax_type_id: Mapped[int] = mapped_column(
        ForeignKey("tax_types.id"), nullable=False
    )
    rate_at_time: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    sales_return: Mapped[SalesReturn] = relationship(back_populates="tax_lines")
    tax_type: Mapped["TaxType"] = relationship()


class QuotationStatus(str, enum.Enum):
    DRAFT = "draft"  # مسودة — قابلة للتعديل والحذف
    SENT = "sent"  # مرسل للعميل — قابل للتحويل لفاتورة
    ACCEPTED = "accepted"  # مقبول من العميل
    REJECTED = "rejected"  # مرفوض من العميل
    CONVERTED = "converted"  # تم تحويله لفاتورة مبيعات


class SalesQuotation(Base):
    """عرض أسعار مبيعات —预备或正式报价给客户，可转换为发票。"""

    __tablename__ = "sales_quotations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    salesman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    quotation_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[QuotationStatus] = mapped_column(
        Enum(QuotationStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=QuotationStatus.DRAFT,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Links to the invoice created after conversion; NULL until converted.
    converted_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_invoices.id")
    )

    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["SalesQuotationLine"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )
    tax_lines: Mapped[list["QuotationTaxLine"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )
    converted_invoice: Mapped[SalesInvoice | None] = relationship()


class SalesQuotationLine(Base):
    """سطر في عرض الأسعار — product + quantity + unit price (no batch yet)."""

    __tablename__ = "sales_quotation_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("sales_quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    quotation: Mapped[SalesQuotation] = relationship(back_populates="lines")


class QuotationTaxLine(Base):
    """سطر ضريبة عرض الأسعار — each tax applied to a quotation."""

    __tablename__ = "quotation_tax_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("sales_quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tax_type_id: Mapped[int] = mapped_column(
        ForeignKey("tax_types.id"), nullable=False
    )
    rate_at_time: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    quotation: Mapped[SalesQuotation] = relationship(back_populates="tax_lines")
    tax_type: Mapped["TaxType"] = relationship()


class CustomerPayment(Base):
    """سند قبض — a collection from a customer against outstanding balance."""

    __tablename__ = "customer_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CashierPayment(Base):
    """دفعة صندوق — individual payment collection record for cashier reconciliation.

    Polymorphic: reference_type can be 'sales_invoice', 'purchase_invoice', or 'expense'.
    """

    __tablename__ = "cashier_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reference_id: Mapped[int] = mapped_column(nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
