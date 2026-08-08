"""A return recorded before the goods leave must reduce what the warehouse hands over.

Stock is deducted when the invoice is posted, but the goods physically leave at
pickup or delivery. In that window the system's figure and the shelf legitimately
disagree, and a resellable return lands in the middle of it: the goods are added back
to stock as though the customer returned them, when they never left.

Both picking documents summed the invoice lines as issued, so the warehouse was told
to hand over the original count anyway. Measured before the fix: sell 10, return 3,
and the picking list still said 10 — the customer receives goods already credited to
them and the shelf ends up three short of what the books claim, discovered weeks
later as a stocktake shortfall.

Netting the documents makes the arithmetic close exactly: 40 + 3 in the system, 50 − 7
on the shelf, both 43.
"""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer


async def sell(client, headers, customer_id, product_id, quantity, fulfillment="delivery"):
    response = await client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "payment_method": "credit",
            "fulfillment": fulfillment,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def give_back(client, headers, invoice_id, product_id, quantity,
                    reason="resellable"):
    return await client.post(
        "/api/v1/sales/returns",
        headers=headers,
        json={
            "invoice_id": invoice_id,
            "reason": reason,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )


class TestThePickingDocumentsNetTheReturn:
    async def test_the_prep_sheet_shows_what_is_still_owed(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع التجهيز")
        product = await create_product(client, admin, "PRP-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "PRP-B1", 200, "50")
        customer_id = await create_customer(client, admin, "بقالة التجهيز", credit_limit="9999")

        invoice = await sell(client, admin, customer_id, product["id"], "10", "pickup")
        assert (await give_back(client, admin, invoice["id"], product["id"], "3")).status_code == 201

        prep = await client.get(
            f"/api/v1/delivery/invoices/{invoice['id']}/prep", headers=admin
        )
        assert prep.status_code == 200, prep.text
        quantities = [Decimal(row["quantity"]) for row in prep.json()["data"]["lines"]]
        assert sum(quantities) == Decimal("7"), (
            f"prep sheet asks for {sum(quantities)} when only 7 is still owed — the "
            "extra would be handed over free"
        )

    async def test_the_trip_picking_list_nets_the_return(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع الرحلة")
        product = await create_product(client, admin, "PCK-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "PCK-B1", 200, "50")
        customer_id = await create_customer(client, admin, "بقالة الرحلة", credit_limit="9999")

        invoice = await sell(client, admin, customer_id, product["id"], "10")
        await give_back(client, admin, invoice["id"], product["id"], "3")

        trip = await client.post(
            "/api/v1/delivery/trips",
            headers=store,
            json={"driver_name": "سمير", "warehouse_id": warehouse_id},
        )
        trip_id = trip.json()["data"]["id"]
        await client.post(
            f"/api/v1/delivery/trips/{trip_id}/invoices",
            headers=store,
            json={"invoice_id": invoice["id"]},
        )
        picking = await client.get(
            f"/api/v1/delivery/trips/{trip_id}/picking-list", headers=store
        )
        assert picking.status_code == 200, picking.text
        data = picking.json()["data"]
        mine = [row for row in data["lines"] if row["product_id"] == product["id"]]
        assert sum(Decimal(row["quantity"]) for row in mine) == Decimal("7")

    async def test_a_fully_returned_line_disappears_from_the_list(
        self, client: AsyncClient
    ) -> None:
        """Zero to pick means nothing to print, not a line reading 0."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع الصفر")
        product = await create_product(client, admin, "ALL-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "ALL-B1", 200, "50")
        customer_id = await create_customer(client, admin, "بقالة الكامل", credit_limit="9999")

        invoice = await sell(client, admin, customer_id, product["id"], "10", "pickup")
        await give_back(client, admin, invoice["id"], product["id"], "10")

        prep = await client.get(
            f"/api/v1/delivery/invoices/{invoice['id']}/prep", headers=admin
        )
        assert prep.status_code == 200, prep.text
        assert prep.json()["data"]["lines"] == []

    async def test_a_damaged_return_nets_the_documents_too(
        self, client: AsyncClient
    ) -> None:
        """The reason changes where the cost lands, not what is owed to the customer."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع التالف")
        product = await create_product(client, admin, "DMG-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "DMG-B1", 200, "50")
        customer_id = await create_customer(client, admin, "بقالة التالف", credit_limit="9999")

        invoice = await sell(client, admin, customer_id, product["id"], "10", "pickup")
        await give_back(client, admin, invoice["id"], product["id"], "4",
                        reason="damaged_customer")

        prep = await client.get(
            f"/api/v1/delivery/invoices/{invoice['id']}/prep", headers=admin
        )
        quantities = [Decimal(row["quantity"]) for row in prep.json()["data"]["lines"]]
        assert sum(quantities) == Decimal("6")


class TestOnceTheTripHasLeft:
    async def test_a_return_is_refused_while_the_goods_are_on_the_road(
        self, client: AsyncClient
    ) -> None:
        """Netting cannot reach a document already on the seat beside the driver."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع الطريق")
        product = await create_product(client, admin, "RD-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "RD-B1", 200, "50")
        customer_id = await create_customer(client, admin, "بقالة الطريق", credit_limit="9999")

        invoice = await sell(client, admin, customer_id, product["id"], "10")
        trip = await client.post(
            "/api/v1/delivery/trips",
            headers=store,
            json={"driver_name": "ياسر", "warehouse_id": warehouse_id},
        )
        trip_id = trip.json()["data"]["id"]
        await client.post(
            f"/api/v1/delivery/trips/{trip_id}/invoices",
            headers=store,
            json={"invoice_id": invoice["id"]},
        )
        dispatch = await client.post(
            f"/api/v1/delivery/trips/{trip_id}/dispatch", headers=store
        )
        assert dispatch.status_code == 200, dispatch.text

        refused = await give_back(client, admin, invoice["id"], product["id"], "3")
        assert refused.status_code == 400, refused.text
        message = refused.json()["message"]
        # The message must say what to do instead, or it just blocks the user.
        assert "على الطريق" in message and "بعد التسليم" in message, message

    async def test_it_is_allowed_again_once_delivered(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The after-delivery case: the goods really came back, and nothing blocks it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع بعد التسليم")
        product = await create_product(client, admin, "AFT-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "AFT-B1", 200, "50")
        customer_id = await create_customer(client, admin, "بقالة بعد التسليم", credit_limit="9999")

        invoice = await sell(client, admin, customer_id, product["id"], "10")
        trip = await client.post(
            "/api/v1/delivery/trips",
            headers=store,
            json={"driver_name": "منذر", "warehouse_id": warehouse_id},
        )
        trip_id = trip.json()["data"]["id"]
        await client.post(
            f"/api/v1/delivery/trips/{trip_id}/invoices",
            headers=store,
            json={"invoice_id": invoice["id"]},
        )
        await client.post(f"/api/v1/delivery/trips/{trip_id}/dispatch", headers=store)
        detail = (await client.get(f"/api/v1/delivery/trips/{trip_id}", headers=store)).json()["data"]
        stop_id = detail["stops"][0]["id"]
        delivered = await client.post(
            f"/api/v1/delivery/trips/{trip_id}/stops/{stop_id}/status",
            headers=store,
            json={"status": "delivered"},
        )
        assert delivered.status_code == 200, delivered.text

        accepted = await give_back(client, admin, invoice["id"], product["id"], "3")
        assert accepted.status_code == 201, accepted.text
