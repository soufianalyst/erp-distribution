"""Integration tests for physical stocktakes (الجرد): counting, variances, settlement."""

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
)
from app.tests.test_stock_adjustments import (
    entries_for,
    items_by_code,
    receive_with_cost,
)

INVENTORY = "1030"
STOCKTAKE_VARIANCE = "5040"


async def setup_stock(
    client: AsyncClient,
    headers: dict[str, str],
    quantity: str = "100",
    unit_cost: str = "8.00",
    sku: str = "COUNT-1",
) -> tuple[int, dict]:
    """One warehouse holding `quantity` of one product; returns (warehouse_id, product)."""
    warehouse_id = await create_warehouse(client, headers, f"مخزن-{sku}")
    product = await create_product(client, headers, sku, warehouse_id=warehouse_id)
    await receive_with_cost(
        client, headers, product["id"], warehouse_id, "CB-1", 120, quantity, unit_cost
    )
    return warehouse_id, product


async def open_count(
    client: AsyncClient, headers: dict[str, str], warehouse_id: int
) -> dict:
    response = await client.post(
        "/api/v1/inventory/stocktakes",
        headers=headers,
        json={"warehouse_id": warehouse_id, "notes": "جرد دوري"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def save_count(
    client: AsyncClient, headers: dict[str, str], stocktake: dict, counted: str
) -> dict:
    response = await client.put(
        f"/api/v1/inventory/stocktakes/{stocktake['id']}/counts",
        headers=headers,
        json={"counts": [{"line_id": stocktake["lines"][0]["id"], "counted_quantity": counted}]},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def batch_quantity(
    client: AsyncClient, headers: dict[str, str], product_id: int
) -> Decimal:
    batches = (
        await client.get(
            f"/api/v1/inventory/products/{product_id}/batches", headers=headers
        )
    ).json()["data"]
    return sum((as_decimal(b["quantity"]) for b in batches), Decimal("0"))


class TestOpeningACount:
    async def test_opening_snapshots_expected_quantities(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)

        stocktake = await open_count(client, admin, warehouse_id)
        assert stocktake["status"] == "counting"
        assert stocktake["line_count"] == 1
        assert stocktake["counted_line_count"] == 0
        line = stocktake["lines"][0]
        assert line["product_id"] == product["id"]
        assert line["batch_number"] == "CB-1"
        assert as_decimal(line["expected_quantity"]) == Decimal("100")
        # Uncounted, so no variance is implied yet.
        assert line["counted_quantity"] is None
        assert as_decimal(line["variance"]) == Decimal("0")
        assert as_decimal(line["unit_cost"]) == Decimal("8.00")

    async def test_opening_does_not_touch_stock(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)
        await open_count(client, admin, warehouse_id)
        assert await batch_quantity(client, admin, product["id"]) == Decimal("100")

    async def test_second_open_count_rejected(self, client: AsyncClient) -> None:
        """Two live sheets would each hold a stale snapshot; the later post would
        undo the earlier one."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        await open_count(client, admin, warehouse_id)

        response = await client.post(
            "/api/v1/inventory/stocktakes",
            headers=admin,
            json={"warehouse_id": warehouse_id},
        )
        assert response.status_code == 409
        assert "جرد مفتوح" in response.json()["message"]

    async def test_can_reopen_after_cancelling(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        first = await open_count(client, admin, warehouse_id)

        cancelled = await client.post(
            f"/api/v1/inventory/stocktakes/{first['id']}/cancel",
            headers=admin,
            json={"cancel_reason": "بدأنا في الوقت الخطأ"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "cancelled"

        second = await open_count(client, admin, warehouse_id)
        assert second["id"] != first["id"]

    async def test_empty_warehouse_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن فارغ")
        response = await client.post(
            "/api/v1/inventory/stocktakes",
            headers=admin,
            json={"warehouse_id": warehouse_id},
        )
        assert response.status_code == 400
        assert "لا يوجد مخزون" in response.json()["message"]


class TestCounting:
    async def test_saving_counts_computes_variance_without_moving_stock(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)

        saved = await save_count(client, admin, stocktake, "93")
        line = saved["lines"][0]
        assert as_decimal(line["counted_quantity"]) == Decimal("93")
        assert as_decimal(line["variance"]) == Decimal("-7")
        assert as_decimal(line["variance_value"]) == Decimal("-56.00")
        assert saved["counted_line_count"] == 1
        assert saved["variance_line_count"] == 1
        # Still only counting: the shelf figure has not been applied yet.
        assert saved["status"] == "counting"
        assert await batch_quantity(client, admin, product["id"]) == Decimal("100")

    async def test_zero_is_a_real_count(self, client: AsyncClient) -> None:
        """0 means "counted, found nothing" — distinct from NULL "not counted"."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)

        saved = await save_count(client, admin, stocktake, "0")
        assert as_decimal(saved["lines"][0]["counted_quantity"]) == Decimal("0")
        assert as_decimal(saved["lines"][0]["variance"]) == Decimal("-100")
        assert saved["counted_line_count"] == 1

    async def test_recounting_overwrites(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)

        await save_count(client, admin, stocktake, "80")
        saved = await save_count(client, admin, stocktake, "95")
        assert as_decimal(saved["lines"][0]["counted_quantity"]) == Decimal("95")
        assert as_decimal(saved["lines"][0]["variance"]) == Decimal("-5")

    async def test_line_from_another_count_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)

        response = await client.put(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/counts",
            headers=admin,
            json={
                "counts": [
                    {
                        "line_id": stocktake["lines"][0]["id"] + 9999,
                        "counted_quantity": "5",
                    }
                ]
            },
        )
        assert response.status_code == 400
        assert "لا ينتمي" in response.json()["message"]


class TestPostingShortfall:
    async def test_shortfall_reduces_stock_and_posts_a_loss(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        await save_count(client, admin, stocktake, "93")

        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text
        data = posted.json()["data"]
        assert data["status"] == "posted"
        assert data["posted_at"] is not None
        # 7 units short at 8.00 = a 56.00 loss.
        assert as_decimal(data["net_value"]) == Decimal("-56.00")
        assert await batch_quantity(client, admin, product["id"]) == Decimal("93")

        entries = await entries_for(client, admin, "stocktake", stocktake["id"])
        assert len(entries) == 1
        items = items_by_code(entries[0])
        assert items[STOCKTAKE_VARIANCE] == (Decimal("56.00"), Decimal("0"))
        assert items[INVENTORY] == (Decimal("0"), Decimal("56.00"))


class TestPostingSurplus:
    async def test_surplus_increases_stock_and_credits_the_variance(
        self, client: AsyncClient
    ) -> None:
        """The half of counting that write-offs could never express."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        await save_count(client, admin, stocktake, "112")

        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text
        assert as_decimal(posted.json()["data"]["net_value"]) == Decimal("96.00")
        assert await batch_quantity(client, admin, product["id"]) == Decimal("112")

        items = items_by_code(
            (await entries_for(client, admin, "stocktake", stocktake["id"]))[0]
        )
        assert items[INVENTORY] == (Decimal("96.00"), Decimal("0"))
        assert items[STOCKTAKE_VARIANCE] == (Decimal("0"), Decimal("96.00"))


class TestPostingMixedAndEdgeCases:
    async def test_shortfall_and_surplus_net_off_in_one_entry(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن مختلط")
        short = await create_product(client, admin, "MIX-SHORT", warehouse_id=warehouse_id)
        over = await create_product(client, admin, "MIX-OVER", warehouse_id=warehouse_id)
        await receive_with_cost(
            client, admin, short["id"], warehouse_id, "MB-1", 120, "50", "10.00"
        )
        await receive_with_cost(
            client, admin, over["id"], warehouse_id, "MB-2", 120, "50", "10.00"
        )

        stocktake = await open_count(client, admin, warehouse_id)
        by_product = {line["product_id"]: line for line in stocktake["lines"]}
        response = await client.put(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/counts",
            headers=admin,
            json={
                "counts": [
                    # 4 short (-40.00) and 9 over (+90.00) → net +50.00.
                    {"line_id": by_product[short["id"]]["id"], "counted_quantity": "46"},
                    {"line_id": by_product[over["id"]]["id"], "counted_quantity": "59"},
                ]
            },
        )
        assert response.status_code == 200, response.text

        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text
        assert as_decimal(posted.json()["data"]["net_value"]) == Decimal("50.00")
        assert await batch_quantity(client, admin, short["id"]) == Decimal("46")
        assert await batch_quantity(client, admin, over["id"]) == Decimal("59")

        entries = await entries_for(client, admin, "stocktake", stocktake["id"])
        assert len(entries) == 1
        items = items_by_code(entries[0])
        assert items[INVENTORY] == (Decimal("50.00"), Decimal("0"))
        assert items[STOCKTAKE_VARIANCE] == (Decimal("0"), Decimal("50.00"))

    async def test_uncounted_lines_are_left_alone(self, client: AsyncClient) -> None:
        """An aisle nobody reached is not a shortfall."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن جزئي")
        counted = await create_product(client, admin, "PART-A", warehouse_id=warehouse_id)
        skipped = await create_product(client, admin, "PART-B", warehouse_id=warehouse_id)
        await receive_with_cost(
            client, admin, counted["id"], warehouse_id, "PB-1", 120, "40", "5.00"
        )
        await receive_with_cost(
            client, admin, skipped["id"], warehouse_id, "PB-2", 120, "40", "5.00"
        )

        stocktake = await open_count(client, admin, warehouse_id)
        by_product = {line["product_id"]: line for line in stocktake["lines"]}
        await client.put(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/counts",
            headers=admin,
            json={
                "counts": [
                    {"line_id": by_product[counted["id"]]["id"], "counted_quantity": "38"}
                ]
            },
        )
        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text

        assert await batch_quantity(client, admin, counted["id"]) == Decimal("38")
        # Untouched, not zeroed.
        assert await batch_quantity(client, admin, skipped["id"]) == Decimal("40")

    async def test_posting_with_nothing_counted_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)

        response = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert response.status_code == 400
        assert "الكميات الفعلية" in response.json()["message"]

    async def test_no_variance_posts_no_journal_entry(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        await save_count(client, admin, stocktake, "100")

        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text
        assert as_decimal(posted.json()["data"]["net_value"]) == Decimal("0")
        assert await batch_quantity(client, admin, product["id"]) == Decimal("100")
        # Books agreed with the shelf, so there is nothing to post.
        assert await entries_for(client, admin, "stocktake", stocktake["id"]) == []

    async def test_variance_without_a_known_cost_moves_quantity_only(
        self, client: AsyncClient
    ) -> None:
        """Stock received outside a purchase invoice has no cost, so the count can
        correct the quantity without any value to post."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن بلا تكلفة")
        product = await create_product(client, admin, "NOCOST-1", warehouse_id=warehouse_id)
        await client.post(
            "/api/v1/inventory/stock/receive",
            headers=admin,
            json={
                "product_id": product["id"],
                "warehouse_id": warehouse_id,
                "batch_number": "NC-1",
                "expiry_date": "2027-12-31",
                "quantity": "30",
            },
        )

        stocktake = await open_count(client, admin, warehouse_id)
        assert as_decimal(stocktake["lines"][0]["unit_cost"]) == Decimal("0")
        await save_count(client, admin, stocktake, "25")
        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text
        assert as_decimal(posted.json()["data"]["net_value"]) == Decimal("0")
        assert await batch_quantity(client, admin, product["id"]) == Decimal("25")
        assert await entries_for(client, admin, "stocktake", stocktake["id"]) == []

    async def test_variance_is_applied_as_a_delta_not_an_overwrite(
        self, client: AsyncClient
    ) -> None:
        """Stock legitimately moves between counting and posting. Applying the
        variance as a delta preserves that movement; overwriting would resurrect
        the sold units."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        # Counted 95 of the expected 100 — a shortfall of 5.
        await save_count(client, admin, stocktake, "95")

        # Then 20 leave the warehouse before the sheet is posted.
        writeoff = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "damaged",
                "lines": [
                    {
                        "batch_id": stocktake["lines"][0]["batch_id"],
                        "quantity": "20",
                    }
                ],
            },
        )
        assert writeoff.status_code == 201, writeoff.text
        assert await batch_quantity(client, admin, product["id"]) == Decimal("80")

        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text
        # 80 on hand minus the 5 the count found missing = 75, not 95.
        assert await batch_quantity(client, admin, product["id"]) == Decimal("75")

    async def test_settlement_that_would_go_negative_is_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        await save_count(client, admin, stocktake, "10")  # shortfall of 90

        # Nearly everything leaves before posting, so -90 cannot be applied.
        await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=admin,
            json={
                "reason": "damaged",
                "lines": [
                    {"batch_id": stocktake["lines"][0]["batch_id"], "quantity": "95"}
                ],
            },
        )

        response = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert response.status_code == 400
        assert "سالباً" in response.json()["message"]
        # Nothing applied: the count is still open and stock is unchanged.
        assert await batch_quantity(client, admin, product["id"]) == Decimal("5")
        still = (
            await client.get(
                f"/api/v1/inventory/stocktakes/{stocktake['id']}", headers=admin
            )
        ).json()["data"]
        assert still["status"] == "counting"


