"""What a customer reads about their own account.

Two things can go wrong on a read surface, and both are here. One customer reaching
another's invoice — checked by actually issuing invoices to two shops and having each
ask for the other's. And the statement disagreeing with the office's copy of itself,
which is checked by comparing the two documents number for number rather than by
asserting figures this test invented.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_portal_identity import PORTAL_PASSWORD, open_portal_account
from app.tests.test_sales import post_invoice, setup_stocked_catalog


async def ready_portal_customer(
    client: AsyncClient, admin: dict, name: str, login_id: str
) -> tuple[int, dict]:
    """A customer with portal access who is past the forced password change."""
    customer_id, _ = await open_portal_account(client, admin, name, login_id)
    signed_in = (await client.post(
        "/api/v1/portal/auth/login",
        json={"login_id": login_id, "password": PORTAL_PASSWORD},
    )).json()["data"]
    headers = {"Authorization": f"Bearer {signed_in['access_token']}"}
    changed = await client.post(
        "/api/v1/portal/auth/change-password",
        headers=headers,
        json={"current_password": PORTAL_PASSWORD, "new_password": "Settled@12345"},
    )
    assert changed.status_code == 200, changed.text
    # Re-issued after the change so the token is not the pre-change one.
    signed_in = (await client.post(
        "/api/v1/portal/auth/login",
        json={"login_id": login_id, "password": "Settled@12345"},
    )).json()["data"]
    return customer_id, {"Authorization": f"Bearer {signed_in['access_token']}"}


class TestOneCustomerCannotReadAnother:
    async def test_an_invoice_belonging_to_another_shop_is_not_found(
        self, client: AsyncClient
    ) -> None:
        """The isolation that matters most once there is anything to read."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)

        mine_id, mine = await ready_portal_customer(
            client, admin, "بقالة الأولى", "0501000001")
        theirs_id, theirs = await ready_portal_customer(
            client, admin, "بقالة الثانية", "0501000002")

        my_invoice = (await post_invoice(
            client, admin, mine_id, warehouse_id, product["id"], "3"
        )).json()["data"]["id"]
        their_invoice = (await post_invoice(
            client, admin, theirs_id, warehouse_id, product["id"], "4"
        )).json()["data"]["id"]
        assert my_invoice != their_invoice

        assert (await client.get(
            f"/api/v1/portal/invoices/{my_invoice}", headers=mine)).status_code == 200
        # Not 403 — which would confirm the invoice exists. Same answer as a number
        # that was never issued at all.
        assert (await client.get(
            f"/api/v1/portal/invoices/{their_invoice}", headers=mine)
        ).status_code == 404
        assert (await client.get(
            "/api/v1/portal/invoices/999999", headers=mine)).status_code == 404

    async def test_each_list_holds_only_the_signed_in_customer(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        mine_id, mine = await ready_portal_customer(
            client, admin, "بقالة القائمة أ", "0501000003")
        theirs_id, theirs = await ready_portal_customer(
            client, admin, "بقالة القائمة ب", "0501000004")

        (await post_invoice(
            client, admin, mine_id, warehouse_id, product["id"], "2"
        )).json()["data"]["id"]
        (await post_invoice(
            client, admin, theirs_id, warehouse_id, product["id"], "5"
        )).json()["data"]["id"]
        (await post_invoice(
            client, admin, theirs_id, warehouse_id, product["id"], "6"
        )).json()["data"]["id"]

        mine_list = (await client.get(
            "/api/v1/portal/invoices", headers=mine)).json()["data"]
        theirs_list = (await client.get(
            "/api/v1/portal/invoices", headers=theirs)).json()["data"]
        assert len(mine_list) == 1
        assert len(theirs_list) == 2
        assert not {i["id"] for i in mine_list} & {i["id"] for i in theirs_list}


class TestTheStatementAgreesWithTheOffice:
    async def test_the_customer_and_the_office_read_the_same_numbers(
        self, client: AsyncClient
    ) -> None:
        """The one thing a statement cannot survive is being two documents.

        Compared against the staff statement rather than against figures written into
        this test, so the check keeps its meaning when the balance formula changes.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id, customer = await ready_portal_customer(
            client, admin, "بقالة الكشف", "0501000005")
        (await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "7"
        )).json()["data"]["id"]
        (await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "2"
        )).json()["data"]["id"]

        office = (await client.get(
            f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
        )).json()["data"]
        portal = (await client.get(
            "/api/v1/portal/statement", headers=customer)).json()["data"]

        for field in ("opening_balance", "total_invoices", "total_returns",
                      "total_paid", "balance"):
            assert Decimal(str(portal[field])) == Decimal(str(office[field])), field
        assert {i["id"] for i in portal["invoices"]} == {
            i["id"] for i in office["invoices"]}

    async def test_the_statement_never_carries_the_credit_limit(
        self, client: AsyncClient
    ) -> None:
        """The office's view of a customer is not the customer's business."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id, customer = await ready_portal_customer(
            client, admin, "بقالة الحد", "0501000006")
        body = (await client.get(
            "/api/v1/portal/statement", headers=customer)).text
        for leaked in ("credit_limit", "price_tier", "salesman", "unit_cost"):
            assert leaked not in body, f"statement leaked {leaked}"


