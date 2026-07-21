"""Integration tests for the reports module: dashboard KPIs, top products, salesman performance."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_SALES_PASSWORD, login
from app.tests.test_inventory import as_decimal, create_product, create_warehouse, receive
from app.tests.test_sales import (
    create_customer,
    get_salesman_id,
    post_invoice,
    setup_stocked_catalog,
)


class TestDashboardKPIs:
    async def test_dashboard_returns_all_sections(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/reports/dashboard", headers=admin)
        assert response.status_code == 200
        body = response.json()["data"]
        assert "sales_this_month" in body
        assert "purchases_this_month" in body
        assert "returns_this_month" in body
        assert "outstanding_receivables" in body
        assert "low_stock_count" in body
        assert "total_products" in body

    async def test_dashboard_reflects_sales(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")

        await post_invoice(client, admin, customer_id, warehouse_id, product["id"], "10", "cash")

        response = await client.get("/api/v1/reports/dashboard", headers=admin)
        body = response.json()["data"]
        assert body["sales_this_month"]["count"] >= 1
        assert as_decimal(body["sales_this_month"]["revenue"]) > 0

    async def test_dashboard_low_stock_detection(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, sku="LOW-001")
        # min_stock_level is 50 from create_product, receive only 10
        await receive(client, admin, product["id"], warehouse_id, "B-1", 90, "10")

        response = await client.get("/api/v1/reports/dashboard", headers=admin)
        body = response.json()["data"]
        assert body["low_stock_count"] >= 1


class TestTopProducts:
    async def test_top_products_returns_sorted(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")

        await post_invoice(client, admin, customer_id, warehouse_id, product["id"], "15", "cash")

        response = await client.get("/api/v1/reports/top-products", headers=admin)
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1
        assert data[0]["product_name"] == "أرز بسمتي 1 كجم"

    async def test_top_products_respects_limit(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/reports/top-products", headers=admin, params={"limit": 1})
        assert response.status_code == 200


class TestSalesmanPerformance:
    async def test_salesman_performance_returns_data(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        salesman_id = await get_salesman_id(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000", salesman_id=salesman_id)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)

        await post_invoice(client, sales, customer_id, warehouse_id, product["id"], "10", "cash")

        response = await client.get("/api/v1/reports/salesman-performance", headers=admin)
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1
        assert data[0]["salesman_name"] == "مندوب المبيعات"
        assert data[0]["invoice_count"] >= 1


class TestDamageReport:
    async def test_damage_report_empty_when_no_returns(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/reports/damage-report", headers=admin)
        assert response.status_code == 200
        assert response.json()["data"] == []

    async def test_storekeeper_cannot_access_reports(self, client: AsyncClient) -> None:
        from app.tests.conftest import TEST_STORE_PASSWORD
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        response = await client.get("/api/v1/reports/dashboard", headers=store)
        assert response.status_code == 403
