"""Pydantic schemas (DTOs) for the sales module."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.sales import (
    CreditResolution,
    ReturnStatus,
    FulfillmentType,
    PriceTier,
    QuotationStatus,
    ReturnReason,
    RoundSettlementStatus,
    SalesPaymentMethod,
)


# --- Customers ---
class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier = PriceTier.WHOLESALE
    credit_limit: Decimal = Field(default=Decimal("0"), ge=0)
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0)
    salesman_id: int | None = None


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0)
    salesman_id: int | None = None
    is_active: bool | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str | None
    address: str | None
    price_tier: PriceTier
    credit_limit: Decimal
    opening_balance: Decimal
    salesman_id: int | None
    is_active: bool


# --- Sales invoices ---
class SalesLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    # Optional alternative unit; when omitted the quantity is in the base unit.
    unit_id: int | None = None
    # المواد المقننة: file this line in the customer's regulated-goods register as
    # well as selling it. Purely additional — the line is priced, charged, posted and
    # picked exactly as any other, and the register has no accounting effect at all.
    rationed: bool = False


class SalesInvoiceCreate(BaseModel):
    customer_id: int
    payment_method: SalesPaymentMethod
    # Warehouse pickup (استلام من المستودع) or driver delivery (توصيل).
    fulfillment: FulfillmentType = FulfillmentType.DELIVERY
    # Which configured taxes to apply (see /settings/tax-rates); empty = tax-free.
    # Several may be selected at once (e.g. VAT + a local municipality tax).
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[SalesLineIn] = Field(min_length=1)
    # Manager approval flag: lets an admin exceed the customer's credit limit.
    credit_override: bool = False
    # What the customer will actually be charged. When it is below the computed
    # gross (goods + tax), the difference is recorded as a discount — this is how
    # the counter rounds 12,005 down to 12,000. Omit to charge the full amount.
    collectable_amount: Decimal | None = Field(default=None, ge=0)


class SalesLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    batch_id: int
    batch_number: str
    # Named on the line itself, so printing an invoice needs no product lookup and a
    # later rename cannot rewrite what this invoice says it sold.
    product_name: str
    unit_name: str
    # Warehouse this line was picked from — drives print grouping by warehouse.
    warehouse_id: int | None
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class SalesInvoiceTaxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tax_rate_id: int | None
    name: str
    rate: Decimal
    amount: Decimal


class SalesInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    salesman_id: int | None
    # Set only when every line shares one warehouse; NULL for mixed-warehouse invoices.
    warehouse_id: int | None
    invoice_date: date
    payment_method: SalesPaymentMethod
    fulfillment: FulfillmentType
    picked_up_at: datetime | None
    # NULL for cash/card invoices awaiting cashier collection; credit invoices are
    # confirmed immediately since they're settled later through the customer's account.
    payment_confirmed_at: datetime | None
    subtotal: Decimal
    # Sum of all applied taxes' amounts (see `taxes` for the per-tax breakdown).
    vat_amount: Decimal
    # Granted at issue time by lowering the collectable amount; applied after VAT.
    discount_amount: Decimal
    # What the customer owes: subtotal + vat_amount - discount_amount.
    total: Decimal
    paid_amount: Decimal
    notes: str | None
    created_at: datetime
    # Total credited back via returns; net = total - returned_total.
    returned_total: Decimal = Decimal("0")
    # What is still owed: total - returned_total - paid_amount.
    #
    # Derived, never stored. `total` is what the invoice billed and must not change
    # once issued — the document is in the customer's hands, its journal entries are
    # posted, and its tax period may already be filed. What a return changes is the
    # amount *due*, which is this. Populated by the cashier's pending list; elsewhere
    # it defaults to the full unpaid amount.
    amount_due: Decimal | None = None
    lines: list[SalesLineOut]
    taxes: list[SalesInvoiceTaxOut]


# --- Customer credits (money owed back after a return) ---
class CustomerCreditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str | None = None
    invoice_id: int
    return_id: int | None
    amount: Decimal
    resolution: CreditResolution
    notes: str | None
    created_at: datetime
    resolved_at: datetime | None


class CustomerCreditResolveIn(BaseModel):
    """Hand the money back, or leave it on the customer's account.

    No default. A walk-in who paid cash usually wants the money and a wholesale
    account usually prefers it against the next invoice, and only the person at the
    counter knows which — so the software refuses to guess.
    """

    resolution: Literal["refunded", "credited"]
    notes: str | None = Field(default=None, max_length=300)



# --- Quotations ---
class QuotationLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_id: int | None = None


class SalesQuotationCreate(BaseModel):
    customer_id: int
    valid_until: date | None = None
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[QuotationLineIn] = Field(min_length=1)


class QuotationConvertIn(BaseModel):
    payment_method: SalesPaymentMethod
    fulfillment: FulfillmentType = FulfillmentType.DELIVERY
    # Manager approval flag: lets an admin exceed the customer's credit limit.
    credit_override: bool = False


class QuotationLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class QuotationTaxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tax_rate_id: int | None
    name: str
    rate: Decimal
    amount: Decimal


class SalesQuotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    salesman_id: int | None
    quote_date: date
    valid_until: date | None
    status: QuotationStatus
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    notes: str | None
    converted_invoice_id: int | None
    created_at: datetime
    lines: list[QuotationLineOut]
    taxes: list[QuotationTaxOut]


# --- Returns ---
class ReturnLineIn(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_id: int | None = None


class SalesReturnCreate(BaseModel):
    invoice_id: int
    reason: ReturnReason
    notes: str | None = Field(default=None, max_length=300)
    lines: list[ReturnLineIn] = Field(min_length=1)


class ReturnLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    # Named on the line, so no consumer needs the product catalogue to read it.
    product_name: str
    batch_id: int
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class ReturnCancelIn(BaseModel):
    """Why it is being reversed — optional, but it is what makes the record readable."""

    cancel_reason: str | None = Field(default=None, max_length=300)


class SalesReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    customer_id: int
    reason: ReturnReason
    subtotal: Decimal
    vat_amount: Decimal
    # Share of the invoice's discount attributable to the returned goods; it was
    # never charged, so it is withheld from the credit rather than refunded.
    discount_amount: Decimal
    # What the customer is credited: subtotal + vat_amount - discount_amount.
    total: Decimal
    notes: str | None
    created_at: datetime
    status: ReturnStatus = ReturnStatus.POSTED
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    lines: list[ReturnLineOut]
    # Set when this return left the invoice paid for more than it is now worth, so
    # the screen can ask what to do with the difference. Without it the API knew a
    # decision was owed and the user was never asked — the obligation existed only
    # as a negative statement balance nobody was looking at.
    pending_credit_id: int | None = None
    pending_credit_amount: Decimal | None = None


# --- Customer payments & statement ---
class CustomerPaymentCreate(BaseModel):
    customer_id: int
    amount: Decimal = Field(gt=0)
    payment_date: date | None = None
    method: Literal["cash", "bank", "cheque"] = "cash"
    reference: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=300)


class CustomerPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    amount: Decimal
    payment_date: date
    method: str
    reference: str | None
    notes: str | None


class CustomerStatementOut(BaseModel):
    customer: CustomerOut
    opening_balance: Decimal
    total_invoices: Decimal
    total_returns: Decimal
    total_paid: Decimal
    # What the customer still owes us.
    balance: Decimal
    invoices: list[SalesInvoiceOut]
    returns: list[SalesReturnOut]
    payments: list[CustomerPaymentOut]


# --- Salesman commissions ---
class CommissionRow(BaseModel):
    salesman_id: int
    salesman_name: str
    total_sales: Decimal
    total_returns: Decimal
    # total_sales - total_returns, both excluding VAT.
    net_sales: Decimal
    commission_rate: Decimal
    commission_amount: Decimal


class CommissionReportOut(BaseModel):
    date_from: date | None
    date_to: date | None
    rows: list[CommissionRow]
    total_commission: Decimal


# --- Field sync (offline salesman app) ---
class FieldCustomerIn(BaseModel):
    """A shop registered on the round, before the server has ever seen it."""

    client_uuid: str = Field(min_length=8, max_length=36)
    name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    price_tier: PriceTier = PriceTier.WHOLESALE


class FieldDocumentIn(BaseModel):
    """One visit's outcome: goods sold off the van, or an order to fulfil later."""

    client_uuid: str = Field(min_length=8, max_length=36)
    # Exactly one of these identifies the buyer: an existing customer, or one
    # created in this same batch and not yet holding a server id.
    customer_id: int | None = None
    customer_uuid: str | None = None
    kind: Literal["van_sale", "order"]
    payment_method: SalesPaymentMethod = SalesPaymentMethod.CASH
    tax_rate_ids: list[int] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=300)
    lines: list[SalesLineIn] = Field(min_length=1)
    # Mirrors the counter's rounding-down of the collectable amount.
    collectable_amount: Decimal | None = Field(default=None, ge=0)


