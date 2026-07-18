"""Integration tests for stock adjustments (write-offs): damaged/expired/spoiled/count-shortfall."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    days_from_now,
    receive,
)


def items_by_code(entry: dict) -> dict[str, tuple[Decimal, Decimal]]:
    return {
        item["account"]["code"]: (as_decimal(item["debit"]), as_decimal(item["credit"]))
        for item in entry["items"]
    }


async def entries_for(
    client: AsyncClient, headers: dict[str, str], reference_type: str, reference_id: int
) -> list[dict]:
    response = await client.get(
        "/api/v1/accounting/journal-entries",
        headers=headers,
        params={"reference_type": reference_type, "reference_id": reference_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def receive_with_cost(
    client: AsyncClient,
    headers: dict[str, str],
    product_id: int,
    warehouse_id: int,
    batch_number: str,
    expiry_days: int,
    quantity: str,
    unit_cost: str,
) -> dict:
    response = await client.post(
        "/api/v1/inventory/stock/receive",
        headers=headers,
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "batch_number": batch_number,
            "expiry_date": days_from_now(expiry_days),
            "quantity": quantity,
            "unit_cost": unit_cost,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestStockAdjustments:
    async def test_adjustment_reduces_stock_and_posts_journal_entry(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "100", "5.00"
        )

        response = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "damaged",
                "notes": "تلف أثناء التخزين",
                "lines": [{"batch_id": batch["id"], "quantity": "20"}],
            },
        )
        assert response.status_code == 201, response.text
        adjustment = response.json()["data"]
        assert adjustment["reason"] == "damaged"
        # 20 x 5.00 = 100.00
        assert as_decimal(adjustment["total_cost"]) == Decimal("100.00")
        assert as_decimal(adjustment["lines"][0]["line_total"]) == Decimal("100.00")

        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("80")

        entries = await entries_for(client, admin, "stock_adjustment", adjustment["id"])
        assert len(entries) == 1
        items = items_by_code(entries[0])
        assert items["5030"] == (Decimal("100.00"), Decimal("0"))
        assert items["1030"] == (Decimal("0"), Decimal("100.00"))

    async def test_adjustment_without_batch_cost_posts_no_journal_entry(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        # receive() omits unit_cost -> batch.unit_cost stays NULL.
        batch = await receive(
            client, admin, product["id"], warehouse_id, "B-1", 60, "50"
        )

        response = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "count_shortfall",
                "lines": [{"batch_id": batch["id"], "quantity": "5"}],
            },
        )
        assert response.status_code == 201, response.text
        adjustment = response.json()["data"]
        assert as_decimal(adjustment["total_cost"]) == Decimal("0.00")

        entries = await entries_for(client, admin, "stock_adjustment", adjustment["id"])
        assert entries == []

    async def test_adjustment_exceeding_batch_quantity_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "10", "5.00"
        )

        response = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "expired",
                "lines": [{"batch_id": batch["id"], "quantity": "11"}],
            },
        )
        assert response.status_code == 400
        assert "أكبر من الرصيد المتاح" in response.json()["message"]

    async def test_storekeeper_can_create_adjustment(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "30", "4.00"
        )

        storekeeper = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        response = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=storekeeper,
            json={
                "reason": "spoiled",
                "lines": [{"batch_id": batch["id"], "quantity": "5"}],
            },
        )
        assert response.status_code == 201, response.text

    async def test_sales_role_cannot_create_adjustment(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "30", "4.00"
        )

        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=sales,
            json={
                "reason": "other",
                "lines": [{"batch_id": batch["id"], "quantity": "5"}],
            },
        )
        assert response.status_code == 403

    async def test_list_adjustments(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "30", "4.00"
        )
        await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "damaged",
                "lines": [{"batch_id": batch["id"], "quantity": "5"}],
            },
        )

        response = await client.get("/api/v1/inventory/stock/adjustments", headers=admin)
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
