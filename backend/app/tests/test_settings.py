"""Integration tests for the settings module: configurable tax rates and company info."""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    DEFAULT_TAX_RATE_ID,
    TEST_ADMIN_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    receive,
)
from app.tests.test_sales import create_customer, post_invoice


class TestTaxRatePermissions:
    async def test_storekeeper_can_view_but_not_manage(
        self, client: AsyncClient
    ) -> None:
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        assert (
            await client.get("/api/v1/settings/tax-rates", headers=store)
        ).status_code == 200
        assert (
            await client.post(
                "/api/v1/settings/tax-rates",
                headers=store,
                json={"name": "ضريبة تجريبية", "code": "TEST1", "rate": "5"},
            )
        ).status_code == 403


class TestTaxRateCrud:
    async def test_seeded_default_vat_rate(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        rates = (await client.get("/api/v1/settings/tax-rates", headers=admin)).json()[
            "data"
        ]
        vat = next(r for r in rates if r["code"] == "VAT")
        assert vat["id"] == DEFAULT_TAX_RATE_ID
        assert as_decimal(vat["rate"]) == Decimal("16.000")
        assert vat["is_default"] is True
        assert vat["is_active"] is True

    async def test_create_new_tax_type(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={
                "name": "ضريبة السلع والخدمات",
                "code": "GST",
                "rate": "10",
                "country": "الهند",
            },
        )
        assert response.status_code == 201, response.text
        gst = response.json()["data"]
        assert as_decimal(gst["rate"]) == Decimal("10")
        assert gst["is_active"] is True
        assert gst["is_default"] is False

    async def test_duplicate_code_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة مكررة", "code": "VAT", "rate": "16"},
        )
        assert response.status_code == 409

    async def test_setting_new_default_clears_old_one(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        created = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={
                "name": "ضريبة مبيعات",
                "code": "ST",
                "rate": "8",
                "is_default": True,
            },
        )
        new_id = created.json()["data"]["id"]

        rates = (await client.get("/api/v1/settings/tax-rates", headers=admin)).json()[
            "data"
        ]
        defaults = [r for r in rates if r["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["id"] == new_id

    async def test_deactivate_tax_rate(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.patch(
            f"/api/v1/settings/tax-rates/{DEFAULT_TAX_RATE_ID}",
            headers=admin,
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        active_only = (
            await client.get(
                "/api/v1/settings/tax-rates",
                headers=admin,
                params={"active_only": True},
            )
        ).json()["data"]
        assert all(r["code"] != "VAT" for r in active_only)


class TestCompanySettings:
    async def test_default_company_settings_exist(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/settings/company", headers=admin)
        assert response.status_code == 200
        assert response.json()["data"]["name"]

    async def test_update_company_settings(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.put(
            "/api/v1/settings/company",
            headers=admin,
            json={
                "name": "مؤسسة الأمل التجارية",
                "phone": "0112223344",
                "currency_code": "EGP",
                "currency_symbol": "ج.م",
            },
        )
        assert response.status_code == 200, response.text
        company = response.json()["data"]
        assert company["name"] == "مؤسسة الأمل التجارية"
        assert company["currency_code"] == "EGP"

        # Persisted: a fresh GET reflects the update.
        again = (await client.get("/api/v1/settings/company", headers=admin)).json()[
            "data"
        ]
        assert again["name"] == "مؤسسة الأمل التجارية"

    async def test_storekeeper_cannot_update_company(self, client: AsyncClient) -> None:
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        response = await client.put(
            "/api/v1/settings/company",
            headers=store,
            json={"name": "محاولة غير مصرح بها"},
        )
        assert response.status_code == 403


class TestInvoiceWithConfigurableTax:
    async def test_invoice_uses_selected_tax_rate(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        gst = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة GST", "code": "GST2", "rate": "10"},
        )
        gst_id = gst.json()["data"]["id"]

        response = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "credit",
                "tax_rate_ids": [gst_id],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        # 10 x 10.50 = 105.00; GST 10% = 10.50; total 115.50.
        assert as_decimal(invoice["subtotal"]) == Decimal("105.00")
        assert as_decimal(invoice["vat_amount"]) == Decimal("10.50")
        assert as_decimal(invoice["total"]) == Decimal("115.50")
        assert len(invoice["taxes"]) == 1
        assert invoice["taxes"][0]["tax_rate_id"] == gst_id
        assert invoice["taxes"][0]["name"] == "ضريبة GST"
        assert as_decimal(invoice["taxes"][0]["amount"]) == Decimal("10.50")

    async def test_invoice_with_multiple_taxes_sums_and_keeps_breakdown(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        municipal = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة بلدية", "code": "MUNI", "rate": "2"},
        )
        municipal_id = municipal.json()["data"]["id"]

        response = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "credit",
                # Default VAT (16%) + municipal tax (2%) applied together.
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID, municipal_id],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert response.status_code == 201, response.text
        invoice = response.json()["data"]
        # 10 x 10.50 = 105.00; VAT 16% = 16.80; municipal 2% = 2.10; total tax 18.90.
        assert as_decimal(invoice["subtotal"]) == Decimal("105.00")
        assert as_decimal(invoice["vat_amount"]) == Decimal("18.90")
        assert as_decimal(invoice["total"]) == Decimal("123.90")
        assert len(invoice["taxes"]) == 2
        by_code = {t["name"]: as_decimal(t["amount"]) for t in invoice["taxes"]}
        assert by_code["ضريبة القيمة المضافة"] == Decimal("16.80")
        assert by_code["ضريبة بلدية"] == Decimal("2.10")

    async def test_invalid_tax_rate_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin)

        response = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "cash",
                "tax_rate_ids": [99999],
                "lines": [{"product_id": product["id"], "quantity": "5"}],
            },
        )
        assert response.status_code == 400

    async def test_return_uses_original_invoice_tax_rate_not_current_config(
        self, client: AsyncClient
    ) -> None:
        """A return must reflect whatever tax the ORIGINAL invoice used, even if
        tax rates change afterward (correctness fix over the old hardcoded-rate bug).
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        # Invoice at the default 16% VAT.
        invoice_resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "20", "credit"
        )
        invoice = invoice_resp.json()["data"]

        # Now change the default tax rate's percentage — should NOT affect the
        # already-posted invoice's return calculation.
        await client.patch(
            f"/api/v1/settings/tax-rates/{DEFAULT_TAX_RATE_ID}",
            headers=admin,
            json={"rate": "25"},
        )

        ret = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice["id"],
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert ret.status_code == 201, ret.text
        # 10 x 10.50 = 105.00; must use the ORIGINAL 16%, not the new 25%.
        assert as_decimal(ret.json()["data"]["subtotal"]) == Decimal("105.00")
        assert as_decimal(ret.json()["data"]["vat_amount"]) == Decimal("16.80")


class TestTaxRateDeletion:
    async def test_storekeeper_cannot_delete_tax_rate(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        created = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة للحذف", "code": "DEL1", "rate": "5"},
        )
        tax_id = created.json()["data"]["id"]

        response = await client.delete(
            f"/api/v1/settings/tax-rates/{tax_id}", headers=store
        )
        assert response.status_code == 403

    async def test_admin_deletes_unused_tax_rate(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        created = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة للحذف", "code": "DEL2", "rate": "5"},
        )
        tax_id = created.json()["data"]["id"]

        response = await client.delete(
            f"/api/v1/settings/tax-rates/{tax_id}", headers=admin
        )
        assert response.status_code == 200

        rates = (await client.get("/api/v1/settings/tax-rates", headers=admin)).json()[
            "data"
        ]
        assert all(r["id"] != tax_id for r in rates)

    async def test_deleting_tax_rate_preserves_past_invoice_breakdown(
        self, client: AsyncClient
    ) -> None:
        """Deleting a TaxRate must not corrupt invoices that already applied it —
        the invoice keeps its own snapshot of the name/rate/amount charged.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        gst = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة مؤقتة", "code": "TEMP1", "rate": "10"},
        )
        gst_id = gst.json()["data"]["id"]

        invoice_resp = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "credit",
                "tax_rate_ids": [gst_id],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        invoice_id = invoice_resp.json()["data"]["id"]

        delete_resp = await client.delete(
            f"/api/v1/settings/tax-rates/{gst_id}", headers=admin
        )
        assert delete_resp.status_code == 200

        again = await client.get(
            f"/api/v1/sales/invoices/{invoice_id}", headers=admin
        )
        invoice = again.json()["data"]
        assert as_decimal(invoice["vat_amount"]) == Decimal("10.50")
        assert len(invoice["taxes"]) == 1
        assert invoice["taxes"][0]["tax_rate_id"] is None
        assert invoice["taxes"][0]["name"] == "ضريبة مؤقتة"
        assert as_decimal(invoice["taxes"][0]["amount"]) == Decimal("10.50")