class FieldSyncIn(BaseModel):
    """A whole round uploaded at once. Safe to resend: every item is identified
    by its client_uuid, so anything already stored is reported, not repeated."""

    customers: list[FieldCustomerIn] = Field(default_factory=list)
    documents: list[FieldDocumentIn] = Field(default_factory=list)


class FieldSyncItemOut(BaseModel):
    client_uuid: str
    kind: Literal["customer", "van_sale", "order"]
    # created = stored now; duplicate = already stored by an earlier attempt;
    # failed = rejected, with the reason, and the field app keeps it queued.
    status: Literal["created", "duplicate", "failed"]
    server_id: int | None = None
    # The real invoice number, replacing the provisional field reference.
    message: str | None = None


class FieldSyncOut(BaseModel):
    created_count: int
    duplicate_count: int
    failed_count: int
    results: list[FieldSyncItemOut]


class FieldVanStockLineOut(BaseModel):
    product_id: int
    sku: str
    name: str
    base_unit_name: str
    quantity: Decimal


class FieldVanOut(BaseModel):
    """The salesman's own vehicle and what it is currently carrying.

    The field app caches this so it can check quantities while offline.
    """

    warehouse_id: int
    warehouse_name: str
    lines: list[FieldVanStockLineOut]


# --- Round settlement (تسوية جولة المندوب) ---


