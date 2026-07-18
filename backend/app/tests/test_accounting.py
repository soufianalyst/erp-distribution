"""Integration tests for accounting: automatic postings, manual entries, trial balance."""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.accounting import JournalEntry
from app.domain.models.purchases import PurchaseInvoice
from app.domain.models.sales import SalesInvoice
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


class TestTaxSummary:
    async def test_summary_reflects_sales_and_purchases(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await full_trade_cycle(client, admin)

        response = await client.get(
            "/api/v1/accounting/reports/tax-summary", headers=admin
        )
        assert response.status_code == 200
        report = response.json()["data"]
        assert len(report["rows"]) == 1
        row = report["rows"][0]
        assert row["name"] == "ضريبة القيمة المضافة"
        assert as_decimal(row["collected"]) == Decimal("42.00")
        assert as_decimal(row["paid"]) == Decimal("128.00")
        assert as_decimal(row["net"]) == Decimal("-86.00")
        assert as_decimal(report["total_collected"]) == Decimal("42.00")
        assert as_decimal(report["total_paid"]) == Decimal("128.00")
        assert as_decimal(report["total_net"]) == Decimal("-86.00")

    async def test_date_filter_excludes_other_periods(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        # Push both documents' dates back to last year.
        last_year = date.today().replace(year=date.today().year - 1)
        sale_result = await db_session.execute(
            select(SalesInvoice).where(SalesInvoice.id == ids["sale_id"])
        )
        sale_result.scalar_one().invoice_date = last_year
        purchase_result = await db_session.execute(
            select(PurchaseInvoice).where(PurchaseInvoice.id == ids["purchase_id"])
        )
        purchase_result.scalar_one().invoice_date = last_year
        await db_session.commit()

        this_year = await client.get(
            "/api/v1/accounting/reports/tax-summary",
            headers=admin,
            params={"date_from": date.today().replace(month=1, day=1).isoformat()},
        )
        assert this_year.status_code == 200
        assert this_year.json()["data"]["rows"] == []

        last_year_report = await client.get(
            "/api/v1/accounting/reports/tax-summary",
            headers=admin,
            params={
                "date_from": last_year.replace(month=1, day=1).isoformat(),
                "date_to": last_year.replace(month=12, day=31).isoformat(),
            },
        )
        assert last_year_report.status_code == 200
        assert len(last_year_report.json()["data"]["rows"]) == 1

    async def test_sales_role_cannot_view_tax_summary(
        self, client: AsyncClient
    ) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get(
            "/api/v1/accounting/reports/tax-summary", headers=sales
        )
        assert response.status_code == 403


class TestIncomeStatement:
    async def test_reflects_a_full_trade_cycle(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await full_trade_cycle(client, admin)

        response = await client.get(
            "/api/v1/accounting/reports/income-statement", headers=admin
        )
        assert response.status_code == 200
        report = response.json()["data"]
        # Revenue: 25 x 10.50 = 262.50. COGS: 25 x 8.00 = 200.00.
        assert as_decimal(report["total_revenue"]) == Decimal("262.50")
        assert as_decimal(report["total_cogs"]) == Decimal("200.00")
        assert as_decimal(report["gross_profit"]) == Decimal("62.50")
        assert as_decimal(report["total_expenses"]) == Decimal("0")
        assert as_decimal(report["net_profit"]) == Decimal("62.50")

    async def test_resellable_return_reduces_revenue_and_cogs(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        ret = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": ids["sale_id"],
                "reason": "resellable",
                "lines": [{"product_id": ids["product_id"], "quantity": "5"}],
            },
        )
        assert ret.status_code == 201, ret.text

        response = await client.get(
            "/api/v1/accounting/reports/income-statement", headers=admin
        )
        assert response.status_code == 200
        report = response.json()["data"]
        # Revenue: 262.50 - (5 x 10.50) = 210.00. COGS: 200.00 - (5 x 8.00) = 160.00.
        assert as_decimal(report["total_revenue"]) == Decimal("210.00")
        assert as_decimal(report["total_cogs"]) == Decimal("160.00")
        assert as_decimal(report["gross_profit"]) == Decimal("50.00")
        assert as_decimal(report["net_profit"]) == Decimal("50.00")

    async def test_date_filter_excludes_other_periods(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await full_trade_cycle(client, admin)

        last_year = date.today().replace(year=date.today().year - 1)
        result = await db_session.execute(select(JournalEntry))
        for entry in result.scalars().all():
            entry.entry_date = last_year
        await db_session.commit()

        this_year = await client.get(
            "/api/v1/accounting/reports/income-statement",
            headers=admin,
            params={"date_from": date.today().replace(month=1, day=1).isoformat()},
        )
        assert this_year.status_code == 200
        this_year_report = this_year.json()["data"]
        assert as_decimal(this_year_report["total_revenue"]) == Decimal("0")
        assert as_decimal(this_year_report["net_profit"]) == Decimal("0")

        last_year_report = await client.get(
            "/api/v1/accounting/reports/income-statement",
            headers=admin,
            params={
                "date_from": last_year.replace(month=1, day=1).isoformat(),
                "date_to": last_year.replace(month=12, day=31).isoformat(),
            },
        )
        assert last_year_report.status_code == 200
        assert as_decimal(last_year_report.json()["data"]["total_revenue"]) == Decimal(
            "262.50"
        )

    async def test_sales_role_cannot_view_income_statement(
        self, client: AsyncClient
    ) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get(
            "/api/v1/accounting/reports/income-statement", headers=sales
        )
        assert response.status_code == 403


class TestBalanceSheet:
    async def test_balances_after_full_trade_cycle(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        await client.post(
            "/api/v1/sales/payments",
            headers=admin,
            json={"customer_id": ids["customer_id"], "amount": "100.00", "method": "cash"},
        )

        response = await client.get(
            "/api/v1/accounting/reports/balance-sheet", headers=admin
        )
        assert response.status_code == 200
        report = response.json()["data"]
        assert report["is_balanced"] is True
        assert as_decimal(report["total_assets"]) == as_decimal(
            report["total_liabilities_and_equity"]
        )
        assert as_decimal(report["total_assets"]) > 0

    async def test_retained_earnings_matches_income_statement_net_profit(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await full_trade_cycle(client, admin)

        income = (
            await client.get(
                "/api/v1/accounting/reports/income-statement", headers=admin
            )
        ).json()["data"]
        sheet = (
            await client.get("/api/v1/accounting/reports/balance-sheet", headers=admin)
        ).json()["data"]
        assert as_decimal(sheet["retained_earnings"]) == as_decimal(
            income["net_profit"]
        )

    async def test_sales_role_cannot_view_balance_sheet(
        self, client: AsyncClient
    ) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get(
            "/api/v1/accounting/reports/balance-sheet", headers=sales
        )
        assert response.status_code == 403


class TestBankReconciliation:
    async def _bank_payment(
        self, client: AsyncClient, admin: dict[str, str], amount: str = "100.00"
    ) -> tuple[int, int]:
        """Full trade cycle + a bank-method customer payment; returns (customer_id, journal_item_id)."""
        ids = await full_trade_cycle(client, admin)
        payment = await client.post(
            "/api/v1/sales/payments",
            headers=admin,
            json={
                "customer_id": ids["customer_id"],
                "amount": amount,
                "method": "bank",
            },
        )
        assert payment.status_code == 201, payment.text
        payment_id = int(payment.json()["data"]["id"])

        entries = await entries_for(client, admin, "customer_payment", payment_id)
        bank_item = next(
            item
            for item in entries[0]["items"]
            if item["account"]["code"] == "1015"
        )
        return ids["customer_id"], bank_item["id"]

    async def test_create_line(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.post(
            "/api/v1/accounting/bank-reconciliation/lines",
            headers=admin,
            json={
                "line_date": date.today().isoformat(),
                "description": "إيداع من عميل",
                "amount": "100.00",
                "direction": "in",
            },
        )
        assert response.status_code == 201, response.text
        line = response.json()["data"]
        assert line["matched_journal_item_id"] is None
        assert as_decimal(line["amount"]) == Decimal("100.00")

    async def test_unmatched_journal_items_lists_bank_entries(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, journal_item_id = await self._bank_payment(client, admin, "100.00")

        response = await client.get(
            "/api/v1/accounting/bank-reconciliation/unmatched-entries", headers=admin
        )
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["data"]]
        assert journal_item_id in ids

    async def test_match_and_unmatch(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, journal_item_id = await self._bank_payment(client, admin, "100.00")

        line = (
            await client.post(
                "/api/v1/accounting/bank-reconciliation/lines",
                headers=admin,
                json={
                    "line_date": date.today().isoformat(),
                    "description": "إيداع من عميل",
                    "amount": "100.00",
                    "direction": "in",
                },
            )
        ).json()["data"]

        match = await client.post(
            f"/api/v1/accounting/bank-reconciliation/lines/{line['id']}/match",
            headers=admin,
            json={"journal_item_id": journal_item_id},
        )
        assert match.status_code == 200, match.text
        matched_line = match.json()["data"]
        assert matched_line["matched_journal_item_id"] == journal_item_id
        assert matched_line["matched_journal_item"]["debit"] is not None

        # No longer appears in the unmatched list.
        unmatched = (
            await client.get(
                "/api/v1/accounting/bank-reconciliation/unmatched-entries",
                headers=admin,
            )
        ).json()["data"]
        assert journal_item_id not in [item["id"] for item in unmatched]

        summary = (
            await client.get(
                "/api/v1/accounting/bank-reconciliation/summary", headers=admin
            )
        ).json()["data"]
        assert summary["matched_count"] == 1
        assert summary["unmatched_count"] == 0

        unmatch = await client.post(
            f"/api/v1/accounting/bank-reconciliation/lines/{line['id']}/unmatch",
            headers=admin,
        )
        assert unmatch.status_code == 200
        assert unmatch.json()["data"]["matched_journal_item_id"] is None

        unmatched_again = (
            await client.get(
                "/api/v1/accounting/bank-reconciliation/unmatched-entries",
                headers=admin,
            )
        ).json()["data"]
        assert journal_item_id in [item["id"] for item in unmatched_again]

    async def test_direction_mismatch_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        # The customer payment debits BANK (an inflow), so "out" is the wrong direction.
        _, journal_item_id = await self._bank_payment(client, admin, "100.00")

        line = (
            await client.post(
                "/api/v1/accounting/bank-reconciliation/lines",
                headers=admin,
                json={
                    "line_date": date.today().isoformat(),
                    "description": "سحب",
                    "amount": "100.00",
                    "direction": "out",
                },
            )
        ).json()["data"]

        match = await client.post(
            f"/api/v1/accounting/bank-reconciliation/lines/{line['id']}/match",
            headers=admin,
            json={"journal_item_id": journal_item_id},
        )
        assert match.status_code == 400
        assert "اتجاه الحركة" in match.json()["message"]

    async def test_matching_same_journal_item_twice_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, journal_item_id = await self._bank_payment(client, admin, "100.00")

        async def _new_line() -> dict:
            return (
                await client.post(
                    "/api/v1/accounting/bank-reconciliation/lines",
                    headers=admin,
                    json={
                        "line_date": date.today().isoformat(),
                        "description": "إيداع",
                        "amount": "100.00",
                        "direction": "in",
                    },
                )
            ).json()["data"]

        first_line = await _new_line()
        second_line = await _new_line()

        first_match = await client.post(
            f"/api/v1/accounting/bank-reconciliation/lines/{first_line['id']}/match",
            headers=admin,
            json={"journal_item_id": journal_item_id},
        )
        assert first_match.status_code == 200

        second_match = await client.post(
            f"/api/v1/accounting/bank-reconciliation/lines/{second_line['id']}/match",
            headers=admin,
            json={"journal_item_id": journal_item_id},
        )
        assert second_match.status_code == 400
        assert "مطابقة ببند آخر" in second_match.json()["message"]

    async def test_non_bank_account_item_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        ids = await full_trade_cycle(client, admin)

        # The receivable-side item of the sale is on account 1020, not the bank account.
        entries = await entries_for(client, admin, "sales_invoice", ids["sale_id"])
        receivable_item = next(
            item
            for entry in entries
            for item in entry["items"]
            if item["account"]["code"] == "1020"
        )

        line = (
            await client.post(
                "/api/v1/accounting/bank-reconciliation/lines",
                headers=admin,
                json={
                    "line_date": date.today().isoformat(),
                    "description": "خطأ",
                    "amount": "100.00",
                    "direction": "in",
                },
            )
        ).json()["data"]

        match = await client.post(
            f"/api/v1/accounting/bank-reconciliation/lines/{line['id']}/match",
            headers=admin,
            json={"journal_item_id": receivable_item["id"]},
        )
        assert match.status_code == 400
        assert "ليست على حساب البنك" in match.json()["message"]

    async def test_sales_role_cannot_use_bank_reconciliation(
        self, client: AsyncClient
    ) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get(
            "/api/v1/accounting/bank-reconciliation/lines", headers=sales
        )
        assert response.status_code == 403

    async def test_accountant_can_create_and_match(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, journal_item_id = await self._bank_payment(client, admin, "50.00")

        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        line = (
            await client.post(
                "/api/v1/accounting/bank-reconciliation/lines",
                headers=accountant,
                json={
                    "line_date": date.today().isoformat(),
                    "description": "إيداع",
                    "amount": "50.00",
                    "direction": "in",
                },
            )
        ).json()["data"]

        match = await client.post(
            f"/api/v1/accounting/bank-reconciliation/lines/{line['id']}/match",
            headers=accountant,
            json={"journal_item_id": journal_item_id},
        )
        assert match.status_code == 200, match.text
