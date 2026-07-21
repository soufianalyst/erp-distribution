"""Integration tests for the sales quotations module: CRUD, status transitions, convert-to-invoice."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_SALES_PASSWORD, TEST_STORE_PASSWORD, login
from app.tests.test_inventory import as_decimal, create_product, create_warehouse, receive
from app.tests.test_sales import (
    create_customer,
    get_salesman_id,
    setup_stocked_catalog,
)


async def create_quotation(
    client: AsyncClient,
    headers: dict[str, str],
    customer_id: int,
    warehouse_id: int,
    product_id: int,
    quantity: str = "10",
    unit_price: str = "10.50",
    product_name: str = "أرز بسمتي 1 كجم",
    tax_type_ids: list[int] | None = None,
) -> dict:
    response = await client.post(
        "/api/v1/sales/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "tax_type_ids": tax_type_ids if tax_type_ids is not None else [1],
            "lines": [
                {
                    "product_id": product_id,
                    "product_name": product_name,
                    "quantity": quantity,
                    "unit_price": unit_price,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestQuotationCRUD:
    async def test_create_quotation(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")

        data = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])
        assert data["status"] == "draft"
        assert data["customer_id"] == customer_id
        assert data["warehouse_id"] == warehouse_id
        assert len(data["lines"]) == 1
        assert as_decimal(data["subtotal"]) == Decimal("105.00")
        assert as_decimal(data["total"]) > Decimal("105.00")  # VAT included

    async def test_get_quotation(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        response = await client.get(f"/api/v1/sales/quotations/{quote['id']}", headers=admin)
        assert response.status_code == 200
        assert response.json()["data"]["id"] == quote["id"]

    async def test_list_quotations(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        response = await client.get("/api/v1/sales/quotations", headers=admin)
        assert response.status_code == 200
        assert len(response.json()["data"]) >= 1

    async def test_delete_draft_quotation(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        response = await client.delete(f"/api/v1/sales/quotations/{quote['id']}", headers=admin)
        assert response.status_code == 200

        get_response = await client.get(f"/api/v1/sales/quotations/{quote['id']}", headers=admin)
        assert get_response.status_code == 404

    async def test_delete_non_draft_quotation_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        # Move to sent status
        await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "sent"},
        )

        response = await client.delete(f"/api/v1/sales/quotations/{quote['id']}", headers=admin)
        assert response.status_code == 400


class TestQuotationStatusTransitions:
    async def test_draft_to_sent(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        response = await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "sent"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "sent"

    async def test_sent_to_accepted(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        # draft -> sent
        await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "sent"},
        )
        # sent -> accepted
        response = await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "accepted"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "accepted"

    async def test_sent_to_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "sent"},
        )
        response = await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "rejected"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "rejected"

    async def test_invalid_transition_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        # draft -> accepted (invalid)
        response = await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "accepted"},
        )
        assert response.status_code == 400


class TestQuotationConvert:
    async def test_convert_accepted_creates_invoice(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        # draft -> sent -> accepted
        await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "sent"},
        )
        await client.patch(
            f"/api/v1/sales/quotations/{quote['id']}/status",
            headers=admin,
            params={"status": "accepted"},
        )

        # Convert to cash invoice
        response = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            params={"payment_method": "cash"},
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        assert invoice["customer_id"] == customer_id
        assert as_decimal(invoice["total"]) > Decimal("0")

        # Verify quotation is now converted
        get_quote = await client.get(f"/api/v1/sales/quotations/{quote['id']}", headers=admin)
        assert get_quote.json()["data"]["status"] == "converted"
        assert get_quote.json()["data"]["converted_invoice_id"] == invoice["id"]

    async def test_convert_non_accepted_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = await create_quotation(client, admin, customer_id, warehouse_id, product["id"])

        response = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            params={"payment_method": "cash"},
        )
        assert response.status_code == 400


class TestQuotationPermissions:
    async def test_storekeeper_cannot_create_quotation(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "المستودع")
        product = await create_product(client, admin, sku="Q-001")
        await receive(client, admin, product["id"], warehouse_id, "B-1", 90, "10")
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)

        response = await client.post(
            "/api/v1/sales/quotations",
            headers=store,
            json={
                "customer_id": 1,
                "warehouse_id": warehouse_id,
                "lines": [
                    {
                        "product_id": product["id"],
                        "product_name": "صنف تجريبي",
                        "quantity": "5",
                        "unit_price": "10.00",
                    }
                ],
            },
        )
        assert response.status_code == 403

    async def test_sales_rep_can_create_quotation(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        salesman_id = await get_salesman_id(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000", salesman_id=salesman_id)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)

        response = await client.post(
            "/api/v1/sales/quotations",
            headers=sales,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "lines": [
                    {
                        "product_id": product["id"],
                        "product_name": product["name"],
                        "quantity": "5",
                        "unit_price": "10.50",
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
