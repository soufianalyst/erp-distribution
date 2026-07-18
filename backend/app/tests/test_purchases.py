"""Integration tests for the purchases module: suppliers, atomic invoices, payments."""

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


async def create_supplier(
    client: AsyncClient, headers: dict[str, str], name: str = "شركة الأغذية المتحدة"
) -> int:
    response = await client.post(
        "/api/v1/purchases/suppliers",
        headers=headers,
        json={"name": name, "phone": "0791234567"},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["id"])


async def setup_catalog(
    client: AsyncClient, headers: dict[str, str]
) -> tuple[int, dict, int]:
    """Create warehouse + product + supplier; returns (warehouse_id, product, supplier_id)."""
    warehouse_id = await create_warehouse(client, headers, "الرئيسي")
    product = await create_product(client, headers)
    supplier_id = await create_supplier(client, headers)
    return warehouse_id, product, supplier_id


class TestSuppliers:
    async def test_create_supplier(self, client: AsyncClient) -> None:
        headers = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        supplier_id = await create_supplier(client, headers)
        assert supplier_id > 0

    async def test_duplicate_supplier_rejected(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await create_supplier(client, headers)
        response = await client.post(
            "/api/v1/purchases/suppliers",
            headers=headers,
            json={"name": "شركة الأغذية المتحدة"},
        )
        assert response.status_code == 409

    async def test_sales_role_cannot_create_supplier(self, client: AsyncClient) -> None:
        headers = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.post(
            "/api/v1/purchases/suppliers", headers=headers, json={"name": "غير مصرح"}
        )
        assert response.status_code == 403


class TestPurchaseInvoices:
    async def test_cash_invoice_adds_stock_and_computes_totals(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
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
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        assert as_decimal(invoice["subtotal"]) == Decimal("800.00")
        # 800 x 16% VAT = 128.00; total = 800 + 20 shipping + 128 tax = 948.00.
        assert as_decimal(invoice["vat_amount"]) == Decimal("128.00")
        assert as_decimal(invoice["total"]) == Decimal("948.00")
        # Cash invoices await cashier disbursement now — not paid until settled there.
        assert as_decimal(invoice["paid_amount"]) == Decimal("0")
        assert invoice["payment_confirmed_at"] is None
        assert len(invoice["lines"]) == 1
        assert as_decimal(invoice["lines"][0]["unit_cost"]) == Decimal("8.00")
        assert len(invoice["taxes"]) == 1
        assert invoice["taxes"][0]["tax_rate_id"] == DEFAULT_TAX_RATE_ID
        assert as_decimal(invoice["taxes"][0]["amount"]) == Decimal("128.00")

        # Stock arrived with the batch and its cost.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert len(batches) == 1
        assert batches[0]["batch_number"] == "PB-1"
        assert as_decimal(batches[0]["quantity"]) == Decimal("100")
        assert as_decimal(batches[0]["unit_cost"]) == Decimal("8.00")

        # Cash purchase shows as owed until the cashier actually pays the
        # supplier out of the register (see test_cashier.py for that flow).
        statement = (
            await client.get(
                f"/api/v1/purchases/suppliers/{supplier_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("948.00")

    async def test_invoice_with_multiple_taxes_sums_and_keeps_breakdown(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        municipal = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة بلدية", "code": "PMUNI", "rate": "2"},
        )
        municipal_id = municipal.json()["data"]["id"]

        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                # Default VAT (16%) + municipal tax (2%) applied together.
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID, municipal_id],
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-2",
                        "expiry_date": days_from_now(120),
                        "quantity": "100",
                        "unit_cost": "8.00",
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        # 800 subtotal; VAT 16% = 128.00; municipal 2% = 16.00; total tax 144.00.
        assert as_decimal(invoice["vat_amount"]) == Decimal("144.00")
        assert as_decimal(invoice["total"]) == Decimal("944.00")
        assert len(invoice["taxes"]) == 2
        by_name = {t["name"]: as_decimal(t["amount"]) for t in invoice["taxes"]}
        assert by_name["ضريبة القيمة المضافة"] == Decimal("128.00")
        assert by_name["ضريبة بلدية"] == Decimal("16.00")

    async def test_carton_line_converts_cost_to_base_unit(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)
        carton_id = product["units"][0]["id"]

        # 5 cartons at 96.00 per carton (factor 12) => 60 base units at 8.00 each.
        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-CTN",
                        "expiry_date": days_from_now(120),
                        "quantity": "5",
                        "unit_id": carton_id,
                        "unit_cost": "96.00",
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text
        line = response.json()["data"]["lines"][0]
        assert as_decimal(line["quantity"]) == Decimal("60")
        assert as_decimal(line["unit_cost"]) == Decimal("8.00")
        assert as_decimal(line["line_total"]) == Decimal("480.00")

    async def test_credit_invoice_increases_supplier_balance(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-CR",
                        "expiry_date": days_from_now(120),
                        "quantity": "50",
                        "unit_cost": "10.00",
                    }
                ],
            },
        )
        assert response.status_code == 201
        assert as_decimal(response.json()["data"]["paid_amount"]) == Decimal("0")

        statement = (
            await client.get(
                f"/api/v1/purchases/suppliers/{supplier_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("500.00")

    async def test_invalid_line_rolls_back_whole_invoice(
        self, client: AsyncClient
    ) -> None:
        """Atomicity: a bad second line must undo the first line's stock too."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-OK",
                        "expiry_date": days_from_now(120),
                        "quantity": "10",
                        "unit_cost": "5.00",
                    },
                    {
                        # Expired goods — must fail the whole invoice.
                        "product_id": product["id"],
                        "batch_number": "PB-BAD",
                        "expiry_date": days_from_now(-5),
                        "quantity": "10",
                        "unit_cost": "5.00",
                    },
                ],
            },
        )
        assert response.status_code == 400

        # No stock at all was saved, not even the valid first line.
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert levels == []

        # And no invoice exists.
        invoices = (
            await client.get("/api/v1/purchases/invoices", headers=admin)
        ).json()["data"]
        assert invoices == []

    async def test_unknown_product_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _, supplier_id = await setup_catalog(client, admin)

        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": 9999,
                        "batch_number": "PB-X",
                        "expiry_date": days_from_now(120),
                        "quantity": "10",
                        "unit_cost": "5.00",
                    }
                ],
            },
        )
        assert response.status_code == 404

    async def test_admin_edits_invoice_and_totals_recalculate(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        created = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-EDIT",
                        "expiry_date": days_from_now(120),
                        "quantity": "100",
                        "unit_cost": "8.00",
                    }
                ],
            },
        )
        invoice_id = created.json()["data"]["id"]

        edited = await client.put(
            f"/api/v1/purchases/invoices/{invoice_id}",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-EDIT-2",
                        "expiry_date": days_from_now(120),
                        "quantity": "50",
                        "unit_cost": "10.00",
                    }
                ],
            },
        )
        assert edited.status_code == 200, edited.text
        invoice = edited.json()["data"]
        assert as_decimal(invoice["subtotal"]) == Decimal("500.00")
        assert as_decimal(invoice["vat_amount"]) == Decimal("80.00")
        assert as_decimal(invoice["total"]) == Decimal("580.00")

        # The original batch (PB-EDIT) had its 100 units fully reversed, so it no
        # longer shows up in the (quantity > 0) batches listing.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert all(b["batch_number"] != "PB-EDIT" for b in batches)
        replacement = next(b for b in batches if b["batch_number"] == "PB-EDIT-2")
        assert as_decimal(replacement["quantity"]) == Decimal("50")

    async def test_edit_blocked_when_stock_already_sold(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        # Product's home warehouse must match the purchase's receiving warehouse,
        # since sales FEFO allocation looks up stock by the product's own warehouse.
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        supplier_id = await create_supplier(client, admin)

        created = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-SOLD",
                        "expiry_date": days_from_now(120),
                        "quantity": "100",
                        "unit_cost": "8.00",
                    }
                ],
            },
        )
        invoice_id = created.json()["data"]["id"]

        customer = await client.post(
            "/api/v1/sales/customers",
            headers=admin,
            json={"name": "عميل شراء التجربة", "price_tier": "wholesale"},
        )
        customer_id = customer.json()["data"]["id"]
        sale = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "cash",
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert sale.status_code == 201, sale.text

        edited = await client.put(
            f"/api/v1/purchases/invoices/{invoice_id}",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-SOLD",
                        "expiry_date": days_from_now(120),
                        "quantity": "50",
                        "unit_cost": "8.00",
                    }
                ],
            },
        )
        assert edited.status_code == 400

        deleted = await client.delete(
            f"/api/v1/purchases/invoices/{invoice_id}", headers=admin
        )
        assert deleted.status_code == 400

    async def test_admin_deletes_invoice_reverses_stock(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        created = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-DEL",
                        "expiry_date": days_from_now(120),
                        "quantity": "100",
                        "unit_cost": "8.00",
                    }
                ],
            },
        )
        invoice_id = created.json()["data"]["id"]

        deleted = await client.delete(
            f"/api/v1/purchases/invoices/{invoice_id}", headers=admin
        )
        assert deleted.status_code == 200, deleted.text

        invoices = (
            await client.get("/api/v1/purchases/invoices", headers=admin)
        ).json()["data"]
        assert all(i["id"] != invoice_id for i in invoices)

        # Quantity was fully reversed, so the batch no longer has any stock on hand.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert all(b["batch_number"] != "PB-DEL" for b in batches)

    async def test_accountant_cannot_edit_or_delete_invoice(
        self, client: AsyncClient
    ) -> None:
        """Accountants can create purchase invoices but editing/deleting is admin-only."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        created = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-PERM",
                        "expiry_date": days_from_now(120),
                        "quantity": "10",
                        "unit_cost": "5.00",
                    }
                ],
            },
        )
        invoice_id = created.json()["data"]["id"]

        edited = await client.put(
            f"/api/v1/purchases/invoices/{invoice_id}",
            headers=accountant,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-PERM",
                        "expiry_date": days_from_now(120),
                        "quantity": "5",
                        "unit_cost": "5.00",
                    }
                ],
            },
        )
        assert edited.status_code == 403

        deleted = await client.delete(
            f"/api/v1/purchases/invoices/{invoice_id}", headers=accountant
        )
        assert deleted.status_code == 403

    async def test_sales_role_cannot_create_invoice(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)

        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=sales,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {
                        "product_id": product["id"],
                        "batch_number": "PB-1",
                        "expiry_date": days_from_now(120),
                        "quantity": "10",
                        "unit_cost": "5.00",
                    }
                ],
            },
        )
        assert response.status_code == 403


