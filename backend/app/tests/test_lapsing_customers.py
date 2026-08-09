"""Shops that went quiet, measured against their own rhythm.

The single claim worth testing is that the yardstick is per-customer. A fixed
threshold is wrong twice over: it never fires for the hotel that orders quarterly,
and it fires far too late for the grocery that orders twice a week — by which point
they are buying elsewhere.

So the tests build two customers with deliberately different rhythms and the same
silence, and require the detector to disagree about them.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.domain.models.sales import SalesInvoice
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_sales import create_customer, post_invoice, setup_stocked_catalog

LAPSING = "/api/v1/analytics/customers/lapsing"


async def order_history(
    client: AsyncClient, admin: dict, db_session, customer_id: int,
    warehouse_id: int, product_id: int, days_ago: list[int]
) -> None:
    """Place invoices and backdate them.

    Backdated directly because the pricing path stamps today; the detector reads
    `invoice_date`, so that is the field the history has to live in.
    """
    for offset in days_ago:
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "1")
        assert response.status_code == 201, response.text
        invoice_id = response.json()["data"]["id"]
        invoice = await db_session.get(SalesInvoice, invoice_id)
        invoice.invoice_date = date.today() - timedelta(days=offset)
    await db_session.commit()


def find(items: list[dict], customer_id: int) -> dict | None:
    return next((i for i in items if i["customer_id"] == customer_id), None)


class TestTheYardstickIsPerCustomer:
    async def test_a_frequent_buyer_and_a_rare_one_are_judged_differently(
        self, client: AsyncClient, db_session
    ) -> None:
        """The whole point, in one test.

        Both have been silent 21 days. For the shop that orders every 3 days that is
        seven of its own cycles and a crisis; for the one that orders every 60 it is
        early. A single company-wide threshold cannot express that, which is why this
        does not use one.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)

        frequent = await create_customer(client, admin, name="بقالة يومية",
                                         credit_limit="90000")
        rare = await create_customer(client, admin, name="فندق فصلي",
                                     credit_limit="90000")

        # Every ~3 days, then silent 21.
        await order_history(client, admin, db_session, frequent, warehouse_id,
                            product["id"], [33, 30, 27, 24, 21])
        # Every ~60 days, then silent 21.
        await order_history(client, admin, db_session, rare, warehouse_id,
                            product["id"], [141, 81, 21])

        data = (await client.get(LAPSING, headers=admin)).json()["data"]

        assert find(data["items"], frequent) is not None, (
            "a shop silent seven of its own cycles was not flagged"
        )
        assert find(data["items"], rare) is None, (
            "a quarterly buyer was flagged after three weeks"
        )

    async def test_a_customer_ordering_normally_is_not_flagged(
        self, client: AsyncClient, db_session
    ) -> None:
        """A detector that fires on healthy customers gets switched off."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        healthy = await create_customer(client, admin, name="بقالة منتظمة",
                                        credit_limit="90000")
        await order_history(client, admin, db_session, healthy, warehouse_id,
                            product["id"], [21, 14, 7, 2])

        data = (await client.get(LAPSING, headers=admin)).json()["data"]
        assert find(data["items"], healthy) is None


class TestItRefusesToGuess:
    async def test_a_customer_with_too_little_history_is_left_alone(
        self, client: AsyncClient, db_session
    ) -> None:
        """One order establishes no rhythm, so there is nothing to be late against.

        Flagging them would be inventing a expectation the customer never set.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        new_customer = await create_customer(client, admin, name="عميل جديد جداً",
                                             credit_limit="90000")
        await order_history(client, admin, db_session, new_customer, warehouse_id,
                            product["id"], [60])

        data = (await client.get(LAPSING, headers=admin)).json()["data"]
        assert find(data["items"], new_customer) is None

    async def test_a_few_days_silence_never_counts(
        self, client: AsyncClient, db_session
    ) -> None:
        """A shop that orders daily is not lost on Thursday.

        Without a floor, a one-day median makes three days of quiet look like a 3×
        lapse — and the list fills with people who ordered this week.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        daily = await create_customer(client, admin, name="بقالة كل يوم",
                                      credit_limit="90000")
        await order_history(client, admin, db_session, daily, warehouse_id,
                            product["id"], [6, 5, 4, 3])

        data = (await client.get(LAPSING, headers=admin)).json()["data"]
        assert find(data["items"], daily) is None


class TestRanking:
    async def test_the_list_is_ordered_by_what_is_at_stake(
        self, client: AsyncClient
    ) -> None:
        """Ranked by value, not by who is latest. A shop worth 200 a year being ten
        times overdue matters less than one worth 90,000 being three times."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        data = (await client.get(LAPSING, headers=admin)).json()["data"]
        values = [Decimal(i["annual_value"]) for i in data["items"]]
        assert values == sorted(values, reverse=True)

    async def test_each_row_names_the_rep_who_should_call(
        self, client: AsyncClient
    ) -> None:
        """A worklist that does not say whose job it is becomes nobody's."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        data = (await client.get(LAPSING, headers=admin)).json()["data"]
        for item in data["items"]:
            assert "salesman_name" in item
            assert "phone" in item
            # The reasoning, so the rep can disagree with the flag.
            assert Decimal(item["overdue_multiple"]) >= Decimal("3")
            assert item["silent_days"] >= 7
