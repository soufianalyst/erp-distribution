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


class TestAdjustmentQuantityAndCostVisibility:
    async def test_total_quantity_and_cost_known_reported(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        priced = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-P", 60, "100", "4.00"
        )

        response = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "damaged",
                "lines": [{"batch_id": priced["id"], "quantity": "7"}],
            },
        )
        assert response.status_code == 201, response.text
        adjustment = response.json()["data"]
        assert as_decimal(adjustment["total_quantity"]) == Decimal("7")
        assert as_decimal(adjustment["total_cost"]) == Decimal("28.00")
        assert adjustment["cost_known"] is True
        assert adjustment["status"] == "posted"
        # Lines carry readable labels so the printed report needs no extra lookups.
        line = adjustment["lines"][0]
        assert line["product_name"] == product["name"]
        assert line["batch_number"] == "B-P"
        assert line["warehouse_name"] == "الرئيسي"

    async def test_cost_known_false_when_batch_has_no_cost(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive(client, admin, product["id"], warehouse_id, "B-N", 60, "50")

        response = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "expired",
                "lines": [{"batch_id": batch["id"], "quantity": "9"}],
            },
        )
        assert response.status_code == 201
        adjustment = response.json()["data"]
        # Quantity is still known even though the money value is not.
        assert as_decimal(adjustment["total_quantity"]) == Decimal("9")
        assert as_decimal(adjustment["total_cost"]) == Decimal("0.00")
        assert adjustment["cost_known"] is False


class TestAdjustmentCancellation:
    async def _post_adjustment(
        self, client: AsyncClient, admin: dict[str, str], quantity: str = "20"
    ) -> tuple[dict, dict, int]:
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
                "lines": [{"batch_id": batch["id"], "quantity": quantity}],
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["data"], product, warehouse_id

    async def test_cancel_restocks_and_reverses_journal_entry(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        adjustment, product, _ = await self._post_adjustment(client, admin)

        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("80")

        cancel = await client.post(
            f"/api/v1/inventory/stock/adjustments/{adjustment['id']}/cancel",
            headers=admin,
            json={"cancel_reason": "سُجّل بالخطأ"},
        )
        assert cancel.status_code == 200, cancel.text
        cancelled = cancel.json()["data"]
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancel_reason"] == "سُجّل بالخطأ"
        assert cancelled["cancelled_at"] is not None

        # The goods are back in the original batch.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("100")

        # And the loss posting is reversed: inventory debited, damage credited.
        entries = await entries_for(
            client, admin, "stock_adjustment_cancel", adjustment["id"]
        )
        assert len(entries) == 1
        items = items_by_code(entries[0])
        assert items["1030"] == (Decimal("100.00"), Decimal("0"))
        assert items["5030"] == (Decimal("0"), Decimal("100.00"))

    async def test_double_cancel_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        adjustment, product, _ = await self._post_adjustment(client, admin)

        first = await client.post(
            f"/api/v1/inventory/stock/adjustments/{adjustment['id']}/cancel",
            headers=admin,
            json={},
        )
        assert first.status_code == 200

        second = await client.post(
            f"/api/v1/inventory/stock/adjustments/{adjustment['id']}/cancel",
            headers=admin,
            json={},
        )
        assert second.status_code == 400
        assert "ملغى من قبل" in second.json()["message"]

        # Stock was only restored once.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("100")

    async def test_cancel_nonexistent_returns_404(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.post(
            "/api/v1/inventory/stock/adjustments/9999/cancel", headers=admin, json={}
        )
        assert response.status_code == 404

    async def test_storekeeper_cannot_cancel(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        adjustment, _, _ = await self._post_adjustment(client, admin)

        response = await client.post(
            f"/api/v1/inventory/stock/adjustments/{adjustment['id']}/cancel",
            headers=store,
            json={},
        )
        assert response.status_code == 403

    async def test_get_single_adjustment_for_printing(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        adjustment, product, _ = await self._post_adjustment(client, admin)

        response = await client.get(
            f"/api/v1/inventory/stock/adjustments/{adjustment['id']}", headers=admin
        )
        assert response.status_code == 200, response.text
        fetched = response.json()["data"]
        assert fetched["id"] == adjustment["id"]
        assert fetched["lines"][0]["product_name"] == product["name"]


class TestDamageReport:
    async def test_report_groups_by_reason_and_product_over_period(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "100", "5.00"
        )

        for reason, quantity in (("damaged", "10"), ("expired", "4")):
            response = await client.post(
                "/api/v1/inventory/stock/adjustments",
                headers=admin,
                json={
                    "reason": reason,
                    "lines": [{"batch_id": batch["id"], "quantity": quantity}],
                },
            )
            assert response.status_code == 201, response.text

        report = await client.get(
            "/api/v1/analytics/inventory/damage-report", headers=admin
        )
        assert report.status_code == 200, report.text
        data = report.json()["data"]
        # 14 units total x 5.00 = 70.00
        assert data["adjustment_count"] == 2
        assert as_decimal(data["total_quantity"]) == Decimal("14")
        assert as_decimal(data["total_cost"]) == Decimal("70.00")

        by_reason = {row["reason"]: row for row in data["by_reason"]}
        assert as_decimal(by_reason["damaged"]["total_quantity"]) == Decimal("10")
        assert as_decimal(by_reason["damaged"]["total_cost"]) == Decimal("50.00")
        assert as_decimal(by_reason["expired"]["total_cost"]) == Decimal("20.00")

        assert len(data["by_product"]) == 1
        assert data["by_product"][0]["product_name"] == product["name"]
        assert as_decimal(data["by_product"][0]["total_quantity"]) == Decimal("14")

    async def test_cancelled_adjustments_excluded_from_report(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "100", "5.00"
        )
        adjustment = (
            await client.post(
                "/api/v1/inventory/stock/adjustments",
                headers=admin,
                json={
                    "reason": "damaged",
                    "lines": [{"batch_id": batch["id"], "quantity": "10"}],
                },
            )
        ).json()["data"]

        before = (
            await client.get("/api/v1/analytics/inventory/damage-report", headers=admin)
        ).json()["data"]
        assert as_decimal(before["total_cost"]) == Decimal("50.00")

        cancel = await client.post(
            f"/api/v1/inventory/stock/adjustments/{adjustment['id']}/cancel",
            headers=admin,
            json={},
        )
        assert cancel.status_code == 200

        after = (
            await client.get("/api/v1/analytics/inventory/damage-report", headers=admin)
        ).json()["data"]
        assert after["adjustment_count"] == 0
        assert as_decimal(after["total_cost"]) == Decimal("0.00")
        assert after["by_reason"] == []

    async def test_period_filter_excludes_out_of_range(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        batch = await receive_with_cost(
            client, admin, product["id"], warehouse_id, "B-1", 60, "100", "5.00"
        )
        await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "damaged",
                "lines": [{"batch_id": batch["id"], "quantity": "10"}],
            },
        )

        # A window that ended before today cannot contain today's write-off.
        report = await client.get(
            "/api/v1/analytics/inventory/damage-report",
            headers=admin,
            params={"date_from": "2020-01-01", "date_to": "2020-12-31"},
        )
        assert report.status_code == 200
        assert report.json()["data"]["adjustment_count"] == 0
