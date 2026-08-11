"""The 80/20 report, and the several ways it can lie.

A Pareto chart is the easiest report in the world to produce and one of the easiest
to produce wrongly, because almost any sorted list *looks* like a correct one. The
tests here are built around the four ways this one could mislead:

1. **An off-by-one at the 80% line.** The item that crosses the threshold either
   belongs to class A or it does not, and the headline count and the class table must
   agree about it. They disagreed in the first draft.
2. **A denominator quietly chosen to flatter.** 213 products out of the 494 that sold
   is 43%; the same 213 out of a catalogue of 1,060 is 20% and looks like the textbook
   rule. Both are true, so the report states both.
3. **Dead stock hidden inside "low value".** 566 products here have never sold and
   hold 29.2M — more than half the warehouse. Folded into class C they would be a
   footnote; they get their own class.
4. **A curve built from mixed signs.** A negative margin in the middle of a
   cumulative total makes the running share go *down*, and then "80%" is crossed
   twice and means nothing.

Fixtures use quantities that make the shares exact — 70/15/10/5 of a round total —
so the assertions are arithmetic rather than approximate.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.domain.models.sales import SalesInvoice
from app.services.analytics.pareto_service import (
    ParetoDimension,
    ParetoMeasure,
    ParetoService,
)
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer, post_invoice

PARETO = "/api/v1/analytics/pareto"

# The product helper prices everything at 10.50, so a quantity is a share.
UNIT_PRICE = Decimal("10.50")


async def sell(
    client: AsyncClient, admin: dict, customer_id: int, warehouse_id: int,
    product_id: int, quantity: str, on: date | None = None, db_session=None,
) -> None:
    response = await post_invoice(
        client, admin, customer_id, warehouse_id, product_id, quantity,
        tax_rate_ids=[])
    assert response.status_code == 201, response.text
    if on is not None:
        invoice = await db_session.get(SalesInvoice, response.json()["data"]["id"])
        invoice.invoice_date = on
        await db_session.commit()


async def four_customers(client: AsyncClient, admin: dict) -> tuple[int, int, list[int]]:
    """Revenues of exactly 70%, 15%, 10% and 5% of the total."""
    warehouse_id = await create_warehouse(client, admin, "مخزن باريتو")
    product = await create_product(
        client, admin, sku="PAR-1", warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, "B-PAR", 300, "5000",
                  unit_cost="4")
    ids = []
    for index, quantity in enumerate(("70", "15", "10", "5")):
        customer_id = await create_customer(
            client, admin, name=f"عميل باريتو {index}", credit_limit="900000")
        await sell(client, admin, customer_id, warehouse_id, product["id"], quantity)
        ids.append(customer_id)
    return warehouse_id, product["id"], ids


def by_class(report, abc: str) -> list:
    return [item for item in report.items if item.abc_class == abc]


class TestTheArithmetic:
    async def test_shares_and_classes_on_a_known_distribution(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await four_customers(client, admin)

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.CUSTOMERS, measure=ParetoMeasure.REVENUE)

        assert report.total_value == (UNIT_PRICE * 100).quantize(Decimal("0.01"))
        assert [item.share for item in report.items] == [
            Decimal("70.00"), Decimal("15.00"), Decimal("10.00"), Decimal("5.00")
        ]
        assert [item.cumulative_share for item in report.items] == [
            Decimal("70.00"), Decimal("85.00"), Decimal("95.00"), Decimal("100.00")
        ]
        # 70 alone is not 80; it takes the second customer to cross, so that second
        # customer is in A.
        assert [item.abc_class for item in report.items] == ["A", "A", "B", "C"]
        assert report.entities_for_80_percent == 2
        assert report.share_of_entities_for_80 == Decimal("50.00")

    async def test_the_headline_count_equals_the_size_of_class_a(
        self, client: AsyncClient, db_session
    ) -> None:
        """The off-by-one that was there.

        "80 customers make 80% of revenue" and a class-A row showing 79 is the kind
        of discrepancy that makes a manager stop believing the whole screen, and it
        happens whenever the crossing item is classified by `cumulative <= 80` while
        the headline counts it.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await four_customers(client, admin)

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.CUSTOMERS)
        a_class = next(c for c in report.classes if c.abc_class == "A")
        assert a_class.entities == report.entities_for_80_percent
        assert len(by_class(report, "A")) == report.entities_for_80_percent

    async def test_class_a_holds_at_least_eighty_percent_of_the_value(
        self, client: AsyncClient, db_session
    ) -> None:
        """The definition of the class, stated as a property rather than a count."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await four_customers(client, admin)

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.CUSTOMERS)
        a_class = next(c for c in report.classes if c.abc_class == "A")
        assert a_class.value_share >= Decimal("80")
        # And removing its last member would drop it below — otherwise A is padded.
        without_last = sum(
            (item.value for item in by_class(report, "A")[:-1]), Decimal("0")
        )
        assert without_last / report.total_value * 100 < Decimal("80")

    async def test_the_cumulative_share_never_goes_backwards(
        self, client: AsyncClient, db_session
    ) -> None:
        """What keeps this a Pareto curve.

        On the profit measure a line sold below cost is a negative contribution. Left
        in the ranking it would make the running total fall, so the 80% line could be
        crossed, uncrossed and crossed again, and every class boundary after it would
        be arbitrary. Loss-makers are excluded from the curve — they are a different
        report, and one this does not pretend to be.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الخسارة")
        good = await create_product(
            client, admin, sku="PROFIT-1", warehouse_id=warehouse_id)
        bad = await create_product(
            client, admin, sku="LOSS-1", warehouse_id=warehouse_id)
        # The loss-maker cost more than it sells for: 20.00 against a 10.50 price.
        await receive(client, admin, good["id"], warehouse_id, "B-P", 300, "500",
                      unit_cost="4")
        await receive(client, admin, bad["id"], warehouse_id, "B-L", 300, "500",
                      unit_cost="20")
        customer_id = await create_customer(
            client, admin, name="عميل الخسارة", credit_limit="900000")
        await sell(client, admin, customer_id, warehouse_id, good["id"], "50")
        await sell(client, admin, customer_id, warehouse_id, bad["id"], "50")

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.PRODUCTS, measure=ParetoMeasure.PROFIT)

        ranked = [item for item in report.items if item.rank > 0]
        shares = [item.cumulative_share for item in ranked]
        assert shares == sorted(shares), "the curve must be monotonic"
        assert [item.code for item in ranked] == ["PROFIT-1"]
        # The loss-maker is not silently dropped from the report — it holds stock, so
        # it appears where unsold value belongs.
        loss = next(item for item in report.items if item.code == "LOSS-1")
        assert loss.abc_class == "D"
        assert loss.carrying_value > 0


