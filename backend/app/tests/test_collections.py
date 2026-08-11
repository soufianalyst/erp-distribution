"""Chasing debt: the worklist, the promises, and the block the credit limit cannot be.

Measured on the seeded database before any of this was written: 114,668 past ninety
days across 189 invoices, against 4,086 sitting in the 31-60 and 61-90 buckets
combined. Debt here does not age — it is paid inside a month or it is abandoned, and
an empty middle bucket is what a missing collections process looks like in data.

Two claims are worth testing hard.

**Ranking is the product.** A list of debtors sorted by size is the aging report with
a different heading. The order here is overdue amount weighted by age, so a large
recent debt — still collectable — outranks a small ancient one that is really a
write-off waiting to be admitted. Get the ordering wrong and nobody works the list.

**A promise is checked against money, not against itself.** Whether a customer kept
their word is derived from payments received, never stored. A stored flag is a second
opinion about something the ledger already knows, and the two diverge the first time a
shop pays cash to a driver.

The credit block gets its own class because it is the part that stops the bleeding.
Every one of the worst debtors on this database is *under* their 25,000 credit limit
while a year overdue: a limit measures how much is owed and can say nothing about how
long, so it passed them every time.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient

from app.domain.models.sales import (
    CollectionActivity,
    CollectionOutcome,
    CustomerPayment,
    SalesInvoice,
)
from app.services.settings.settings_service import SettingsService
from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer, post_invoice

WORKLIST = "/api/v1/sales/collections/worklist"


async def stocked(client: AsyncClient, admin: dict, sku: str) -> tuple[int, int]:
    warehouse_id = await create_warehouse(client, admin, f"مخزن {sku}")
    product = await create_product(client, admin, sku=sku, warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, f"B-{sku}", 300, "9000",
                  unit_cost="4")
    return warehouse_id, product["id"]


async def owes(
    client: AsyncClient, admin: dict, db_session, *, name: str, warehouse_id: int,
    product_id: int, quantity: str, days_ago: int, credit_limit: str = "900000",
) -> int:
    """A customer with one unpaid credit invoice, aged by backdating it."""
    customer_id = await create_customer(
        client, admin, name=name, credit_limit=credit_limit)
    response = await post_invoice(
        client, admin, customer_id, warehouse_id, product_id, quantity,
        payment_method="credit", tax_rate_ids=[])
    assert response.status_code == 201, response.text
    invoice = await db_session.get(SalesInvoice, response.json()["data"]["id"])
    invoice.invoice_date = date.today() - timedelta(days=days_ago)
    await db_session.commit()
    return customer_id


def find(items: list[dict], name: str) -> dict | None:
    return next((i for i in items if i["name"] == name), None)


class TestTheOrderIsTheProduct:
    async def test_a_large_recent_debt_outranks_a_small_ancient_one(
        self, client: AsyncClient, db_session
    ) -> None:
        """Sorted by size it is the aging report; sorted by age it is a graveyard.

        Overdue amount weighted by age puts the calls that still recover money first.
        The ancient trickle is a write-off to be admitted, not a morning's work.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "COLL-1")
        await owes(client, admin, db_session, name="متجر الكبير الحديث",
                   warehouse_id=warehouse_id, product_id=product_id,
                   quantity="400", days_ago=45)
        await owes(client, admin, db_session, name="بقالة الصغير القديم",
                   warehouse_id=warehouse_id, product_id=product_id,
                   quantity="4", days_ago=400)

        items = (await client.get(WORKLIST, headers=admin)).json()["data"]["items"]
        assert [i["name"] for i in items[:2]] == [
            "متجر الكبير الحديث", "بقالة الصغير القديم"
        ]

    async def test_age_actually_moves_the_order_not_just_the_display(
        self, client: AsyncClient, db_session
    ) -> None:
        """The case where size and priority disagree.

        The test above proves the ranking is not age alone; this one proves it is not
        amount alone, which the first could not — there the bigger debt was also the
        higher-priority one, so a plain sort by amount would have passed it happily.

        Here the smaller debt is five times older, and weighting puts it first:
        525 × 200 days beats 1,050 × 40.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "COLL-5")
        await owes(client, admin, db_session, name="دين أكبر وأحدث",
                   warehouse_id=warehouse_id, product_id=product_id,
                   quantity="100", days_ago=40)
        await owes(client, admin, db_session, name="دين أصغر وأقدم بكثير",
                   warehouse_id=warehouse_id, product_id=product_id,
                   quantity="50", days_ago=200)

        items = (await client.get(WORKLIST, headers=admin)).json()["data"]["items"]
        assert [i["name"] for i in items[:2]] == [
            "دين أصغر وأقدم بكثير", "دين أكبر وأحدث"
        ]
        # And the smaller one really is smaller, so this cannot pass by amount.
        assert Decimal(items[0]["overdue"]) < Decimal(items[1]["overdue"])

    async def test_debt_inside_the_grace_window_is_not_on_the_list(
        self, client: AsyncClient, db_session
    ) -> None:
        """Trade credit doing its job is not a collections problem."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "COLL-2")
        await owes(client, admin, db_session, name="عميل حديث العهد",
                   warehouse_id=warehouse_id, product_id=product_id,
                   quantity="50", days_ago=10)

        data = (await client.get(WORKLIST, headers=admin)).json()["data"]
        assert find(data["items"], "عميل حديث العهد") is None
        # The money is still counted as outstanding — it is simply not overdue.
        assert Decimal(data["total_outstanding"]) > 0
        assert Decimal(data["total_overdue"]) == 0

    async def test_never_contacted_is_its_own_answer(
        self, client: AsyncClient, db_session
    ) -> None:
        """47 of 47 debtors were in this state when the feature was written.

        A blank "last contacted" column reads as missing data. Counting it as a state
        turns it into the finding it actually is: nobody has rung any of them.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "COLL-3")
        await owes(client, admin, db_session, name="عميل منسي",
                   warehouse_id=warehouse_id, product_id=product_id,
                   quantity="100", days_ago=120)

        data = (await client.get(WORKLIST, headers=admin)).json()["data"]
        row = find(data["items"], "عميل منسي")
        assert row["last_contact"] is None
        assert data["never_contacted"] == 1
        assert "لم يُتصل به إطلاقاً" in row["reason"]

    async def test_the_buckets_split_the_balance_by_age(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "COLL-4")
        customer_id = await owes(
            client, admin, db_session, name="عميل الشرائح",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=120)
        # A second, recent invoice for the same customer.
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "10",
            payment_method="credit", tax_rate_ids=[])
        assert response.status_code == 201, response.text

        row = find((await client.get(WORKLIST, headers=admin)).json()["data"]["items"],
                   "عميل الشرائح")
        assert row["invoice_count"] == 2
        assert Decimal(row["buckets"]["d90_plus"]) > 0
        assert Decimal(row["buckets"]["current"]) > 0
        # Only the aged part is overdue; the fresh invoice is not being chased.
        assert Decimal(row["overdue"]) == Decimal(row["buckets"]["d90_plus"])
        assert Decimal(row["balance"]) > Decimal(row["overdue"])


class TestPromisesAreCheckedAgainstMoney:
    async def test_a_promise_needs_an_amount_and_a_date(
        self, client: AsyncClient, db_session
    ) -> None:
        """Otherwise there is nothing to check it against, and it is just a note."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-1")
        customer_id = await owes(
            client, admin, db_session, name="عميل الوعد الناقص",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        response = await client.post(
            f"/api/v1/sales/customers/{customer_id}/collections",
            headers=admin, json={"outcome": "promised", "note": "قال سيدفع"})
        assert response.status_code == 400
        assert "مبلغاً وتاريخاً" in response.json()["message"]

    async def test_a_promise_dated_in_the_past_is_refused(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-2")
        customer_id = await owes(
            client, admin, db_session, name="عميل الوعد الماضي",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        response = await client.post(
            f"/api/v1/sales/customers/{customer_id}/collections",
            headers=admin,
            json={
                "outcome": "promised", "promised_amount": "500",
                "promised_on": str(date.today() - timedelta(days=1)),
            })
        assert response.status_code == 400

    async def test_a_promise_not_yet_due_is_open_and_says_so(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-3")
        customer_id = await owes(
            client, admin, db_session, name="عميل الوعد المفتوح",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        due = date.today() + timedelta(days=5)
        response = await client.post(
            f"/api/v1/sales/customers/{customer_id}/collections",
            headers=admin,
            json={"outcome": "promised", "promised_amount": "500",
                  "promised_on": str(due)})
        assert response.status_code == 201, response.text

        row = find((await client.get(WORKLIST, headers=admin)).json()["data"]["items"],
                   "عميل الوعد المفتوح")
        assert row["promise"]["state"] == "open"
        assert row["promise"]["due_on"] == str(due)
        assert "لم يحن موعده بعد" in row["reason"]

    async def test_a_payment_that_covers_the_promise_marks_it_kept(
        self, client: AsyncClient, db_session
    ) -> None:
        """Read from the payments, so a promise cannot be marked kept by hand."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-4")
        customer_id = await owes(
            client, admin, db_session, name="عميل يفي بوعده",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        await client.post(
            f"/api/v1/sales/customers/{customer_id}/collections",
            headers=admin,
            json={"outcome": "promised", "promised_amount": "500",
                  "promised_on": str(date.today() + timedelta(days=3))})
        db_session.add(CustomerPayment(
            customer_id=customer_id, amount=Decimal("500"),
            payment_date=date.today(), method="cash"))
        await db_session.commit()

        row = find((await client.get(WORKLIST, headers=admin)).json()["data"]["items"],
                   "عميل يفي بوعده")
        assert row["promise"]["state"] == "kept"
        assert Decimal(row["promise"]["paid_since"]) == Decimal("500.00")

    async def test_a_part_payment_shows_progress_without_counting_as_kept(
        self, client: AsyncClient, db_session
    ) -> None:
        """Half of what was promised is not a kept promise, but it is not nothing.

        Showing the part-payment beside the promise is what stops the caller opening
        with "you promised 500 and paid nothing" to someone who paid 300.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-5")
        customer_id = await owes(
            client, admin, db_session, name="عميل يدفع بعضاً",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        await client.post(
            f"/api/v1/sales/customers/{customer_id}/collections",
            headers=admin,
            json={"outcome": "promised", "promised_amount": "500",
                  "promised_on": str(date.today() + timedelta(days=3))})
        db_session.add(CustomerPayment(
            customer_id=customer_id, amount=Decimal("300"),
            payment_date=date.today(), method="cash"))
        await db_session.commit()

        row = find((await client.get(WORKLIST, headers=admin)).json()["data"]["items"],
                   "عميل يدفع بعضاً")
        assert row["promise"]["state"] == "open"
        assert Decimal(row["promise"]["paid_since"]) == Decimal("300.00")

    async def test_a_promise_past_its_date_with_no_payment_is_broken(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-6")
        customer_id = await owes(
            client, admin, db_session, name="عميل أخلف وعده",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        # Written directly: the API refuses a past date, which is the point of it.
        db_session.add(CollectionActivity(
            customer_id=customer_id, outcome=CollectionOutcome.PROMISED,
            promised_amount=Decimal("500"),
            promised_on=date.today() - timedelta(days=10),
            created_at=datetime.now(timezone.utc) - timedelta(days=20),
        ))
        await db_session.commit()

        data = (await client.get(WORKLIST, headers=admin)).json()["data"]
        row = find(data["items"], "عميل أخلف وعده")
        assert row["promise"]["state"] == "broken"
        assert data["broken_promises"] == 1
        assert "ولم يصل المبلغ" in row["reason"]

    async def test_the_grace_period_protects_a_promise_due_today(
        self, client: AsyncClient, db_session
    ) -> None:
        """Shops pay on the day; the receipt is keyed in the morning after.

        Failing them at midnight would fill the broken list with clerical lag and
        teach everyone to ignore it.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-7")
        customer_id = await owes(
            client, admin, db_session, name="عميل وعده اليوم",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        db_session.add(CollectionActivity(
            customer_id=customer_id, outcome=CollectionOutcome.PROMISED,
            promised_amount=Decimal("500"), promised_on=date.today(),
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        ))
        await db_session.commit()

        row = find((await client.get(WORKLIST, headers=admin)).json()["data"]["items"],
                   "عميل وعده اليوم")
        assert row["promise"]["state"] == "open"

    async def test_a_non_promise_outcome_cannot_smuggle_promise_fields(
        self, client: AsyncClient, db_session
    ) -> None:
        """A "no answer" carrying a date would be a promise nobody made."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "PROM-8")
        customer_id = await owes(
            client, admin, db_session, name="عميل لا يرد",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=90)

        response = await client.post(
            f"/api/v1/sales/customers/{customer_id}/collections",
            headers=admin,
            json={"outcome": "no_answer", "promised_amount": "500",
                  "promised_on": str(date.today() + timedelta(days=3))})
        assert response.status_code == 201
        body = response.json()["data"]
        assert body["promised_amount"] is None
        assert body["promised_on"] is None


class TestTheBlockTheCreditLimitCannotBe:
    """A limit measures how much is owed. It cannot see how long.

    On the seeded book every worst debtor is under a 25,000 limit while sitting a
    year overdue, and one was sold to on credit two days before this was written.
    """

    async def test_it_is_off_until_somebody_turns_it_on(
        self, client: AsyncClient, db_session
    ) -> None:
        """Shipping this on by default would stop sales on somebody's behalf."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "BLK-1")
        customer_id = await owes(
            client, admin, db_session, name="عميل متأخر جداً",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=400)

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "5",
            payment_method="credit", tax_rate_ids=[])
        assert response.status_code == 201, response.text

    async def test_it_refuses_a_credit_sale_over_the_age_threshold(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        company = await SettingsService(db_session).get_company_settings()
        company.credit_block_after_days = 90
        await db_session.commit()

        warehouse_id, product_id = await stocked(client, admin, "BLK-2")
        customer_id = await owes(
            client, admin, db_session, name="عميل يجب إيقافه",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=200, credit_limit="900000")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "5",
            payment_method="credit", tax_rate_ids=[])
        assert response.status_code == 400
        message = response.json()["message"]
        assert "200 يوماً" in message and "90 يوماً" in message

    async def test_the_block_is_about_age_not_size(
        self, client: AsyncClient, db_session
    ) -> None:
        """The whole reason it exists.

        This customer is far inside a generous credit limit, so the limit check
        passes without comment — exactly as it did for every real debtor on this
        database. Only the age gate stops the sale.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        company = await SettingsService(db_session).get_company_settings()
        company.credit_block_after_days = 90
        await db_session.commit()

        warehouse_id, product_id = await stocked(client, admin, "BLK-3")
        customer_id = await owes(
            client, admin, db_session, name="عميل تحت الحد ومتأخر",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="2", days_ago=365, credit_limit="900000")

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "1",
            payment_method="credit", tax_rate_ids=[])
        assert response.status_code == 400

    async def test_a_cash_sale_is_never_blocked(
        self, client: AsyncClient, db_session
    ) -> None:
        """Refusing cash from someone who owes money would be a strange way to collect it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        company = await SettingsService(db_session).get_company_settings()
        company.credit_block_after_days = 90
        await db_session.commit()

        warehouse_id, product_id = await stocked(client, admin, "BLK-4")
        customer_id = await owes(
            client, admin, db_session, name="عميل يدفع نقداً",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=300)

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "5",
            payment_method="cash", tax_rate_ids=[])
        assert response.status_code == 201, response.text

    async def test_a_manager_may_override_it(
        self, client: AsyncClient, db_session
    ) -> None:
        """The same flag and permission as the limit.

        Inventing a second override would mean two ways to say the same yes, and a
        manager who approved one blocked sale would be surprised by the other.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        company = await SettingsService(db_session).get_company_settings()
        company.credit_block_after_days = 90
        await db_session.commit()

        warehouse_id, product_id = await stocked(client, admin, "BLK-5")
        customer_id = await owes(
            client, admin, db_session, name="عميل بموافقة المدير",
            warehouse_id=warehouse_id, product_id=product_id,
            quantity="100", days_ago=300)

        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "5",
            payment_method="credit", credit_override=True, tax_rate_ids=[])
        assert response.status_code == 201, response.text

    async def test_a_salesman_cannot_override_it_himself(
        self, client: AsyncClient, db_session
    ) -> None:
        """Otherwise the block is a checkbox on the form of the person it constrains."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        company = await SettingsService(db_session).get_company_settings()
        company.credit_block_after_days = 90
        await db_session.commit()

        warehouse_id, product_id = await stocked(client, admin, "BLK-6")
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        me = (await client.get("/api/v1/auth/me", headers=sales)).json()["data"]
        # His own shop, so the only thing standing between him and the sale is the
        # age gate — not the separate rule about invoicing other reps' customers.
        customer_id = await create_customer(
            client, admin, name="عميل مندوب متأخر", credit_limit="900000",
            salesman_id=me["id"])
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, "100",
            payment_method="credit", tax_rate_ids=[])
        invoice = await db_session.get(SalesInvoice, response.json()["data"]["id"])
        invoice.invoice_date = date.today() - timedelta(days=300)
        await db_session.commit()

        response = await post_invoice(
            client, sales, customer_id, warehouse_id, product_id, "5",
            payment_method="credit", credit_override=True, tax_rate_ids=[])
        assert response.status_code == 400


class TestWhoSeesWhichDebts:
    async def test_a_salesman_chases_only_his_own_shops(
        self, client: AsyncClient, db_session
    ) -> None:
        """Two people ringing about one debt is worse than nobody ringing.

        Same scoping rule the customer list already applies, so a rep's worklist and
        his customer list cannot disagree about whose shop it is.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        me = (await client.get("/api/v1/auth/me", headers=sales)).json()["data"]

        warehouse_id, product_id = await stocked(client, admin, "SCOPE-1")
        mine = await create_customer(
            client, admin, name="شوب المندوب", credit_limit="900000",
            salesman_id=me["id"])
        response = await post_invoice(
            client, admin, mine, warehouse_id, product_id, "100",
            payment_method="credit", tax_rate_ids=[])
        invoice = await db_session.get(SalesInvoice, response.json()["data"]["id"])
        invoice.invoice_date = date.today() - timedelta(days=120)
        await db_session.commit()

        await owes(client, admin, db_session, name="شوب غيره",
                   warehouse_id=warehouse_id, product_id=product_id,
                   quantity="100", days_ago=120)

        seen = [i["name"] for i in
                (await client.get(WORKLIST, headers=sales)).json()["data"]["items"]]
        assert "شوب المندوب" in seen
        assert "شوب غيره" not in seen

        # The accountant works the whole book.
        everyone = [i["name"] for i in
                    (await client.get(WORKLIST, headers=admin)).json()["data"]["items"]]
        assert {"شوب المندوب", "شوب غيره"} <= set(everyone)

    async def test_the_worklist_needs_the_collections_permission(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(WORKLIST)
        assert response.status_code == 401