class RoundSettlementOpenIn(BaseModel):
    """Open a round for a van. The date defaults to today on the server."""

    warehouse_id: int
    round_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class RoundSettlementSettleIn(BaseModel):
    """Close a round.

    `notes` becomes mandatory once there is a stock difference — the service
    enforces that, not this schema, because whether a difference exists is only
    knowable by looking at the linked count.
    """

    stocktake_id: int | None = None
    notes: str | None = Field(default=None, max_length=500)


class RoundVanSettleIn(RoundSettlementSettleIn):
    """Close a van's day in one step, opening the round first if none is open.

    Opening a round separately stays available for anyone who wants the morning
    handover recorded explicitly, but it is not required: the step recorded only a
    date and a note, and the expected-versus-counted comparison it might have
    justified is already what the stocktake provides.
    """

    warehouse_id: int
    round_date: date | None = None


class RoundInvoiceOut(BaseModel):
    """One invoice belonging to the round, with its collection state."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_name: str
    payment_method: SalesPaymentMethod
    total: Decimal
    collected: Decimal
    outstanding: Decimal
    is_collected: bool


class RoundPositionOut(BaseModel):
    """The live position of a round — computed on read, never stored.

    This is what the settlement screen shows *before* closing: what has been
    sold, what the cashier has taken in, and what is still owed. The settled
    record keeps its own snapshot of these figures, because they are the numbers
    that were true at sign-off and must not drift afterwards.
    """

    warehouse_id: int
    warehouse_name: str
    salesman_id: int
    salesman_name: str
    round_date: date

    invoice_count: int
    cash_sales_total: Decimal
    card_sales_total: Decimal
    credit_sales_total: Decimal
    total_sales: Decimal

    # Cash and card both have to reach the drawer; credit is the customer's debt
    # and is deliberately excluded from what the salesman owes tonight.
    cash_collected_total: Decimal
    cash_outstanding_total: Decimal

    stocktake_id: int | None
    stock_variance_value: Decimal
    stock_variance_qty: Decimal
    # Whether any counted quantity differed. Separate from the value because the
    # value is zero when the batch has no cost — an unvalued shortfall is real.
    has_stock_variance: bool
    variance_needs_approval: bool
    variance_approval_limit: Decimal

    can_settle: bool
    blockers: list[str]

    invoices: list[RoundInvoiceOut]


class RoundSettlementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    warehouse_name: str | None = None
    salesman_id: int
    salesman_name: str | None = None
    round_date: date
    status: RoundSettlementStatus

    invoice_count: int
    cash_sales_total: Decimal
    card_sales_total: Decimal
    credit_sales_total: Decimal
    total_sales: Decimal
    cash_collected_total: Decimal
    cash_outstanding_total: Decimal

    stocktake_id: int | None
    stock_variance_value: Decimal
    stock_variance_qty: Decimal
    is_balanced: bool

    notes: str | None
    opened_at: datetime
    settled_at: datetime | None
    cancelled_at: datetime | None

# --- Invoice tracker ---
class InvoiceStepOut(BaseModel):
    """One stage of an invoice's journey, as the tracker draws it."""

    key: str
    label: str
    # done = behind us, current = where it is now, pending = ahead,
    # failed = stopped here and needs a human.
    state: Literal["done", "current", "pending", "failed"]
    at: datetime | None
    detail: str | None


