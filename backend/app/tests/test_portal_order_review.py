"""The office deciding what to do with a customer's request.

This is where an order stops being a request and becomes money, so the tests are
about the join: the invoice must come out of the ordinary sales pipeline (stock
actually deducted, ledger actually posted), the order must end up pointing at it, and
one request must never be billed twice.

The other half is reach. A salesman may work his own shops' orders and must not see
another rep's — checked on the queue and on every action, because a queue that filters
correctly while `approve` does not is no protection at all.
"""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_portal_account import ready_portal_customer
from app.tests.test_portal_orders import stock_level
from app.tests.test_sales import setup_stocked_catalog


async def place(client: AsyncClient, customer: dict, product_id: int, qty: str) -> int:
    response = await client.post("/api/v1/portal/orders", headers=customer, json={
        "lines": [{"product_id": product_id, "quantity": qty}]})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestTurningAnOrderIntoASale:
    async def test_the_invoice_comes_from_the_ordinary_pipeline(
        self, client: AsyncClient
    ) -> None:
        """Stock must actually move and the order must point at the invoice.

        If this passed while stock stayed put, the portal would have grown a second
        way to sell goods — the one thing the order model exists to prevent.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة التحويل", "0503000001")

        order_id = await place(client, customer, product["id"], "4")
        before = await stock_level(client, admin, product["id"])

        invoiced = await client.post(
            f"/api/v1/customer-orders/{order_id}/invoice", headers=admin,
            json={"payment_method": "cash", "tax_rate_ids": [],
                  "warehouse_id": warehouse_id})
        assert invoiced.status_code == 201, invoiced.text
        invoice = invoiced.json()["data"]

        # Stock deducted by exactly the quantity ordered — FEFO ran for real.
        assert await stock_level(client, admin, product["id"]) == before - Decimal("4")
        assert Decimal(str(invoice["total"])) > 0

        # And the request now points at the sale that answered it.
        order = (await client.get(
            f"/api/v1/portal/orders/{order_id}", headers=customer)).json()["data"]
        assert order["status"] == "invoiced"
        assert order["invoice_id"] == invoice["id"]

        # The customer can open that invoice through their own portal.
        assert (await client.get(
            f"/api/v1/portal/invoices/{invoice['id']}", headers=customer)
        ).status_code == 200

    async def test_one_request_cannot_be_billed_twice(
        self, client: AsyncClient
    ) -> None:
        """A double-click must not charge a shop twice for one order."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة المزدوج", "0503000002")
        order_id = await place(client, customer, product["id"], "3")

        body = {"payment_method": "cash", "tax_rate_ids": [],
                "warehouse_id": warehouse_id}
        first = await client.post(
            f"/api/v1/customer-orders/{order_id}/invoice", headers=admin, json=body)
        assert first.status_code == 201, first.text
        after_first = await stock_level(client, admin, product["id"])

        second = await client.post(
            f"/api/v1/customer-orders/{order_id}/invoice", headers=admin, json=body)
        assert second.status_code == 409, second.text
        assert await stock_level(client, admin, product["id"]) == after_first

    async def test_a_rejected_order_cannot_be_invoiced(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة المرفوض", "0503000003")
        order_id = await place(client, customer, product["id"], "2")

        await client.post(f"/api/v1/customer-orders/{order_id}/reject",
                          headers=admin, json={"reason": "الصنف موقوف مؤقتاً"})
        blocked = await client.post(
            f"/api/v1/customer-orders/{order_id}/invoice", headers=admin,
            json={"payment_method": "cash", "tax_rate_ids": [],
                  "warehouse_id": warehouse_id})
        assert blocked.status_code == 400, blocked.text


class TestWhatTheCustomerSeesOfTheDecision:
    async def test_a_rejection_reason_reaches_the_customer(
        self, client: AsyncClient
    ) -> None:
        """The reason is written for them, so they must actually receive it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة السبب", "0503000004")
        order_id = await place(client, customer, product["id"], "2")

        await client.post(f"/api/v1/customer-orders/{order_id}/reject",
                          headers=admin, json={"reason": "الكمية غير متوفرة هذا الأسبوع"})
        order = (await client.get(
            f"/api/v1/portal/orders/{order_id}", headers=customer)).json()["data"]
        assert order["status"] == "cancelled"
        assert order["decision_note"] == "الكمية غير متوفرة هذا الأسبوع"

    async def test_approval_closes_the_customers_cancel_button(
        self, client: AsyncClient
    ) -> None:
        """Once the office is picking against it, withdrawing is a phone call."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الاعتماد", "0503000005")
        order_id = await place(client, customer, product["id"], "2")

        approved = await client.post(
            f"/api/v1/customer-orders/{order_id}/approve", headers=admin)
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "confirmed"

        refused = await client.post(
            f"/api/v1/portal/orders/{order_id}/cancel", headers=customer, json={})
        assert refused.status_code == 400, refused.text

    async def test_the_office_view_still_carries_no_money(
        self, client: AsyncClient
    ) -> None:
        """An order has no value until it is invoiced, on either side of the wall."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة المكتب", "0503000006")
        await place(client, customer, product["id"], "2")

        queue = await client.get("/api/v1/customer-orders", headers=admin)
        assert queue.status_code == 200, queue.text
        assert queue.json()["data"][0]["customer_name"] == "بقالة المكتب"
        for forbidden in ("unit_price", "total", "unit_cost"):
            assert forbidden not in queue.text.lower(), (
                f"the review queue quoted {forbidden}"
            )


class TestReach:
    async def test_a_salesman_sees_and_touches_only_his_own_shops_orders(
        self, client: AsyncClient
    ) -> None:
        """Filtered on the queue *and* on every action.

        A queue that hides another rep's order while `approve` still accepts its id
        is not protection, just a tidier list.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        me = (await client.get("/api/v1/auth/me", headers=salesman)).json()["data"]

        mine_id, mine = await ready_portal_customer(
            client, admin, "بقالة مندوبي", "0503000007")
        theirs_id, theirs = await ready_portal_customer(
            client, admin, "بقالة غيري", "0503000008")
        # Only the first shop belongs to this salesman.
        assigned = await client.patch(
            f"/api/v1/sales/customers/{mine_id}", headers=admin,
            json={"salesman_id": me["id"]})
        assert assigned.status_code == 200, assigned.text

        my_order = await place(client, mine, product["id"], "2")
        their_order = await place(client, theirs, product["id"], "3")

        queue = (await client.get(
            "/api/v1/customer-orders", headers=salesman)).json()["data"]
        listed = {o["id"] for o in queue}
        assert my_order in listed
        assert their_order not in listed, "a rep saw another rep's customer's order"

        # And the actions agree with the queue.
        assert (await client.post(
            f"/api/v1/customer-orders/{their_order}/approve", headers=salesman
        )).status_code == 404
        assert (await client.post(
            f"/api/v1/customer-orders/{their_order}/reject", headers=salesman,
            json={"reason": "لا"})).status_code == 404
        assert (await client.post(
            f"/api/v1/customer-orders/{my_order}/approve", headers=salesman
        )).status_code == 200

    async def test_a_customer_cannot_reach_the_review_queue(
        self, client: AsyncClient
    ) -> None:
        """The obvious one, and cheap to keep."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الفضولي", "0503000009")
        order_id = await place(client, customer, product["id"], "2")

        assert (await client.get(
            "/api/v1/customer-orders", headers=customer)).status_code == 401
        assert (await client.post(
            f"/api/v1/customer-orders/{order_id}/approve", headers=customer
        )).status_code == 401
