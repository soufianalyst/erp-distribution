"""Integration tests for accounting: automatic postings, manual entries, trial balance."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    DEFAULT_TAX_RATE_ID,
    TEST_ACCOUNTANT_PASSWORD,
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    days_from_now,
)
from app.tests.test_purchases import create_supplier


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


async def full_trade_cycle(
    client: AsyncClient, admin: dict[str, str]
) -> dict[str, int]:
    """Purchase on credit with known costs, then sell on credit; returns document ids."""
    warehouse_id = await create_warehouse(client, admin, "الرئيسي")
    product = await create_product(client, admin, warehouse_id=warehouse_id)
    supplier_id = await create_supplier(client, admin)

    purchase = await client.post(
        "/api/v1/purchases/invoices",
        headers=admin,
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "payment_method": "credit",
            "shipping_cost": "20.00",
            "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
            "lines": [
                {
                    "product_id": product["id"],
                    "batch_number": "PB-1",
                    "expiry_date": days_from_now(120),
                    "quantity": "100",
                    "unit_cost": "8.00",
                }
            ],
        },
    )
    assert purchase.status_code == 201, purchase.text

    customer = await client.post(
        "/api/v1/sales/customers",
        headers=admin,
        json={
            "name": "سوبرماركت الاختبار",
            "price_tier": "wholesale",
            "credit_limit": "1000",
        },
    )
    assert customer.status_code == 201

    sale = await client.post(
        "/api/v1/sales/invoices",
        headers=admin,
        json={
            "customer_id": customer.json()["data"]["id"],
            "warehouse_id": warehouse_id,
            "payment_method": "credit",
            "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
            "lines": [{"product_id": product["id"], "quantity": "25"}],
        },
    )
    assert sale.status_code == 201, sale.text

    return {
        "purchase_id": int(purchase.json()["data"]["id"]),
        "sale_id": int(sale.json()["data"]["id"]),
        "customer_id": int(customer.json()["data"]["id"]),
        "supplier_id": supplier_id,
        "product_id": int(product["id"]),
    }


class TestChartOfAccounts:
    async def test_default_chart_is_seeded(self, client: AsyncClient) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        response = await client.get("/api/v1/accounting/accounts", headers=accountant)
        assert response.status_code == 200
        codes = {a["code"] for a in response.json()["data"]}
        assert {"1010", "1020", "1030", "2010", "2020", "4010", "5010"} <= codes

    async def test_sales_role_cannot_view_ledger(self, client: AsyncClient) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get("/api/v1/accounting/accounts", headers=sales)
        assert response.status_code == 403


class TestAutomaticPostings:
    async def test_credit_purchase_posting(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        entries = await entries_for(
            client, admin, "purchase_invoice", ids["purchase_id"]
        )
        assert len(entries) == 1
        items = items_by_code(entries[0])
        # Dr inventory 820 (goods 800 + shipping 20), Dr VAT 128 (16% of 800), Cr payable 948.
        assert items["1030"] == (Decimal("820.00"), Decimal("0"))
        assert items["2020"] == (Decimal("128.00"), Decimal("0"))
        assert items["2010"] == (Decimal("0"), Decimal("948.00"))

    async def test_credit_sale_posting_with_cogs(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        entries = await entries_for(client, admin, "sales_invoice", ids["sale_id"])
        assert len(entries) == 2

        by_desc = {e["description"]: items_by_code(e) for e in entries}
        revenue_entry = next(v for k, v in by_desc.items() if "فاتورة مبيعات" in k)
        cogs_entry = next(v for k, v in by_desc.items() if "تكلفة" in k)

        # 25 x 10.50 = 262.50 + VAT 42.00 = 304.50 receivable.
        assert revenue_entry["1020"] == (Decimal("304.50"), Decimal("0"))
        assert revenue_entry["4010"] == (Decimal("0"), Decimal("262.50"))
        assert revenue_entry["2020"] == (Decimal("0"), Decimal("42.00"))

        # COGS: 25 x 8.00 = 200 out of inventory.
        assert cogs_entry["5010"] == (Decimal("200.00"), Decimal("0"))
        assert cogs_entry["1030"] == (Decimal("0"), Decimal("200.00"))

    async def test_customer_payment_posting(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        payment = await client.post(
            "/api/v1/sales/payments",
            headers=admin,
            json={
                "customer_id": ids["customer_id"],
                "amount": "150.00",
                "method": "bank",
            },
        )
        assert payment.status_code == 201
        payment_id = int(payment.json()["data"]["id"])

        entries = await entries_for(client, admin, "customer_payment", payment_id)
        items = items_by_code(entries[0])
        # Bank method routes to 1015, receivable credited.
        assert items["1015"] == (Decimal("150.00"), Decimal("0"))
        assert items["1020"] == (Decimal("0"), Decimal("150.00"))

    async def test_supplier_payment_posting(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        payment = await client.post(
            "/api/v1/purchases/payments",
            headers=admin,
            json={
                "supplier_id": ids["supplier_id"],
                "amount": "300.00",
                "method": "cash",
            },
        )
        assert payment.status_code == 201
        payment_id = int(payment.json()["data"]["id"])

        entries = await entries_for(client, admin, "supplier_payment", payment_id)
        items = items_by_code(entries[0])
        assert items["2010"] == (Decimal("300.00"), Decimal("0"))
        assert items["1010"] == (Decimal("0"), Decimal("300.00"))

    async def test_resellable_return_posting(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        ret = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": ids["sale_id"],
                "reason": "resellable",
                "lines": [{"product_id": ids["product_id"], "quantity": "10"}],
            },
        )
        assert ret.status_code == 201
        return_id = int(ret.json()["data"]["id"])

        entries = await entries_for(client, admin, "sales_return", return_id)
        assert len(entries) == 2
        by_desc = {e["description"]: items_by_code(e) for e in entries}
        revenue_entry = next(v for k, v in by_desc.items() if "مرتجع مبيعات" in k)
        cost_entry = next(v for k, v in by_desc.items() if "تكلفة" in k)

        # 10 x 10.50 = 105 + VAT 16.80 = 121.80 credited to the customer.
        assert revenue_entry["4020"] == (Decimal("105.00"), Decimal("0"))
        assert revenue_entry["2020"] == (Decimal("16.80"), Decimal("0"))
        assert revenue_entry["1020"] == (Decimal("0"), Decimal("121.80"))

        # Resellable: cost 80 back into inventory, out of COGS.
        assert cost_entry["1030"] == (Decimal("80.00"), Decimal("0"))
        assert cost_entry["5010"] == (Decimal("0"), Decimal("80.00"))

    async def test_damaged_return_posts_loss_not_inventory(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        ret = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": ids["sale_id"],
                "reason": "damaged_transport",
                "lines": [{"product_id": ids["product_id"], "quantity": "10"}],
            },
        )
        assert ret.status_code == 201
        return_id = int(ret.json()["data"]["id"])

        entries = await entries_for(client, admin, "sales_return", return_id)
        cost_entry = next(
            items_by_code(e) for e in entries if "تكلفة" in e["description"]
        )
        # Damaged goods become a loss (5030), never inventory (1030).
        assert cost_entry["5030"] == (Decimal("80.00"), Decimal("0"))
        assert "1030" not in cost_entry


class TestManualEntriesAndTrialBalance:
    async def test_manual_balanced_entry_accepted(self, client: AsyncClient) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        response = await client.post(
            "/api/v1/accounting/journal-entries",
            headers=accountant,
            json={
                "description": "إيداع رأس المال الافتتاحي",
                "items": [
                    {"account_code": "1010", "debit": "5000.00"},
                    {"account_code": "3010", "credit": "5000.00"},
                ],
            },
        )
        assert response.status_code == 201, response.text
        items = items_by_code(response.json()["data"])
        assert items["1010"] == (Decimal("5000.00"), Decimal("0"))
        assert items["3010"] == (Decimal("0"), Decimal("5000.00"))

    async def test_unbalanced_entry_rejected(self, client: AsyncClient) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        response = await client.post(
            "/api/v1/accounting/journal-entries",
            headers=accountant,
            json={
                "description": "قيد غير متوازن",
                "items": [
                    {"account_code": "1010", "debit": "100.00"},
                    {"account_code": "3010", "credit": "90.00"},
                ],
            },
        )
        assert response.status_code == 400
        assert "غير متوازن" in response.json()["message"]

    async def test_unknown_account_rejected(self, client: AsyncClient) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        response = await client.post(
            "/api/v1/accounting/journal-entries",
            headers=accountant,
            json={
                "description": "قيد بحساب مجهول",
                "items": [
                    {"account_code": "9999", "debit": "100.00"},
                    {"account_code": "3010", "credit": "100.00"},
                ],
            },
        )
        assert response.status_code == 404

    async def test_sales_role_cannot_post_manual_entry(
        self, client: AsyncClient
    ) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.post(
            "/api/v1/accounting/journal-entries",
            headers=sales,
            json={
                "description": "محاولة غير مصرح بها",
                "items": [
                    {"account_code": "1010", "debit": "100.00"},
                    {"account_code": "3010", "credit": "100.00"},
                ],
            },
        )
        assert response.status_code == 403

    async def test_trial_balance_balances_after_full_cycle(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        # Add every kind of movement: collection, supplier payment, and a return.
        await client.post(
            "/api/v1/sales/payments",
            headers=admin,
            json={
                "customer_id": ids["customer_id"],
                "amount": "100.00",
                "method": "cash",
            },
        )
        await client.post(
            "/api/v1/purchases/payments",
            headers=admin,
            json={
                "supplier_id": ids["supplier_id"],
                "amount": "400.00",
                "method": "bank",
            },
        )
        await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": ids["sale_id"],
                "reason": "resellable",
                "lines": [{"product_id": ids["product_id"], "quantity": "5"}],
            },
        )

        response = await client.get(
            "/api/v1/accounting/reports/trial-balance", headers=admin
        )
        assert response.status_code == 200
        report = response.json()["data"]
        assert report["is_balanced"] is True
        assert as_decimal(report["total_debit"]) == as_decimal(report["total_credit"])
        assert as_decimal(report["total_debit"]) > 0