class TestTheLongTailIsThePoint:
    async def test_stock_that_never_sold_gets_its_own_class(
        self, client: AsyncClient, db_session
    ) -> None:
        """Class D, which the textbooks do not have and this business needs.

        566 products in the seeded catalogue have never sold and hold 29.2M of stock.
        Inside class C they read as "low value"; as their own class they read as what
        they are — no value, at a cost.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id, _ = await four_customers(client, admin)
        silent = await create_product(
            client, admin, sku="SILENT-1", warehouse_id=warehouse_id)
        await receive(client, admin, silent["id"], warehouse_id, "B-SIL", 300,
                      "100", unit_cost="30")

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.PRODUCTS)
        row = next(item for item in report.items if item.code == "SILENT-1")
        assert row.abc_class == "D"
        assert row.value == Decimal("0")
        # No rank: an unsold product is not "last", it is outside the ranking.
        assert row.rank == 0
        assert row.carrying_value == Decimal("3000.00")
        assert row.last_activity is None

        d_class = next(c for c in report.classes if c.abc_class == "D")
        assert d_class.entities == 1
        assert d_class.carrying_value == Decimal("3000.00")

    async def test_entity_shares_across_classes_add_up_to_the_whole(
        self, client: AsyncClient, db_session
    ) -> None:
        """The bug this catches printed class D as 114% of the population.

        A share measured against a denominator that excludes its own numerator is
        not a share, and on a screen it simply reads as broken.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, _, _ = await four_customers(client, admin)
        for index in range(3):
            silent = await create_product(
                client, admin, sku=f"SIL-{index}", warehouse_id=warehouse_id)
            await receive(client, admin, silent["id"], warehouse_id, f"B-S{index}",
                          300, "10", unit_cost="5")

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.PRODUCTS)
        total = sum((c.entity_share for c in report.classes), Decimal("0"))
        assert abs(total - Decimal("100")) <= Decimal("0.05")

    async def test_the_carrying_column_is_what_makes_this_actionable(
        self, client: AsyncClient, db_session
    ) -> None:
        """Value ranked against cost held — the pairing is the whole report.

        A list of best sellers is a leaderboard. A best seller sitting beside the
        stock it ties up, next to a non-seller tying up more, is a decision.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن المقابلة")
        star = await create_product(
            client, admin, sku="STAR-1", warehouse_id=warehouse_id)
        hoard = await create_product(
            client, admin, sku="HOARD-1", warehouse_id=warehouse_id)
        await receive(client, admin, star["id"], warehouse_id, "B-ST", 300, "200",
                      unit_cost="4")
        await receive(client, admin, hoard["id"], warehouse_id, "B-HO", 300, "2000",
                      unit_cost="50")
        customer_id = await create_customer(
            client, admin, name="عميل المقابلة", credit_limit="900000")
        await sell(client, admin, customer_id, warehouse_id, star["id"], "100")

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.PRODUCTS)
        star_row = next(i for i in report.items if i.code == "STAR-1")
        hoard_row = next(i for i in report.items if i.code == "HOARD-1")

        assert star_row.abc_class == "A"
        assert star_row.share == Decimal("100.00")
        # Both sides pinned, not merely compared: an earlier version asserted only
        # that the hoard held more, which stayed true when the seller's own carrying
        # value was zeroed by mistake — a comparison passes happily against nothing.
        assert star_row.carrying_value == Decimal("400.00")     # 100 left × 4
        assert hoard_row.carrying_value == Decimal("100000.00")  # 2,000 × 50
        # The star makes every riyal of revenue and holds a fortieth of the stock.
        assert hoard_row.carrying_value > star_row.carrying_value * 40
        assert "تحتجز" in report.verdict


class TestItReadsTheDistributionHonestly:
    async def test_a_flat_distribution_is_reported_as_not_concentrated(
        self, client: AsyncClient, db_session
    ) -> None:
        """The answer a Pareto chart cannot give.

        On this book of business 80% of revenue takes 53% of customers and the
        largest account is 2.2%. Drawing the famous curve over that and calling it
        20/80 would be a story, not a finding — the correct advice is that there is
        no key-account tier here to build.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التساوي")
        product = await create_product(
            client, admin, sku="FLAT-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-FL", 300,
                      "5000", unit_cost="4")
        for index in range(10):
            customer_id = await create_customer(
                client, admin, name=f"عميل متساوٍ {index}", credit_limit="900000")
            await sell(client, admin, customer_id, warehouse_id, product["id"], "10")

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.CUSTOMERS)
        assert report.entities_for_80_percent == 8  # ten equal customers
        assert "غير مركّز" in report.verdict

    async def test_a_concentrated_distribution_says_so(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التركيز")
        product = await create_product(
            client, admin, sku="CONC-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-CO", 300,
                      "5000", unit_cost="4")
        # One whale and nine minnows.
        for index, quantity in enumerate(["500"] + ["5"] * 9):
            customer_id = await create_customer(
                client, admin, name=f"عميل مركّز {index}", credit_limit="900000")
            await sell(client, admin, customer_id, warehouse_id, product["id"],
                       quantity)

        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.CUSTOMERS)
        assert report.entities_for_80_percent == 1
        assert report.top_shares[1] > Decimal("80")
        assert "تركيز مرتفع" in report.verdict

    async def test_no_sales_in_the_window_says_so_instead_of_dividing_by_zero(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        report = await ParetoService(db_session).report(
            dimension=ParetoDimension.CUSTOMERS)
        assert report.entity_count == 0
        assert report.total_value == Decimal("0")
        assert report.verdict == "لا توجد مبيعات في هذه الفترة."


class TestTheWindowAndTheMeasure:
    async def test_the_date_window_excludes_older_sales(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الفترة")
        product = await create_product(
            client, admin, sku="WIN-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-WI", 300,
                      "1000", unit_cost="4")
        recent = await create_customer(
            client, admin, name="عميل حديث", credit_limit="900000")
        old = await create_customer(
            client, admin, name="عميل قديم", credit_limit="900000")
        await sell(client, admin, recent, warehouse_id, product["id"], "10")
        await sell(client, admin, old, warehouse_id, product["id"], "90",
                   on=date.today() - timedelta(days=200), db_session=db_session)

        service = ParetoService(db_session)
        everything = await service.report(dimension=ParetoDimension.CUSTOMERS)
        assert everything.entity_count == 2
        assert everything.items[0].name == "عميل قديم"

        window = await service.report(
            dimension=ParetoDimension.CUSTOMERS,
            date_from=date.today() - timedelta(days=30))
        assert window.entity_count == 1
        assert window.items[0].name == "عميل حديث"
        # The excluded customer still shows a last-activity date: on a silent row the
        # question is how long it has been silent, which a clipped date cannot say.
        clipped = next(
            (i for i in window.items if i.name == "عميل قديم"), None)
        if clipped is not None:
            assert clipped.last_activity is not None

    async def test_profit_reorders_what_revenue_ranked(
        self, client: AsyncClient, db_session
    ) -> None:
        """A high-revenue, thin-margin line is not the best product in the catalogue.

        The two measures existing separately is the point: sorted by revenue the
        cheap bulk line wins, and a buyer chasing it discovers at the year end that
        it earned nothing.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الهامش")
        thin = await create_product(
            client, admin, sku="THIN-1", warehouse_id=warehouse_id)
        fat = await create_product(
            client, admin, sku="FAT-1", warehouse_id=warehouse_id)
        await receive(client, admin, thin["id"], warehouse_id, "B-TH", 300, "1000",
                      unit_cost="10")   # 0.50 margin on 10.50
        await receive(client, admin, fat["id"], warehouse_id, "B-FA", 300, "1000",
                      unit_cost="2")    # 8.50 margin
        customer_id = await create_customer(
            client, admin, name="عميل الهامش", credit_limit="900000")
        await sell(client, admin, customer_id, warehouse_id, thin["id"], "100")
        await sell(client, admin, customer_id, warehouse_id, fat["id"], "20")

        service = ParetoService(db_session)
        by_revenue = await service.report(
            dimension=ParetoDimension.PRODUCTS, measure=ParetoMeasure.REVENUE)
        by_profit = await service.report(
            dimension=ParetoDimension.PRODUCTS, measure=ParetoMeasure.PROFIT)

        assert by_revenue.items[0].code == "THIN-1"   # 1,050 of revenue
        assert by_profit.items[0].code == "FAT-1"     # 170 of margin against 50


class TestTheEndpoint:
    async def test_it_needs_the_analytics_permission(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(PARETO)
        assert response.status_code == 401

    async def test_it_serves_both_dimensions_and_measures(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await four_customers(client, admin)

        for dimension in ("customers", "products"):
            for measure in ("revenue", "profit"):
                response = await client.get(
                    PARETO, headers=admin,
                    params={"dimension": dimension, "measure": measure})
                assert response.status_code == 200, response.text
                data = response.json()["data"]
                assert data["dimension"] == dimension
                assert data["measure"] == measure
                assert data["verdict"]
                assert data["items"]

    async def test_an_unknown_dimension_is_refused(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get(
            PARETO, headers=admin, params={"dimension": "suppliers"})
        assert response.status_code == 422
