"""Integration tests for the analytics module: RFM, trends, waste, credit, delivery, reps."""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.sales import SalesInvoice
from app.tests.conftest import (
    TEST_ACCOUNTANT_PASSWORD,
    TEST_ADMIN_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_delivery import create_trip
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    receive,
)
from app.tests.test_sales import create_customer, post_invoice


async def backdate_invoice(
    db_session: AsyncSession, invoice_id: int, target: date
) -> None:
    """Directly age an invoice past `date.today()` so recency/aging logic has signal."""
    invoice = await db_session.get(SalesInvoice, invoice_id)
    invoice.invoice_date = target
    await db_session.commit()


class TestPermissions:
    async def test_storekeeper_denied_admin_and_accountant_allowed(
        self, client: AsyncClient
    ) -> None:
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)

        assert (
            await client.get("/api/v1/analytics/summary", headers=store)
        ).status_code == 403
        assert (
            await client.get("/api/v1/analytics/summary", headers=admin)
        ).status_code == 200
        assert (
            await client.get("/api/v1/analytics/summary", headers=accountant)
        ).status_code == 200


class TestCustomerRFM:
    async def test_recent_frequent_customer_is_champion(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "500")
        customer_id = await create_customer(client, admin, credit_limit="10000")

        # Several invoices today => recency 0, decent frequency.
        for _ in range(5):
            resp = await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
            )
            assert resp.status_code == 201, resp.text

        rfm = (
            await client.get("/api/v1/analytics/customers/rfm", headers=admin)
        ).json()["data"]
        row = next(r for r in rfm if r["customer_id"] == customer_id)
        assert row["recency_days"] == 0
        assert row["frequency"] == 5
        assert as_decimal(row["monetary"]) > 0
        # With only one active customer, it's automatically the top (p80) earner.
        assert row["segment"] == "بطل (Champion)"

    async def test_customer_with_no_invoices_is_unclassified(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id = await create_customer(client, admin, name="عميل بلا فواتير")

        rfm = (
            await client.get("/api/v1/analytics/customers/rfm", headers=admin)
        ).json()["data"]
        row = next(r for r in rfm if r["customer_id"] == customer_id)
        assert row["frequency"] == 0
        assert row["recency_days"] is None
        assert row["segment"] == "لم يشترِ بعد"


class TestProductRFM:
    async def test_stock_and_expiry_reflected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-SOON", 5, "20")
        await receive(client, admin, product["id"], warehouse_id, "B-LATE", 200, "80")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
        )
        assert response.status_code == 201, response.text

        rfm = (
            await client.get("/api/v1/analytics/products/rfm", headers=admin)
        ).json()["data"]
        row = next(r for r in rfm if r["product_id"] == product["id"])
        assert row["frequency"] == 1
        assert row["recency_days"] == 0
        # 20 + 80 received - 10 sold (FEFO drains B-SOON first) = 90 remaining.
        assert as_decimal(row["stock_on_hand"]) == Decimal("90")
        assert row["nearest_expiry_days"] == 5

    async def test_never_sold_product_unclassified(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(
            client, admin, sku="NEVER-SOLD", warehouse_id=warehouse_id
        )

        rfm = (
            await client.get("/api/v1/analytics/products/rfm", headers=admin)
        ).json()["data"]
        row = next(r for r in rfm if r["product_id"] == product["id"])
        assert row["frequency"] == 0
        assert row["segment"] == "لم يُباع بعد"
        assert as_decimal(row["stock_on_hand"]) == Decimal("0")


class TestSalesTrendAndWarehouseSplit:
    async def test_trend_captures_current_month(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin)

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
        )
        invoice = response.json()["data"]

        trend = (
            await client.get("/api/v1/analytics/sales/trend", headers=admin)
        ).json()["data"]
        this_month = date.today().strftime("%Y-%m")
        point = next(p for p in trend if p["period"] == this_month)
        assert as_decimal(point["revenue"]) >= as_decimal(invoice["subtotal"])
        assert point["invoice_count"] >= 1

    async def test_revenue_split_across_two_warehouses(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        wh_main = await create_warehouse(client, admin, "الرئيسي")
        wh_cold = await create_warehouse(client, admin, "مستودع التبريد")
        dry_product = await create_product(
            client, admin, sku="DRY-01", warehouse_id=wh_main
        )
        cold_product = await create_product(
            client, admin, sku="COLD-01", warehouse_id=wh_cold
        )
        await receive(client, admin, dry_product["id"], wh_main, "B-1", 180, "100")
        await receive(client, admin, cold_product["id"], wh_cold, "B-1", 90, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        response = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "cash",
                "lines": [
                    {"product_id": dry_product["id"], "quantity": "5"},
                    {"product_id": cold_product["id"], "quantity": "3"},
                ],
            },
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        # Mixed-warehouse invoice: header warehouse_id must be None.
        assert invoice["warehouse_id"] is None

        by_wh = (
            await client.get("/api/v1/analytics/sales/by-warehouse", headers=admin)
        ).json()["data"]
        main_row = next(r for r in by_wh if r["warehouse_id"] == wh_main)
        cold_row = next(r for r in by_wh if r["warehouse_id"] == wh_cold)
        assert as_decimal(main_row["revenue"]) > 0
        assert as_decimal(cold_row["revenue"]) > 0


class TestExpiryRiskAndTurnover:
    async def test_expiry_risk_lists_near_expiry_batch(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive(
            client, admin, product["id"], warehouse_id, "B-EXP", 10, "40"
        )

        risk = (
            await client.get("/api/v1/analytics/inventory/expiry-risk", headers=admin)
        ).json()["data"]
        row = next(r for r in risk if r["batch_id"] == batch["id"])
        assert row["days_remaining"] <= 10
        assert as_decimal(row["quantity"]) == Decimal("40")

    async def test_turnover_ratio_computed(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        # Turnover needs cost data, so receive with an explicit unit_cost
        # (the shared `receive()` helper always omits it).
        receive_resp = await client.post(
            "/api/v1/inventory/stock/receive",
            headers=admin,
            json={
                "product_id": product["id"],
                "warehouse_id": warehouse_id,
                "batch_number": "B-1",
                "expiry_date": (date.today() + timedelta(days=180)).isoformat(),
                "quantity": "100",
                "unit_cost": "5.00",
            },
        )
        assert receive_resp.status_code == 201, receive_resp.text
        customer_id = await create_customer(client, admin)
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "20", "cash"
        )
        assert response.status_code == 201, response.text

        turnover = (
            await client.get("/api/v1/analytics/inventory/turnover", headers=admin)
        ).json()["data"]
        row = next(r for r in turnover if r["product_id"] == product["id"])
        assert as_decimal(row["cogs_12m"]) > 0
        assert as_decimal(row["stock_on_hand_value"]) > 0


class TestCreditAgingAndRisk:
    async def test_old_unpaid_invoice_falls_in_90_plus_bucket(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
        )
        invoice_id = response.json()["data"]["id"]
        await backdate_invoice(
            db_session, invoice_id, date.today() - timedelta(days=120)
        )

        aging = (
            await client.get("/api/v1/analytics/credit/aging", headers=admin)
        ).json()["data"]
        row = next(r for r in aging if r["customer_id"] == customer_id)
        assert as_decimal(row["bucket_90_plus"]) > 0
        assert as_decimal(row["bucket_0_30"]) == Decimal("0")

    async def test_credit_utilization_percentage(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="1000")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5", "credit"
        )
        assert response.status_code == 201, response.text
        invoice_total = as_decimal(response.json()["data"]["total"])

        risk = (
            await client.get("/api/v1/analytics/credit/at-risk", headers=admin)
        ).json()["data"]
        row = next(r for r in risk if r["customer_id"] == customer_id)
        expected_pct = (invoice_total / Decimal("1000") * 100).quantize(Decimal("0.01"))
        assert as_decimal(row["utilization_pct"]) == expected_pct


class TestDeliveryAndRepAnalytics:
    async def test_fulfillment_and_driver_performance_after_delivery(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
        )
        invoice_id = response.json()["data"]["id"]

        trip = await create_trip(client, admin, warehouse_id)
        added = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": invoice_id},
        )
        stop_id = added.json()["data"]["stops"][0]["id"]
        await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/dispatch", headers=admin
        )
        await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/stops/{stop_id}/status",
            headers=admin,
            json={"status": "delivered"},
        )
        await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/complete", headers=admin
        )

        fulfillment = (
            await client.get("/api/v1/analytics/delivery/fulfillment", headers=admin)
        ).json()["data"]
        delivery_row = next(r for r in fulfillment if r["fulfillment"] == "delivery")
        assert delivery_row["completed_count"] >= 1

        drivers = (
            await client.get("/api/v1/analytics/delivery/drivers", headers=admin)
        ).json()["data"]
        row = next(d for d in drivers if d["driver_name"] == "سائق التوصيل")
        assert row["delivered_stops"] >= 1

    async def test_rep_performance_attributes_revenue(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")

        users = (await client.get("/api/v1/auth/users", headers=admin)).json()["data"]
        rep_id = next(u["id"] for u in users if u["username"] == "salesman")
        customer_id = await create_customer(
            client, admin, credit_limit="5000", salesman_id=rep_id
        )
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
        )
        assert response.status_code == 201, response.text
        invoice_total = as_decimal(response.json()["data"]["total"])

        reps = (
            await client.get("/api/v1/analytics/reps/performance", headers=admin)
        ).json()["data"]
        row = next(r for r in reps if r["salesman_id"] == rep_id)
        assert as_decimal(row["revenue"]) == invoice_total
        assert row["invoice_count"] == 1
        assert row["customer_count"] == 1
