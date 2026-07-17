"""Integration tests for the delivery module: trips, stops, lifecycle, picking lists."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_inventory import as_decimal
from app.tests.test_sales import create_customer, post_invoice, setup_stocked_catalog


async def create_trip(
    client: AsyncClient, headers: dict[str, str], warehouse_id: int
) -> dict:
    response = await client.post(
        "/api/v1/delivery/trips",
        headers=headers,
        json={
            "driver_name": "سائق التوصيل",
            "vehicle": "شاحنة 1234",
            "warehouse_id": warehouse_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def sold_setup(
    client: AsyncClient, admin: dict[str, str]
) -> tuple[int, int, int]:
    """Stock, customer, and two posted invoices; returns (warehouse_id, inv1, inv2)."""
    warehouse_id, product = await setup_stocked_catalog(client, admin)
    customer_id = await create_customer(client, admin, credit_limit="5000")
    inv1 = await post_invoice(
        client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
    )
    inv2 = await post_invoice(
        client, admin, customer_id, warehouse_id, product["id"], "15", "credit"
    )
    assert inv1.status_code == 201 and inv2.status_code == 201
    return warehouse_id, int(inv1.json()["data"]["id"]), int(inv2.json()["data"]["id"])


class TestTrips:
    async def test_storekeeper_manages_full_lifecycle(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id, inv1, inv2 = await sold_setup(client, admin)

        # Storekeeper (default permissions) creates, loads, dispatches, delivers, completes.
        trip = await create_trip(client, store, warehouse_id)
        trip_id = trip["id"]
        assert trip["status"] == "planned"

        for invoice_id in (inv1, inv2):
            response = await client.post(
                f"/api/v1/delivery/trips/{trip_id}/invoices",
                headers=store,
                json={"invoice_id": invoice_id},
            )
            assert response.status_code == 200, response.text
        stops = response.json()["data"]["stops"]
        assert [s["sequence"] for s in stops] == [1, 2]

        dispatched = await client.post(
            f"/api/v1/delivery/trips/{trip_id}/dispatch", headers=store
        )
        assert dispatched.json()["data"]["status"] == "in_transit"

        for stop in stops:
            response = await client.post(
                f"/api/v1/delivery/trips/{trip_id}/stops/{stop['id']}/status",
                headers=store,
                json={"status": "delivered"},
            )
            assert response.status_code == 200

        completed = await client.post(
            f"/api/v1/delivery/trips/{trip_id}/complete", headers=store
        )
        assert completed.status_code == 200
        assert completed.json()["data"]["status"] == "completed"

    async def test_invoice_cannot_ride_two_active_trips(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, inv1, _ = await sold_setup(client, admin)

        trip_a = await create_trip(client, admin, warehouse_id)
        trip_b = await create_trip(client, admin, warehouse_id)
        first = await client.post(
            f"/api/v1/delivery/trips/{trip_a['id']}/invoices",
            headers=admin,
            json={"invoice_id": inv1},
        )
        assert first.status_code == 200
        second = await client.post(
            f"/api/v1/delivery/trips/{trip_b['id']}/invoices",
            headers=admin,
            json={"invoice_id": inv1},
        )
        assert second.status_code == 409

    async def test_dispatch_requires_stops_and_completion_requires_resolution(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, inv1, _ = await sold_setup(client, admin)
        trip = await create_trip(client, admin, warehouse_id)

        empty = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/dispatch", headers=admin
        )
        assert empty.status_code == 400

        added = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": inv1},
        )
        stop_id = added.json()["data"]["stops"][0]["id"]
        await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/dispatch", headers=admin
        )

        # Pending stop blocks completion.
        blocked = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/complete", headers=admin
        )
        assert blocked.status_code == 400

        # A failed delivery still resolves the stop.
        await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/stops/{stop_id}/status",
            headers=admin,
            json={"status": "failed", "notes": "المحل مغلق"},
        )
        done = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/complete", headers=admin
        )
        assert done.status_code == 200

    async def test_picking_list_aggregates_by_product_and_batch(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, inv1, inv2 = await sold_setup(client, admin)
        trip = await create_trip(client, admin, warehouse_id)
        for invoice_id in (inv1, inv2):
            await client.post(
                f"/api/v1/delivery/trips/{trip['id']}/invoices",
                headers=admin,
                json={"invoice_id": invoice_id},
            )

        response = await client.get(
            f"/api/v1/delivery/trips/{trip['id']}/picking-list", headers=admin
        )
        assert response.status_code == 200
        picking = response.json()["data"]
        assert picking["invoice_count"] == 2
        # 10 + 15 = 25 units total, all from B-SOON (20) then B-LATE (5) per FEFO.
        assert as_decimal(picking["total_quantity"]) == Decimal("25")
        by_batch = {
            line["batch_number"]: as_decimal(line["quantity"])
            for line in picking["lines"]
        }
        assert by_batch == {"B-SOON": Decimal("20"), "B-LATE": Decimal("5")}

    async def test_wrong_warehouse_invoice_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, inv1, _ = await sold_setup(client, admin)
        other_warehouse = await client.post(
            "/api/v1/inventory/warehouses", headers=admin, json={"name": "مستودع آخر"}
        )
        trip = await create_trip(
            client, admin, int(other_warehouse.json()["data"]["id"])
        )

        response = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": inv1},
        )
        assert response.status_code == 400
        assert "مستودع مختلف" in response.json()["message"]

    async def test_sales_rep_views_but_cannot_manage(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        warehouse_id, _, _ = await sold_setup(client, admin)

        # Default sales permissions: delivery.view yes, delivery.manage no.
        listing = await client.get("/api/v1/delivery/trips", headers=sales)
        assert listing.status_code == 200

        denied = await client.post(
            "/api/v1/delivery/trips",
            headers=sales,
            json={"driver_name": "غير مصرح", "warehouse_id": warehouse_id},
        )
        assert denied.status_code == 403
