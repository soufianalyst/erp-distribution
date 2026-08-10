"""Actionable alerts for the dashboard.

This service owns no data of its own: every alert is an existing report, read
through the module that already knows how to compute it, then reduced to "how
many, how bad, and where do I go to fix it". Keeping the queries where they live
means an alert can never drift away from the report it summarises.

Each group is gated by the permission needed to *act* on it, so a salesman is
never shown purchase-order or warehouse work they cannot do anything about.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.analytics import AlertGroupOut, AlertItemOut, AlertsOut
from app.core import arabic
from app.core.permissions import effective_permissions, has_permission
from app.domain.models.inventory import Stocktake, StocktakeStatus, Warehouse
from app.domain.models.sales import Customer, CustomerOrder, CustomerOrderStatus
from app.domain.models.purchases import (
    PurchaseOrder,
    PurchaseOrderStatus,
    Supplier,
)
from app.services.analytics.analytics_service import AnalyticsService
from app.services.inventory.stock_service import StockService
from app.services.sales.round_settlement_service import RoundSettlementService
from app.domain.models.user import User

# How many examples to carry per group; the dashboard shows a preview, not a report.
PREVIEW_LIMIT = 5
# Batches inside this window count as expiring soon (already-expired is separate).
EXPIRY_WINDOW_DAYS = 30

# How long a customer's order may sit unanswered before it stops being "new" and
# becomes a problem. Four hours is roughly half a working day: long enough that a
# busy morning does not raise a false alarm, short enough that nothing waits
# overnight without shouting about it.
PENDING_ORDER_CRITICAL_HOURS = 4


class AlertsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stock = StockService(session)
        self.analytics = AnalyticsService(session)
        self.settlements = RoundSettlementService(session)

    async def alerts(self, user: User) -> AlertsOut:
        """Every alert the caller is able to act on, worst first.

        Takes the user rather than a permission set because some alerts are scoped
        to them as well as gated by them: a salesman's order queue is his own
        customers', not the company's. Passing permissions alone made that
        impossible to express, and optional scoping is the kind of argument someone
        eventually forgets to pass.
        """
        permissions = effective_permissions(user)
        groups: list[AlertGroupOut] = []

        if "stock.view" in permissions:
            groups.extend(await self._expiry_groups())
        if "purchases.orders" in permissions or "purchases.view" in permissions:
            groups.extend(await self._reorder_group())
            groups.extend(await self._overdue_order_group())
        if "stock.stocktake" in permissions:
            groups.extend(await self._open_stocktake_group())
        if "sales.round_settle" in permissions:
            groups.extend(await self._unsettled_round_group())
        if "customers.view" in permissions:
            groups.extend(await self._credit_group())
        if "sales.orders_review" in permissions:
            groups.extend(await self._pending_orders_group(user))

        # Critical first, then by how many items are waiting.
        severity_rank = {"critical": 0, "warning": 1, "info": 2}
        groups.sort(key=lambda g: (severity_rank[g.severity], -g.count))
        return AlertsOut(
            generated_at=date.today(),
            critical_count=sum(1 for g in groups if g.severity == "critical"),
            warning_count=sum(1 for g in groups if g.severity == "warning"),
            groups=groups,
        )

    async def _pending_orders_group(self, user: User) -> list[AlertGroupOut]:
        """Orders a shop has sent that nobody has answered yet.

        The only alert here that represents a customer actively waiting on us
        rather than housekeeping we owe ourselves. A shop that ordered through the
        portal is standing at their counter wondering whether it went through; every
        hour it sits unanswered is an hour they might spend phoning a competitor.

        That is why waiting time drives the severity rather than the count. One
        order from this morning is routine; one order from yesterday is a problem,
        and a single unanswered request is worse than five that arrived a minute
        ago.

        Scoped to the rep's own customers, matching the review queue exactly — an
        alert about work someone cannot do is noise, and it names shops they have no
        business seeing.
        """
        query = (
            select(CustomerOrder, Customer.name)
            .join(Customer, Customer.id == CustomerOrder.customer_id)
            .where(CustomerOrder.status == CustomerOrderStatus.PENDING)
            .order_by(CustomerOrder.created_at)
        )
        if not has_permission(user, "sales.all_customers"):
            query = query.where(Customer.salesman_id == user.id)

        rows = (await self.session.execute(query)).all()
        if not rows:
            return []

        now = datetime.now(timezone.utc)
        oldest, _ = rows[0]
        waited = now - self._as_utc(oldest.created_at)
        hours = waited.total_seconds() / 3600

        overdue = hours >= PENDING_ORDER_CRITICAL_HOURS
        return [
            AlertGroupOut(
                key="pending_customer_orders",
                label=(
                    "طلبات عملاء لم يُرد عليها بعد"
                    if overdue
                    else "طلبات جديدة من بوابة العملاء"
                ),
                severity="critical" if overdue else "warning",
                count=len(rows),
                hint=(
                    f"أقدم طلب ينتظر منذ {self._waited(waited)} — راجعه الآن قبل أن "
                    "يطلب العميل من غيرنا."
                    if overdue
                    else "راجع الطلب واعتمده أو أصدر فاتورته."
                ),
                route="/customer-requests",
                items=[
                    AlertItemOut(
                        label=name,
                        detail=(
                            "توصيل"
                            if order.fulfillment.value == "delivery"
                            else "استلام من المستودع"
                        ),
                        value=f"منذ {self._waited(now - self._as_utc(order.created_at))}",
                    )
                    for order, name in rows[:PREVIEW_LIMIT]
                ],
            )
        ]

    @staticmethod
    def _as_utc(moment: datetime) -> datetime:
        """SQLite hands back naive datetimes for `DateTime(timezone=True)`.

        Postgres returns aware ones, so subtracting `now()` works in production and
        raises in the test suite — a difference that only shows up where it is least
        convenient to discover.
        """
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    @staticmethod
    def _waited(delta) -> str:
        """How long, in words a person would use."""
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            return f"{max(minutes, 1)} دقيقة"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} ساعة"
        return f"{hours // 24} يوم"

    async def _expiry_groups(self) -> list[AlertGroupOut]:
        """Expired stock is a loss already on the shelf; near-expiry is still sellable."""
        batches = await self.stock.near_expiry(EXPIRY_WINDOW_DAYS)
        expired = [b for b in batches if b.days_remaining < 0]
        expiring = [b for b in batches if b.days_remaining >= 0]

        groups: list[AlertGroupOut] = []
        if expired:
            groups.append(
                AlertGroupOut(
                    key="expired_stock",
                    label="تشغيلات منتهية الصلاحية وما زالت في المخزون",
                    severity="critical",
                    count=len(expired),
                    hint="أخرجها من المخزون بتسجيل إتلاف حتى لا تُصرف للعملاء.",
                    route="/stock",
                    items=[
                        AlertItemOut(
                            label=b.product_name,
                            detail=f"{b.warehouse_name} — تشغيلة {b.batch_number}",
                            value=f"منتهية منذ {-b.days_remaining} يوم",
                        )
                        for b in expired[:PREVIEW_LIMIT]
                    ],
                )
            )
        if expiring:
            groups.append(
                AlertGroupOut(
                    key="near_expiry",
                    label=f"تشغيلات تنتهي خلال {EXPIRY_WINDOW_DAYS} يوماً",
                    severity="warning",
                    count=len(expiring),
                    hint="صرّفها أولاً (FEFO) أو خصّصها لعرض بيع قبل انتهائها.",
                    route="/stock",
                    items=[
                        AlertItemOut(
                            label=b.product_name,
                            detail=f"{b.warehouse_name} — تشغيلة {b.batch_number}",
                            value=f"{b.days_remaining} يوم",
                        )
                        for b in expiring[:PREVIEW_LIMIT]
                    ],
                )
            )
        return groups

    async def _reorder_group(self) -> list[AlertGroupOut]:
        """Out of stock is lost sales today; at/below minimum is a warning."""
        suggestions = await self.stock.reorder_suggestions()
        if not suggestions:
            return []
        out_of_stock = [s for s in suggestions if s.out_of_stock]
        low = [s for s in suggestions if not s.out_of_stock]

        groups: list[AlertGroupOut] = []
        if out_of_stock:
            groups.append(
                AlertGroupOut(
                    key="out_of_stock",
                    label="أصناف نفدت من المخزون",
                    severity="critical",
                    count=len(out_of_stock),
                    hint="أضفها إلى طلب شراء جديد؛ القائمة جاهزة في وحدة المشتريات.",
                    route="/purchases",
                    items=[
                        AlertItemOut(
                            label=s.name,
                            detail=s.sku,
                            value="نفد",
                        )
                        for s in out_of_stock[:PREVIEW_LIMIT]
                    ],
                )
            )
        if low:
            groups.append(
                AlertGroupOut(
                    key="below_minimum",
                    label="أصناف وصلت حدها الأدنى",
                    severity="warning",
                    count=len(low),
                    hint="راجع كمياتها قبل أن تنفد وأضفها لطلب الشراء القادم.",
                    route="/purchases",
                    items=[
                        AlertItemOut(
                            label=s.name,
                            detail=f"{s.sku} — المتوفر {s.current_stock} {s.base_unit_name}",
                            value=f"ينقص {s.shortfall}",
                        )
                        for s in low[:PREVIEW_LIMIT]
                    ],
                )
            )
        return groups

    async def _overdue_order_group(self) -> list[AlertGroupOut]:
        """Orders past their expected delivery date and still not fully received."""
        result = await self.session.execute(
            select(PurchaseOrder, Supplier.name)
            .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
            .options(selectinload(PurchaseOrder.lines))
            .where(
                PurchaseOrder.expected_date.is_not(None),
                PurchaseOrder.expected_date < date.today(),
                PurchaseOrder.status.in_(
                    [PurchaseOrderStatus.SENT, PurchaseOrderStatus.PARTIALLY_RECEIVED]
                ),
            )
            .order_by(PurchaseOrder.expected_date)
        )
        rows = result.all()
        if not rows:
            return []
        return [
            AlertGroupOut(
                key="overdue_orders",
                label="طلبات شراء تأخر توريدها",
                severity="warning",
                count=len(rows),
                hint="تابع المورد، أو ألغِ ما تبقى على الطلب إن لم يعد متوقعاً.",
                route="/purchases",
                items=[
                    AlertItemOut(
                        label=f"طلب شراء رقم {order.id}",
                        detail=supplier_name,
                        value=f"متأخر {(date.today() - order.expected_date).days} يوم",
                    )
                    for order, supplier_name in rows[:PREVIEW_LIMIT]
                ],
            )
        ]

    async def _open_stocktake_group(self) -> list[AlertGroupOut]:
        """A count left open blocks the next one for that warehouse."""
        result = await self.session.execute(
            select(Stocktake, Warehouse.name)
            .join(Warehouse, Stocktake.warehouse_id == Warehouse.id)
            .options(selectinload(Stocktake.lines))
            .where(Stocktake.status == StocktakeStatus.COUNTING)
            .order_by(Stocktake.count_date)
        )
        rows = result.all()
        if not rows:
            return []
        return [
            AlertGroupOut(
                key="open_stocktakes",
                label="عمليات جرد مفتوحة لم تُثبّت",
                severity="info",
                count=len(rows),
                hint="أكمل الجرد وثبّت الفروقات، أو ألغِه — الجرد المفتوح يمنع بدء جرد جديد لنفس المستودع.",
                route="/stock",
                items=[
                    AlertItemOut(
                        label=f"جرد رقم {stocktake.id}",
                        detail=warehouse_name,
                        value=(
                            f"{stocktake.counted_line_count} من "
                            f"{stocktake.line_count} سطر"
                        ),
                    )
                    for stocktake, warehouse_name in rows[:PREVIEW_LIMIT]
                ],
            )
        ]

    async def _unsettled_round_group(self) -> list[AlertGroupOut]:
        """Vans that sold today and have not been closed off.

        This is the alert the settlement feature exists for. Before it, a round
        that was never closed looked exactly like a round that had no sales — the
        absence of a record is invisible by nature, so nothing on any screen could
        distinguish "nothing happened" from "nobody checked". A van with uncollected
        cash is the sharper case and is escalated: that is money in a pocket
        overnight, not paperwork.
        """
        pending = await self.settlements.unsettled_rounds()
        if not pending:
            return []
        owing = [r for r in pending if r["cash_outstanding"] > 0]
        if owing:
            severity, rows = "critical", owing
            label = "جولات لم تُسوَّ ونقدها لم يُحصَّل"
            hint = (
                "حصّل نقد الجولة من صندوق الكاشير ثم أقفلها — "
                "النقد غير المحصَّل يمنع الإقفال."
            )
        else:
            severity, rows = "warning", pending
            label = "جولات مناديب لم تُسوَّ بعد"
            hint = "اجرد المركبة وأقفل الجولة لتثبيت مبيعات اليوم."
        return [
            AlertGroupOut(
                key="unsettled_rounds",
                label=label,
                severity=severity,
                count=len(rows),
                hint=hint,
                route="/rounds",
                items=[
                    AlertItemOut(
                        label=r["warehouse_name"],
                        detail=f"{r['salesman_name']} — {arabic.invoices(r['invoice_count'])}",
                        value=(
                            f"غير محصَّل {r['cash_outstanding']}"
                            if r["cash_outstanding"] > 0
                            else "جاهزة للإقفال"
                        ),
                    )
                    for r in rows[:PREVIEW_LIMIT]
                ],
            )
        ]

    async def _credit_group(self) -> list[AlertGroupOut]:
        """Customers at or past their credit limit; further credit sales need approval."""
        at_risk = await self.analytics.credit_risk()
        over = [c for c in at_risk if c.utilization_pct >= Decimal("100")]
        if not over:
            return []
        return [
            AlertGroupOut(
                key="over_credit_limit",
                label="عملاء تجاوزوا حدهم الائتماني",
                severity="critical",
                count=len(over),
                hint="حصّل من رصيدهم قبل أي بيع آجل جديد؛ البيع فوق الحد يتطلب موافقة المدير.",
                route="/customers",
                items=[
                    AlertItemOut(
                        label=c.customer_name,
                        detail=f"الحد {c.credit_limit} — المستحق {c.outstanding_balance}",
                        value=f"{c.utilization_pct}%",
                    )
                    for c in over[:PREVIEW_LIMIT]
                ],
            )
        ]
