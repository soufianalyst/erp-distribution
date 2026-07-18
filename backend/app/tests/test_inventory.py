"""Integration tests for the inventory module: catalog, receiving, FEFO, transfers, alerts."""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)


def days_from_now(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def as_decimal(value: object) -> Decimal:
    """Compare API numbers safely whether serialized as string or number."""
    return Decimal(str(value))


async def create_warehouse(
    client: AsyncClient, headers: dict[str, str], name: str
) -> int:
    response = await client.post(
        "/api/v1/inventory/warehouses", headers=headers, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["id"])


async def create_product(
    client: AsyncClient,
    headers: dict[str, str],
    sku: str = "RICE-001",
    warehouse_id: int | None = None,
) -> dict:
    """Creates a product; auto-creates its home warehouse when none is given."""
    if warehouse_id is None:
        warehouse_id = await create_warehouse(client, headers, f"مخزن-{sku}")
    response = await client.post(
        "/api/v1/inventory/products",
        headers=headers,
        json={
            "sku": sku,
            "name": "أرز بسمتي 1 كجم",
            "base_unit_name": "كيس",
            "wholesale_price": "10.50",
            "half_wholesale_price": "11.25",
            "retail_price": "12.00",
            "min_stock_level": "50",
            "warehouse_id": warehouse_id,
            "units": [{"name": "كرتونة", "factor": "12"}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def receive(
    client: AsyncClient,
    headers: dict[str, str],
    product_id: int,
    warehouse_id: int,
    batch_number: str,
    expiry_days: int,
    quantity: str,
    unit_id: int | None = None,
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
            "unit_id": unit_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestCatalog:
    async def test_create_warehouse(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        assert warehouse_id > 0

    async def test_duplicate_warehouse_name_rejected(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_warehouse(client, headers, "المستودع الرئيسي")
        response = await client.post(
            "/api/v1/inventory/warehouses",
            headers=headers,
            json={"name": "المستودع الرئيسي"},
        )
        assert response.status_code == 409

    async def test_create_product_with_units(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        product = await create_product(client, headers)
        assert product["sku"] == "RICE-001"
        assert len(product["units"]) == 1
        assert product["units"][0]["name"] == "كرتونة"
        assert as_decimal(product["units"][0]["factor"]) == Decimal("12")
        assert as_decimal(product["wholesale_price"]) == Decimal("10.50")

    async def test_duplicate_sku_rejected(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_product(client, headers)
        response = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={
                "sku": "RICE-001",
                "name": "صنف مكرر",
                "base_unit_name": "حبة",
                "wholesale_price": "1",
                "half_wholesale_price": "1",
                "retail_price": "1",
                "warehouse_id": 1,
            },
        )
        assert response.status_code == 409

    async def test_product_search(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_product(client, headers)
        response = await client.get(
            "/api/v1/inventory/products", headers=headers, params={"search": "بسمتي"}
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    async def test_storekeeper_cannot_create_product(self, client: AsyncClient) -> None:
        headers = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        response = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={
                "sku": "X-1",
                "name": "غير مصرح",
                "base_unit_name": "حبة",
                "wholesale_price": "1",
                "half_wholesale_price": "1",
                "retail_price": "1",
                "warehouse_id": 1,
            },
        )
        assert response.status_code == 403


class TestBarcode:
    async def test_create_product_with_barcode(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        response = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={
                "sku": "BAR-1",
                "barcode": "6221234567890",
                "name": "صنف بباركود",
                "base_unit_name": "حبة",
                "wholesale_price": "5",
                "half_wholesale_price": "5.5",
                "retail_price": "6",
                "warehouse_id": warehouse_id,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["barcode"] == "6221234567890"

    async def test_duplicate_barcode_rejected(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        base = {
            "barcode": "6221234567890",
            "base_unit_name": "حبة",
            "wholesale_price": "5",
            "half_wholesale_price": "5.5",
            "retail_price": "6",
            "warehouse_id": warehouse_id,
        }
        first = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={**base, "sku": "BAR-1", "name": "الأول"},
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={**base, "sku": "BAR-2", "name": "الثاني"},
        )
        assert second.status_code == 409

    async def test_two_products_without_barcode_allowed(
        self, client: AsyncClient
    ) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        base = {
            "base_unit_name": "حبة",
            "wholesale_price": "5",
            "half_wholesale_price": "5.5",
            "retail_price": "6",
            "warehouse_id": warehouse_id,
        }
        first = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={**base, "sku": "NB-1", "name": "بدون باركود 1"},
        )
        second = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={**base, "sku": "NB-2", "name": "بدون باركود 2"},
        )
        assert first.status_code == 201
        assert second.status_code == 201

    async def test_update_barcode_rejects_duplicate(
        self, client: AsyncClient
    ) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        base = {
            "base_unit_name": "حبة",
            "wholesale_price": "5",
            "half_wholesale_price": "5.5",
            "retail_price": "6",
            "warehouse_id": warehouse_id,
        }
        first = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={**base, "sku": "UB-1", "barcode": "111", "name": "الأول"},
        )
        second = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={**base, "sku": "UB-2", "name": "الثاني"},
        )
        second_id = second.json()["data"]["id"]

        response = await client.patch(
            f"/api/v1/inventory/products/{second_id}",
            headers=headers,
            json={"barcode": "111"},
        )
        assert response.status_code == 409
        assert first.status_code == 201

    async def test_get_product_by_barcode(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        created = await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={
                "sku": "GB-1",
                "barcode": "999888777",
                "name": "صنف للبحث بالباركود",
                "base_unit_name": "حبة",
                "wholesale_price": "5",
                "half_wholesale_price": "5.5",
                "retail_price": "6",
                "warehouse_id": warehouse_id,
            },
        )
        product_id = created.json()["data"]["id"]

        response = await client.get(
            "/api/v1/inventory/products/barcode/999888777", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["id"] == product_id

    async def test_get_product_by_unknown_barcode_404(
        self, client: AsyncClient
    ) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get(
            "/api/v1/inventory/products/barcode/no-such-barcode", headers=headers
        )
        assert response.status_code == 404

    async def test_search_matches_barcode(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        await client.post(
            "/api/v1/inventory/products",
            headers=headers,
            json={
                "sku": "SB-1",
                "barcode": "555444333",
                "name": "منتج",
                "base_unit_name": "حبة",
                "wholesale_price": "5",
                "half_wholesale_price": "5.5",
                "retail_price": "6",
                "warehouse_id": warehouse_id,
            },
        )
        response = await client.get(
            "/api/v1/inventory/products",
            headers=headers,
            params={"search": "555444333"},
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1


class TestProductDelete:
    async def test_delete_unused_product_succeeds(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        product = await create_product(client, headers, warehouse_id=warehouse_id)

        response = await client.delete(
            f"/api/v1/inventory/products/{product['id']}", headers=headers
        )
        assert response.status_code == 200, response.text

        get_response = await client.get(
            f"/api/v1/inventory/products/{product['id']}", headers=headers
        )
        assert get_response.status_code == 404

    async def test_delete_blocked_once_stock_received(
        self, client: AsyncClient
    ) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, headers, "المستودع الرئيسي")
        product = await create_product(client, headers, warehouse_id=warehouse_id)
        await receive(client, headers, product["id"], warehouse_id, "B-1", 60, "10")

        response = await client.delete(
            f"/api/v1/inventory/products/{product['id']}", headers=headers
        )
        assert response.status_code == 400
        assert "حركات مخزنية" in response.json()["message"]

    async def test_delete_nonexistent_product_404(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.delete(
            "/api/v1/inventory/products/999999", headers=headers
        )
        assert response.status_code == 404

    async def test_storekeeper_cannot_delete_product(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "المستودع الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)

        headers = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        response = await client.delete(
            f"/api/v1/inventory/products/{product['id']}", headers=headers
        )
        assert response.status_code == 403


class TestReceiving:
    async def test_receive_stock_in_base_unit(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)

        batch = await receive(
            client, store, product["id"], warehouse_id, "B-100", 90, "100"
        )
        assert batch["batch_number"] == "B-100"
        assert as_decimal(batch["quantity"]) == Decimal("100")

    async def test_receive_in_carton_converts_to_base(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)
        carton_id = product["units"][0]["id"]

        # 2 cartons x 12 = 24 base units.
        batch = await receive(
            client,
            store,
            product["id"],
            warehouse_id,
            "B-200",
            90,
            "2",
            unit_id=carton_id,
        )
        assert as_decimal(batch["quantity"]) == Decimal("24")

    async def test_receive_expired_goods_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)

        response = await client.post(
            "/api/v1/inventory/stock/receive",
            headers=admin,
            json={
                "product_id": product["id"],
                "warehouse_id": warehouse_id,
                "batch_number": "B-OLD",
                "expiry_date": days_from_now(-1),
                "quantity": "10",
            },
        )
        assert response.status_code == 400
        assert "منتهية الصلاحية" in response.json()["message"]

    async def test_receive_without_batch_number_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)

        response = await client.post(
            "/api/v1/inventory/stock/receive",
            headers=admin,
            json={
                "product_id": product["id"],
                "warehouse_id": warehouse_id,
                "expiry_date": days_from_now(90),
                "quantity": "10",
            },
        )
        assert response.status_code == 422

    async def test_same_batch_accumulates(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)

        await receive(client, admin, product["id"], warehouse_id, "B-1", 90, "10")
        batch = await receive(
            client, admin, product["id"], warehouse_id, "B-1", 90, "5"
        )
        assert as_decimal(batch["quantity"]) == Decimal("15")

    async def test_same_batch_different_expiry_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)

        await receive(client, admin, product["id"], warehouse_id, "B-1", 90, "10")
        response = await client.post(
            "/api/v1/inventory/stock/receive",
            headers=admin,
            json={
                "product_id": product["id"],
                "warehouse_id": warehouse_id,
                "batch_number": "B-1",
                "expiry_date": days_from_now(120),
                "quantity": "5",
            },
        )
        assert response.status_code == 409

    async def test_sales_role_cannot_receive_stock(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)

        response = await client.post(
            "/api/v1/inventory/stock/receive",
            headers=sales,
            json={
                "product_id": product["id"],
                "warehouse_id": warehouse_id,
                "batch_number": "B-1",
                "expiry_date": days_from_now(90),
                "quantity": "10",
            },
        )
        assert response.status_code == 403


class TestFefoAndTransfers:
    async def test_transfer_picks_earliest_expiry_first(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        source = await create_warehouse(client, admin, "الرئيسي")
        destination = await create_warehouse(client, admin, "الفرعي")
        product = await create_product(client, admin)

        # B-LATE received first but expires later; FEFO must still drain B-SOON first.
        await receive(client, store, product["id"], source, "B-LATE", 180, "30")
        await receive(client, store, product["id"], source, "B-SOON", 30, "20")

        response = await client.post(
            "/api/v1/inventory/stock/transfer",
            headers=store,
            json={
                "product_id": product["id"],
                "from_warehouse_id": source,
                "to_warehouse_id": destination,
                "quantity": "25",
            },
        )
        assert response.status_code == 200, response.text
        moved = response.json()["data"]
        assert [m["batch_number"] for m in moved] == ["B-SOON", "B-LATE"]
        assert as_decimal(moved[0]["quantity"]) == Decimal("20")
        assert as_decimal(moved[1]["quantity"]) == Decimal("5")

        # Source keeps 25 of B-LATE; destination holds both batches with their expiry dates.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches",
                headers=store,
                params={"warehouse_id": source},
            )
        ).json()["data"]
        assert len(batches) == 1
        assert batches[0]["batch_number"] == "B-LATE"
        assert as_decimal(batches[0]["quantity"]) == Decimal("25")

        dest_batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches",
                headers=store,
                params={"warehouse_id": destination},
            )
        ).json()["data"]
        assert {b["batch_number"] for b in dest_batches} == {"B-SOON", "B-LATE"}

    async def test_transfer_insufficient_stock_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        source = await create_warehouse(client, admin, "الرئيسي")
        destination = await create_warehouse(client, admin, "الفرعي")
        product = await create_product(client, admin)
        await receive(client, admin, product["id"], source, "B-1", 90, "10")

        response = await client.post(
            "/api/v1/inventory/stock/transfer",
            headers=admin,
            json={
                "product_id": product["id"],
                "from_warehouse_id": source,
                "to_warehouse_id": destination,
                "quantity": "11",
            },
        )
        assert response.status_code == 400
        assert "غير كافية" in response.json()["message"]

    async def test_transfer_to_same_warehouse_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 90, "10")

        response = await client.post(
            "/api/v1/inventory/stock/transfer",
            headers=admin,
            json={
                "product_id": product["id"],
                "from_warehouse_id": warehouse_id,
                "to_warehouse_id": warehouse_id,
                "quantity": "5",
            },
        )
        assert response.status_code == 400


class TestReports:
    async def test_stock_levels_aggregate_batches(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 60, "10")
        await receive(client, admin, product["id"], warehouse_id, "B-2", 90, "15.5")

        response = await client.get("/api/v1/inventory/stock/levels", headers=admin)
        assert response.status_code == 200
        levels = response.json()["data"]
        assert len(levels) == 1
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("25.5")
        assert levels[0]["product_name"] == "أرز بسمتي 1 كجم"
        assert levels[0]["warehouse_name"] == "الرئيسي"

    async def test_near_expiry_report(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin)
        await receive(client, admin, product["id"], warehouse_id, "B-NEAR", 10, "10")
        await receive(client, admin, product["id"], warehouse_id, "B-FAR", 200, "10")

        response = await client.get(
            "/api/v1/inventory/stock/near-expiry", headers=admin, params={"days": 30}
        )
        assert response.status_code == 200
        items = response.json()["data"]
        assert [i["batch_number"] for i in items] == ["B-NEAR"]
        assert items[0]["days_remaining"] == 10
