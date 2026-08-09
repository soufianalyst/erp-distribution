"""The catalogue and the orders placed from it.

The catalogue is the one portal surface a competitor would pay for: it lists the whole
range and, done carelessly, what we charge for it. So the first test here reads the
raw response and looks for any of the three prices a product carries.

The rest is about an order being a *request*. It must move no stock and reserve
nothing — checked by placing one and then confirming the warehouse is untouched —
and it must not become a second way to sell.
"""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_portal_account import ready_portal_customer
from app.tests.test_inventory import create_product, receive
from app.tests.test_sales import setup_stocked_catalog


async def stock_level(client: AsyncClient, admin: dict, product_id: int) -> Decimal:
    """Total on-hand for a product, read through the staff API."""
    levels = (await client.get(
        "/api/v1/inventory/stock/levels", headers=admin)).json()["data"]
    return sum(
        (Decimal(str(row["total_quantity"])) for row in levels
         if row["product_id"] == product_id),
        Decimal("0"),
    )


class TestTheCatalogueShowsNoPrices:
    async def test_an_ordinary_line_still_carries_no_price(
        self, client: AsyncClient
    ) -> None:
        """A product carries wholesale, half-wholesale and retail. None may leak.

        Discounted lines are the one exception and are covered separately; a line with
        no live offer must show nothing, because which of the three applies is still
        the office's decision at invoicing time.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الكتالوج", "0502000001")

        response = await client.get("/api/v1/portal/catalog", headers=customer)
        assert response.status_code == 200, response.text
        for forbidden in ("cost", "wholesale", "retail", "tier"):
            assert forbidden not in response.text.lower(), (
                f"the catalogue leaked {forbidden}"
            )

        item = next(
            i for i in response.json()["data"] if i["product_id"] == product["id"]
        )
        assert item["price_before"] is None
        assert item["price_now"] is None
        assert item["discount_percent"] is None

    async def test_the_band_tracks_the_products_own_reorder_threshold(
        self, client: AsyncClient
    ) -> None:
        """All three bands, and never a number.

        The fixture leaves 50 units against a `min_stock_level` of 50, which is
        precisely the level at which the business already calls itself short — so
        "limited" here is the threshold being honoured, not an off-by-one. Receiving
        more crosses back to "available", which is what makes this a test of the rule
        rather than of one fixture.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة المؤشر", "0502000002")

        async def band_of(product_id: int) -> str:
            items = (await client.get(
                "/api/v1/portal/catalog", headers=customer)).json()["data"]
            return next(i for i in items if i["product_id"] == product_id)["availability"]

        # 50 on hand, threshold 50 — at the line counts as short.
        assert await band_of(product["id"]) == "limited"

        await receive(client, admin, product["id"], warehouse_id, "B-EXTRA", 200, "500")
        assert await band_of(product["id"]) == "available"

        # A product nobody has received stock for.
        empty = await create_product(client, admin, sku="EMPTY-001")
        assert await band_of(empty["id"]) == "unavailable"

        # And at no point is the quantity itself disclosed.
        body = (await client.get("/api/v1/portal/catalog", headers=customer)).text
        for quantity in ("550", "500", "50"):
            assert quantity not in body, f"the catalogue disclosed {quantity} units"

    async def test_a_stopped_product_is_not_offered(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الموقوف", "0502000003")

        stopped = await client.patch(
            f"/api/v1/inventory/products/{product['id']}",
            headers=admin, json={"is_active": False})
        assert stopped.status_code == 200, stopped.text
        items = (await client.get(
            "/api/v1/portal/catalog", headers=customer)).json()["data"]
        assert product["id"] not in {i["product_id"] for i in items}


class TestPlacingAnOrderChangesNothingButTheOrder:
    async def test_stock_is_untouched(self, client: AsyncClient) -> None:
        """The whole premise: an order is a request, not a sale."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الطلب", "0502000004")

        before = await stock_level(client, admin, product["id"])
        placed = await client.post("/api/v1/portal/orders", headers=customer, json={
            "lines": [{"product_id": product["id"], "quantity": "5"}],
            "fulfillment": "delivery",
        })
        assert placed.status_code == 201, placed.text
        assert placed.json()["data"]["status"] == "pending"
        assert await stock_level(client, admin, product["id"]) == before

    async def test_the_order_carries_no_money_at_all(
        self, client: AsyncClient
    ) -> None:
        """Pricing happens once, when the office invoices it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة بلا سعر", "0502000005")

        placed = await client.post("/api/v1/portal/orders", headers=customer, json={
            "lines": [{"product_id": product["id"], "quantity": "3"}]})
        for forbidden in ("price", "total", "amount", "cost"):
            assert forbidden not in placed.text.lower(), (
                f"an order quoted {forbidden} before the office priced it"
            )

    async def test_ordering_more_than_we_hold_is_still_accepted(
        self, client: AsyncClient
    ) -> None:
        """Deliberate. A short line is a phone call from the salesman, not a
        silently rejected form — and the office may well have stock arriving."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الزيادة", "0502000006")

        placed = await client.post("/api/v1/portal/orders", headers=customer, json={
            "lines": [{"product_id": product["id"], "quantity": "99999"}]})
        assert placed.status_code == 201, placed.text

    async def test_the_same_product_twice_is_refused(
        self, client: AsyncClient
    ) -> None:
        """Almost always a double-tap; merging it silently changes the quantity."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة التكرار", "0502000007")

        placed = await client.post("/api/v1/portal/orders", headers=customer, json={
            "lines": [
                {"product_id": product["id"], "quantity": "2"},
                {"product_id": product["id"], "quantity": "3"},
            ]})
        assert placed.status_code == 400, placed.text

    async def test_an_empty_order_is_refused(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة الفارغ", "0502000008")
        assert (await client.post(
            "/api/v1/portal/orders", headers=customer, json={"lines": []}
        )).status_code == 422


class TestOneCustomerCannotTouchAnothersOrder:
    async def test_reading_and_cancelling_another_shops_order(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, mine = await ready_portal_customer(
            client, admin, "بقالة الطلب أ", "0502000009")
        _, theirs = await ready_portal_customer(
            client, admin, "بقالة الطلب ب", "0502000010")

        their_order = (await client.post(
            "/api/v1/portal/orders", headers=theirs,
            json={"lines": [{"product_id": product["id"], "quantity": "4"}]}
        )).json()["data"]["id"]

        assert (await client.get(
            f"/api/v1/portal/orders/{their_order}", headers=mine)).status_code == 404
        assert (await client.post(
            f"/api/v1/portal/orders/{their_order}/cancel", headers=mine, json={}
        )).status_code == 404
        # And it is still theirs, untouched.
        still = (await client.get(
            f"/api/v1/portal/orders/{their_order}", headers=theirs)).json()["data"]
        assert still["status"] == "pending"

    async def test_the_order_list_is_per_customer(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, mine = await ready_portal_customer(
            client, admin, "بقالة قائمة أ", "0502000011")
        _, theirs = await ready_portal_customer(
            client, admin, "بقالة قائمة ب", "0502000012")

        await client.post("/api/v1/portal/orders", headers=mine,
                          json={"lines": [{"product_id": product["id"], "quantity": "1"}]})
        await client.post("/api/v1/portal/orders", headers=theirs,
                          json={"lines": [{"product_id": product["id"], "quantity": "2"}]})

        assert len((await client.get(
            "/api/v1/portal/orders", headers=mine)).json()["data"]) == 1
        assert len((await client.get(
            "/api/v1/portal/orders", headers=theirs)).json()["data"]) == 1


class TestCancelling:
    async def test_a_pending_order_may_be_withdrawn(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة السحب", "0502000013")

        order_id = (await client.post(
            "/api/v1/portal/orders", headers=customer,
            json={"lines": [{"product_id": product["id"], "quantity": "2"}]}
        )).json()["data"]["id"]

        cancelled = await client.post(
            f"/api/v1/portal/orders/{order_id}/cancel", headers=customer,
            json={"reason": "غيّرت رأيي"})
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "cancelled"
        assert cancelled.json()["data"]["decision_note"] == "غيّرت رأيي"

    async def test_cancelling_twice_is_refused(self, client: AsyncClient) -> None:
        """The second attempt is no longer pending, so it must not silently succeed."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await setup_stocked_catalog(client, admin)
        _, customer = await ready_portal_customer(
            client, admin, "بقالة المكرر", "0502000014")

        order_id = (await client.post(
            "/api/v1/portal/orders", headers=customer,
            json={"lines": [{"product_id": product["id"], "quantity": "2"}]}
        )).json()["data"]["id"]
        await client.post(f"/api/v1/portal/orders/{order_id}/cancel",
                          headers=customer, json={})
        again = await client.post(f"/api/v1/portal/orders/{order_id}/cancel",
                                  headers=customer, json={})
        assert again.status_code == 400, again.text


class TestTheOrderingSurfaceIsClosedToEveryoneElse:
    async def test_staff_and_the_unauthenticated_are_refused(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        for path in ("/api/v1/portal/catalog", "/api/v1/portal/orders"):
            assert (await client.get(path, headers=admin)).status_code == 401, path
            assert (await client.get(path)).status_code == 401, path
