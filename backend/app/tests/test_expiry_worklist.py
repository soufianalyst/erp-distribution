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


class TestTheTwoScreensAgree:
    """One product, two screens, one surplus.

    The expiry worklist and the markdown plan both answer "how much of this will
    still be on the shelf when it expires". They each used to divide the same sales
    total by the same window in their own file, which is fine until someone changes
    one — and then a manager reads two different surpluses for one product on two
    tabs on the same morning, and stops trusting both. The projection now lives on
    `Demand`, and this is the test that notices if a call site starts doing its own
    multiplication again.
    """

    async def test_the_worklist_surplus_matches_the_markdown_plan(
        self, client: AsyncClient, db_session
    ) -> None:
        from app.services.inventory.markdown_service import MarkdownService

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الاتفاق")
        product = await create_product(
            client, admin, sku="AGREE-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-AGREE", 40,
                      "600", unit_cost="20")
        customer_id = await create_customer(
            client, admin, name="عميل الاتفاق", credit_limit="900000")
        for offset in [7 * (i + 1) for i in range(10)]:
            response = await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5",
                tax_rate_ids=[])
            assert response.status_code == 201, response.text
            from app.domain.models.sales import SalesInvoice
            invoice = await db_session.get(
                SalesInvoice, response.json()["data"]["id"])
            invoice.invoice_date = date.today() - timedelta(days=offset)
        await db_session.commit()

        worklist = await fetch(client, admin, horizon=60)
        row = find(worklist["items"], product["id"])
        assert row is not None, "the product should be on the worklist"

        plan = await MarkdownService(db_session).plan(horizon_days=60)
        proposal = next(i for i in plan.items if i.sku == "AGREE-1")

        assert Decimal(row["daily_sales_rate"]) == proposal.daily_rate
        assert Decimal(row["surplus_quantity"]) == proposal.surplus

    async def test_a_thin_rate_makes_the_markdown_plan_the_stricter_of_the_two(
        self, client: AsyncClient, db_session
    ) -> None:
        """The one place the screens are meant to disagree, pinned so it stays meant.

        Three sale-days is a rate the worklist will still project — it is advice, and
        its worth is in staying short enough to be worked. The markdown plan refuses
        the same rate, because its output is a price a customer gets charged. Same
        underlying rate from the same service, two different projections, both named
        at the call site.

        Written down because the difference looks exactly like a bug: two screens,
        one product, two surpluses. Deleting it "to make them agree" would either
        flood the worklist or price stock off an anecdote.
        """
        from app.domain.models.sales import SalesInvoice
        from app.services.inventory.demand_service import (
            DemandConfidence,
            DemandService,
        )
        from app.services.inventory.markdown_service import MarkdownService

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن النادر")
        product = await create_product(
            client, admin, sku="RARE-AGREE", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-RARE", 40,
                      "600", unit_cost="20")
        customer_id = await create_customer(
            client, admin, name="عميل النادر", credit_limit="900000")
        for offset in (7, 14, 21):
            response = await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5",
                tax_rate_ids=[])
            assert response.status_code == 201, response.text
            invoice = await db_session.get(
                SalesInvoice, response.json()["data"]["id"])
            invoice.invoice_date = date.today() - timedelta(days=offset)
        await db_session.commit()

        demand = (await DemandService(db_session).for_products(
            [product["id"]], default_lead_time_days=0, window_days=90
        ))[product["id"]]
        assert demand.confidence is DemandConfidence.SPARSE

        row = find((await fetch(client, admin, horizon=60))["items"], product["id"])
        proposal = next(
            i for i in (await MarkdownService(db_session).plan(horizon_days=60)).items
            if i.sku == "RARE-AGREE"
        )

        # The rate is the same number on both — that is the part consolidation buys.
        assert Decimal(row["daily_sales_rate"]) == proposal.daily_rate
        # The projection is not, and the strict one belongs to the pricing decision.
        assert Decimal(row["projected_sales"]) > 0
        assert proposal.surplus > Decimal(row["surplus_quantity"])
        assert proposal.surplus == Decimal("585")