class InvoiceTimelineOut(BaseModel):
    invoice_id: int
    reference: str
    customer_name: str
    fulfillment: Literal["pickup", "delivery"]
    # Driver or vehicle for a delivery; "collected at the warehouse" otherwise.
    shipped_via: str
    # The step the invoice is sitting on, for the heading.
    status_label: str
    # Trip date for a delivery; nothing to promise for a counter collection.
    expected: date | None
    total: Decimal
    amount_due: Decimal
    returned_total: Decimal
    steps: list[InvoiceStepOut]


# --- Collections ---
class PromiseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    activity_id: int
    amount: Decimal
    due_on: date
    made_on: date
    # What the customer has actually paid since making the promise. Shown beside the
    # promise so a part-payment reads as progress rather than as a broken word.
    paid_since: Decimal
    state: Literal["open", "kept", "broken"]


class DebtorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: int
    name: str
    phone: str | None
    salesman_name: str | None
    balance: Decimal
    overdue: Decimal
    oldest_days: int
    invoice_count: int
    # current / d31_60 / d61_90 / d90_plus
    buckets: dict[str, Decimal]
    credit_limit: Decimal
    last_contact: datetime | None
    last_outcome: str | None
    promise: PromiseOut | None
    # Overdue amount weighted by age: the cost of leaving it another week.
    priority: Decimal
    # Why this shop is on today's list, in one line the caller can read aloud.
    reason: str


class CollectionsWorklistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_outstanding: Decimal
    total_overdue: Decimal
    broken_promises: int
    never_contacted: int
    items: list[DebtorOut]


class CollectionActivityIn(BaseModel):
    outcome: Literal["promised", "paid", "no_answer", "refused", "disputed", "note"]
    # Required together when the outcome is a promise; the service refuses a promise
    # missing either, because one without a date or an amount cannot be checked.
    promised_amount: Decimal | None = Field(default=None, gt=0)
    promised_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


class CollectionActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    outcome: str
    promised_amount: Decimal | None
    promised_on: date | None
    note: str | None
    created_by: int | None
    created_at: datetime


# --- المواد المقننة (regulated-goods register) ---
class RationedEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_id: int
    invoice_id: int
    invoice_reference: str
    invoice_date: date
    product_id: int
    product_name: str
    unit_name: str
    quantity: Decimal
    # Sent back on a posted credit note, so the register shows what was kept.
    returned_quantity: Decimal
    net_quantity: Decimal
    unit_price: Decimal
    net_total: Decimal
    added_at: datetime


class RationedRegisterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    record_id: int
    customer_id: int
    customer_name: str
    customer_phone: str | None
    opened_at: datetime
    closed_at: datetime | None
    closed_by_name: str | None
    notes: str | None
    is_open: bool
    line_count: int
    total_quantity: Decimal
    # A value, not an amount due: these goods were already charged on their invoices.
    total_value: Decimal
    entries: list[RationedEntryOut]


class RationedRecordSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    opened_at: datetime
    closed_at: datetime | None
    notes: str | None


class RationedCloseIn(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class RationedCloseOut(BaseModel):
    closed: RationedRegisterOut
    # The register that is now accumulating: closing one always opens the next, so a
    # tag recorded a second later has somewhere to go.
    new_record_id: int
