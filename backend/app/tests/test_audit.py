"""Integration tests for the automatic audit trail (insert/update/delete capture)."""

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_SALES_PASSWORD, login
from app.tests.test_inventory import create_warehouse


async def get_admin_id(client: AsyncClient, admin: dict[str, str]) -> int:
    users = (await client.get("/api/v1/auth/users", headers=admin)).json()["data"]
    return next(u["id"] for u in users if u["username"] == "admin")


async def logs_for(
    client: AsyncClient, headers: dict[str, str], table_name: str, record_id: int
) -> list[dict]:
    response = await client.get(
        "/api/v1/audit/logs",
        headers=headers,
        params={"table_name": table_name, "record_id": record_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class TestAuditTrail:
    async def test_insert_is_logged(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        admin_id = await get_admin_id(client, admin)
        warehouse_id = await create_warehouse(client, admin, "مستودع الاختبار")

        logs = await logs_for(client, admin, "warehouses", warehouse_id)
        assert len(logs) == 1
        entry = logs[0]
        assert entry["action"] == "insert"
        assert entry["record_id"] == warehouse_id
        assert entry["user_id"] == admin_id
        assert entry["changes"]["name"] == "مستودع الاختبار"

    async def test_update_is_logged_with_old_and_new_values(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "قبل التعديل")

        response = await client.patch(
            f"/api/v1/inventory/warehouses/{warehouse_id}",
            headers=admin,
            json={"name": "بعد التعديل"},
        )
        assert response.status_code == 200, response.text

        logs = await logs_for(client, admin, "warehouses", warehouse_id)
        update_entries = [e for e in logs if e["action"] == "update"]
        assert len(update_entries) == 1
        assert update_entries[0]["changes"]["name"] == ["قبل التعديل", "بعد التعديل"]

    async def test_no_op_update_does_not_create_an_entry(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "بلا تغيير")

        # is_active is already True; setting it to the same value is a no-op.
        response = await client.patch(
            f"/api/v1/inventory/warehouses/{warehouse_id}",
            headers=admin,
            json={"is_active": True},
        )
        assert response.status_code == 200, response.text

        logs = await logs_for(client, admin, "warehouses", warehouse_id)
        assert [e["action"] for e in logs] == ["insert"]

    async def test_delete_is_logged_with_full_snapshot(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        supplier = await client.post(
            "/api/v1/purchases/suppliers", headers=admin, json={"name": "مورد للحذف"}
        )
        supplier_id = supplier.json()["data"]["id"]

        warehouse_id = await create_warehouse(client, admin, "مستودع الحذف")
        product = await client.post(
            "/api/v1/inventory/products",
            headers=admin,
            json={
                "sku": "DEL-1",
                "name": "صنف للحذف",
                "base_unit_name": "قطعة",
                "wholesale_price": "5.00",
                "half_wholesale_price": "5.50",
                "retail_price": "6.00",
                "warehouse_id": warehouse_id,
            },
        )
        product_id = product.json()["data"]["id"]

        purchase = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "tax_rate_ids": [],
                "lines": [
                    {
                        "product_id": product_id,
                        "batch_number": "B-1",
                        "expiry_date": "2027-01-01",
                        "quantity": "10",
                        "unit_cost": "5.00",
                    }
                ],
            },
        )
        invoice_id = purchase.json()["data"]["id"]

        delete_response = await client.delete(
            f"/api/v1/purchases/invoices/{invoice_id}", headers=admin
        )
        assert delete_response.status_code == 200, delete_response.text

        logs = await logs_for(client, admin, "purchase_invoices", invoice_id)
        delete_entries = [e for e in logs if e["action"] == "delete"]
        assert len(delete_entries) == 1
        assert delete_entries[0]["changes"]["supplier_id"] == supplier_id
        assert delete_entries[0]["changes"]["total"] == "50.00"

    async def test_audit_logs_table_is_not_recursively_audited(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_warehouse(client, admin, "أي مستودع")

        response = await client.get(
            "/api/v1/audit/logs", headers=admin, params={"table_name": "audit_logs"}
        )
        assert response.status_code == 200
        assert response.json()["data"] == []

    async def test_list_tables(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_warehouse(client, admin, "مستودع القائمة")

        response = await client.get("/api/v1/audit/tables", headers=admin)
        assert response.status_code == 200
        assert "warehouses" in response.json()["data"]

    async def test_sales_role_cannot_view_audit_log(self, client: AsyncClient) -> None:
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get("/api/v1/audit/logs", headers=sales)
        assert response.status_code == 403
