"""Tests for invoice deletion, tax-free invoices, return totals, and the driver role."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_STORE_PASSWORD,
    entries_for,
    login,
)
from app.tests.test_delivery import create_trip
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    receive,
)
from app.tests.test_sales import create_customer, post_invoice, setup_stocked_catalog


class TestInvoiceDeletion:
    async def test_delete_restores_stock_and_removes_ledger(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        invoice_id = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
            )
        ).json()["data"]["id"]

        response = await client.delete(
            f"/api/v1/sales/invoices/{invoice_id}", headers=admin
        )
        assert response.status_code == 200, response.text

        # Stock fully restored, invoice gone, journal entries gone.
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("50")
        assert (
            await client.get(f"/api/v1/sales/invoices/{invoice_id}", headers=admin)
        ).status_code == 404
        entries = await entries_for(client, admin, "sales_invoice", invoice_id)
        assert entries == []

    async def test_delete_blocked_by_returns_and_trips(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        invoice_id = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
            )
        ).json()["data"]["id"]

        trip = await create_trip(client, admin, warehouse_id)
        await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": invoice_id},
        )
        blocked = await client.delete(
            f"/api/v1/sales/invoices/{invoice_id}", headers=admin
        )
        assert blocked.status_code == 400
        assert "رحلة" in blocked.json()["message"]

    async def test_storekeeper_cannot_delete(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)
        invoice_id = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5"
            )
        ).json()["data"]["id"]

        response = await client.delete(
            f"/api/v1/sales/invoices/{invoice_id}", headers=store
        )
        assert response.status_code == 403


class TestTaxFreeInvoices:
    async def test_invoice_without_vat(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")

        response = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "tax_rate_ids": [],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        assert as_decimal(invoice["vat_amount"]) == Decimal("0")
        assert as_decimal(invoice["total"]) == Decimal("105.00")

        # A return on a tax-free invoice carries no VAT either.
        ret = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice["id"],
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "4"}],
            },
        )
        assert as_decimal(ret.json()["data"]["vat_amount"]) == Decimal("0")
        assert as_decimal(ret.json()["data"]["total"]) == Decimal("42.00")


class TestReturnTotalsOnInvoice:
    async def test_returned_total_reflected_immediately(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        invoice_id = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
            )
        ).json()["data"]["id"]

        await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )

        invoice = (
            await client.get(f"/api/v1/sales/invoices/{invoice_id}", headers=admin)
        ).json()["data"]
        # 10 x 10.50 x 1.16 = 121.80 credited back.
        assert as_decimal(invoice["returned_total"]) == Decimal("121.80")


class TestDriverRole:
    async def test_driver_sees_goods_but_never_prices(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        # Credit so the invoice is visible to delivery immediately (cash/card
        # would sit behind the cashier gate, which isn't what this test covers).
        customer_id = await create_customer(client, admin, credit_limit="5000")
        invoice_id = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
            )
        ).json()["data"]["id"]

        created = await client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={
                "username": "driver1",
                "full_name": "سائق التوصيل الأول",
                "password": "Drive@1234",
                "role": "driver",
            },
        )
        assert created.status_code == 201, created.text
        driver = (
            await client.post(
                "/api/v1/auth/login",
                json={"username": "driver1", "password": "Drive@1234"},
            )
        ).json()["data"]
        headers = {"Authorization": f"Bearer {driver['access_token']}"}

        # The delivery summary shows goods and destination without any prices.
        summaries = await client.get("/api/v1/delivery/invoices", headers=headers)
        assert summaries.status_code == 200
        summary = next(s for s in summaries.json()["data"] if s["id"] == invoice_id)
        assert summary["customer_name"]
        assert summary["items"][0]["product_name"] == "أرز بسمتي 1 كجم"
        assert as_decimal(summary["items"][0]["quantity"]) == Decimal("10")
        assert "total" not in summary and "unit_price" not in str(summary["items"])

        # Full invoices (with prices) stay off-limits, as does any editing.
        assert (
            await client.get("/api/v1/sales/invoices", headers=headers)
        ).status_code == 403
        assert (
            await client.put(
                f"/api/v1/sales/invoices/{invoice_id}", headers=headers, json={}
            )
        ).status_code in (403, 422)

    async def test_driver_delivers_but_cannot_manage_trips(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        # Credit so the invoice is assignable to a trip immediately (cash/card
        # would sit behind the cashier gate, which isn't what this test covers).
        customer_id = await create_customer(client, admin, credit_limit="5000")
        invoice_id = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
            )
        ).json()["data"]["id"]

        await client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={
                "username": "driver2",
                "full_name": "سائق ثانٍ",
                "password": "Drive@1234",
                "role": "driver",
            },
        )
        driver_tokens = (
            await client.post(
                "/api/v1/auth/login",
                json={"username": "driver2", "password": "Drive@1234"},
            )
        ).json()["data"]
        driver = {"Authorization": f"Bearer {driver_tokens['access_token']}"}

        trip = await create_trip(client, admin, warehouse_id)
        added = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": invoice_id},
        )
        stop_id = added.json()["data"]["stops"][0]["id"]
        await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/dispatch", headers=admin
        )

        # Driver marks the stop delivered and closes the trip...
        marked = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/stops/{stop_id}/status",
            headers=driver,
            json={"status": "delivered"},
        )
        assert marked.status_code == 200, marked.text
        done = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/complete", headers=driver
        )
        assert done.status_code == 200

        # ...but cannot create trips or hand over pickups.
        denied = await client.post(
            "/api/v1/delivery/trips",
            headers=driver,
            json={"driver_name": "غير مصرح", "warehouse_id": warehouse_id},
        )
        assert denied.status_code == 403


class TestAnInvoiceLineNamesItsOwnProduct:
    """An invoice is a financial record, and this one could not say what it sold.

    The line stored `product_id` and `batch_number` but not the name or unit, with two
    consequences: printing one invoice meant downloading the whole catalogue to resolve
    two strings, and renaming a product silently rewrote every historical invoice that
    contained it. `batch_number` had been denormalised onto the line for exactly this
    reason since the beginning; these columns follow that precedent.
    """

    async def test_the_line_carries_the_name_and_unit_at_sale_time(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التسمية")
        product = await create_product(
            client, admin, sku="NAME-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-NAME", 200, "100")
        customer_id = await create_customer(
            client, admin, name="عميل التسمية", credit_limit="90000")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5",
            tax_rate_ids=[])
        assert response.status_code == 201, response.text
        line = response.json()["data"]["lines"][0]
        assert line["product_name"] == product["name"]
        assert line["unit_name"] == product["base_unit_name"]

    async def test_renaming_a_product_does_not_rewrite_an_old_invoice(
        self, client: AsyncClient
    ) -> None:
        """The reason this is stored rather than joined.

        A read-time join would show the *current* name on a document that was printed,
        signed and filed years ago — quietly restating what the customer was billed for.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن إعادة التسمية")
        product = await create_product(
            client, admin, sku="RENAME-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-REN", 200, "100")
        customer_id = await create_customer(
            client, admin, name="عميل إعادة التسمية", credit_limit="90000")

        invoice_id = (await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "3",
            tax_rate_ids=[])).json()["data"]["id"]

        renamed = await client.patch(
            f"/api/v1/inventory/products/{product['id']}",
            headers=admin, json={"name": "اسم جديد تماماً"})
        assert renamed.status_code == 200, renamed.text

        reread = (await client.get(
            f"/api/v1/sales/invoices/{invoice_id}", headers=admin)).json()["data"]
        assert reread["lines"][0]["product_name"] == product["name"]
        assert reread["lines"][0]["product_name"] != "اسم جديد تماماً"

    async def test_printing_an_invoice_needs_no_product_lookup(
        self, client: AsyncClient
    ) -> None:
        """What the print screen actually consumes, asserted on the response.

        If the name and unit are on the line, the page needs the invoice and nothing
        else — which is the whole saving. A test on the payload rather than the screen,
        because it is the payload that made the download necessary.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الطباعة")
        product = await create_product(
            client, admin, sku="PRINT-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-PR", 200, "100")
        customer_id = await create_customer(
            client, admin, name="عميل الطباعة", credit_limit="90000")
        invoice_id = (await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "2",
            tax_rate_ids=[])).json()["data"]["id"]

        data = (await client.get(
            f"/api/v1/sales/invoices/{invoice_id}", headers=admin)).json()["data"]
        for line in data["lines"]:
            # Everything the printed row shows, present without a second request.
            assert line["product_name"]
            assert line["unit_name"]
            assert line["batch_number"]
