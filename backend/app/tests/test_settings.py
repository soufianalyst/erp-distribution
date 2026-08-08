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
                "country_code": "IN",
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


class TestCountryReference:
    async def test_countries_list_is_available_for_pickers(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/settings/countries", headers=admin)
        assert response.status_code == 200, response.text
        countries = response.json()["data"]
        assert len(countries) > 10
        by_code = {c["code"]: c for c in countries}
        # Each entry carries the currency so choosing a country can suggest it.
        assert by_code["SA"]["name"] == "المملكة العربية السعودية"
        assert by_code["SA"]["currency_code"] == "SAR"
        assert by_code["JO"]["currency_symbol"] == "د.أ"

    async def test_unknown_country_code_is_rejected(self, client: AsyncClient) -> None:
        """Free text would drift away from the picker; codes must be known."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة وهمية", "code": "FAKE", "rate": "5", "country_code": "ZZ"},
        )
        assert response.status_code == 400
        assert "رمز الدولة" in response.json()["message"]

    async def test_country_code_is_normalised_to_uppercase(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة أردنية", "code": "JO_GST", "rate": "16", "country_code": "jo"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["country_code"] == "JO"
        assert response.json()["data"]["country_name"] == "الأردن"

    async def test_company_country_is_validated_too(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        bad = await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "XX"}
        )
        assert bad.status_code == 400

        good = await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "AE"}
        )
        assert good.status_code == 200, good.text
        assert good.json()["data"]["country_code"] == "AE"
        assert good.json()["data"]["country_name"] == "الإمارات العربية المتحدة"


class TestTaxRateCountryScoping:
    async def _tax_codes(
        self, client: AsyncClient, admin: dict[str, str], **params
    ) -> list[str]:
        response = await client.get(
            "/api/v1/settings/tax-rates", headers=admin, params=params
        )
        assert response.status_code == 200, response.text
        return [t["code"] for t in response.json()["data"]]

    async def _add_tax(
        self,
        client: AsyncClient,
        admin: dict[str, str],
        code: str,
        country_code: str | None,
    ) -> None:
        response = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={
                "name": f"ضريبة {code}",
                "code": code,
                "rate": "10",
                "country_code": country_code,
            },
        )
        assert response.status_code == 201, response.text

    async def test_in_scope_keeps_universal_and_matching_only(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "JO"}
        )
        await self._add_tax(client, admin, "UNIVERSAL", None)
        await self._add_tax(client, admin, "JO_LOCAL", "JO")
        await self._add_tax(client, admin, "SA_LOCAL", "SA")

        # The control panel shows everything so foreign taxes stay manageable.
        all_codes = await self._tax_codes(client, admin)
        assert {"UNIVERSAL", "JO_LOCAL", "SA_LOCAL"} <= set(all_codes)

        # Invoicing only offers what applies where the company operates.
        scoped = await self._tax_codes(client, admin, in_scope_only=True)
        assert "UNIVERSAL" in scoped
        assert "JO_LOCAL" in scoped
        assert "SA_LOCAL" not in scoped

    async def test_changing_company_country_changes_what_applies(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await self._add_tax(client, admin, "JO_LOCAL", "JO")
        await self._add_tax(client, admin, "SA_LOCAL", "SA")

        await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "JO"}
        )
        assert "JO_LOCAL" in await self._tax_codes(client, admin, in_scope_only=True)
        assert "SA_LOCAL" not in await self._tax_codes(client, admin, in_scope_only=True)

        # Expanding into another market flips which local tax is offered.
        await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "SA"}
        )
        assert "SA_LOCAL" in await self._tax_codes(client, admin, in_scope_only=True)
        assert "JO_LOCAL" not in await self._tax_codes(client, admin, in_scope_only=True)

    async def test_without_a_company_country_only_universal_taxes_apply(
        self, client: AsyncClient
    ) -> None:
        """Before the country is set, a country-specific tax is ambiguous."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await self._add_tax(client, admin, "JO_LOCAL", "JO")

        scoped = await self._tax_codes(client, admin, in_scope_only=True)
        assert "JO_LOCAL" not in scoped
        # The seeded default tax has no country, so it still applies.
        assert scoped

    async def test_scoping_combines_with_active_only(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "JO"}
        )
        await self._add_tax(client, admin, "JO_OFF", "JO")
        created = await client.get("/api/v1/settings/tax-rates", headers=admin)
        jo_off = next(t for t in created.json()["data"] if t["code"] == "JO_OFF")
        await client.patch(
            f"/api/v1/settings/tax-rates/{jo_off['id']}",
            headers=admin,
            json={"is_active": False},
        )

        scoped = await self._tax_codes(
            client, admin, in_scope_only=True, active_only=True
        )
        assert "JO_OFF" not in scoped

    async def test_a_foreign_tax_can_still_be_applied_deliberately(
        self, client: AsyncClient
    ) -> None:
        """Scoping decides what the forms *offer*, not what the API accepts — an
        export invoice may legitimately carry another country's tax."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "JO"}
        )
        foreign = await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة سعودية", "code": "SA_VAT", "rate": "15", "country_code": "SA"},
        )
        foreign_id = foreign.json()["data"]["id"]

        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "EXPORT-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "EX-1", 200, "100")
        customer_id = await create_customer(client, admin, "مشتري خارجي")

        response = await post_invoice(
            client,
            admin,
            customer_id,
            warehouse_id,
            product["id"],
            "10",
            tax_rate_ids=[foreign_id],
        )
        assert response.status_code == 201, response.text
        taxes = response.json()["data"]["taxes"]
        assert [t["name"] for t in taxes] == ["ضريبة سعودية"]


class TestClearingOptionalCompanyFields:
    """An optional field must be clearable, not set-once.

    Every field here used to apply only when non-null, which silently made
    "— لم تُحدد —" and an emptied address do nothing at all.
    """

    async def test_explicit_null_clears_but_omitting_preserves(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        filled = await client.put(
            "/api/v1/settings/company",
            headers=admin,
            json={
                "country_code": "SA",
                "address": "شارع الملك فهد",
                "phone": "0500000000",
            },
        )
        assert filled.status_code == 200, filled.text

        # Omitting a field leaves it alone.
        untouched = await client.put(
            "/api/v1/settings/company", headers=admin, json={"tax_number": "3001"}
        )
        data = untouched.json()["data"]
        assert data["country_code"] == "SA"
        assert data["address"] == "شارع الملك فهد"

        # Sending null clears it.
        cleared = await client.put(
            "/api/v1/settings/company",
            headers=admin,
            json={"country_code": None, "address": None, "phone": None},
        )
        data = cleared.json()["data"]
        assert data["country_code"] is None
        assert data["country_name"] is None
        assert data["address"] is None
        assert data["phone"] is None
        # The one that was not mentioned this time survives.
        assert data["tax_number"] == "3001"

    async def test_required_fields_ignore_null(self, client: AsyncClient) -> None:
        """Name and currency have no valid empty value to fall back to."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        before = (await client.get("/api/v1/settings/company", headers=admin)).json()["data"]

        response = await client.put(
            "/api/v1/settings/company",
            headers=admin,
            json={"name": None, "currency_code": None, "currency_symbol": None},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["name"] == before["name"]
        assert data["currency_code"] == before["currency_code"]
        assert data["currency_symbol"] == before["currency_symbol"]

    async def test_clearing_the_country_widens_tax_scope_again(
        self, client: AsyncClient
    ) -> None:
        """With no country set, only universal taxes are unambiguous."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await client.post(
            "/api/v1/settings/tax-rates",
            headers=admin,
            json={"name": "ضريبة سعودية", "code": "SA_ONLY", "rate": "15", "country_code": "SA"},
        )
        await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": "SA"}
        )
        scoped = await client.get(
            "/api/v1/settings/tax-rates", headers=admin, params={"in_scope_only": True}
        )
        assert "SA_ONLY" in [t["code"] for t in scoped.json()["data"]]

        await client.put(
            "/api/v1/settings/company", headers=admin, json={"country_code": None}
        )
        scoped = await client.get(
            "/api/v1/settings/tax-rates", headers=admin, params={"in_scope_only": True}
        )
        assert "SA_ONLY" not in [t["code"] for t in scoped.json()["data"]]
