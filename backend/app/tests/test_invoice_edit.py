"""Integration tests for manager-only sales invoice editing."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    DEFAULT_TAX_RATE_ID,
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_inventory import as_decimal
from app.tests.test_sales import create_customer, post_invoice, setup_stocked_catalog


async def sold_invoice(
    client: AsyncClient, admin: dict[str, str]
) -> tuple[int, dict, int, int]:
    """Stock two batches (B-SOON 20, B-LATE 30) and sell 25 on credit; returns ids."""
    warehouse_id, product = await setup_stocked_catalog(client, admin)
    customer_id = await create_customer(client, admin, credit_limit="1000")
    response = await post_invoice(
        client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
    )
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["id"]), product, customer_id, warehouse_id


class TestInvoiceEdit:
    async def test_admin_edits_quantity_and_everything_recalculates(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice_id, product, customer_id, warehouse_id = await sold_invoice(
            client, admin
        )

        # Shrink the sale from 25 to 10 units.
        response = await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=admin,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert response.status_code == 200, response.text
        invoice = response.json()["data"]

        # New totals: 10 x 10.50 = 105 + VAT 16.80 = 121.80.
        assert as_decimal(invoice["subtotal"]) == Decimal("105.00")
        assert as_decimal(invoice["total"]) == Decimal("121.80")
        # FEFO re-applied: all 10 come from B-SOON.
        assert [line["batch_number"] for line in invoice["lines"]] == ["B-SOON"]

        # Stock restored then re-deducted: B-SOON 20-10=10, B-LATE full 30.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        by_number = {b["batch_number"]: as_decimal(b["quantity"]) for b in batches}
        assert by_number == {"B-SOON": Decimal("10"), "B-LATE": Decimal("30")}

        # Customer balance reflects only the new total.
        statement = (
            await client.get(
                f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("121.80")

    async def test_edit_replaces_journal_entries(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice_id, product, customer_id, warehouse_id = await sold_invoice(
            client, admin
        )

        await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=admin,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )

        entries = (
            await client.get(
                "/api/v1/accounting/journal-entries",
                headers=admin,
                params={"reference_type": "sales_invoice", "reference_id": invoice_id},
            )
        ).json()["data"]
        # Exactly one revenue entry remains (no cost entry: direct receiving has no unit cost).
        revenue_entries = [e for e in entries if "فاتورة مبيعات" in e["description"]]
        assert len(revenue_entries) == 1
        items = {
            i["account"]["code"]: (as_decimal(i["debit"]), as_decimal(i["credit"]))
            for i in revenue_entries[0]["items"]
        }
        assert items["1020"] == (Decimal("121.80"), Decimal("0"))
        assert items["4010"] == (Decimal("0"), Decimal("105.00"))

        # The trial balance still balances after the swap.
        report = (
            await client.get("/api/v1/accounting/reports/trial-balance", headers=admin)
        ).json()["data"]
        assert report["is_balanced"] is True

    async def test_edit_with_insufficient_stock_leaves_invoice_intact(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice_id, product, customer_id, warehouse_id = await sold_invoice(
            client, admin
        )

        # Only 50 exist in total; asking for 60 must fail atomically.
        response = await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=admin,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "60"}],
            },
        )
        assert response.status_code == 400

        # Original invoice and stock are untouched.
        invoice = (
            await client.get(f"/api/v1/sales/invoices/{invoice_id}", headers=admin)
        ).json()["data"]
        assert as_decimal(invoice["total"]) == Decimal("304.50")
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("25")

    async def test_edit_blocked_when_returns_exist(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice_id, product, customer_id, warehouse_id = await sold_invoice(
            client, admin
        )

        ret = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "5"}],
            },
        )
        assert ret.status_code == 201

        response = await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=admin,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert response.status_code == 400
        assert "مرتجعات" in response.json()["message"]

    async def test_sales_rep_cannot_edit_invoice(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        invoice_id, product, customer_id, warehouse_id = await sold_invoice(
            client, admin
        )

        response = await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=sales,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert response.status_code == 403