class TestStocktakeLifecycleGuards:
    async def test_posted_count_cannot_be_recounted_or_reposted(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        await save_count(client, admin, stocktake, "97")
        await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )

        recount = await client.put(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/counts",
            headers=admin,
            json={
                "counts": [
                    {"line_id": stocktake["lines"][0]["id"], "counted_quantity": "99"}
                ]
            },
        )
        assert recount.status_code == 400

        repost = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert repost.status_code == 400

    async def test_posted_count_cannot_be_cancelled(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        await save_count(client, admin, stocktake, "97")
        await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )

        response = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/cancel",
            headers=admin,
            json={},
        )
        assert response.status_code == 400

    async def test_cancelled_count_cannot_be_posted(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)
        await save_count(client, admin, stocktake, "97")
        await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/cancel",
            headers=admin,
            json={},
        )

        response = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert response.status_code == 400

    async def test_counts_can_be_filtered_by_status(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)
        stocktake = await open_count(client, admin, warehouse_id)

        counting = (
            await client.get(
                "/api/v1/inventory/stocktakes",
                headers=admin,
                params={"stocktake_status": "counting"},
            )
        ).json()["data"]
        assert stocktake["id"] in [s["id"] for s in counting]

        posted = (
            await client.get(
                "/api/v1/inventory/stocktakes",
                headers=admin,
                params={"stocktake_status": "posted"},
            )
        ).json()["data"]
        assert stocktake["id"] not in [s["id"] for s in posted]


class TestStocktakePermissions:
    async def test_storekeeper_can_run_a_count(self, client: AsyncClient) -> None:
        """Counting is warehouse floor work, so the storekeeper role owns it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stock(client, admin)

        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        stocktake = await open_count(client, store, warehouse_id)
        await save_count(client, store, stocktake, "98")
        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=store
        )
        assert posted.status_code == 200, posted.text
        assert await batch_quantity(client, admin, product["id"]) == Decimal("98")

    async def test_sales_role_cannot_open_a_count(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _ = await setup_stock(client, admin)

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.post(
            "/api/v1/inventory/stocktakes",
            headers=salesman,
            json={"warehouse_id": warehouse_id},
        )
        assert response.status_code == 403
