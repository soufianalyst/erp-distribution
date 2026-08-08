"""Integration tests for warehouse-pickup fulfillment (استلام من المستودع)."""

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_STORE_PASSWORD, login
from app.tests.test_delivery import create_trip
from app.tests.test_sales import create_customer, setup_stocked_catalog


async def post_pickup_invoice(
    client: AsyncClient,
    headers: dict[str, str],
    customer_id: int,
    warehouse_id: int,
    product_id: int,
    fulfillment: str = "pickup",
):
    return await client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "payment_method": "cash",
            "fulfillment": fulfillment,
            "lines": [{"product_id": product_id, "quantity": "5"}],
        },
    )


class TestPickupFulfillment:
    async def test_pickup_invoice_awaits_then_handed_over(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        response = await post_pickup_invoice(
            client, admin, customer_id, warehouse_id, product["id"]
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        assert invoice["fulfillment"] == "pickup"
        assert invoice["picked_up_at"] is None
        assert invoice["payment_confirmed_at"] is None

        # Cash invoice: storekeeper cannot hand it over before the cashier collects it.
        blocked = await client.post(
            f"/api/v1/sales/invoices/{invoice['id']}/pickup", headers=store
        )
        assert blocked.status_code == 400
        assert "الصندوق" in blocked.json()["message"]

        confirmed = await client.post(
            f"/api/v1/cashier/invoices/{invoice['id']}/collect",
            headers=admin,
            json={"amount": invoice["total"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["data"]["payment_confirmed_at"] is not None

        # Storekeeper hands the goods over at the counter.
        handover = await client.post(
            f"/api/v1/sales/invoices/{invoice['id']}/pickup", headers=store
        )
        assert handover.status_code == 200, handover.text
        assert handover.json()["data"]["picked_up_at"] is not None

        # A second handover is rejected.
        again = await client.post(
            f"/api/v1/sales/invoices/{invoice['id']}/pickup", headers=store
        )
        assert again.status_code == 400

    async def test_delivery_invoice_cannot_be_picked_up(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        response = await post_pickup_invoice(
            client,
            admin,
            customer_id,
            warehouse_id,
            product["id"],
            fulfillment="delivery",
        )
        invoice_id = response.json()["data"]["id"]

        handover = await client.post(
            f"/api/v1/sales/invoices/{invoice_id}/pickup", headers=admin
        )
        assert handover.status_code == 400
        assert "توصيل" in handover.json()["message"]

    async def test_pickup_invoice_rejected_from_delivery_trips(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        response = await post_pickup_invoice(
            client, admin, customer_id, warehouse_id, product["id"]
        )
        invoice_id = response.json()["data"]["id"]

        trip = await create_trip(client, admin, warehouse_id)
        added = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": invoice_id},
        )
        assert added.status_code == 400
        assert "استلام من المستودع" in added.json()["message"]
