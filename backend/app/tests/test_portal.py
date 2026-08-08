"""Integration tests for the customer portal: account binding, price-free
catalog, statement scoping, the order lifecycle, and the credit guard."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_ACCOUNTANT_PASSWORD,
    login,
)
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer

PORTAL_PASSWORD = "Portal@Test1234"


async def create_portal_product(
    client: AsyncClient, admin: dict[str, str]
) -> tuple[int, dict]:
    """One warehouse with 20 units of a product (prices: 10.50 / 11.25 / 12.00)."""
    warehouse_id = await create_warehouse(client, admin, "الرئيسي")
    product = await create_product(client, admin, warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "20")
    return warehouse_id, product


async def create_portal_account(
    client: AsyncClient,
    admin: dict[str, str],
    customer_id: int,
    username: str = "customer_a",
) -> dict[str, str]:
    response = await client.post(
        f"/api/v1/portal/accounts/{customer_id}",
        headers=admin,
        json={"username": username, "password": PORTAL_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return await login(client, username, PORTAL_PASSWORD)


class TestPortalAccounts:
    async def test_admin_creates_and_manages_portal_account(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id = await create_customer(client, admin, name="عميل البوابة")
        portal_headers = await create_portal_account(client, admin, customer_id)

        me = await client.get("/api/v1/auth/me", headers=portal_headers)
        assert me.status_code == 200, me.text
        assert me.json()["data"]["role"] == "customer"

        # Password reset: the old one stops working, the new one works.
        response = await client.patch(
            f"/api/v1/portal/accounts/{customer_id}",
            headers=admin,
            json={"password": "NewPortal@Test1234"},
        )
        assert response.status_code == 200, response.text
        old = await client.post(
            "/api/v1/auth/login",
            json={"username": "customer_a", "password": PORTAL_PASSWORD},
        )
        assert old.status_code == 401
        new = await client.post(
            "/api/v1/auth/login",
            json={"username": "customer_a", "password": "NewPortal@Test1234"},
        )
        assert new.status_code == 200

    async def test_username_collision_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id = await create_customer(client, admin, name="عميل تعارض")
        await create_portal_account(client, admin, customer_id)
        other = await create_customer(client, admin, name="عميل ثانٍ")

        response = await client.post(
            f"/api/v1/portal/accounts/{other}",
            headers=admin,
            json={"username": "customer_a", "password": PORTAL_PASSWORD},
        )
        assert response.status_code == 409

    async def test_non_manager_cannot_create_account(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        storekeeper = await login(client, "storekeeper", "Store@Test1234")
        customer_id = await create_customer(client, admin, name="عميل صلاحيات")
        response = await client.post(
            f"/api/v1/portal/accounts/{customer_id}",
            headers=storekeeper,
            json={"username": "nope", "password": PORTAL_PASSWORD},
        )
        assert response.status_code == 403


class TestPortalCatalog:
    async def test_catalog_shows_quantities_never_prices(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_portal_product(client, admin)
        customer_id = await create_customer(client, admin, name="عميل الكتالوج")
        portal = await create_portal_account(client, admin, customer_id)

        response = await client.get("/api/v1/portal/catalog", headers=portal)
        assert response.status_code == 200
        items = response.json()["data"]
        assert len(items) == 1
        row = items[0]
        assert row["product_name"] == "أرز بسمتي 1 كجم"
        assert Decimal(row["available_quantity"]) == Decimal("20")
        assert row["in_stock"] is True
        assert "price" not in response.text.lower()
        assert "wholesale" not in response.text.lower()

    async def test_out_of_stock_product_visible_but_greyed(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        await create_product(client, admin, warehouse_id=warehouse_id)
        customer_id = await create_customer(client, admin, name="عميل كتالوج 2")
        portal = await create_portal_account(
            client, admin, customer_id, username="customer_b"
        )
        # No stock was received for the second product → zero.
        items = (await client.get("/api/v1/portal/catalog", headers=portal)).json()["data"]
        assert len(items) == 1
        assert Decimal(items[0]["available_quantity"]) == Decimal("0")


class TestPortalOrders:
    async def test_customer_places_order_and_staff_confirms(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await create_portal_product(client, admin)
        customer_id = await create_customer(client, admin, name="عميل طلب")
        portal = await create_portal_account(client, admin, customer_id)

        placed = await client.post(
            "/api/v1/portal/orders",
            headers=portal,
            json={
                "warehouse_id": warehouse_id,
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert placed.status_code == 201, placed.text
        order = placed.json()["data"]
        assert order["status"] == "pending"
        assert Decimal(order["total_quantity"]) == Decimal("10")
        assert order["lines"][0]["product_name"] == "أرز بسمتي 1 كجم"
        assert "price" not in placed.text.lower()

        # Staff queue shows it pending; confirming creates a real invoice.
        queue = await client.get("/api/v1/portal/orders/pending", headers=admin)
        assert queue.status_code == 200
        assert any(o["id"] == order["id"] for o in queue.json()["data"])

        confirmed = await client.post(
            f"/api/v1/portal/orders/{order['id']}/confirm",
            headers=admin,
            json={"payment_method": "credit", "credit_override": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        confirmed_order = confirmed.json()["data"]
        assert confirmed_order["status"] == "invoiced"
        assert confirmed_order["converted_invoice_id"] is not None

        # Customer sees the order as invoiced and the invoice in their list.
        mine = await client.get("/api/v1/portal/orders", headers=portal)
        assert mine.json()["data"][0]["status"] == "invoiced"
        invoices = await client.get("/api/v1/portal/invoices", headers=portal)
        assert invoices.status_code == 200
        assert len(invoices.json()["data"]) == 1
        assert invoices.json()["data"][0]["id"] == confirmed_order["converted_invoice_id"]

    async def test_customer_cannot_touch_another_customers_order(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await create_portal_product(client, admin)
        customer_a = await create_customer(client, admin, name="عميل أ")
        customer_b = await create_customer(client, admin, name="عميل ب")
        portal_a = await create_portal_account(client, admin, customer_a, "customer_a")
        portal_b = await create_portal_account(client, admin, customer_b, "customer_b")

        placed = await client.post(
            "/api/v1/portal/orders",
            headers=portal_a,
            json={"lines": [{"product_id": product["id"], "quantity": "5"}]},
        )
        order_id = placed.json()["data"]["id"]

        # B's list is empty, and B cannot cancel A's order either.
        b_orders = await client.get("/api/v1/portal/orders", headers=portal_b)
        assert b_orders.json()["data"] == []
        steal = await client.post(
            f"/api/v1/portal/orders/{order_id}/cancel",
            headers=portal_b,
            json={"reason": "محاولة عبث"},
        )
        assert steal.status_code == 403

    async def test_customer_cancels_own_pending_order(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await create_portal_product(client, admin)
        customer_id = await create_customer(client, admin, name="عميل إلغاء")
        portal = await create_portal_account(client, admin, customer_id)

        placed = await client.post(
            "/api/v1/portal/orders",
            headers=portal,
            json={"lines": [{"product_id": product["id"], "quantity": "5"}]},
        )
        order_id = placed.json()["data"]["id"]
        cancelled = await client.post(
            f"/api/v1/portal/orders/{order_id}/cancel",
            headers=portal,
            json={"reason": "غيرته رأيي"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "cancelled"

        # Confirming a cancelled order must fail.
        again = await client.post(
            f"/api/v1/portal/orders/{order_id}/confirm",
            headers=admin,
            json={"payment_method": "credit"},
        )
        assert again.status_code == 400

    async def test_credit_guard_blocks_order_over_the_limit(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await create_portal_product(client, admin)
        # Credit limit 100; 15 units × 10.50 wholesale = 157.50 → over.
        customer_id = await create_customer(
            client, admin, name="عميل بحد ائتماني", credit_limit="100"
        )
        portal = await create_portal_account(client, admin, customer_id)

        over = await client.post(
            "/api/v1/portal/orders",
            headers=portal,
            json={"lines": [{"product_id": product["id"], "quantity": "15"}]},
        )
        assert over.status_code == 400
        assert "الحد الائتماني" in over.json()["message"]

        # 2 units × 10.50 = 21 < 100 → allowed.
        ok = await client.post(
            "/api/v1/portal/orders",
            headers=portal,
            json={"lines": [{"product_id": product["id"], "quantity": "2"}]},
        )
        assert ok.status_code == 201

    async def test_staff_cannot_confirm_without_customers_manage(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await create_portal_product(client, admin)
        customer_id = await create_customer(client, admin, name="عميل تأكيد")
        portal = await create_portal_account(client, admin, customer_id)
        placed = await client.post(
            "/api/v1/portal/orders",
            headers=portal,
            json={"lines": [{"product_id": product["id"], "quantity": "2"}]},
        )
        order_id = placed.json()["data"]["id"]

        storekeeper = await login(client, "storekeeper", "Store@Test1234")
        denied = await client.post(
            f"/api/v1/portal/orders/{order_id}/confirm",
            headers=storekeeper,
            json={"payment_method": "credit"},
        )
        assert denied.status_code == 403


class TestPortalStatement:
    async def test_statement_and_invoice_detail_scoped_to_customer(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await create_portal_product(client, admin)
        customer_id = await create_customer(client, admin, name="عميل الكشف")
        portal = await create_portal_account(client, admin, customer_id)

        placed = await client.post(
            "/api/v1/portal/orders",
            headers=portal,
            json={"lines": [{"product_id": product["id"], "quantity": "4"}]},
        )
        order_id = placed.json()["data"]["id"]
        # 4 × 10.50 = 42; the confirmation passes no tax rates, so the invoice
        # carries the order through exactly as a counter sale without taxes.
        await client.post(
            f"/api/v1/portal/orders/{order_id}/confirm",
            headers=admin,
            json={"payment_method": "credit", "credit_override": True},
        )

        statement = await client.get("/api/v1/portal/statement", headers=portal)
        assert statement.status_code == 200
        data = statement.json()["data"]
        assert data["customer"]["name"] == "عميل الكشف"
        assert Decimal(data["balance"]) == Decimal("42.00")
        assert len(data["invoices"]) == 1

        detail = await client.get(
            f"/api/v1/portal/invoices/{data['invoices'][0]['id']}", headers=portal
        )
        assert detail.status_code == 200
        assert Decimal(detail.json()["data"]["total"]) == Decimal("42.00")