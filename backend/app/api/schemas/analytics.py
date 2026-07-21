"""Pydantic schemas (DTOs) for the analytics/dashboard module."""

from datetime import date
from decimal import Decimal

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
