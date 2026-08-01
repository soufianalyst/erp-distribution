"""Integration tests for dashboard alerts: which fire, how severe, and who sees them."""

from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.inventory import ProductBatch

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_inventory import create_product, create_warehouse, days_from_now, receive
from app.tests.test_purchases import create_supplier
from app.tests.test_sales import create_customer, post_invoice


async def fetch_alerts(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/api/v1/alerts", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def group(alerts: dict, key: str) -> dict | None:
    return next((g for g in alerts["groups"] if g["key"] == key), None)


def keys(alerts: dict) -> list[str]:
    return [g["key"] for g in alerts["groups"]]


async def age_batch_to_expired(
    db_session: AsyncSession, batch_number: str, days_ago: int
) -> None:
    """Backdate a batch's expiry so it reads as expired stock still on hand.

    Receiving deliberately refuses goods that are already expired, so this state
    cannot be reached through the API — real stock gets here by sitting on the
    shelf until its date passes, which is exactly what this reproduces.
    """
    await db_session.execute(
        update(ProductBatch)
        .where(ProductBatch.batch_number == batch_number)
        .values(expiry_date=date.today() - timedelta(days=days_ago))
    )
    await db_session.commit()


class TestNoAlerts:
    async def test_clean_system_reports_nothing(self, client: AsyncClient) -> None:
        """Nothing wrong means an empty list, not a list of zero-count groups."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        alerts = await fetch_alerts(client, admin)
        assert alerts["groups"] == []
        assert alerts["critical_count"] == 0
        assert alerts["warning_count"] == 0

    async def test_healthy_stock_raises_no_alert(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "HEALTHY-1", warehouse_id=warehouse_id)
        # Comfortably above min_stock_level (50) and expiring far out.
        await receive(client, admin, product["id"], warehouse_id, "OK-1", 400, "500")

        alerts = await fetch_alerts(client, admin)
        assert keys(alerts) == []


class TestStockAlerts:
    async def test_expired_stock_is_critical(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "EXP-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "OLD-1", 30, "100")
        await age_batch_to_expired(db_session, "OLD-1", 5)

        alerts = await fetch_alerts(client, admin)
        expired = group(alerts, "expired_stock")
        assert expired is not None
        assert expired["severity"] == "critical"
        assert expired["count"] == 1
        assert expired["route"] == "/stock"
        assert expired["items"][0]["label"] == product["name"]
        assert "منتهية منذ 5 يوم" in expired["items"][0]["value"]

    async def test_near_expiry_is_a_warning_not_critical(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "SOON-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "SOON-B", 10, "100")

        alerts = await fetch_alerts(client, admin)
        near = group(alerts, "near_expiry")
        assert near is not None
        assert near["severity"] == "warning"
        assert near["count"] == 1
        assert group(alerts, "expired_stock") is None

    async def test_far_expiry_raises_nothing(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "FAR-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "FAR-B", 200, "100")

        alerts = await fetch_alerts(client, admin)
        assert group(alerts, "near_expiry") is None
        assert group(alerts, "expired_stock") is None

    async def test_out_of_stock_is_critical(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        # A product with no batches at all: nothing to sell right now.
        product = await create_product(client, admin, "GONE-1")

        alerts = await fetch_alerts(client, admin)
        out = group(alerts, "out_of_stock")
        assert out is not None
        assert out["severity"] == "critical"
        assert out["count"] == 1
        assert out["route"] == "/purchases"
        assert out["items"][0]["detail"] == product["sku"]

    async def test_below_minimum_is_a_warning(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "LOW-1", warehouse_id=warehouse_id)
        # min_stock_level is 50 (see create_product); 20 on hand is short by 30.
        await receive(client, admin, product["id"], warehouse_id, "LOW-B", 300, "20")

        alerts = await fetch_alerts(client, admin)
        low = group(alerts, "below_minimum")
        assert low is not None
        assert low["severity"] == "warning"
        assert low["count"] == 1
        assert "30" in low["items"][0]["value"]
        # Stock exists, so it is not the out-of-stock alert.
        assert group(alerts, "out_of_stock") is None


class TestPurchaseAlerts:
    async def test_overdue_purchase_order_is_a_warning(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "PO-LATE", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "PB-1", 300, "500")
        supplier_id = await create_supplier(client, admin)

        order = await client.post(
            "/api/v1/purchases/orders",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "expected_date": str(date.today() - timedelta(days=6)),
                "lines": [
                    {"product_id": product["id"], "quantity": "10", "unit_cost": "5.00"}
                ],
            },
        )
        assert order.status_code == 201, order.text
        order_id = order.json()["data"]["id"]

        # A draft is not overdue — nobody has promised anything yet.
        assert group(await fetch_alerts(client, admin), "overdue_orders") is None

        await client.post(f"/api/v1/purchases/orders/{order_id}/send", headers=admin)
        overdue = group(await fetch_alerts(client, admin), "overdue_orders")
        assert overdue is not None
        assert overdue["severity"] == "warning"
        assert overdue["count"] == 1
        assert f"طلب شراء رقم {order_id}" == overdue["items"][0]["label"]
        assert "متأخر 6 يوم" in overdue["items"][0]["value"]

    async def test_received_order_stops_being_overdue(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "PO-DONE", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "PB-1", 300, "500")
        supplier_id = await create_supplier(client, admin)

        order = await client.post(
            "/api/v1/purchases/orders",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "expected_date": str(date.today() - timedelta(days=3)),
                "lines": [
                    {"product_id": product["id"], "quantity": "10", "unit_cost": "5.00"}
                ],
            },
        )
        order_data = order.json()["data"]
        await client.post(
            f"/api/v1/purchases/orders/{order_data['id']}/send", headers=admin
        )
        assert group(await fetch_alerts(client, admin), "overdue_orders") is not None

        received = await client.post(
            f"/api/v1/purchases/orders/{order_data['id']}/receive",
            headers=admin,
            json={
                "payment_method": "credit",
                "lines": [
                    {
                        "order_line_id": order_data["lines"][0]["id"],
                        "quantity": "10",
                        "batch_number": "LATE-1",
                        "expiry_date": days_from_now(200),
                    }
                ],
            },
        )
        assert received.status_code == 201, received.text
        # Fully received: late, but no longer outstanding.
        assert group(await fetch_alerts(client, admin), "overdue_orders") is None


class TestStocktakeAlerts:
    async def test_open_stocktake_is_info(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "COUNT-A", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "CB-1", 300, "500")

        opened = await client.post(
            "/api/v1/inventory/stocktakes",
            headers=admin,
            json={"warehouse_id": warehouse_id},
        )
        assert opened.status_code == 201, opened.text
        stocktake = opened.json()["data"]

        open_group = group(await fetch_alerts(client, admin), "open_stocktakes")
        assert open_group is not None
        assert open_group["severity"] == "info"
        assert open_group["count"] == 1
        assert open_group["items"][0]["label"] == f"جرد رقم {stocktake['id']}"

        # Posting clears it.
        await client.put(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/counts",
            headers=admin,
            json={
                "counts": [
                    {"line_id": stocktake["lines"][0]["id"], "counted_quantity": "500"}
                ]
            },
        )
        await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert group(await fetch_alerts(client, admin), "open_stocktakes") is None


class TestCreditAlerts:
    async def test_customer_over_limit_is_critical(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "CREDIT-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "CB-1", 300, "500")
        customer_id = await create_customer(
            client, admin, "عميل على الحد", credit_limit="100"
        )

        # 20 x 10.50 wholesale + VAT well exceeds the 100 limit; the manager
        # override is what lets it through, and that is exactly the risk to flag.
        sale = await post_invoice(
            client,
            admin,
            customer_id,
            warehouse_id,
            product["id"],
            "20",
            payment_method="credit",
            credit_override=True,
        )
        assert sale.status_code == 201, sale.text

        over = group(await fetch_alerts(client, admin), "over_credit_limit")
        assert over is not None
        assert over["severity"] == "critical"
        assert over["count"] == 1
        assert over["route"] == "/customers"
        assert over["items"][0]["label"] == "عميل على الحد"

    async def test_customer_within_limit_raises_nothing(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "CREDIT-2", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "CB-1", 300, "500")
        customer_id = await create_customer(
            client, admin, "عميل منتظم", credit_limit="100000"
        )
        await post_invoice(
            client,
            admin,
            customer_id,
            warehouse_id,
            product["id"],
            "20",
            payment_method="credit",
        )

        assert group(await fetch_alerts(client, admin), "over_credit_limit") is None


class TestAlertOrderingAndAccess:
    async def test_critical_groups_come_first(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        # Expired stock (critical) alongside a below-minimum product (warning).
        expired = await create_product(client, admin, "MIX-EXP", warehouse_id=warehouse_id)
        await receive(client, admin, expired["id"], warehouse_id, "E-1", 30, "100")
        await age_batch_to_expired(db_session, "E-1", 2)
        low = await create_product(client, admin, "MIX-LOW", warehouse_id=warehouse_id)
        await receive(client, admin, low["id"], warehouse_id, "L-1", 300, "20")

        alerts = await fetch_alerts(client, admin)
        severities = [g["severity"] for g in alerts["groups"]]
        assert severities == sorted(
            severities, key=lambda s: {"critical": 0, "warning": 1, "info": 2}[s]
        )
        assert alerts["critical_count"] >= 1
        assert alerts["warning_count"] >= 1

    async def test_every_group_carries_a_hint_and_a_route(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """An alert with nowhere to go is just noise."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "HINT-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "H-1", 30, "10")
        await age_batch_to_expired(db_session, "H-1", 1)

        alerts = await fetch_alerts(client, admin)
        assert alerts["groups"]
        for g in alerts["groups"]:
            assert g["hint"].strip()
            assert g["route"].startswith("/")
            assert g["count"] >= 1

    async def test_salesman_only_sees_what_they_can_act_on(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Warehouse and purchasing work is not a salesman's to do."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        stocked = await create_product(client, admin, "PERM-1", warehouse_id=warehouse_id)
        await receive(client, admin, stocked["id"], warehouse_id, "P-1", 30, "50")
        await age_batch_to_expired(db_session, "P-1", 3)
        await create_product(client, admin, "PERM-GONE")  # out of stock

        admin_keys = keys(await fetch_alerts(client, admin))
        assert "out_of_stock" in admin_keys
        assert "expired_stock" in admin_keys

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        sales_keys = keys(await fetch_alerts(client, salesman))
        # Sales holds stock.view, so expiry is visible — they sell that stock.
        assert "expired_stock" in sales_keys
        # But purchasing and counting are not theirs.
        assert "out_of_stock" not in sales_keys
        assert "below_minimum" not in sales_keys
        assert "open_stocktakes" not in sales_keys

    async def test_storekeeper_sees_counting_work(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "SK-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "SK-B", 300, "500")
        await client.post(
            "/api/v1/inventory/stocktakes",
            headers=admin,
            json={"warehouse_id": warehouse_id},
        )

        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        assert "open_stocktakes" in keys(await fetch_alerts(client, store))

    async def test_alerts_require_login(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/alerts")
        assert response.status_code == 401
