"""The expiry worklist: what will not sell in time, and who to call.

The arithmetic is the whole product here, so it is tested directly rather than
through "the endpoint returns 200". Three claims matter:

* stock that will clear on its own must not appear — a list that cries wolf gets
  ignored, and then the real items go unworked;
* stock that will not clear must appear with the *surplus* quantified, not the whole
  holding, or every fast-moving line looks like a crisis;
* the suggested buyers must be people who actually bought the thing.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer, post_invoice

WORKLIST = "/api/v1/analytics/inventory/expiry-worklist"


async def fetch(client: AsyncClient, admin: dict, horizon: int = 60) -> dict:
    response = await client.get(WORKLIST, headers=admin, params={"horizon_days": horizon})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def find(items: list[dict], product_id: int) -> dict | None:
    return next((i for i in items if i["product_id"] == product_id), None)


class TestWhatCountsAsAtRisk:
    async def test_stock_that_will_sell_in_time_is_left_off_the_list(
        self, client: AsyncClient
    ) -> None:
        """The judgement that makes this a worklist rather than another alert.

        Thirty units expiring in fifty days, selling steadily, will be gone well
        before then — putting it in front of a manager wastes the one thing the
        screen is asking for, which is their attention.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن السريع")
        product = await create_product(client, admin, sku="FAST-001",
                                       warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-FAST", 50, "30")

        customer_id = await create_customer(client, admin, name="بقالة السريع")
        # 24 of the 30 sold. The rate is measured over the 90-day window, so
        # 24/90 ≈ 0.27 a day, and over the 50 days left that clears roughly 13 —
        # comfortably more than the 6 still on the shelf.
        for _ in range(3):
            sold = await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "8")
            assert sold.status_code == 201, sold.text

        data = await fetch(client, admin)
        assert find(data["items"], product["id"]) is None, (
            "a product that will sell out before expiry was flagged as at risk"
        )

    async def test_slow_stock_is_flagged_with_only_the_surplus(
        self, client: AsyncClient
    ) -> None:
        """The number must be what will be *left*, not the whole holding.

        Reporting the full quantity would make a line that is 90% fine look like a
        total loss, and the totals across the screen would be meaningless.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن البطيء")
        product = await create_product(client, admin, sku="SLOW-001",
                                       warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-SLOW", 40, "500")

        customer_id = await create_customer(client, admin, name="بقالة البطيء")
        sold = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10")
        assert sold.status_code == 201, sold.text

        data = await fetch(client, admin)
        item = find(data["items"], product["id"])
        assert item is not None, "500 units moving slowly should be flagged"

        # 490 remain; only a sliver will sell before expiry, so the surplus is most
        # of it — but strictly less than everything held.
        assert Decimal(item["surplus_quantity"]) > 0
        assert Decimal(item["surplus_quantity"]) < Decimal(item["quantity_at_risk"])
        assert Decimal(item["projected_sales"]) > 0
        assert item["has_sales_history"] is True

    async def test_expired_stock_is_not_a_selling_opportunity(
        self, client: AsyncClient
    ) -> None:
        """Already-expired goods are a write-off. Letting them pile up in here would
        inflate a list meant to prompt phone calls."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        data = await fetch(client, admin, horizon=365)
        everything = data["items"] + data["dead_stock"]
        assert all(i["days_remaining"] >= 0 for i in everything), (
            "expired stock appeared in the worklist"
        )


class TestTheTwoProblemsStayApart:
    async def test_never_sold_stock_is_listed_separately(
        self, client: AsyncClient
    ) -> None:
        """A product nobody has ever bought has no one to ring.

        It belongs in the same report — it is money about to be lost — but not in the
        call list, where it would outrank every real opportunity because "never sold"
        always scores maximum surplus.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الراكد")
        product = await create_product(client, admin, sku="DEAD-001",
                                       warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-DEAD", 30, "200")

        data = await fetch(client, admin)
        assert find(data["items"], product["id"]) is None, (
            "unsellable stock was mixed into the call list"
        )
        dead = find(data["dead_stock"], product["id"])
        assert dead is not None, "never-sold stock vanished from the report entirely"
        assert dead["has_sales_history"] is False
        assert dead["suggested_buyers"] == []
        # Nothing sells, so the whole holding is the surplus.
        assert Decimal(dead["surplus_quantity"]) == Decimal(dead["quantity_at_risk"])


class TestWhoToCall:
    async def test_the_suggested_buyers_actually_bought_it(
        self, client: AsyncClient
    ) -> None:
        """No modelling, no lookalikes — only shops with this product in their history.

        Suggesting a customer who has never bought it would be worse than suggesting
        nobody: the rep makes the call, it lands badly, and they stop trusting the
        screen.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الاتصال")
        product = await create_product(client, admin, sku="CALL-001",
                                       warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-CALL", 40, "400")

        buyer_id = await create_customer(client, admin, name="بقالة المشتري")
        await create_customer(client, admin, name="بقالة لم تشترِ")
        sold = await post_invoice(
            client, admin, buyer_id, warehouse_id, product["id"], "5")
        assert sold.status_code == 201, sold.text

        data = await fetch(client, admin)
        item = find(data["items"], product["id"])
        assert item is not None

        names = {b["customer_name"] for b in item["suggested_buyers"]}
        assert "بقالة المشتري" in names
        assert "بقالة لم تشترِ" not in names, "a customer who never bought it was suggested"

    async def test_the_reasoning_is_shown_not_just_the_score(
        self, client: AsyncClient
    ) -> None:
        """A ranking nobody can question is a ranking nobody trusts."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        data = await fetch(client, admin)
        if not data["items"]:
            return
        item = data["items"][0]
        for field in (
            "daily_sales_rate",
            "projected_sales",
            "surplus_quantity",
            "surplus_value",
            "urgency",
            "days_remaining",
            "earliest_expiry",
            "warehouses",
        ):
            assert field in item, f"the worklist hides {field} behind its ranking"

    async def test_the_list_is_ordered_by_cost_of_doing_nothing(
        self, client: AsyncClient
    ) -> None:
        """Urgency is surplus value per day of runway, descending."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        data = await fetch(client, admin)
        urgencies = [Decimal(i["urgency"]) for i in data["items"]]
        assert urgencies == sorted(urgencies, reverse=True)
