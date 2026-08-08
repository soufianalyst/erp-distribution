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
    Integer,
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
    CARD = "card"  # بطاقة
    CREDIT = "credit"  # آجل — يخضع للحد الائتماني


class FulfillmentType(str, enum.Enum):
    PICKUP = "pickup"  # استلام من المستودع (عند محلنا)
    DELIVERY = "delivery"  # توصيل إلى العميل عبر رحلات التوزيع


class ReturnReason(str, enum.Enum):
    RESELLABLE = "resellable"  # صالح لإعادة البيع — يعود للمخزون
    DAMAGED_CUSTOMER = "damaged_customer"  # تالف بسبب العميل
    DAMAGED_TRANSPORT = "damaged_transport"  # تالف بسبب النقل


class ReturnStatus(str, enum.Enum):
    """A credit note stands, or it was entered by mistake and reversed.

    Cancelled rather than deleted: the mistake itself is part of the record, and a
    credit note that simply vanishes leaves a customer statement nobody can explain.
    """

    POSTED = "posted"
    CANCELLED = "cancelled"


class QuotationStatus(str, enum.Enum):
    DRAFT = "draft"  # مسودة — بانتظار قرار العميل
    CONVERTED = "converted"  # تم تحويلها إلى فاتورة
    CANCELLED = "cancelled"  # ملغاة


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    # Identifier minted by the field app before this record ever reaches the
    # server. Unique, so replaying a sync batch over a flaky connection returns
    # the record already created instead of duplicating it. NULL for anything
    # created online.
    client_uuid: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True
    )
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
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesInvoice(Base):
    __tablename__ = "sales_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Identifier minted by the field app before this record ever reaches the
    # server. Unique, so replaying a sync batch over a flaky connection returns
    # the record already created instead of duplicating it. NULL for anything
    # created online.
    client_uuid: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    salesman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    # Set automatically from the lines' products. NULL when the invoice spans several
    # warehouses (each line still carries its own warehouse_id for print grouping).
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
    # Cashier gate: cash/card invoices sit here until the cashier actually
    # collects the money, only then are they released to delivery/pickup.
    # Credit invoices are confirmed immediately (collected later via accounts).
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Granted when the collectable amount is adjusted down at issue time (e.g.
    # rounding 12,005 to 12,000). Applied after VAT, so it never changes the
    # taxable base — `total` is what the customer actually owes.
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
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
    taxes: Mapped[list["SalesInvoiceTax"]] = relationship(
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
    # Snapshot of the product's warehouse at sale time — drives print grouping for
    # delivery/pickup regardless of any later change to the product's home warehouse.
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id"), nullable=True
    )
    # Base-unit quantity, sell price per base unit, and cost snapshot for profit reports.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")


class SalesInvoiceTax(Base):
    """One applied tax on an invoice — an invoice may carry several at once.

    Name/rate/amount are snapshotted at invoice time so an invoice keeps showing
    exactly what was charged even if the TaxRate is later edited or deleted.
    """

    __tablename__ = "sales_invoice_taxes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tax_rate_id: Mapped[int | None] = mapped_column(
        ForeignKey("tax_rates.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    invoice: Mapped[SalesInvoice] = relationship(back_populates="taxes")


class SalesQuotation(Base):
    """عرض سعر — a price commitment for a customer; converts to a real invoice on
    acceptance, at which point the normal FEFO/credit-limit/accounting path runs.
    Carries no stock or accounting effect on its own.
    """

    __tablename__ = "sales_quotations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Identifier minted by the field app before this record ever reaches the
    # server. Unique, so replaying a sync batch over a flaky connection returns
    # the record already created instead of duplicating it. NULL for anything
    # created online.
    client_uuid: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    salesman_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[QuotationStatus] = mapped_column(
        Enum(QuotationStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=QuotationStatus.DRAFT,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    converted_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_invoices.id"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    lines: Mapped[list["SalesQuotationLine"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )
    taxes: Mapped[list["SalesQuotationTax"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan"
    )


class SalesQuotationLine(Base):
    __tablename__ = "sales_quotation_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("sales_quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    # Base-unit quantity and price snapshot — same convention as SalesInvoiceLine.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    quotation: Mapped[SalesQuotation] = relationship(back_populates="lines")


class SalesQuotationTax(Base):
    __tablename__ = "sales_quotation_taxes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quotation_id: Mapped[int] = mapped_column(
        ForeignKey("sales_quotations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tax_rate_id: Mapped[int | None] = mapped_column(
        ForeignKey("tax_rates.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    quotation: Mapped[SalesQuotation] = relationship(back_populates="taxes")


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
    # Share of the invoice's discount attributable to the returned goods. The
    # customer was never charged this, so it is not credited back to them.
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    # What the customer is actually credited: subtotal + vat - discount_amount.
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[ReturnStatus] = mapped_column(
        Enum(ReturnStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ReturnStatus.POSTED,
        server_default=ReturnStatus.POSTED.value,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    lines: Mapped[list["SalesReturnLine"]] = relationship(
        back_populates="sales_return", cascade="all, delete-orphan"
    )


class CreditResolution(str, enum.Enum):
    """How an over-collection created by a return is settled."""

    PENDING = "pending"      # awaiting a human decision
    # Decided: hand the cash back. The money has NOT moved yet — the till pays it,
    # which is a second act by a second person. Collapsing this into REFUNDED was a
    # real bug found by testing the flow: the decision marked it refunded, and the
    # payout then refused because it was already refunded, so no cash could ever
    # leave the drawer. A decision and a disbursement are different events.
    AWAITING_REFUND = "awaiting_refund"
    REFUNDED = "refunded"    # cash actually paid back out of the till
    CREDITED = "credited"    # left on the customer's account against future invoices


class CustomerCredit(Base):
    """Money owed back to a customer because goods were returned after payment.

    Raised automatically when a return leaves an invoice paid for more than it is
    now worth, because the alternative is that the obligation exists only as a
    negative number on a statement nobody is looking at. Two of these appeared in
    the dev database exactly that way.

    The decision — hand the cash back, or leave it on account — is a human one, and
    deliberately not defaulted silently: a walk-in who paid cash usually wants the
    money, a wholesale account usually prefers it against the next invoice, and only
    the person at the counter knows which.

    The accounting is asymmetric in a way worth stating: **crediting posts nothing.**
    The invoice debited receivables, the payment credited them, and the return
    credited them again, so the account already carries the balance owed. Leaving it
    on account is simply recognising that. Only a cash refund moves money, and it is
    the till that moves it, so it flows through the same cash movement and day-close
    as every other disbursement.
    """

    __tablename__ = "customer_credits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sales_invoices.id"), nullable=False, index=True
    )
    # The return that caused it, kept so the paperwork can be traced back.
    return_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_returns.id"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    resolution: Mapped[CreditResolution] = mapped_column(
        Enum(CreditResolution, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=CreditResolution.PENDING,
    )
    notes: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who decided, and who handed the money over — a money decision with no name on
    # it is a gap in the audit trail.
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


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


class RoundSettlementStatus(str, enum.Enum):
    OPEN = "open"  # مفتوحة — الجولة جارية أو بانتظار التسوية
    SETTLED = "settled"  # مُسوّاة — سُلّم النقد وسُوّي المخزون ووُقّعت
    CANCELLED = "cancelled"  # ملغاة — أُهملت دون تسوية


class RoundSettlement(Base):
    """تسوية جولة مندوب — closing the day for one van.

    A salesman drives off with stock every morning and comes back with cash, an
    emptier van, and a set of invoices. Each of those three was already tracked
    separately — the load-out is a transfer, the sales are invoices, the cash is
    collected by the cashier, the remaining stock is a stocktake — but nothing
    tied them together, so nobody could say whether a given round was *closed*.

    This record is that missing tie. Two deliberate constraints shape it:

    **It reports and gates; it never posts money.** Cash from van sales already
    flows through the cashier gate on each invoice, and the cashier's collection
    is the single place a cash movement is written. If settling also posted cash,
    every round would be counted twice. So closing a round *requires* that its
    cash invoices are already collected and records what it found — it does not
    move a riyal itself.

    **Stock variance belongs to the stocktake.** Posting a count already applies
    differences per batch and nets one journal entry against 5040. Settlement
    links to that stocktake rather than reimplementing it, because two code paths
    adjusting the same batches is how ledgers drift.

    The figures are snapshotted on settling rather than computed on read: they are
    what was true at sign-off, and must not silently change afterwards if a late
    invoice is edited.
    """

    __tablename__ = "round_settlements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The van. Always a warehouse with is_vehicle=true — enforced in the service.
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False, index=True
    )
    salesman_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    round_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[RoundSettlementStatus] = mapped_column(
        # values_callable is not optional here, and the omission was a live bug:
        # without it SQLAlchemy sends the member *name* ("OPEN") while the type
        # created by the migration holds the lowercase *values*, so Postgres
        # rejected every insert. The tests could not catch it — they build the
        # schema from this same metadata, so the type and the parameter agreed
        # with each other and disagreed only with the migrated database.
        Enum(
            RoundSettlementStatus,
            name="roundsettlementstatus",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=RoundSettlementStatus.OPEN,
    )

    # --- Snapshot of the round, filled in on settling ---
    invoice_count: Mapped[int] = mapped_column(nullable=False, default=0)
    cash_sales_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    card_sales_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    credit_sales_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # What the cashier has actually taken in against this round's invoices.
    cash_collected_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # What is still owed — the reason a round cannot be settled while non-zero.
    cash_outstanding_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )

    # The count that reconciled the van, when one was done.
    stocktake_id: Mapped[int | None] = mapped_column(
        ForeignKey("stocktakes.id"), nullable=True, index=True
    )
    # Value of that count's differences: negative is a shortfall on the van.
    stock_variance_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    # And the difference in units. Stored alongside the value because the value is
    # priced at the batch's cost and is therefore *zero whenever that cost is
    # unknown* — recording only money would leave a genuine shortfall of goods
    # looking like a perfectly balanced round.
    stock_variance_qty: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal("0")
    )

    notes: Mapped[str | None] = mapped_column(String(500))

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    opened_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    @property
    def total_sales(self) -> Decimal:
        """All sales on the round, however they were paid."""
        return self.cash_sales_total + self.card_sales_total + self.credit_sales_total

    @property
    def is_balanced(self) -> bool:
        """Whether nothing is left hanging: no cash owed and no stock difference.

        Checks the *quantity*, not the value: an unvalued shortfall is still a
        shortfall, and testing the money alone would call such a round balanced.

        A settled round can still be unbalanced — a shortfall may be accepted and
        written off deliberately — so this describes the round, it does not gate
        it. The gate on outstanding cash lives in the service.
        """
        return self.cash_outstanding_total == 0 and self.stock_variance_qty == 0

    # Eagerly loaded rather than lazy: the names are wanted on every read of a
    # settlement, and `lazy="selectin"` both avoids N+1 on the history list and
    # avoids a lazy load firing outside the async session, which raises.
    #
    # `foreign_keys` is required, not decorative — this table has four columns
    # pointing at users.id (the salesman plus who opened, settled and cancelled
    # it), so SQLAlchemy cannot tell which one this relationship follows.
    warehouse: Mapped["Warehouse"] = relationship(  # noqa: F821 — inventory module
        "Warehouse", lazy="selectin", foreign_keys=[warehouse_id]
    )
    salesman: Mapped["User"] = relationship(  # noqa: F821 — user module
        "User", lazy="selectin", foreign_keys=[salesman_id]
    )

    @property
    def warehouse_name(self) -> str | None:
        return self.warehouse.name if self.warehouse else None

    @property
    def salesman_name(self) -> str | None:
        return self.salesman.full_name if self.salesman else None


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


class CustomerLogin(Base):
    """A customer's own way into the portal — deliberately not a `User`.

    Staff and customers are different kinds of principal and must not share a table.
    Sharing one would mean a single `role` column separating a shop owner from an
    accountant, and one wrong default anywhere in the permission catalogue would hand
    a customer the run of the business. Two tables cannot be confused by a default.

    One login per customer for now. A shop with several people ordering shares it;
    if that becomes a problem the fix is more rows here, not a second concept.
    """

    __tablename__ = "customer_logins"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, unique=True, index=True
    )
    # Phone or email — whichever the office gives them. Kept as one opaque
    # identifier because a grocery is reached by phone and an office by email, and
    # the system has no business insisting on either.
    login_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # The office issues a temporary password; the portal refuses to do anything else
    # until it is changed. There is no mail or SMS gateway configured, so an emailed
    # invite link would be a feature that silently never arrives.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Lockout state. Counting failures in the row rather than in memory means a
    # restart does not reset an attack, and several workers cannot each grant a
    # fresh allowance of guesses.
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customer: Mapped["Customer"] = relationship(lazy="selectin")
