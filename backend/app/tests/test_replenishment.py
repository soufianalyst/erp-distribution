"""When to reorder, judged against demand instead of a number somebody typed.

The old rule was `stock <= min_stock_level`, and on the seeded database it matched
nothing at all while 329 of 1,060 products carried a minimum of zero — meaning their
first warning would arrive once the shelf was already empty. In food distribution
that is not a late warning, it is a lost order.

What these tests hold is mostly restraint. It is easy to compute a reorder point for
everything; the hard part is refusing to, for the 439 products that sold on three
days or fewer in a year, where a mean and a standard deviation would be noise
wearing the clothes of arithmetic. A fabricated number is worse than the buyer's own
guess precisely because it looks calculated.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

from app.domain.models.sales import SalesInvoice
from app.services.inventory.demand_service import DemandConfidence, DemandService
from app.services.inventory.replenishment import ReplenishmentSettings, reorder_for
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer, post_invoice

SETTINGS = ReplenishmentSettings(lead_time_days=7, safety_stock_days=7, review_days=14)


async def sell_on_days(
    client: AsyncClient, admin: dict, db_session, customer_id: int,
    warehouse_id: int, product_id: int, days_ago: list[int], quantity: str
) -> None:
    """Place invoices and backdate them, so demand has a history to measure."""
    for offset in days_ago:
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, quantity,
            tax_rate_ids=[])
        assert response.status_code == 201, response.text
        invoice = await db_session.get(SalesInvoice, response.json()["data"]["id"])
        invoice.invoice_date = date.today() - timedelta(days=offset)
    await db_session.commit()


async def a_product_that_sells(
    client: AsyncClient, admin: dict, db_session, *, sale_days: int, each: str = "10",
    sku: str = "REP-1", stock: str = "2000",
) -> tuple[int, int, int]:
    """A stocked product sold on `sale_days` separate days over the past year."""
    warehouse_id = await create_warehouse(client, admin, f"مخزن {sku}")
    product = await create_product(client, admin, sku=sku, warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, f"B-{sku}", 300, stock)
    customer_id = await create_customer(
        client, admin, name=f"عميل {sku}", credit_limit="900000")
    # Spread across the year so they are distinct sale-days, not one busy week.
    offsets = [7 * (i + 1) for i in range(sale_days)]
    await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                       product["id"], offsets, each)
    return warehouse_id, product["id"], customer_id


class TestItComputesOnlyWhatItCanMeasure:
    async def test_a_regular_seller_gets_a_point_from_its_own_rate(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product_id, _ = await a_product_that_sells(
            client, admin, db_session, sale_days=20, each="10", sku="REG-1")

        demand = (await DemandService(db_session).for_products(
            [product_id], default_lead_time_days=7))[product_id]
        assert demand.confidence is DemandConfidence.MEASURED
        assert demand.sale_days == 20

        plan = reorder_for(demand, Decimal("50"), Decimal("0"), SETTINGS)
        assert plan.computed is True
        # 200 units over 365 days ≈ 0.548/day, over 14 days of cover ≈ 8.
        assert plan.reorder_point == (demand.daily_rate * 14).quantize(Decimal("1"))
        assert "يبيع" in plan.basis and "نقطة الطلب" in plan.basis

    async def test_a_product_sold_three_times_keeps_the_human_number(
        self, client: AsyncClient, db_session
    ) -> None:
        """The restraint that matters.

        439 of 1,060 products are in this state. A rate from three sale-days moves
        more with one unusual order than with the underlying trade, and a reorder
        point built on it would carry the authority of a calculation without the
        substance of one.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product_id, _ = await a_product_that_sells(
            client, admin, db_session, sale_days=3, each="5", sku="RARE-1")

        demand = (await DemandService(db_session).for_products(
            [product_id], default_lead_time_days=7))[product_id]
        assert demand.confidence is DemandConfidence.SPARSE

        plan = reorder_for(demand, Decimal("10"), Decimal("40"), SETTINGS)
        assert plan.computed is False
        assert plan.reorder_point == Decimal("40")  # the typed minimum, untouched
        assert "غير كافٍ" in plan.basis

    async def test_a_product_that_never_sold_does_not_get_a_point_of_zero(
        self, client: AsyncClient, db_session
    ) -> None:
        """Zero demand must not become "reorder at zero".

        A product with no recorded sales still sells — it may be new, or seasonal.
        Setting its threshold to nothing is how an item quietly falls out of the
        catalogue and is never ordered again.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الجديد")
        product = await create_product(
            client, admin, sku="NEW-1", warehouse_id=warehouse_id)

        demand = (await DemandService(db_session).for_products(
            [product["id"]], default_lead_time_days=7))[product["id"]]
        assert demand.confidence is DemandConfidence.NONE

        plan = reorder_for(demand, Decimal("0"), Decimal("25"), SETTINGS)
        assert plan.reorder_point == Decimal("25")
        assert plan.computed is False


class TestTheOrderQuantity:
    async def test_it_covers_until_the_next_order_not_just_the_delivery(
        self, client: AsyncClient, db_session
    ) -> None:
        """Ordering only up to the reorder point means reordering the same shortfall
        at every review. The quantity has to span the review period too."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product_id, _ = await a_product_that_sells(
            client, admin, db_session, sale_days=30, each="20", sku="QTY-1")

        demand = (await DemandService(db_session).for_products(
            [product_id], default_lead_time_days=7))[product_id]
        plan = reorder_for(demand, Decimal("0"), Decimal("0"), SETTINGS)

        # 7 lead + 7 safety + 14 review = 28 days of demand, from empty.
        assert plan.suggested_quantity == (demand.daily_rate * 28).quantize(Decimal("1"))
        assert plan.suggested_quantity > plan.reorder_point

    async def test_it_never_orders_more_than_will_sell_before_it_expires(
        self, client: AsyncClient, db_session
    ) -> None:
        """The part a generic ERP gets wrong.

        Economic order quantity says buy more and save on ordering cost. The yoghurt
        disagrees. Here the batch history says the goods keep ten days, so a 28-day
        order would put eighteen days of stock in the bin.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن سريع التلف")
        product = await create_product(
            client, admin, sku="FRESH-1", warehouse_id=warehouse_id)
        # Received with only ten days to expiry — that is this product's shelf life.
        await receive(client, admin, product["id"], warehouse_id, "B-FRESH", 10, "2000")
        customer_id = await create_customer(
            client, admin, name="عميل الطازج", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(30)], "20")

        demand = (await DemandService(db_session).for_products(
            [product["id"]], default_lead_time_days=7))[product["id"]]
        assert demand.shelf_life_days is not None and demand.shelf_life_days <= 11

        plan = reorder_for(demand, Decimal("0"), Decimal("0"), SETTINGS)
        assert plan.capped_by_expiry is True
        # Ten days of sales, not twenty-eight.
        assert plan.suggested_quantity <= (
            demand.daily_rate * Decimal(demand.shelf_life_days)
        ).quantize(Decimal("1"))
        assert "الصلاحية" in plan.basis


class TestLeadTimeComesFromTheSupplierWhereKnown:
    async def test_a_supplier_lead_time_beats_the_company_default(
        self, client: AsyncClient, db_session
    ) -> None:
        """A local dairy delivers tomorrow and imported rice takes a month. One
        averaged figure orders the dairy far too early and the rice far too late."""
        from app.domain.models.purchases import Supplier
        from app.tests.test_purchases import create_supplier

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التوريد")
        product = await create_product(
            client, admin, sku="LEAD-1", warehouse_id=warehouse_id)
        supplier_id = await create_supplier(client, admin, name="مورد بعيد")

        supplier = await db_session.get(Supplier, supplier_id)
        supplier.lead_time_days = 30
        await db_session.commit()

        bought = await client.post("/api/v1/purchases/invoices", headers=admin, json={
            "supplier_id": supplier_id, "warehouse_id": warehouse_id,
            "payment_method": "credit", "tax_rate_ids": [],
            "lines": [{"product_id": product["id"], "batch_number": "B-LEAD",
                       "expiry_date": str(date.today() + timedelta(days=200)),
                       "quantity": "100", "unit_cost": "5"}],
        })
        assert bought.status_code == 201, bought.text

        demand = (await DemandService(db_session).for_products(
            [product["id"]], default_lead_time_days=7))[product["id"]]
        assert demand.lead_time_days == 30, "لم تُستخدم مهلة المورد"
        assert demand.supplier_name == "مورد بعيد"


class TestTheListItself:
    async def test_a_well_stocked_product_is_not_on_it(
        self, client: AsyncClient, db_session
    ) -> None:
        """What the seeded warehouse actually shows: holding 235 to 1,394 days of
        cover, nothing is due. An empty list is the right answer, not a broken one."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await a_product_that_sells(
            client, admin, db_session, sale_days=20, each="10",
            sku="FULL-1", stock="5000")

        suggestions = (await client.get(
            "/api/v1/inventory/stock/reorder-suggestions", headers=admin)).json()["data"]
        assert not any(s["sku"] == "FULL-1" for s in suggestions)

    async def test_a_product_below_its_computed_point_appears_with_its_reasoning(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id, customer_id = await a_product_that_sells(
            client, admin, db_session, sale_days=30, each="30",
            sku="LOW-1", stock="1000")

        # The helper already sold 30 x 30 = 900 of the 1,000 received, so 100 are
        # left. Take 95 more today, leaving 5 against a reorder point of ~35.
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "95",
            tax_rate_ids=[])
        assert response.status_code == 201, response.text

        suggestions = (await client.get(
            "/api/v1/inventory/stock/reorder-suggestions", headers=admin)).json()["data"]
        row = next((s for s in suggestions if s["sku"] == "LOW-1"), None)
        assert row is not None, "الصنف المنخفض لم يظهر في قائمة إعادة الطلب"
        assert row["computed"] is True
        assert Decimal(str(row["suggested_quantity"])) > 0
        assert row["basis"]
        assert row["lead_time_days"] == 7
