"""Integration tests for the sales module: FEFO invoices, credit limits, tiers, returns."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    DEFAULT_TAX_RATE_ID,
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    receive,
)

# Product prices from create_product: wholesale 10.50, half 11.25, retail 12.00.
# VAT_RATE default is 0.16.


async def get_salesman_id(client: AsyncClient, admin: dict[str, str]) -> int:
    users = (await client.get("/api/v1/auth/users", headers=admin)).json()["data"]
    return next(u["id"] for u in users if u["username"] == "salesman")


async def create_customer(
    client: AsyncClient,
    admin: dict[str, str],
    name: str = "سوبرماركت النخبة",
    price_tier: str = "wholesale",
    credit_limit: str = "0",
    salesman_id: int | None = None,
) -> int:
    response = await client.post(
        "/api/v1/sales/customers",
        headers=admin,
        json={
            "name": name,
            "phone": "0785556677",
            "price_tier": price_tier,
            "credit_limit": credit_limit,
            "salesman_id": salesman_id,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["id"])


async def setup_stocked_catalog(
    client: AsyncClient, admin: dict[str, str]
) -> tuple[int, dict]:
    """Warehouse + product with two batches: B-SOON (20 units) expires before B-LATE (30)."""
    warehouse_id = await create_warehouse(client, admin, "الرئيسي")
    product = await create_product(client, admin, warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, "B-LATE", 180, "30")
    await receive(client, admin, product["id"], warehouse_id, "B-SOON", 30, "20")
    return warehouse_id, product


async def post_invoice(
    client: AsyncClient,
    headers: dict[str, str],
    customer_id: int,
    warehouse_id: int,
    product_id: int,
    quantity: str,
    payment_method: str = "cash",
    credit_override: bool = False,
    tax_rate_ids: list[int] | None = None,
):
    if tax_rate_ids is None:
        tax_rate_ids = [DEFAULT_TAX_RATE_ID]
    return await client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "payment_method": payment_method,
            "credit_override": credit_override,
            "tax_rate_ids": tax_rate_ids,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )


class TestSalesInvoices:
    async def test_cash_invoice_fefo_and_totals(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "25"
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]

        # FEFO: 20 from B-SOON first, then 5 from B-LATE.
        assert [line["batch_number"] for line in invoice["lines"]] == [
            "B-SOON",
            "B-LATE",
        ]
        assert as_decimal(invoice["lines"][0]["quantity"]) == Decimal("20")
        assert as_decimal(invoice["lines"][1]["quantity"]) == Decimal("5")

        # Wholesale tier: 25 x 10.50 = 262.50; VAT 16% = 42.00; total 304.50.
        assert as_decimal(invoice["subtotal"]) == Decimal("262.50")
        assert as_decimal(invoice["vat_amount"]) == Decimal("42.00")
        assert as_decimal(invoice["total"]) == Decimal("304.50")
        # Cash invoices await cashier collection now — not paid until confirmed there.
        assert as_decimal(invoice["paid_amount"]) == Decimal("0")
        assert invoice["payment_confirmed_at"] is None

        # Stock is reduced: B-SOON drained, B-LATE has 25 left.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert len(batches) == 1
        assert batches[0]["batch_number"] == "B-LATE"
        assert as_decimal(batches[0]["quantity"]) == Decimal("25")

    async def test_retail_tier_uses_retail_price(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, price_tier="retail")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10"
        )
        assert response.status_code == 201
        invoice = response.json()["data"]
        assert as_decimal(invoice["lines"][0]["unit_price"]) == Decimal("12.00")
        assert as_decimal(invoice["subtotal"]) == Decimal("120.00")

    async def test_carton_quantity_converts(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)
        carton_id = product["units"][0]["id"]

        response = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "warehouse_id": warehouse_id,
                "payment_method": "cash",
                "lines": [
                    {"product_id": product["id"], "quantity": "2", "unit_id": carton_id}
                ],
            },
        )
        assert response.status_code == 201, response.text
        total_qty = sum(
            as_decimal(line["quantity"]) for line in response.json()["data"]["lines"]
        )
        assert total_qty == Decimal("24")

    async def test_insufficient_stock_saves_nothing(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        # Only 50 in stock.
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "60"
        )
        assert response.status_code == 400
        assert "غير كافية" in response.json()["message"]

        # Stock untouched and no invoice recorded.
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("50")
        invoices = (await client.get("/api/v1/sales/invoices", headers=admin)).json()[
            "data"
        ]
        assert invoices == []


class TestCreditLimit:
    async def test_credit_invoice_within_limit(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="500")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
        )
        assert response.status_code == 201
        assert as_decimal(response.json()["data"]["paid_amount"]) == Decimal("0")

        statement = (
            await client.get(
                f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("304.50")

    async def test_credit_limit_exceeded_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        # Limit 100 < invoice total 304.50.
        customer_id = await create_customer(client, admin, credit_limit="100")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
        )
        assert response.status_code == 400
        assert "الحد الائتماني" in response.json()["message"]

        # Stock untouched thanks to the single transaction.
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("50")

    async def test_admin_override_allows_exceeding_limit(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="100")

        response = await post_invoice(
            client,
            admin,
            customer_id,
            warehouse_id,
            product["id"],
            "25",
            "credit",
            credit_override=True,
        )
        assert response.status_code == 201

    async def test_sales_rep_cannot_override_limit(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        salesman_id = await get_salesman_id(client, admin)
        customer_id = await create_customer(
            client, admin, credit_limit="100", salesman_id=salesman_id
        )

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
        assert response.status_code == 400


class TestSalesRepRestrictions:
    async def test_rep_sells_to_own_customer_only(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        salesman_id = await get_salesman_id(client, admin)

        own_customer = await create_customer(
            client, admin, name="عميل المندوب", salesman_id=salesman_id
        )
        other_customer = await create_customer(client, admin, name="عميل مندوب آخر")

        allowed = await post_invoice(
            client, sales, own_customer, warehouse_id, product["id"], "5"
        )
        assert allowed.status_code == 201

        denied = await post_invoice(
            client, sales, other_customer, warehouse_id, product["id"], "5"
        )
        assert denied.status_code == 403

    async def test_rep_sees_only_own_customers(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        salesman_id = await get_salesman_id(client, admin)
        await create_customer(
            client, admin, name="عميل المندوب", salesman_id=salesman_id
        )
        await create_customer(client, admin, name="عميل آخر")

        mine = (await client.get("/api/v1/sales/customers", headers=sales)).json()[
            "data"
        ]
        assert [c["name"] for c in mine] == ["عميل المندوب"]

        everyone = (await client.get("/api/v1/sales/customers", headers=admin)).json()[
            "data"
        ]
        assert len(everyone) == 2

    async def test_storekeeper_cannot_create_invoice(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        response = await post_invoice(
            client, store, customer_id, warehouse_id, product["id"], "5"
        )
        assert response.status_code == 403


class TestReturns:
    async def _sell(
        self, client: AsyncClient, admin: dict[str, str], quantity: str = "25"
    ) -> tuple[int, dict, int]:
        """Stock, sell `quantity` on credit (limit 1000); returns (invoice_id, product, customer_id)."""
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], quantity, "credit"
        )
        assert response.status_code == 201, response.text
        return int(response.json()["data"]["id"]), product, customer_id

    async def test_resellable_return_restocks_original_batches(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice_id, product, customer_id = await self._sell(client, admin)

        # Sold 25 (B-SOON 20 + B-LATE 5); return 22 resellable.
        response = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "22"}],
            },
        )
        assert response.status_code == 201, response.text
        ret = response.json()["data"]
        # 22 x 10.50 = 231.00 + VAT 36.96 = 267.96.
        assert as_decimal(ret["subtotal"]) == Decimal("231.00")
        assert as_decimal(ret["total"]) == Decimal("267.96")

        # B-SOON gets its 20 back, B-LATE gets 2 back (25 + 2 = 27).
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        by_number = {b["batch_number"]: as_decimal(b["quantity"]) for b in batches}
        assert by_number == {"B-SOON": Decimal("20"), "B-LATE": Decimal("27")}

        # Balance drops: 304.50 - 267.96 = 36.54.
        statement = (
            await client.get(
                f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("36.54")

    async def test_damaged_return_credits_without_restocking(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice_id, product, customer_id = await self._sell(client, admin)

        response = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "damaged_transport",
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert response.status_code == 201

        # Stock unchanged: 50 - 25 sold = 25 (nothing restocked).
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("25")

        # But the customer is still credited: 10 x 10.50 x 1.16 = 121.80.
        statement = (
            await client.get(
                f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["total_returns"]) == Decimal("121.80")

    async def test_return_exceeding_sold_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice_id, product, _ = await self._sell(client, admin)

        # Sold 25; return 20 then attempt 6 more.
        first = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "20"}],
            },
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "6"}],
            },
        )
        assert second.status_code == 400
        assert "أكبر من الكمية المباعة" in second.json()["message"]


class TestCustomerPayments:
    async def test_payment_reduces_balance_and_overpayment_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
        )
        assert response.status_code == 201

        # Collect 200 of the 304.50 owed.
        payment = await client.post(
            "/api/v1/sales/payments",
            headers=admin,
            json={"customer_id": customer_id, "amount": "200.00", "method": "cash"},
        )
        assert payment.status_code == 201

        statement = (
            await client.get(
                f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("104.50")

        # Overpayment beyond the remaining balance is rejected.
        overpay = await client.post(
            "/api/v1/sales/payments",
            headers=admin,
            json={"customer_id": customer_id, "amount": "150.00", "method": "cash"},
        )
        assert overpay.status_code == 400
