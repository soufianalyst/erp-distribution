"""What a shop sees when it asks "where is my order".

Two things are being tested at once, and the second is the one that bites.

The steps must be right: an order runs from "we got it" to "it arrived", and after
the office prices it the honest answer comes from the invoice — is it on a van, is
it waiting on the counter. Reusing `InvoiceTimelineService` for that half is what
stops the portal and the office disagreeing about where the goods are.

And the portal must stay a portal. It is the only surface outside the company, so
a step that leaks a trip number, a cost, or the phrase "لن تخرج البضاعة قبل
التحصيل" is a small operational disclosure to every shop we sell to — and one
customer must never be able to follow another's order by guessing a number.
"""

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_invoice_timeline import schedule
from app.tests.test_portal_account import ready_portal_customer
from app.tests.test_sales import setup_stocked_catalog


async def place_order(client: AsyncClient, portal: dict, product_id: int,
                      fulfillment: str = "delivery") -> int:
    response = await client.post("/api/v1/portal/orders", headers=portal, json={
        "lines": [{"product_id": product_id, "quantity": "3"}],
        "fulfillment": fulfillment,
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def track(client: AsyncClient, portal: dict, order_id: int) -> dict:
    response = await client.get(
        f"/api/v1/portal/orders/{order_id}/timeline", headers=portal)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def states(data: dict) -> dict[str, str]:
    return {s["key"]: s["state"] for s in data["steps"]}


def current(data: dict) -> str | None:
    """The one live step.

    Asserts there is at most one, because the first version of this helper
    returned the first of several and happily hid a card whose stepper glowed in
    two places at once.
    """
    live = [s["key"] for s in data["steps"] if s["state"] == "current"]
    assert len(live) <= 1, f"أكثر من مرحلة نشطة في الوقت نفسه: {live}"
    return live[0] if live else None


class TestTheJourneyTheShopSees:
    async def test_a_new_order_waits_at_the_office(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, portal = await ready_portal_customer(client, admin, "بقالة التتبع", "0507000001")
        order_id = await place_order(client, portal, product["id"])

        data = await track(client, portal, order_id)
        assert states(data)["placed"] == "done"
        assert current(data) == "confirmed"
        assert "مراجعة" in data["status_label"]

    async def test_confirming_moves_it_along_without_promising_delivery(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, portal = await ready_portal_customer(client, admin, "بقالة الموافقة", "0507000002")
        order_id = await place_order(client, portal, product["id"])

        approved = await client.post(
            f"/api/v1/customer-orders/{order_id}/approve", headers=admin)
        assert approved.status_code == 200, approved.text

        data = await track(client, portal, order_id)
        assert states(data)["confirmed"] == "done"
        assert current(data) == "prepared"
        # Nothing is on a van yet, so no date may be shown.
        assert data["expected"] is None

    async def test_a_refused_order_stops_and_says_why(self, client: AsyncClient) -> None:
        """Not "still being reviewed" forever. The office wrote a reason for the
        customer; this is where the customer reads it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, portal = await ready_portal_customer(client, admin, "بقالة الرفض", "0507000003")
        order_id = await place_order(client, portal, product["id"])

        refused = await client.post(
            f"/api/v1/customer-orders/{order_id}/reject", headers=admin,
            json={"reason": "الصنف غير متوفر حالياً"})
        assert refused.status_code == 200, refused.text

        data = await track(client, portal, order_id)
        assert states(data)["cancelled"] == "failed"
        assert current(data) is None, "خطوة بعد الإلغاء ظهرت كأن الطلب مستمر"
        assert "غير متوفر" in next(
            s for s in data["steps"] if s["key"] == "cancelled")["detail"]

    async def test_a_pickup_order_becomes_ready_to_collect(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        _, portal = await ready_portal_customer(client, admin, "بقالة الاستلام", "0507000004")
        order_id = await place_order(client, portal, product["id"], "pickup")

        await client.post(
            f"/api/v1/customer-orders/{order_id}/approve", headers=admin)
        invoiced = await client.post(
            f"/api/v1/customer-orders/{order_id}/invoice", headers=admin,
            json={"payment_method": "cash", "tax_rate_ids": [],
                  "warehouse_id": warehouse_id})
        assert invoiced.status_code == 201, invoiced.text

        data = await track(client, portal, order_id)
        assert states(data)["prepared"] == "done"
        ready = next(s for s in data["steps"] if s["key"] == "ready")
        assert ready["label"] == "جاهز للاستلام"
        assert ready["state"] == "done"
        assert current(data) == "completed"


class TestItStaysAPortal:
    async def test_no_step_leaks_how_we_run_the_warehouse(
        self, client: AsyncClient
    ) -> None:
        """The staff tracker says things like "لن تخرج البضاعة قبل التحصيل" and
        names trip numbers. Those are instructions to our own people; to a shop they
        are noise at best and a disclosure at worst."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        _, portal = await ready_portal_customer(client, admin, "بقالة الخصوصية", "0507000005")
        order_id = await place_order(client, portal, product["id"])
        await client.post(
            f"/api/v1/customer-orders/{order_id}/approve", headers=admin)
        invoiced = await client.post(
            f"/api/v1/customer-orders/{order_id}/invoice", headers=admin,
            json={"payment_method": "credit", "tax_rate_ids": [],
                  "warehouse_id": warehouse_id})
        assert invoiced.status_code == 201, invoiced.text
        # Actually put it on a round. Without a trip there is no trip number to
        # leak, and this test passed against a deliberately leaky build — which
        # made it worth nothing.
        await schedule(
            client, admin, invoiced.json()["data"]["id"], warehouse_id,
            driver="ياسر", vehicle="شاحنة 3")

        data = await track(client, portal, order_id)
        blob = " ".join(
            f"{s['label']} {s.get('detail') or ''}" for s in data["steps"]
        )
        for leak in ("رحلة رقم", "التحصيل", "الصندوق", "تكلفة", "المطلوب تحصيله"):
            assert leak not in blob, f"تسرّبت عبارة داخلية إلى البوابة: {leak}"
        # And no money at all: an order carries quantities, never a price.
        assert "total" not in data and "amount_due" not in data

    async def test_a_customer_cannot_follow_another_customers_order(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, theirs = await ready_portal_customer(client, admin, "بقالة الأولى", "0507000006")
        _, mine = await ready_portal_customer(client, admin, "بقالة الثانية", "0507000007")
        order_id = await place_order(client, theirs, product["id"])

        refused = await client.get(
            f"/api/v1/portal/orders/{order_id}/timeline", headers=mine)
        assert refused.status_code in (403, 404), refused.text

    async def test_a_staff_token_is_not_a_portal_token(
        self, client: AsyncClient
    ) -> None:
        """Realm separation applies here like everywhere else in the portal."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        refused = await client.get("/api/v1/portal/orders/1/timeline", headers=admin)
        assert refused.status_code == 401
