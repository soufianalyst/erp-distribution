"""Integration tests for the expenses module: categories and payable expense notes."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ACCOUNTANT_PASSWORD,
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_inventory import as_decimal
from app.tests.test_cashier import items_by_code


async def create_category(
    client: AsyncClient, headers: dict[str, str], name: str = "كهرباء"
) -> int:
    response = await client.post(
        "/api/v1/expenses/categories", headers=headers, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["id"])


async def create_expense(
    client: AsyncClient,
    headers: dict[str, str],
    category_id: int,
    amount: str = "150.00",
    payment_method: str = "cash",
    description: str = "فاتورة كهرباء شهر يوليو",
):
    return await client.post(
        "/api/v1/expenses",
        headers=headers,
        json={
            "category_id": category_id,
            "description": description,
            "amount": amount,
            "payment_method": payment_method,
        },
    )


class TestExpenseCategories:
    async def test_create_and_list_categories(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        category_id = await create_category(client, admin, "مياه شرب")

        categories = (
            await client.get("/api/v1/expenses/categories", headers=admin)
        ).json()["data"]
        assert any(c["id"] == category_id and c["name"] == "مياه شرب" for c in categories)

    async def test_duplicate_category_name_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_category(client, admin, "مصاريف عائلية")
        response = await client.post(
            "/api/v1/expenses/categories",
            headers=admin,
            json={"name": "مصاريف عائلية"},
        )
        assert response.status_code == 409

    async def test_deactivate_category_excluded_from_active_only(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        category_id = await create_category(client, admin, "طعام")

        updated = await client.patch(
            f"/api/v1/expenses/categories/{category_id}",
            headers=admin,
            json={"is_active": False},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["is_active"] is False

        active_only = (
            await client.get(
                "/api/v1/expenses/categories",
                headers=admin,
                params={"active_only": True},
            )
        ).json()["data"]
        assert all(c["id"] != category_id for c in active_only)

    async def test_storekeeper_cannot_manage_categories(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        assert (
            await client.post(
                "/api/v1/expenses/categories", headers=store, json={"name": "أخرى"}
            )
        ).status_code == 403
        # Viewing isn't granted to storekeeper either (no natural need).
        assert (
            await client.get("/api/v1/expenses/categories", headers=store)
        ).status_code == 403
        assert admin  # keep admin session alive/used for symmetry


class TestExpenses:
    async def test_create_expense_starts_unpaid_and_posts_payable_entry(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        category_id = await create_category(client, admin, "كهرباء")

        response = await create_expense(client, admin, category_id, amount="300.00")
        assert response.status_code == 201, response.text
        expense = response.json()["data"]
        assert as_decimal(expense["paid_amount"]) == Decimal("0")
        assert expense["payment_confirmed_at"] is None

        entries = (
            await client.get(
                "/api/v1/accounting/journal-entries",
                headers=admin,
                params={"reference_type": "expense", "reference_id": expense["id"]},
            )
        ).json()["data"]
        assert len(entries) == 1
        items = items_by_code(entries[0])
        assert items["5020"] == (Decimal("300.00"), Decimal("0"))
        assert items["2010"] == (Decimal("0"), Decimal("300.00"))

    async def test_expense_appears_in_cashier_pending_payables(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        category_id = await create_category(client, admin, "مياه")

        expense = (
            await create_expense(client, admin, category_id, amount="75.00")
        ).json()["data"]

        payables = (
            await client.get("/api/v1/cashier/payables", headers=admin)
        ).json()["data"]
        match = next(
            p
            for p in payables
            if p["payable_type"] == "expense" and p["id"] == expense["id"]
        )
        assert as_decimal(match["remaining"]) == Decimal("75.00")

    async def test_cannot_create_expense_on_inactive_category(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        category_id = await create_category(client, admin, "بند موقوف")
        await client.patch(
            f"/api/v1/expenses/categories/{category_id}",
            headers=admin,
            json={"is_active": False},
        )
        response = await create_expense(client, admin, category_id)
        assert response.status_code == 400

    async def test_list_expenses_filters_by_category(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cat_a = await create_category(client, admin, "بند أ")
        cat_b = await create_category(client, admin, "بند ب")
        exp_a = (await create_expense(client, admin, cat_a)).json()["data"]
        exp_b = (await create_expense(client, admin, cat_b)).json()["data"]

        only_a = (
            await client.get(
                "/api/v1/expenses", headers=admin, params={"category_id": cat_a}
            )
        ).json()["data"]
        ids = {e["id"] for e in only_a}
        assert exp_a["id"] in ids
        assert exp_b["id"] not in ids

    async def test_accountant_can_create_expenses(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        category_id = await create_category(client, admin, "صيانة")

        response = await create_expense(client, accountant, category_id)
        assert response.status_code == 201, response.text

    async def test_sales_role_cannot_create_expenses(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        category_id = await create_category(client, admin, "بند مقيد")

        response = await create_expense(client, sales, category_id)
        assert response.status_code == 403