class TestInvoiceDetail:
    async def test_a_customer_sees_what_they_were_charged_but_not_what_it_cost_us(
        self, client: AsyncClient
    ) -> None:
        """Prices yes, cost never. They are adjacent columns on the same row."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id, customer = await ready_portal_customer(
            client, admin, "بقالة التفاصيل", "0501000007")
        invoice_id = (await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "4"
        )).json()["data"]["id"]

        response = await client.get(
            f"/api/v1/portal/invoices/{invoice_id}", headers=customer)
        assert response.status_code == 200, response.text
        detail = response.json()["data"]

        assert detail["lines"], "an invoice with no lines tells the customer nothing"
        line = detail["lines"][0]
        assert line["product_name"] == product["name"]
        assert Decimal(str(line["unit_price"])) > 0
        assert "unit_cost" not in response.text
        assert "batch" not in response.text.lower(), (
            "batch numbers are our stock records, not the customer's"
        )
        # The arithmetic the customer would redo by hand.
        assert Decimal(str(detail["amount_due"])) == (
            Decimal(str(detail["total"])) - Decimal(str(detail["paid_amount"]))
        )


class TestProfile:
    async def test_a_customer_may_fix_their_phone_without_losing_their_address(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة العنوان", "0501000008")
        await client.put("/api/v1/portal/profile", headers=customer,
                         json={"phone": "0555000111", "address": "شارع الملك فهد"})

        only_phone = await client.put(
            "/api/v1/portal/profile", headers=customer, json={"phone": "0555000222"})
        assert only_phone.status_code == 200, only_phone.text
        data = only_phone.json()["data"]
        assert data["phone"] == "0555000222"
        assert data["address"] == "شارع الملك فهد", (
            "sending one field blanked the other"
        )

    async def test_a_customer_cannot_rename_themselves(
        self, client: AsyncClient
    ) -> None:
        """The name is what the ledger and every invoice are filed under."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الاسم", "0501000009")
        await client.put("/api/v1/portal/profile", headers=customer,
                         json={"name": "شركة أخرى تماماً"})
        me = (await client.get("/api/v1/portal/me", headers=customer)).json()["data"]
        assert me["name"] == "بقالة الاسم"


class TestTheTemporaryPasswordStillGates:
    async def test_none_of_the_account_is_readable_before_the_password_changes(
        self, client: AsyncClient
    ) -> None:
        """The gate proven through the routes, not just against the dependency."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "بقالة المؤقتة", "0501000010")
        signed_in = (await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0501000010", "password": PORTAL_PASSWORD},
        )).json()["data"]
        headers = {"Authorization": f"Bearer {signed_in['access_token']}"}

        for path in ("/api/v1/portal/statement", "/api/v1/portal/invoices"):
            assert (await client.get(path, headers=headers)).status_code == 403, path
        # But the screen that lets them get past it still answers.
        assert (await client.get(
            "/api/v1/portal/me", headers=headers)).status_code == 200


class TestStaffCannotWalkInThroughTheReadRoutes:
    @pytest.mark.parametrize(
        "path", ["/api/v1/portal/statement", "/api/v1/portal/invoices"]
    )
    async def test_a_staff_token_is_refused(
        self, client: AsyncClient, path: str
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        assert (await client.get(path, headers=admin)).status_code == 401
