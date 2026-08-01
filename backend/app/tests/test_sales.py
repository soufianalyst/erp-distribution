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


class TestCommissions:
    async def test_report_nets_returns_against_the_commission_rate(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        salesman_id = await get_salesman_id(client, admin)
        rate_update = await client.patch(
            f"/api/v1/auth/users/{salesman_id}",
            headers=admin,
            json={"commission_rate": "5"},
        )
        assert rate_update.status_code == 200

        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(
            client, admin, credit_limit="1000", salesman_id=salesman_id
        )
        invoice = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "25", "credit"
        )
        assert invoice.status_code == 201, invoice.text
        invoice_id = invoice.json()["data"]["id"]

        ret = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "5"}],
            },
        )
        assert ret.status_code == 201, ret.text

        report = await client.get(
            "/api/v1/sales/reports/commissions",
            headers=admin,
            params={"salesman_id": salesman_id},
        )
        assert report.status_code == 200, report.text
        rows = report.json()["data"]["rows"]
        assert len(rows) == 1
        row = rows[0]
        # 25 x 10.50 = 262.50 sold; 5 x 10.50 = 52.50 returned; net 210.00 x 5% = 10.50.
        assert as_decimal(row["total_sales"]) == Decimal("262.50")
        assert as_decimal(row["total_returns"]) == Decimal("52.50")
        assert as_decimal(row["net_sales"]) == Decimal("210.00")
        assert as_decimal(row["commission_rate"]) == Decimal("5.00")
        assert as_decimal(row["commission_amount"]) == Decimal("10.50")

    async def test_salesman_without_invoices_excluded_from_report(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        salesman_id = await get_salesman_id(client, admin)

        report = await client.get(
            "/api/v1/sales/reports/commissions",
            headers=admin,
            params={"salesman_id": salesman_id},
        )
        assert report.status_code == 200
        assert report.json()["data"]["rows"] == []

    async def test_non_privileged_role_cannot_view_commission_report(
        self, client: AsyncClient
    ) -> None:
        headers = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get(
            "/api/v1/sales/reports/commissions", headers=headers
        )
        assert response.status_code == 403


class TestInvoiceDiscount:
    """Adjusting the collectable amount down records the shortfall as a discount."""

    async def _sell_with_collectable(
        self,
        client: AsyncClient,
        admin: dict[str, str],
        collectable: str | None,
        quantity: str = "10",
        payment_method: str = "credit",
        credit_limit: str = "5000",
    ):
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit=credit_limit)
        body = {
            "customer_id": customer_id,
            "payment_method": payment_method,
            "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
            "lines": [{"product_id": product["id"], "quantity": quantity}],
        }
        if collectable is not None:
            body["collectable_amount"] = collectable
        response = await client.post("/api/v1/sales/invoices", headers=admin, json=body)
        return response, customer_id

    async def test_rounding_down_records_the_difference_as_discount(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        # 10 x 10.50 = 105.00 + VAT 16.80 = 121.80 gross; collect 120.00.
        response, _ = await self._sell_with_collectable(client, admin, "120.00")
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]

        assert as_decimal(invoice["subtotal"]) == Decimal("105.00")
        assert as_decimal(invoice["vat_amount"]) == Decimal("16.80")
        assert as_decimal(invoice["discount_amount"]) == Decimal("1.80")
        assert as_decimal(invoice["total"]) == Decimal("120.00")

    async def test_omitting_collectable_charges_full_amount(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response, _ = await self._sell_with_collectable(client, admin, None)
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        assert as_decimal(invoice["discount_amount"]) == Decimal("0.00")
        assert as_decimal(invoice["total"]) == Decimal("121.80")

    async def test_discount_does_not_change_the_taxable_base(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response, _ = await self._sell_with_collectable(client, admin, "100.00")
        invoice = response.json()["data"]
        # VAT is still 16% of the goods value, untouched by the discount.
        assert as_decimal(invoice["vat_amount"]) == Decimal("16.80")
        assert as_decimal(invoice["subtotal"]) == Decimal("105.00")
        assert as_decimal(invoice["discount_amount"]) == Decimal("21.80")

    async def test_collectable_above_total_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response, _ = await self._sell_with_collectable(client, admin, "200.00")
        assert response.status_code == 400
        assert "أكبر من إجمالي الفاتورة" in response.json()["message"]

    async def test_negative_collectable_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response, _ = await self._sell_with_collectable(client, admin, "-5.00")
        assert response.status_code == 422

    async def test_journal_posts_discount_as_contra_revenue_and_balances(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response, _ = await self._sell_with_collectable(client, admin, "120.00")
        invoice_id = response.json()["data"]["id"]

        entries = await client.get(
            "/api/v1/accounting/journal-entries",
            headers=admin,
            params={"reference_type": "sales_invoice", "reference_id": invoice_id},
        )
        assert entries.status_code == 200, entries.text
        by_code: dict[str, tuple[Decimal, Decimal]] = {}
        for entry in entries.json()["data"]:
            for item in entry["items"]:
                code = item["account"]["code"]
                debit, credit = as_decimal(item["debit"]), as_decimal(item["credit"])
                prev = by_code.get(code, (Decimal("0"), Decimal("0")))
                by_code[code] = (prev[0] + debit, prev[1] + credit)

        # Receivable is the net collectable; the 1.80 sits in contra-revenue 4030.
        assert by_code["1020"][0] == Decimal("120.00")
        assert by_code["4030"][0] == Decimal("1.80")
        assert by_code["4010"][1] == Decimal("105.00")
        assert by_code["2020"][1] == Decimal("16.80")

        total_debit = sum(d for d, _ in by_code.values())
        total_credit = sum(c for _, c in by_code.values())
        assert total_debit == total_credit

    async def test_customer_balance_uses_the_discounted_total(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response, customer_id = await self._sell_with_collectable(client, admin, "120.00")
        assert response.status_code == 201

        statement = (
            await client.get(
                f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
            )
        ).json()["data"]
        assert as_decimal(statement["balance"]) == Decimal("120.00")

    async def test_cashier_collects_the_discounted_total(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response, _ = await self._sell_with_collectable(
            client, admin, "120.00", payment_method="cash"
        )
        invoice_id = response.json()["data"]["id"]

        collected = await client.post(
            f"/api/v1/cashier/invoices/{invoice_id}/collect",
            headers=admin,
            json={"amount": "120.00"},
        )
        assert collected.status_code == 200, collected.text
        assert collected.json()["data"]["payment_confirmed_at"] is not None

    async def test_edit_can_change_the_discount(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="5000")
        created = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
                "collectable_amount": "120.00",
            },
        )
        invoice_id = created.json()["data"]["id"]

        edited = await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
                "collectable_amount": "121.80",
            },
        )
        assert edited.status_code == 200, edited.text
        assert as_decimal(edited.json()["data"]["discount_amount"]) == Decimal("0.00")
        assert as_decimal(edited.json()["data"]["total"]) == Decimal("121.80")


async def post_quotation(
    client: AsyncClient,
    headers: dict[str, str],
    customer_id: int,
    product_id: int,
    quantity: str,
    valid_until: str | None = None,
    tax_rate_ids: list[int] | None = None,
):
    if tax_rate_ids is None:
        tax_rate_ids = [DEFAULT_TAX_RATE_ID]
    return await client.post(
        "/api/v1/sales/quotations",
        headers=headers,
        json={
            "customer_id": customer_id,
            "valid_until": valid_until,
            "tax_rate_ids": tax_rate_ids,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )


class TestQuotations:
    async def test_quotation_prices_at_customer_tier_no_stock_effect(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")

        response = await post_quotation(client, admin, customer_id, product["id"], "10")
        assert response.status_code == 201, response.text
        quote = response.json()["data"]
        # 10 x 10.50 = 105.00 + VAT 16.80 = 121.80.
        assert as_decimal(quote["subtotal"]) == Decimal("105.00")
        assert as_decimal(quote["total"]) == Decimal("121.80")
        assert quote["status"] == "draft"

        # Quoting never touches stock.
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("50")

    async def test_convert_honors_quoted_price_even_after_price_change(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")

        quote = (
            await post_quotation(client, admin, customer_id, product["id"], "10")
        ).json()["data"]
        assert as_decimal(quote["subtotal"]) == Decimal("105.00")

        # Price rises after the quote was made.
        bump = await client.patch(
            f"/api/v1/inventory/products/{product['id']}",
            headers=admin,
            json={"wholesale_price": "50.00"},
        )
        assert bump.status_code == 200

        convert = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            json={"payment_method": "credit"},
        )
        assert convert.status_code == 200, convert.text
        invoice = convert.json()["data"]
        # Still the OLD 10.50 price, not the new 50.00.
        assert as_decimal(invoice["subtotal"]) == Decimal("105.00")
        assert as_decimal(invoice["lines"][0]["unit_price"]) == Decimal("10.50")

        # Stock was deducted only on conversion, via the normal FEFO path.
        levels = (
            await client.get("/api/v1/inventory/stock/levels", headers=admin)
        ).json()["data"]
        assert as_decimal(levels[0]["total_quantity"]) == Decimal("40")

    async def test_cannot_convert_twice(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = (
            await post_quotation(client, admin, customer_id, product["id"], "5")
        ).json()["data"]

        first = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            json={"payment_method": "credit"},
        )
        assert first.status_code == 200

        second = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            json={"payment_method": "credit"},
        )
        assert second.status_code == 400
        assert "تم تحويله أو إلغاؤه" in second.json()["message"]

    async def test_cancelled_quotation_cannot_be_converted(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = (
            await post_quotation(client, admin, customer_id, product["id"], "5")
        ).json()["data"]

        cancel = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/cancel", headers=admin
        )
        assert cancel.status_code == 200
        assert cancel.json()["data"]["status"] == "cancelled"

        convert = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            json={"payment_method": "credit"},
        )
        assert convert.status_code == 400

    async def test_expired_quotation_cannot_be_converted(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, credit_limit="1000")
        quote = (
            await post_quotation(
                client, admin, customer_id, product["id"], "5", valid_until="2020-01-01"
            )
        ).json()["data"]

        convert = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            json={"payment_method": "credit"},
        )
        assert convert.status_code == 400
        assert "انتهت صلاحية" in convert.json()["message"]

    async def test_conversion_still_enforces_credit_limit(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        # Credit limit far below the quote's total.
        customer_id = await create_customer(client, admin, credit_limit="10")

        quote = (
            await post_quotation(client, admin, customer_id, product["id"], "10")
        ).json()["data"]

        convert = await client.post(
            f"/api/v1/sales/quotations/{quote['id']}/convert",
            headers=admin,
            json={"payment_method": "credit"},
        )
        assert convert.status_code == 400
        assert "الحد الائتماني" in convert.json()["message"]

    async def test_rep_cannot_quote_for_another_reps_customer(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        other_customer = await create_customer(client, admin, name="عميل مندوب آخر")

        response = await post_quotation(client, sales, other_customer, product["id"], "5")
        assert response.status_code == 403

    async def test_storekeeper_cannot_create_quotation(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin)

        response = await post_quotation(client, store, customer_id, product["id"], "5")
        assert response.status_code == 403
