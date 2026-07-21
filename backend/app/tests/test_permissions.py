"""Integration tests for granular, per-user permission overrides."""

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_sales import create_customer, post_invoice, setup_stocked_catalog


async def user_id_of(client: AsyncClient, admin: dict[str, str], username: str) -> int:
    users = (await client.get("/api/v1/auth/users", headers=admin)).json()["data"]
    return next(u["id"] for u in users if u["username"] == username)


async def set_permissions(
    client: AsyncClient, admin: dict[str, str], username: str, permissions: list[str]
) -> dict:
    uid = await user_id_of(client, admin, username)
    response = await client.patch(
        f"/api/v1/auth/users/{uid}", headers=admin, json={"permissions": permissions}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class TestPermissionCatalog:
    async def test_admin_gets_grouped_catalog(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/auth/permissions", headers=admin)
        assert response.status_code == 200
        groups = response.json()["data"]
        codes = {p["code"] for g in groups for p in g["permissions"]}
        assert {
            "sales.create",
            "stock.receive",
            "users.manage",
            "sales.credit_override",
        } <= codes

    async def test_non_manager_cannot_view_catalog(self, client: AsyncClient) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get("/api/v1/auth/permissions", headers=sales)
        assert response.status_code == 403


class TestPermissionOverrides:
    async def test_login_returns_effective_permissions(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "storekeeper", "password": TEST_STORE_PASSWORD},
        )
        perms = response.json()["data"]["user"]["effective_permissions"]
        assert "stock.receive" in perms
        assert "sales.create" not in perms
        # No overrides yet: explicit permissions are null.
        assert response.json()["data"]["user"]["permissions"] is None

    async def test_granting_storekeeper_selling_rights(
        self, client: AsyncClient
    ) -> None:
        """Full control: a storekeeper granted sales permissions can invoice."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        # Before the grant: 403.
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        denied = await post_invoice(
            client, store, customer_id, warehouse_id, product["id"], "5"
        )
        assert denied.status_code == 403

        updated = await set_permissions(
            client,
            admin,
            "storekeeper",
            [
                "products.view",
                "warehouses.view",
                "stock.view",
                "customers.view",
                "sales.view",
                "sales.create",
                "sales.all_customers",
            ],
        )
        assert "sales.create" in updated["effective_permissions"]

        allowed = await post_invoice(
            client, store, customer_id, warehouse_id, product["id"], "5"
        )
        assert allowed.status_code == 201, allowed.text

    async def test_revoking_sales_rights_from_salesman(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        salesman_id = await user_id_of(client, admin, "salesman")
        customer_id = await create_customer(client, admin, salesman_id=salesman_id)

        # Strip the rep down to viewing only.
        await set_permissions(
            client, admin, "salesman", ["customers.view", "sales.view"]
        )

        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        denied = await post_invoice(
            client, sales, customer_id, warehouse_id, product["id"], "5"
        )
        assert denied.status_code == 403

    async def test_granting_credit_override_to_salesman(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        salesman_id = await user_id_of(client, admin, "salesman")
        # Limit 100 < invoice total 304.50.
        customer_id = await create_customer(
            client, admin, credit_limit="100", salesman_id=salesman_id
        )

        await set_permissions(
            client,
            admin,
            "salesman",
            [
                "products.view",
                "warehouses.view",
                "stock.view",
                "customers.view",
                "sales.view",
                "sales.create",
                "sales.credit_override",
            ],
        )
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await post_invoice(
            client,
            sales,
            customer_id,
            warehouse_id,
            product["id"],
            "25",
            "credit",
            credit_override=True,
        )
        assert response.status_code == 201, response.text

    async def test_all_customers_permission_widens_rep_scope(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        salesman_id = await user_id_of(client, admin, "salesman")
        await create_customer(
            client, admin, name="عميل المندوب", salesman_id=salesman_id
        )
        await create_customer(client, admin, name="عميل آخر")

        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        mine = (await client.get("/api/v1/sales/customers", headers=sales)).json()[
            "data"
        ]
        assert len(mine) == 1

        await set_permissions(
            client,
            admin,
            "salesman",
            ["customers.view", "sales.view", "sales.all_customers"],
        )
        everyone = (await client.get("/api/v1/sales/customers", headers=sales)).json()[
            "data"
        ]
        assert len(everyone) == 2

    async def test_reset_restores_role_defaults(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await set_permissions(client, admin, "salesman", ["customers.view"])

        uid = await user_id_of(client, admin, "salesman")
        response = await client.patch(
            f"/api/v1/auth/users/{uid}", headers=admin, json={"reset_permissions": True}
        )
        assert response.status_code == 200
        user = response.json()["data"]
        assert user["permissions"] is None
        assert "sales.create" in user["effective_permissions"]

    async def test_unknown_permission_code_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        uid = await user_id_of(client, admin, "salesman")
        response = await client.patch(
            f"/api/v1/auth/users/{uid}",
            headers=admin,
            json={"permissions": ["hack.everything"]},
        )
        assert response.status_code == 400

    async def test_admin_overrides_are_ignored(self, client: AsyncClient) -> None:
        """Admins always keep full access so the system can't be locked out."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        updated = await set_permissions(client, admin, "admin", [])
        assert "users.manage" in updated["effective_permissions"]

        # Still fully operational.
        response = await client.get("/api/v1/auth/users", headers=admin)
        assert response.status_code == 200
