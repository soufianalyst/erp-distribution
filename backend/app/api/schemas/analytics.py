"""Pydantic schemas (DTOs) for the analytics/dashboard module."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


# --- RFM ---
class CustomerRFMOut(BaseModel):
    customer_id: int
    customer_name: str
    salesman_name: str | None
    recency_days: int | None
    frequency: int
    monetary: Decimal
    segment: str


class ProductRFMOut(BaseModel):
    product_id: int
    product_name: str
    sku: str
    recency_days: int | None
    frequency: int
    monetary: Decimal
    margin: Decimal
    segment: str
    stock_on_hand: Decimal
    nearest_expiry_days: int | None


# --- Sales performance ---
class SalesTrendPointOut(BaseModel):
    period: str
    revenue: Decimal
    vat: Decimal
    margin: Decimal
    cash_revenue: Decimal
    credit_revenue: Decimal
    invoice_count: int


class WarehouseRevenueOut(BaseModel):
    warehouse_id: int
    warehouse_name: str
    revenue: Decimal


class PriceTierRevenueOut(BaseModel):
    price_tier: str
    revenue: Decimal
    invoice_count: int


class ReturnsTrendPointOut(BaseModel):
    period: str
    sales_value: Decimal
    returned_value: Decimal
    return_rate_pct: Decimal
    resellable_value: Decimal
    damaged_value: Decimal


# --- Inventory & waste ---
class ExpiryRiskOut(BaseModel):
    batch_id: int
    product_name: str
    warehouse_name: str
    batch_number: str
    expiry_date: date
    days_remaining: int
    quantity: Decimal
    value_at_risk: Decimal


class SuggestedBuyerOut(BaseModel):
    """A customer who has actually bought this product before — not a prediction."""

    customer_id: int
    customer_name: str
    phone: str | None
    total_quantity: Decimal
    last_bought: date


class ExpiryWorklistItemOut(BaseModel):
    """One product worth a phone call, with the reasoning shown.

    Every input to the ranking is exposed rather than just the score: a manager who
    cannot see why something is at the top will not trust the order, and the rate is
    an estimate that deserves to be argued with.
    """

    product_id: int
    product_name: str
    unit: str
    batches: int
    warehouses: list[str]
    earliest_expiry: date
    days_remaining: int
    quantity_at_risk: Decimal
    # Units per day over the recent window; zero when nothing has sold.
    daily_sales_rate: Decimal
    projected_sales: Decimal
    # What will still be on the shelf when it expires, at the current rate.
    surplus_quantity: Decimal
    surplus_value: Decimal
    # Surplus value per day of runway — the sort key.
    urgency: Decimal
    # False when the rate is a guess of zero rather than a measurement.
    has_sales_history: bool
    suggested_buyers: list[SuggestedBuyerOut]


class ExpiryWorklistOut(BaseModel):
    """Two different problems, kept apart.

    `items` is stock that sells but will not clear in time — a phone call, with the
    buyers to make it to. `dead_stock` has never sold at all, so there is nobody to
    ring: it is a markdown, a return to the supplier, or a write-off to accept.

    Mixed into one list the dead stock swamps the calls, because "never sold" always
    scores maximum surplus. A worklist whose top is unactionable is one people stop
    opening.
    """

    horizon_days: int
    velocity_window_days: int
    total_products: int
    total_surplus_value: Decimal
    items: list[ExpiryWorklistItemOut]
    dead_stock: list[ExpiryWorklistItemOut]
    dead_stock_value: Decimal


class TurnoverOut(BaseModel):
    product_id: int
    product_name: str
    cogs_12m: Decimal
    stock_on_hand_value: Decimal
    turnover_ratio: Decimal | None


# --- Financial / credit ---
class ARAgingRowOut(BaseModel):
    customer_id: int
    customer_name: str
    bucket_0_30: Decimal
    bucket_31_60: Decimal
    bucket_61_90: Decimal
    bucket_90_plus: Decimal
    total_outstanding: Decimal


class CreditRiskCustomerOut(BaseModel):
    customer_id: int
    customer_name: str
    outstanding_balance: Decimal
    credit_limit: Decimal
    utilization_pct: Decimal
    recency_days: int | None


# --- Delivery & fulfillment ---
class FulfillmentSummaryOut(BaseModel):
    fulfillment: str
    invoice_count: int
    completed_count: int
    failed_or_pending_count: int
    completion_rate_pct: Decimal


class DriverPerformanceOut(BaseModel):
    driver_name: str
    trip_count: int
    delivered_stops: int
    failed_stops: int
    failure_rate_pct: Decimal


# --- Sales rep performance ---
class RepPerformanceOut(BaseModel):
    salesman_id: int
    salesman_name: str
    revenue: Decimal
    invoice_count: int
    avg_basket: Decimal
    customer_count: int
    return_rate_pct: Decimal


# --- Top-level KPIs ---
class DashboardSummaryOut(BaseModel):
    total_revenue_12m: Decimal
    total_margin_12m: Decimal
    invoice_count_12m: int
    active_customers_12m: int
    ar_outstanding: Decimal
    waste_risk_value_30d: Decimal
    avg_order_value: Decimal
    return_rate_pct_12m: Decimal


# --- Damaged / written-off stock report ---
class DamageByReasonOut(BaseModel):
    reason: str
    adjustment_count: int
    total_quantity: Decimal
    total_cost: Decimal


class DamageByProductOut(BaseModel):
    product_id: int
    product_name: str
    base_unit_name: str
    total_quantity: Decimal
    total_cost: Decimal


class DamageReportOut(BaseModel):
    date_from: date | None
    date_to: date | None
    # Cancelled write-offs are excluded — the goods went back to stock.
    adjustment_count: int
    total_quantity: Decimal
    total_cost: Decimal
    by_reason: list[DamageByReasonOut]
    by_product: list[DamageByProductOut]


# --- Invoice discounts granted ---
class DiscountInvoiceOut(BaseModel):
    invoice_id: int
    invoice_date: date
    customer_name: str
    salesman_name: str | None
    # Goods + tax before the discount was applied.
    gross_amount: Decimal
    discount_amount: Decimal
    total: Decimal


class DiscountByCustomerOut(BaseModel):
    customer_id: int
    customer_name: str
    invoice_count: int
    discount_amount: Decimal


class DiscountBySalesmanOut(BaseModel):
    salesman_id: int | None
    salesman_name: str
    invoice_count: int
    discount_amount: Decimal


class DiscountReportOut(BaseModel):
    date_from: date | None
    date_to: date | None
    invoice_count: int
    total_discount: Decimal
    # Gross and net across the discounted invoices, so the share is visible.
    total_gross: Decimal
    total_net: Decimal
    by_customer: list[DiscountByCustomerOut]
    by_salesman: list[DiscountBySalesmanOut]
    invoices: list[DiscountInvoiceOut]


# --- Dashboard alerts ---
class AlertItemOut(BaseModel):
    """One example inside an alert group — a preview line, not a full record."""

    label: str
    detail: str
    value: str | None = None


class AlertGroupOut(BaseModel):
    """One kind of thing needing attention, with somewhere to go and act on it."""

    key: str
    label: str
    # critical = costing money or blocking a sale now; warning = act soon;
    # info = tidy-up work.
    severity: Literal["critical", "warning", "info"]
    count: int
    # What to actually do about it, in plain Arabic.
    hint: str
    # Frontend route where the work gets done.
    route: str
    items: list[AlertItemOut]


class AlertsOut(BaseModel):
    generated_at: date
    critical_count: int
    warning_count: int
    # Ordered worst first; only groups the caller has permission to act on.
    groups: list[AlertGroupOut]
