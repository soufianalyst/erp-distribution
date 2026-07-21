"""Integration tests for the expenses module and unified cashier queue."""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_ACCOUNTANT_PASSWORD, login


@pytest.mark.anyio
class TestExpensesCRUD:
    async def test_create_and_list_expense(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)

        create = await client.post(
            "/api/v1/expenses/",
            headers=admin,
            json={
                "category": "utilities",
                "payee_name": "شركة الكهرباء",
                "description": "فاتورة شهر يوليو",
                "amount": "500.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "account_code": "5100",
            },
        )
        assert create.status_code == 200, create.text
        exp = create.json()["data"]
        assert exp["category"] == "utilities"
        assert Decimal(exp["paid_amount"]) == Decimal("0")

        listing = await client.get("/api/v1/expenses/", headers=admin)
        assert listing.status_code == 200
        assert len(listing.json()["data"]) >= 1

    async def test_update_expense(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)

        create = await client.post(
            "/api/v1/expenses/",
            headers=admin,
            json={
                "category": "food",
                "payee_name": "مطعم الشرق",
                "amount": "120.50",
                "expense_date": "2026-07-18",
                "payment_method": "credit",
                "account_code": "5200",
            },
        )
        exp_id = create.json()["data"]["id"]

        update = await client.put(
            f"/api/v1/expenses/{exp_id}",
            headers=admin,
            json={
                "category": "food",
                "payee_name": "مطعم الشرق الجديد",
                "amount": "150.00",
                "expense_date": "2026-07-18",
                "payment_method": "credit",
                "account_code": "5200",
            },
        )
        assert update.status_code == 200
        assert update.json()["data"]["payee_name"] == "مطعم الشرق الجديد"

    async def test_delete_expense(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)

        create = await client.post(
            "/api/v1/expenses/",
            headers=admin,
            json={
                "category": "other",
                "payee_name": "متنوعة",
                "amount": "50.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "account_code": "5900",
            },
        )
        exp_id = create.json()["data"]["id"]

        delete = await client.delete(f"/api/v1/expenses/{exp_id}", headers=admin)
        assert delete.status_code == 200

        get = await client.get(f"/api/v1/expenses/{exp_id}", headers=admin)
        assert get.status_code == 404

    async def test_invalid_account_code_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)

        resp = await client.post(
            "/api/v1/expenses/",
            headers=admin,
            json={
                "category": "water",
                "payee_name": "مياه نقية",
                "amount": "30.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "account_code": "9999",
            },
        )
        assert resp.status_code == 400

    async def test_accountant_can_create_expenses(self, client: AsyncClient) -> None:
        acct = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)

        resp = await client.post(
            "/api/v1/expenses/",
            headers=acct,
            json={
                "category": "office",
                "payee_name": "مكتبة",
                "amount": "80.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "account_code": "5800",
            },
        )
        assert resp.status_code == 200


@pytest.mark.anyio
class TestUnifiedCashier:
    async def test_pending_shows_expenses(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)

        # Create a cash expense.
        await client.post(
            "/api/v1/expenses/",
            headers=admin,
            json={
                "category": "utilities",
                "payee_name": "كهرباء",
                "amount": "200.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "account_code": "5100",
            },
        )

        pending = await client.get("/api/v1/cashier/payables", headers=admin)
        assert pending.status_code == 200
        items = pending.json()["data"]
        expense_items = [i for i in items if i["type"] == "expense"]
        assert len(expense_items) >= 1
        assert expense_items[0]["party_name"] == "كهرباء"

    async def test_cashier_can_pay_expense(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)

        create = await client.post(
            "/api/v1/expenses/",
            headers=admin,
            json={
                "category": "water",
                "payee_name": "مياه",
                "amount": "100.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "account_code": "5300",
            },
        )
        exp_id = create.json()["data"]["id"]

        pay = await client.post(
            "/api/v1/cashier/pay",
            headers=admin,
            json={
                "reference_type": "expense",
                "reference_id": exp_id,
                "amount": 60,
            },
        )
        assert pay.status_code == 200, pay.text
        result = pay.json()["data"]
        assert Decimal(result["paid_amount"]) == Decimal("60.00")
        assert Decimal(result["remaining"]) == Decimal("40.00")

        # Still pending.
        pending = await client.get("/api/v1/cashier/payables", headers=admin)
        ids = [i["id"] for i in pending.json()["data"] if i["type"] == "expense"]
        assert exp_id in ids

        # Pay the rest.
        pay2 = await client.post(
            "/api/v1/cashier/pay",
            headers=admin,
            json={
                "reference_type": "expense",
                "reference_id": exp_id,
                "amount": 40,
            },
        )
        assert pay2.status_code == 200
        assert Decimal(pay2.json()["data"]["paid_amount"]) == Decimal("100.00")

        # No longer pending.
        pending2 = await client.get("/api/v1/cashier/payables", headers=admin)
        ids2 = [i["id"] for i in pending2.json()["data"] if i["type"] == "expense"]
        assert exp_id not in ids2

    async def test_cashier_daily_summary_includes_expenses(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)

        create = await client.post(
            "/api/v1/expenses/",
            headers=admin,
            json={
                "category": "transport",
                "payee_name": "تاكسي",
                "amount": "50.00",
                "expense_date": "2026-07-18",
                "payment_method": "cash",
                "account_code": "5600",
            },
        )
        exp_id = create.json()["data"]["id"]

        await client.post(
            "/api/v1/cashier/pay",
            headers=admin,
            json={
                "reference_type": "expense",
                "reference_id": exp_id,
                "amount": 50,
            },
        )

        summary = await client.get("/api/v1/cashier/daily-summary", headers=admin)
        assert summary.status_code == 200
        data = summary.json()["data"]
        assert data["total_count"] >= 1
        assert Decimal(data["grand_total"]) >= Decimal("50.00")
        assert "expense" in data["by_type"]
