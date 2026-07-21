"""Integration tests for the cashier module: receivables, payables, partial payments, daily summary."""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_sales import create_customer, post_invoice, setup_stocked_catalog


async def pay(client, headers, ref_type, ref_id, amount):
    """Helper to call the new unified cashier payment endpoint."""
    return await client.post(
        "/api/v1/cashier/pay",
        headers=headers,
        json={
            "reference_type": ref_type,
            "reference_id": ref_id,
            "amount": amount,
        },
    )


@pytest.mark.anyio
class TestCashierPayments:
    async def test_full_payment_via_amount(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10"
        )
        assert resp.status_code == 201
        invoice_id = resp.json()["data"]["id"]
        total = Decimal(resp.json()["data"]["total"])

        p = await pay(client, admin, "sales", invoice_id, str(total))
        assert p.status_code == 200, p.text
        assert Decimal(p.json()["data"]["paid_amount"]) == total

        pending = await client.get("/api/v1/cashier/receivables", headers=admin)
        ids = [i["id"] for i in pending.json()["data"] if i["type"] == "sales"]
        assert invoice_id not in ids

    async def test_partial_payment(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10"
        )
        invoice_id = resp.json()["data"]["id"]
        total = Decimal(resp.json()["data"]["total"])

        half = total / 2
        p1 = await pay(client, admin, "sales", invoice_id, str(half))
        assert p1.status_code == 200
        assert Decimal(p1.json()["data"]["paid_amount"]) == half

        pending = await client.get("/api/v1/cashier/receivables", headers=admin)
        ids = [i["id"] for i in pending.json()["data"] if i["type"] == "sales"]
        assert invoice_id in ids

        remaining = total - half
        p2 = await pay(client, admin, "sales", invoice_id, str(remaining))
        assert p2.status_code == 200
        assert Decimal(p2.json()["data"]["paid_amount"]) == total

        pending2 = await client.get("/api/v1/cashier/receivables", headers=admin)
        ids2 = [i["id"] for i in pending2.json()["data"] if i["type"] == "sales"]
        assert invoice_id not in ids2

    async def test_zero_amount_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5"
        )
        invoice_id = resp.json()["data"]["id"]

        p = await pay(client, admin, "sales", invoice_id, "0")
        assert p.status_code == 422

    async def test_overpayment_capped(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5"
        )
        invoice_id = resp.json()["data"]["id"]
        total = Decimal(resp.json()["data"]["total"])

        p = await pay(client, admin, "sales", invoice_id, str(total + 1000))
        assert p.status_code == 200, p.text
        assert Decimal(p.json()["data"]["paid_amount"]) == total

    async def test_already_paid_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5"
        )
        invoice_id = resp.json()["data"]["id"]
        total = Decimal(resp.json()["data"]["total"])

        await pay(client, admin, "sales", invoice_id, str(total))

        p2 = await pay(client, admin, "sales", invoice_id, str(total))
        assert p2.status_code == 400

    async def test_cash_invoice_not_in_delivery_before_payment(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5"
        )
        invoice_id = resp.json()["data"]["id"]

        delivery = await client.get("/api/v1/delivery/invoices", headers=admin)
        ids = [inv["id"] for inv in delivery.json()["data"]]
        assert invoice_id not in ids

        total = Decimal(resp.json()["data"]["total"])
        await pay(client, admin, "sales", invoice_id, str(total / 2))
        delivery2 = await client.get("/api/v1/delivery/invoices", headers=admin)
        ids2 = [inv["id"] for inv in delivery2.json()["data"]]
        assert invoice_id not in ids2

        await pay(client, admin, "sales", invoice_id, str(total))
        delivery3 = await client.get("/api/v1/delivery/invoices", headers=admin)
        ids3 = [inv["id"] for inv in delivery3.json()["data"]]
        assert invoice_id in ids3


@pytest.mark.anyio
class TestCashierDailySummary:
    async def test_summary_after_payments(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        resp1 = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5"
        )
        resp2 = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "3"
        )
        inv1 = resp1.json()["data"]
        inv2 = resp2.json()["data"]

        amt1 = Decimal("20")
        amt2 = Decimal("15")

        await pay(client, admin, "sales", inv1["id"], str(amt1))
        await pay(client, admin, "sales", inv2["id"], str(amt2))

        summary = await client.get("/api/v1/cashier/daily-summary", headers=admin)
        assert summary.status_code == 200
        data = summary.json()["data"]
        assert data["total_count"] == 2
        assert Decimal(data["grand_total"]) == amt1 + amt2
        assert len(data["payments"]) == 2
        assert "cash" in data["by_method"]
        assert "sales" in data["by_type"]

    async def test_summary_empty(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        summary = await client.get("/api/v1/cashier/daily-summary", headers=admin)
        assert summary.status_code == 200
        data = summary.json()["data"]
        assert data["total_count"] == 0
        assert Decimal(data["grand_total"]) == Decimal("0")
        assert data["payments"] == []