class TestSupplierPayments:
    async def _post_credit_invoice(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        warehouse_id: int,
        product_id: int,
        supplier_id: int,
    ) -> None:
        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=headers,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "lines": [
                    {
                        "product_id": product_id,
                        "batch_number": "PB-CR",
                        "expiry_date": days_from_now(120),
                        "quantity": "50",
                        "unit_cost": "10.00",
                    }
                ],
            },
        )
        assert response.status_code == 201, response.text

    async def test_payment_reduces_balance(self, client: AsyncClient) -> None:
        accountant = await login(client, "accountant", TEST_ACCOUNTANT_PASSWORD)
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)
        await self._post_credit_invoice(
            client, accountant, warehouse_id, product["id"], supplier_id
        )

        response = await client.post(
            "/api/v1/purchases/payments",
            headers=accountant,
            json={"supplier_id": supplier_id, "amount": "200.00", "method": "cash"},
        )
        assert response.status_code == 201, response.text

        statement = (
            await client.get(
                f"/api/v1/purchases/suppliers/{supplier_id}/statement",
                headers=accountant,
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("300.00")
        assert len(statement["payments"]) == 1

    async def test_overpayment_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, supplier_id = await setup_catalog(client, admin)
        await self._post_credit_invoice(
            client, admin, warehouse_id, product["id"], supplier_id
        )

        response = await client.post(
            "/api/v1/purchases/payments",
            headers=admin,
            json={"supplier_id": supplier_id, "amount": "600.00", "method": "cash"},
        )
        assert response.status_code == 400
        assert "أكبر من رصيد" in response.json()["message"]
