"""Analytics/reporting business logic: RFM, sales trends, inventory waste,
credit risk, delivery performance, and sales-rep performance.

Read-only aggregation over existing sales/inventory/delivery data. Time-series
grouping is done in Python (not SQL date functions) so the same queries work
unchanged on both SQLite (dev) and PostgreSQL (production).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.analytics import (
    ARAgingRowOut,
    CreditRiskCustomerOut,
    CustomerRFMOut,
    DamageByProductOut,
    DamageByReasonOut,
    DamageReportOut,
    DiscountByCustomerOut,
    DiscountBySalesmanOut,
    DiscountInvoiceOut,
    DiscountReportOut,
    DashboardSummaryOut,
    DriverPerformanceOut,
    ExpiryRiskOut,
    FulfillmentSummaryOut,
    PriceTierRevenueOut,
    ProductRFMOut,
    RepPerformanceOut,
    ReturnsTrendPointOut,
    SalesTrendPointOut,
    TurnoverOut,
    WarehouseRevenueOut,
)
from app.domain.models.delivery import DeliveryStop, DeliveryTrip
from app.domain.models.inventory import (
    AdjustmentStatus,
    Product,
    ProductBatch,
    StockAdjustment,
    StockAdjustmentLine,
    Warehouse,
)
from app.domain.models.sales import (
    Customer,
    CustomerPayment,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPaymentMethod,
    SalesReturn,
    SalesReturnLine,
)
from app.domain.models.user import User
from app.services.sales.sales_service import SalesService

TWO_PLACES = Decimal("0.01")
WINDOW_DAYS = 365


def _d(value: object) -> Decimal:
    """Normalize a DB-returned aggregate (int/float/Decimal/None) to Decimal."""
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return ((numerator / denominator) * 100).quantize(TWO_PLACES)


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sales = SalesService(session)

    # --- Customer RFM ---
    async def customer_rfm(self) -> list[CustomerRFMOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)

        result = await self.session.execute(
            select(
                Customer.id,
                Customer.name,
                User.full_name,
                func.max(SalesInvoice.invoice_date),
                func.count(SalesInvoice.id),
                func.coalesce(func.sum(SalesInvoice.total), 0),
            )
            .outerjoin(User, Customer.salesman_id == User.id)
            .outerjoin(
                SalesInvoice,
                (SalesInvoice.customer_id == Customer.id)
                & (SalesInvoice.invoice_date >= window_start),
            )
            .group_by(Customer.id, Customer.name, User.full_name)
        )
        rows = result.all()

        returns_result = await self.session.execute(
            select(
                SalesReturn.customer_id, func.coalesce(func.sum(SalesReturn.total), 0)
            )
            .where(SalesReturn.created_at >= window_start)
            .group_by(SalesReturn.customer_id)
        )
        returns_by_customer = {cid: _d(t) for cid, t in returns_result.all()}

        metrics = []
        for customer_id, name, rep_name, last_date, freq, monetary in rows:
            net_monetary = _d(monetary) - returns_by_customer.get(
                customer_id, Decimal("0")
            )
            recency = (today - last_date).days if last_date else None
            metrics.append(
                {
                    "customer_id": customer_id,
                    "name": name,
                    "rep_name": rep_name,
                    "recency": recency,
                    "frequency": freq,
                    "monetary": net_monetary,
                }
            )

        monetary_values = sorted(m["monetary"] for m in metrics if m["frequency"] > 0)
        monetary_p80 = (
            monetary_values[int(len(monetary_values) * 0.8)]
            if monetary_values
            else Decimal("0")
        )

        out = [
            CustomerRFMOut(
                customer_id=m["customer_id"],
                customer_name=m["name"],
                salesman_name=m["rep_name"],
                recency_days=m["recency"],
                frequency=m["frequency"],
                monetary=m["monetary"].quantize(TWO_PLACES),
                segment=self._customer_segment(
                    m["frequency"], m["recency"], m["monetary"], monetary_p80
                ),
            )
            for m in metrics
        ]
        return sorted(out, key=lambda r: r.monetary, reverse=True)

    @staticmethod
    def _customer_segment(
        frequency: int, recency: int | None, monetary: Decimal, monetary_p80: Decimal
    ) -> str:
        if frequency == 0 or recency is None:
            return "لم يشترِ بعد"
        high_value = monetary_p80 > 0 and monetary >= monetary_p80
        if recency <= 30:
            return "بطل (Champion)" if high_value else "نشط"
        if recency <= 90:
            return "بحاجة لعناية" if high_value else "عادي"
        if recency <= 180:
            return "معرض للخطر" if high_value else "متراجع"
        return "خامل (Lost)"

    # --- Product RFM ---
    async def product_rfm(self) -> list[ProductRFMOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)

        result = await self.session.execute(
            select(
                Product.id,
                Product.name,
                Product.sku,
                func.max(SalesInvoice.invoice_date),
                func.count(SalesInvoiceLine.id),
                func.coalesce(func.sum(SalesInvoiceLine.line_total), 0),
                func.coalesce(
                    func.sum(SalesInvoiceLine.quantity * SalesInvoiceLine.unit_cost), 0
                ),
            )
            .outerjoin(SalesInvoiceLine, SalesInvoiceLine.product_id == Product.id)
            .outerjoin(
                SalesInvoice,
                (SalesInvoice.id == SalesInvoiceLine.invoice_id)
                & (SalesInvoice.invoice_date >= window_start),
            )
            .group_by(Product.id, Product.name, Product.sku)
        )
        rows = result.all()

        returns_result = await self.session.execute(
            select(
                SalesReturnLine.product_id,
                func.coalesce(func.sum(SalesReturnLine.line_total), 0),
            )
            .join(SalesReturn, SalesReturnLine.return_id == SalesReturn.id)
            .where(SalesReturn.created_at >= window_start)
            .group_by(SalesReturnLine.product_id)
        )
        returns_by_product = {pid: _d(t) for pid, t in returns_result.all()}

        stock_result = await self.session.execute(
            select(
                ProductBatch.product_id,
                func.coalesce(func.sum(ProductBatch.quantity), 0),
            )
            .where(ProductBatch.quantity > 0)
            .group_by(ProductBatch.product_id)
        )
        stock_by_product = {pid: _d(q) for pid, q in stock_result.all()}

        expiry_result = await self.session.execute(
            select(ProductBatch.product_id, func.min(ProductBatch.expiry_date))
            .where(ProductBatch.quantity > 0)
            .group_by(ProductBatch.product_id)
        )
        nearest_expiry = dict(expiry_result.all())

        metrics = []
        for product_id, name, sku, last_date, freq, revenue, cost in rows:
            net_revenue = _d(revenue) - returns_by_product.get(product_id, Decimal("0"))
            margin = _d(revenue) - _d(cost)
            recency = (today - last_date).days if last_date else None
            metrics.append(
                {
                    "product_id": product_id,
                    "name": name,
                    "sku": sku,
                    "recency": recency,
                    "frequency": freq,
                    "monetary": net_revenue,
                    "margin": margin,
                }
            )

        monetary_values = sorted(m["monetary"] for m in metrics if m["frequency"] > 0)
        monetary_p80 = (
            monetary_values[int(len(monetary_values) * 0.8)]
            if monetary_values
            else Decimal("0")
        )

        out = []
        for m in metrics:
            expiry_dt = nearest_expiry.get(m["product_id"])
            out.append(
                ProductRFMOut(
                    product_id=m["product_id"],
                    product_name=m["name"],
                    sku=m["sku"],
                    recency_days=m["recency"],
                    frequency=m["frequency"],
                    monetary=m["monetary"].quantize(TWO_PLACES),
                    margin=m["margin"].quantize(TWO_PLACES),
                    segment=self._product_segment(
                        m["frequency"], m["recency"], m["monetary"], monetary_p80
                    ),
                    stock_on_hand=stock_by_product.get(m["product_id"], Decimal("0")),
                    nearest_expiry_days=(expiry_dt - today).days if expiry_dt else None,
                )
            )
        return sorted(out, key=lambda r: r.monetary, reverse=True)

    @staticmethod
    def _product_segment(
        frequency: int, recency: int | None, monetary: Decimal, monetary_p80: Decimal
    ) -> str:
        if frequency == 0 or recency is None:
            return "لم يُباع بعد"
        high_value = monetary_p80 > 0 and monetary >= monetary_p80
        if recency <= 30:
            return "الأكثر مبيعاً" if high_value else "ثابت"
        if recency <= 90:
            return "عادي"
        if recency <= 180:
            return "متراجع"
        return "راكد (Dead Stock)"

    # --- Sales performance ---
    async def sales_trend(self) -> list[SalesTrendPointOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)

        result = await self.session.execute(
            select(
                SalesInvoice.invoice_date,
                SalesInvoice.subtotal,
                SalesInvoice.vat_amount,
                SalesInvoice.total,
                SalesInvoice.payment_method,
            ).where(SalesInvoice.invoice_date >= window_start)
        )
        buckets: dict[str, dict] = defaultdict(
            lambda: {
                "revenue": Decimal("0"),
                "vat": Decimal("0"),
                "cash": Decimal("0"),
                "credit": Decimal("0"),
                "count": 0,
            }
        )
        for invoice_date, subtotal, vat, total, method in result.all():
            key = invoice_date.strftime("%Y-%m")
            b = buckets[key]
            b["revenue"] += _d(subtotal)
            b["vat"] += _d(vat)
            b["count"] += 1
            if method == SalesPaymentMethod.CASH:
                b["cash"] += _d(total)
            else:
                b["credit"] += _d(total)

        cogs_result = await self.session.execute(
            select(
                SalesInvoice.invoice_date,
                SalesInvoiceLine.quantity,
                SalesInvoiceLine.unit_cost,
            )
            .join(SalesInvoice, SalesInvoiceLine.invoice_id == SalesInvoice.id)
            .where(
                SalesInvoice.invoice_date >= window_start,
                SalesInvoiceLine.unit_cost.is_not(None),
            )
        )
        cogs_by_month: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for invoice_date, qty, cost in cogs_result.all():
            key = invoice_date.strftime("%Y-%m")
            cogs_by_month[key] += _d(qty) * _d(cost)

        points = []
        for key in sorted(buckets.keys()):
            b = buckets[key]
            margin = b["revenue"] - cogs_by_month.get(key, Decimal("0"))
            points.append(
                SalesTrendPointOut(
                    period=key,
                    revenue=b["revenue"].quantize(TWO_PLACES),
                    vat=b["vat"].quantize(TWO_PLACES),
                    margin=margin.quantize(TWO_PLACES),
                    cash_revenue=b["cash"].quantize(TWO_PLACES),
                    credit_revenue=b["credit"].quantize(TWO_PLACES),
                    invoice_count=b["count"],
                )
            )
        return points

    async def revenue_by_warehouse(self) -> list[WarehouseRevenueOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)
        result = await self.session.execute(
            select(
                Warehouse.id,
                Warehouse.name,
                func.coalesce(func.sum(SalesInvoiceLine.line_total), 0),
            )
            .join(SalesInvoiceLine, SalesInvoiceLine.warehouse_id == Warehouse.id)
            .join(SalesInvoice, SalesInvoiceLine.invoice_id == SalesInvoice.id)
            .where(SalesInvoice.invoice_date >= window_start)
            .group_by(Warehouse.id, Warehouse.name)
        )
        return [
            WarehouseRevenueOut(
                warehouse_id=wid,
                warehouse_name=name,
                revenue=_d(rev).quantize(TWO_PLACES),
            )
            for wid, name, rev in result.all()
        ]

    async def revenue_by_price_tier(self) -> list[PriceTierRevenueOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)
        result = await self.session.execute(
            select(
                Customer.price_tier,
                func.coalesce(func.sum(SalesInvoice.total), 0),
                func.count(SalesInvoice.id),
            )
            .join(Customer, SalesInvoice.customer_id == Customer.id)
            .where(SalesInvoice.invoice_date >= window_start)
            .group_by(Customer.price_tier)
        )
        return [
            PriceTierRevenueOut(
                price_tier=tier.value if hasattr(tier, "value") else str(tier),
                revenue=_d(rev).quantize(TWO_PLACES),
                invoice_count=count,
            )
            for tier, rev, count in result.all()
        ]

    async def returns_trend(self) -> list[ReturnsTrendPointOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)

        sales_result = await self.session.execute(
            select(SalesInvoice.invoice_date, SalesInvoice.total).where(
                SalesInvoice.invoice_date >= window_start
            )
        )
        sales_by_month: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for invoice_date, total in sales_result.all():
            sales_by_month[invoice_date.strftime("%Y-%m")] += _d(total)

        returns_result = await self.session.execute(
            select(SalesReturn.created_at, SalesReturn.total, SalesReturn.reason).where(
                SalesReturn.created_at >= window_start
            )
        )
        returns_by_month: dict[str, dict] = defaultdict(
            lambda: {
                "total": Decimal("0"),
                "resellable": Decimal("0"),
                "damaged": Decimal("0"),
            }
        )
        for created_at, total, reason in returns_result.all():
            key = created_at.strftime("%Y-%m")
            b = returns_by_month[key]
            b["total"] += _d(total)
            if reason.value == "resellable":
                b["resellable"] += _d(total)
            else:
                b["damaged"] += _d(total)

        all_months = sorted(set(sales_by_month) | set(returns_by_month))
        points = []
        for key in all_months:
            sales_value = sales_by_month.get(key, Decimal("0"))
            r = returns_by_month.get(
                key,
                {
                    "total": Decimal("0"),
                    "resellable": Decimal("0"),
                    "damaged": Decimal("0"),
                },
            )
            points.append(
                ReturnsTrendPointOut(
                    period=key,
                    sales_value=sales_value.quantize(TWO_PLACES),
                    returned_value=r["total"].quantize(TWO_PLACES),
                    return_rate_pct=_pct(r["total"], sales_value),
                    resellable_value=r["resellable"].quantize(TWO_PLACES),
                    damaged_value=r["damaged"].quantize(TWO_PLACES),
                )
            )
        return points

    # --- Inventory & waste ---
    async def expiry_risk(self, days: int = 30) -> list[ExpiryRiskOut]:
        today = date.today()
        threshold = today + timedelta(days=days)
        result = await self.session.execute(
            select(ProductBatch, Product.name, Warehouse.name)
            .join(Product, ProductBatch.product_id == Product.id)
            .join(Warehouse, ProductBatch.warehouse_id == Warehouse.id)
            .where(ProductBatch.quantity > 0, ProductBatch.expiry_date <= threshold)
            .order_by(ProductBatch.expiry_date)
        )
        out = []
        for batch, product_name, warehouse_name in result.all():
            unit_cost = batch.unit_cost or Decimal("0")
            out.append(
                ExpiryRiskOut(
                    batch_id=batch.id,
                    product_name=product_name,
                    warehouse_name=warehouse_name,
                    batch_number=batch.batch_number,
                    expiry_date=batch.expiry_date,
                    days_remaining=(batch.expiry_date - today).days,
                    quantity=batch.quantity,
                    value_at_risk=(batch.quantity * unit_cost).quantize(TWO_PLACES),
                )
            )
        return out

    async def turnover(self) -> list[TurnoverOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)

        cogs_result = await self.session.execute(
            select(
                Product.id,
                Product.name,
                func.coalesce(
                    func.sum(SalesInvoiceLine.quantity * SalesInvoiceLine.unit_cost), 0
                ),
            )
            .join(SalesInvoiceLine, SalesInvoiceLine.product_id == Product.id)
            .join(SalesInvoice, SalesInvoiceLine.invoice_id == SalesInvoice.id)
            .where(
                SalesInvoice.invoice_date >= window_start,
                SalesInvoiceLine.unit_cost.is_not(None),
            )
            .group_by(Product.id, Product.name)
        )
        cogs_rows = cogs_result.all()

        stock_result = await self.session.execute(
            select(
                ProductBatch.product_id,
                func.coalesce(
                    func.sum(ProductBatch.quantity * ProductBatch.unit_cost), 0
                ),
            )
            .where(ProductBatch.quantity > 0, ProductBatch.unit_cost.is_not(None))
            .group_by(ProductBatch.product_id)
        )
        stock_value = {pid: _d(v) for pid, v in stock_result.all()}

        out = []
        for pid, name, cogs in cogs_rows:
            cogs_d = _d(cogs)
            stock_v = stock_value.get(pid, Decimal("0"))
            ratio = (cogs_d / stock_v).quantize(TWO_PLACES) if stock_v > 0 else None
            out.append(
                TurnoverOut(
                    product_id=pid,
                    product_name=name,
                    cogs_12m=cogs_d.quantize(TWO_PLACES),
                    stock_on_hand_value=stock_v.quantize(TWO_PLACES),
                    turnover_ratio=ratio,
                )
            )
        return sorted(out, key=lambda r: r.cogs_12m, reverse=True)

    # --- Financial / credit ---
    async def ar_aging(self) -> list[ARAgingRowOut]:
        today = date.today()
        result = await self.session.execute(
            select(Customer).where(Customer.credit_limit > 0)
        )
        customers = list(result.scalars().all())

        out = []
        for customer in customers:
            balance = await self.sales.customer_balance(customer.id)
            if balance <= 0:
                continue
            inv_result = await self.session.execute(
                select(SalesInvoice.invoice_date, SalesInvoice.total)
                .where(
                    SalesInvoice.customer_id == customer.id,
                    SalesInvoice.payment_method == SalesPaymentMethod.CREDIT,
                )
                .order_by(SalesInvoice.invoice_date.desc())
            )
            invoices = inv_result.all()

            buckets = {
                "0_30": Decimal("0"),
                "31_60": Decimal("0"),
                "61_90": Decimal("0"),
                "90_plus": Decimal("0"),
            }
            remaining = balance
            for invoice_date, total in invoices:
                if remaining <= 0:
                    break
                portion = min(_d(total), remaining)
                age = (today - invoice_date).days
                if age <= 30:
                    buckets["0_30"] += portion
                elif age <= 60:
                    buckets["31_60"] += portion
                elif age <= 90:
                    buckets["61_90"] += portion
                else:
                    buckets["90_plus"] += portion
                remaining -= portion

            out.append(
                ARAgingRowOut(
                    customer_id=customer.id,
                    customer_name=customer.name,
                    bucket_0_30=buckets["0_30"].quantize(TWO_PLACES),
                    bucket_31_60=buckets["31_60"].quantize(TWO_PLACES),
                    bucket_61_90=buckets["61_90"].quantize(TWO_PLACES),
                    bucket_90_plus=buckets["90_plus"].quantize(TWO_PLACES),
                    total_outstanding=balance.quantize(TWO_PLACES),
                )
            )
        return sorted(out, key=lambda r: r.total_outstanding, reverse=True)

    async def credit_risk(self) -> list[CreditRiskCustomerOut]:
        rfm = {r.customer_id: r for r in await self.customer_rfm()}
        result = await self.session.execute(
            select(Customer).where(Customer.credit_limit > 0)
        )
        customers = list(result.scalars().all())

        out = []
        for customer in customers:
            balance = await self.sales.customer_balance(customer.id)
            if balance <= 0:
                continue
            utilization = _pct(balance, customer.credit_limit)
            rfm_row = rfm.get(customer.id)
            out.append(
                CreditRiskCustomerOut(
                    customer_id=customer.id,
                    customer_name=customer.name,
                    outstanding_balance=balance.quantize(TWO_PLACES),
                    credit_limit=customer.credit_limit,
                    utilization_pct=utilization,
                    recency_days=rfm_row.recency_days if rfm_row else None,
                )
            )
        return sorted(out, key=lambda r: r.utilization_pct, reverse=True)

    # --- Delivery & fulfillment ---
    async def fulfillment_summary(self) -> list[FulfillmentSummaryOut]:
        result = await self.session.execute(
            select(
                SalesInvoice.id,
                SalesInvoice.fulfillment,
                SalesInvoice.picked_up_at,
                DeliveryStop.status,
            ).outerjoin(DeliveryStop, DeliveryStop.invoice_id == SalesInvoice.id)
        )
        pickup_total = pickup_done = 0
        delivery_total = delivery_done = 0
        for _id, fulfillment, picked_up_at, stop_status in result.all():
            if fulfillment.value == "pickup":
                pickup_total += 1
                if picked_up_at is not None:
                    pickup_done += 1
            else:
                delivery_total += 1
                if stop_status is not None and stop_status.value == "delivered":
                    delivery_done += 1

        return [
            FulfillmentSummaryOut(
                fulfillment="delivery",
                invoice_count=delivery_total,
                completed_count=delivery_done,
                failed_or_pending_count=delivery_total - delivery_done,
                completion_rate_pct=_pct(
                    Decimal(delivery_done), Decimal(delivery_total)
                ),
            ),
            FulfillmentSummaryOut(
                fulfillment="pickup",
                invoice_count=pickup_total,
                completed_count=pickup_done,
                failed_or_pending_count=pickup_total - pickup_done,
                completion_rate_pct=_pct(Decimal(pickup_done), Decimal(pickup_total)),
            ),
        ]

    async def driver_performance(self) -> list[DriverPerformanceOut]:
        result = await self.session.execute(
            select(DeliveryTrip.driver_name, DeliveryStop.status, DeliveryTrip.id).join(
                DeliveryStop, DeliveryStop.trip_id == DeliveryTrip.id
            )
        )
        by_driver: dict[str, dict] = defaultdict(
            lambda: {"trips": set(), "delivered": 0, "failed": 0}
        )
        for driver_name, status, trip_id in result.all():
            b = by_driver[driver_name]
            b["trips"].add(trip_id)
            if status.value == "delivered":
                b["delivered"] += 1
            elif status.value == "failed":
                b["failed"] += 1

        out = []
        for driver_name, b in by_driver.items():
            total_stops = b["delivered"] + b["failed"]
            out.append(
                DriverPerformanceOut(
                    driver_name=driver_name,
                    trip_count=len(b["trips"]),
                    delivered_stops=b["delivered"],
                    failed_stops=b["failed"],
                    failure_rate_pct=_pct(Decimal(b["failed"]), Decimal(total_stops)),
                )
            )
        return sorted(out, key=lambda r: r.trip_count, reverse=True)

    # --- Sales rep performance ---
    async def rep_performance(self) -> list[RepPerformanceOut]:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)

        result = await self.session.execute(
            select(
                User.id,
                User.full_name,
                func.coalesce(func.sum(SalesInvoice.total), 0),
                func.count(SalesInvoice.id),
                func.count(func.distinct(SalesInvoice.customer_id)),
            )
            .join(Customer, Customer.salesman_id == User.id)
            .join(SalesInvoice, SalesInvoice.customer_id == Customer.id)
            .where(SalesInvoice.invoice_date >= window_start)
            .group_by(User.id, User.full_name)
        )
        rows = result.all()

        returns_result = await self.session.execute(
            select(User.id, func.coalesce(func.sum(SalesReturn.total), 0))
            .join(Customer, Customer.salesman_id == User.id)
            .join(SalesReturn, SalesReturn.customer_id == Customer.id)
            .where(SalesReturn.created_at >= window_start)
            .group_by(User.id)
        )
        returns_by_rep = {uid: _d(t) for uid, t in returns_result.all()}

        out = []
        for uid, name, revenue, invoice_count, customer_count in rows:
            revenue_d = _d(revenue)
            avg_basket = (
                (revenue_d / invoice_count).quantize(TWO_PLACES)
                if invoice_count
                else Decimal("0")
            )
            out.append(
                RepPerformanceOut(
                    salesman_id=uid,
                    salesman_name=name,
                    revenue=revenue_d.quantize(TWO_PLACES),
                    invoice_count=invoice_count,
                    avg_basket=avg_basket,
                    customer_count=customer_count,
                    return_rate_pct=_pct(
                        returns_by_rep.get(uid, Decimal("0")), revenue_d
                    ),
                )
            )
        return sorted(out, key=lambda r: r.revenue, reverse=True)

    # --- Top-level KPIs ---
    async def dashboard_summary(self) -> DashboardSummaryOut:
        today = date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)

        revenue_result = await self.session.execute(
            select(
                func.coalesce(func.sum(SalesInvoice.total), 0),
                func.count(SalesInvoice.id),
                func.count(func.distinct(SalesInvoice.customer_id)),
            ).where(SalesInvoice.invoice_date >= window_start)
        )
        total_revenue, invoice_count, active_customers = revenue_result.one()
        total_revenue = _d(total_revenue)

        cogs_result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(SalesInvoiceLine.quantity * SalesInvoiceLine.unit_cost), 0
                )
            )
            .join(SalesInvoice, SalesInvoiceLine.invoice_id == SalesInvoice.id)
            .where(
                SalesInvoice.invoice_date >= window_start,
                SalesInvoiceLine.unit_cost.is_not(None),
            )
        )
        total_cogs = _d(cogs_result.scalar_one())
        total_margin = total_revenue - total_cogs

        returns_result = await self.session.execute(
            select(func.coalesce(func.sum(SalesReturn.total), 0)).where(
                SalesReturn.created_at >= window_start
            )
        )
        total_returns = _d(returns_result.scalar_one())

        # Global AR outstanding = sum of every customer's running balance (all-time,
        # not just the trailing window — it's a point-in-time snapshot).
        opening = _d(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(Customer.opening_balance), 0))
                )
            ).scalar_one()
        )
        all_invoiced = _d(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(SalesInvoice.total), 0))
                )
            ).scalar_one()
        )
        all_paid = _d(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(SalesInvoice.paid_amount), 0))
                )
            ).scalar_one()
        )
        all_returned = _d(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(SalesReturn.total), 0))
                )
            ).scalar_one()
        )
        all_payments = _d(
            (
                await self.session.execute(
                    select(func.coalesce(func.sum(CustomerPayment.amount), 0))
                )
            ).scalar_one()
        )
        ar_outstanding = opening + all_invoiced - all_paid - all_returned - all_payments

        waste_risk = await self.expiry_risk(days=30)
        waste_value = sum((row.value_at_risk for row in waste_risk), Decimal("0"))

        avg_order = (
            (total_revenue / invoice_count).quantize(TWO_PLACES)
            if invoice_count
            else Decimal("0")
        )

        return DashboardSummaryOut(
            total_revenue_12m=total_revenue.quantize(TWO_PLACES),
            total_margin_12m=total_margin.quantize(TWO_PLACES),
            invoice_count_12m=invoice_count,
            active_customers_12m=active_customers,
            ar_outstanding=ar_outstanding.quantize(TWO_PLACES),
            waste_risk_value_30d=waste_value.quantize(TWO_PLACES),
            avg_order_value=avg_order,
            return_rate_pct_12m=_pct(total_returns, total_revenue),
        )

    async def damage_report(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> DamageReportOut:
        """Written-off stock over a period, broken down by reason and by product.

        Cancelled write-offs are excluded: their goods went back to stock, so
        counting them would overstate the loss.
        """
        stmt = (
            select(StockAdjustment, StockAdjustmentLine, Product)
            .join(StockAdjustmentLine, StockAdjustmentLine.adjustment_id == StockAdjustment.id)
            .join(Product, Product.id == StockAdjustmentLine.product_id)
            .where(StockAdjustment.status != AdjustmentStatus.CANCELLED)
        )
        if date_from is not None:
            stmt = stmt.where(func.date(StockAdjustment.created_at) >= date_from)
        if date_to is not None:
            stmt = stmt.where(func.date(StockAdjustment.created_at) <= date_to)
        rows = (await self.session.execute(stmt)).all()

        adjustment_ids: set[int] = set()
        total_quantity = Decimal("0")
        total_cost = Decimal("0")
        by_reason: dict[str, dict] = defaultdict(
            lambda: {"ids": set(), "quantity": Decimal("0"), "cost": Decimal("0")}
        )
        by_product: dict[int, dict] = {}

        for adjustment, line, product in rows:
            adjustment_ids.add(adjustment.id)
            total_quantity += line.quantity
            total_cost += line.line_total

            reason = adjustment.reason.value
            by_reason[reason]["ids"].add(adjustment.id)
            by_reason[reason]["quantity"] += line.quantity
            by_reason[reason]["cost"] += line.line_total

            entry = by_product.setdefault(
                product.id,
                {
                    "name": product.name,
                    "unit": product.base_unit_name,
                    "quantity": Decimal("0"),
                    "cost": Decimal("0"),
                },
            )
            entry["quantity"] += line.quantity
            entry["cost"] += line.line_total

        return DamageReportOut(
            date_from=date_from,
            date_to=date_to,
            adjustment_count=len(adjustment_ids),
            total_quantity=total_quantity,
            total_cost=total_cost.quantize(TWO_PLACES),
            by_reason=[
                DamageByReasonOut(
                    reason=reason,
                    adjustment_count=len(data["ids"]),
                    total_quantity=data["quantity"],
                    total_cost=data["cost"].quantize(TWO_PLACES),
                )
                for reason, data in sorted(
                    by_reason.items(), key=lambda kv: kv[1]["cost"], reverse=True
                )
            ],
            by_product=[
                DamageByProductOut(
                    product_id=pid,
                    product_name=data["name"],
                    base_unit_name=data["unit"],
                    total_quantity=data["quantity"],
                    total_cost=data["cost"].quantize(TWO_PLACES),
                )
                for pid, data in sorted(
                    by_product.items(), key=lambda kv: kv[1]["cost"], reverse=True
                )
            ],
        )

    async def discount_report(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> DiscountReportOut:
        """Discounts granted on invoices over a period, by customer and salesman.

        Only invoices whose collectable amount was adjusted down appear here, so
        the list is exactly the set of concessions given.
        """
        stmt = (
            select(SalesInvoice, Customer.name, User.full_name)
            .join(Customer, Customer.id == SalesInvoice.customer_id)
            .outerjoin(User, User.id == SalesInvoice.salesman_id)
            .where(SalesInvoice.discount_amount > 0)
            .order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.id.desc())
        )
        if date_from is not None:
            stmt = stmt.where(SalesInvoice.invoice_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(SalesInvoice.invoice_date <= date_to)
        rows = (await self.session.execute(stmt)).all()

        total_discount = Decimal("0")
        total_gross = Decimal("0")
        total_net = Decimal("0")
        by_customer: dict[int, dict] = {}
        by_salesman: dict[int | None, dict] = {}
        invoices: list[DiscountInvoiceOut] = []

        for invoice, customer_name, salesman_name in rows:
            gross = invoice.subtotal + invoice.vat_amount
            total_discount += invoice.discount_amount
            total_gross += gross
            total_net += invoice.total

            customer = by_customer.setdefault(
                invoice.customer_id,
                {"name": customer_name, "count": 0, "discount": Decimal("0")},
            )
            customer["count"] += 1
            customer["discount"] += invoice.discount_amount

            salesman = by_salesman.setdefault(
                invoice.salesman_id,
                {
                    "name": salesman_name or "بدون مندوب",
                    "count": 0,
                    "discount": Decimal("0"),
                },
            )
            salesman["count"] += 1
            salesman["discount"] += invoice.discount_amount

            invoices.append(
                DiscountInvoiceOut(
                    invoice_id=invoice.id,
                    invoice_date=invoice.invoice_date,
                    customer_name=customer_name,
                    salesman_name=salesman_name,
                    gross_amount=gross.quantize(TWO_PLACES),
                    discount_amount=invoice.discount_amount,
                    total=invoice.total,
                )
            )

        return DiscountReportOut(
            date_from=date_from,
            date_to=date_to,
            invoice_count=len(invoices),
            total_discount=total_discount.quantize(TWO_PLACES),
            total_gross=total_gross.quantize(TWO_PLACES),
            total_net=total_net.quantize(TWO_PLACES),
            by_customer=[
                DiscountByCustomerOut(
                    customer_id=cid,
                    customer_name=data["name"],
                    invoice_count=data["count"],
                    discount_amount=data["discount"].quantize(TWO_PLACES),
                )
                for cid, data in sorted(
                    by_customer.items(), key=lambda kv: kv[1]["discount"], reverse=True
                )
            ],
            by_salesman=[
                DiscountBySalesmanOut(
                    salesman_id=sid,
                    salesman_name=data["name"],
                    invoice_count=data["count"],
                    discount_amount=data["discount"].quantize(TWO_PLACES),
                )
                for sid, data in sorted(
                    by_salesman.items(), key=lambda kv: kv[1]["discount"], reverse=True
                )
            ],
            invoices=invoices,
        )
