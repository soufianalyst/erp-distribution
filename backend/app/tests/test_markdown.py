"""Deciding what to do with stock that is running out of shelf life.

The seeded database holds 24.4 million of stock expiring inside sixty days, three
offers have ever been run, and nothing has ever been written off. So the goods are
not being cleared — they are being discovered, on the day they expire, by whoever
opens the fridge.

A discount engine is easy to write and easy to get quietly wrong, and the wrong
version is expensive in a way nobody notices: it discounts stock that would have
sold anyway. That is why the tests below spend most of their effort on the cases
where the right answer is *not* a markdown. A batch that will clear on its own must
be left alone. A product with no demand at all cannot be rescued by price — no
discount reaches a buyer who does not exist — so it gets a phone call if anyone has
ever bought it and an honest write-off if nobody has.

The other half is arithmetic that must not be approximated. The discount comes from
constant-elasticity demand, Q₂/Q₁ = (P₂/P₁)^e, and the elasticity behind it either
was measured from real offers or was not; a guess presented as a measurement is how
a 40% giveaway acquires the authority of a calculation.
"""

import math
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

from app.domain.models.inventory import ProductOffer
from app.domain.models.sales import SalesInvoice
from app.services.inventory.elasticity import (
    MIN_OBSERVATIONS,
    ElasticityService,
)
from app.services.inventory.markdown_service import (
    ASSUMED_ELASTICITY,
    MarkdownService,
)
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer, post_invoice


async def sell_on_days(
    client: AsyncClient, admin: dict, db_session, customer_id: int,
    warehouse_id: int, product_id: int, days_ago: list[int], quantity: str,
) -> None:
    """Invoices backdated onto given days, so demand has a history to read."""
    for offset in days_ago:
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product_id, quantity,
            tax_rate_ids=[])
        assert response.status_code == 201, response.text
        invoice = await db_session.get(SalesInvoice, response.json()["data"]["id"])
        invoice.invoice_date = date.today() - timedelta(days=offset)
    await db_session.commit()


async def expiring_stock(
    client: AsyncClient, admin: dict, *, sku: str, quantity: str,
    expiry_days: int = 40, unit_cost: str = "20",
) -> tuple[int, dict]:
    """A product holding one batch that expires inside the horizon."""
    warehouse_id = await create_warehouse(client, admin, f"مخزن {sku}")
    product = await create_product(client, admin, sku=sku, warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, f"B-{sku}",
                  expiry_days, quantity, unit_cost=unit_cost)
    return warehouse_id, product


def row_for(plan, sku: str):
    return next(item for item in plan.items if item.sku == sku)


class TestItRecommendsTheRightAction:
    async def test_a_batch_that_will_sell_itself_is_left_alone(
        self, client: AsyncClient, db_session
    ) -> None:
        """The restraint that pays for the feature.

        This batch is expiring, which is exactly what makes it tempting. It is also
        selling fast enough to be gone first. Discounting it would hand back margin
        on goods that were never at risk — the single most expensive mistake a
        markdown engine can make, because it looks like diligence.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="CLEAR-1", quantity="300", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="عميل السريع", credit_limit="900000")
        # 10 sale-days × 25 units in 90 days ≈ 2.8/day, so the 50 units left after
        # those sales are about eighteen days of trade against forty of shelf life.
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "25")

        plan = await MarkdownService(db_session).plan(horizon_days=60)
        row = row_for(plan, "CLEAR-1")
        assert row.action == "leave"
        assert row.surplus == Decimal("0")
        assert "سينفد قبل انتهاء صلاحيته" in row.reason

    async def test_a_slow_seller_with_a_surplus_gets_a_priced_markdown(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="SLOW-1", quantity="600", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="عميل البطيء", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        plan = await MarkdownService(db_session).plan(horizon_days=60)
        row = row_for(plan, "SLOW-1")
        assert row.action == "markdown"
        assert row.surplus > 0
        assert row.discount_percent > 0
        # The quoted new price is the old one less the quoted discount — the screen
        # shows both, and a mismatch between them is the customer's argument.
        expected = (row.price_before
                    * (Decimal("100") - row.discount_percent) / Decimal("100"))
        assert row.price_now == expected.quantize(Decimal("0.01"))
        assert row.recovery_value == (row.surplus * row.price_now).quantize(
            Decimal("0.01"))

    async def test_no_demand_but_a_past_buyer_is_a_phone_call_not_a_discount(
        self, client: AsyncClient, db_session
    ) -> None:
        """Price is the wrong lever when the problem is reach.

        This product sold once, long before the demand window. Cutting its price
        does nothing, because nobody is looking at it. The one shop that ever bought
        it is worth more than any discount, so the row names them.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="PUSH-1", quantity="200", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="بقالة الوفاء", credit_limit="900000")
        # 200 days ago: a real buyer, but outside the 90-day demand window.
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [200], "10")

        plan = await MarkdownService(db_session).plan(horizon_days=60)
        row = row_for(plan, "PUSH-1")
        assert row.action == "push"
        assert row.discount_percent is None
        assert [buyer.name for buyer in row.buyers] == ["بقالة الوفاء"]
        assert "اتصل بهم" in row.reason

    async def test_never_sold_and_never_bought_is_a_write_off(
        self, client: AsyncClient, db_session
    ) -> None:
        """The answer nobody wants, which is why it must be automatic.

        No discount reaches a buyer who does not exist. Naming the loss now is the
        only thing that stops the same product being reordered next month.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await expiring_stock(client, admin, sku="DEAD-1", quantity="150",
                             expiry_days=30, unit_cost="12")

        plan = await MarkdownService(db_session).plan(horizon_days=60)
        row = row_for(plan, "DEAD-1")
        assert row.action == "write_off"
        assert row.surplus == Decimal("150")
        assert row.surplus_value == Decimal("1800.00")
        assert plan.write_off_value >= Decimal("1800.00")

    async def test_stock_outside_the_horizon_is_not_in_the_plan(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await expiring_stock(client, admin, sku="FAR-1", quantity="100",
                             expiry_days=200)

        plan = await MarkdownService(db_session).plan(horizon_days=60)
        assert not [item for item in plan.items if item.sku == "FAR-1"]


class TestTheDiscountArithmetic:
    """The depth is derived, not chosen from a table of round numbers."""

    def test_it_is_the_cut_whose_uplift_just_clears_the_batch(self) -> None:
        # 200 units, 40 days, selling 2.5/day: needs 5/day, an uplift of 2×.
        discount = MarkdownService._discount_to_clear(
            Decimal("200"), Decimal("2.5"), 40, Decimal("-1.5"), Decimal("50"))
        # Q₂/Q₁ = (P₂/P₁)^e  ⇒  P₂/P₁ = 2^(1/-1.5) = 0.63
        expected = (1 - 2 ** (1 / -1.5)) * 100
        assert abs(float(discount) - expected) < 0.01

    def test_a_batch_pricing_cannot_save_is_capped_not_given_away(self) -> None:
        """A computed 90% is the model saying "this is unsalvageable".

        Obeying it literally would dump the stock at a fraction of cost and teach
        every customer to wait for the fire sale.
        """
        discount = MarkdownService._discount_to_clear(
            Decimal("5000"), Decimal("0.5"), 10, Decimal("-1.5"), Decimal("50"))
        assert discount == Decimal("50")

    def test_no_uplift_needed_means_no_discount(self) -> None:
        discount = MarkdownService._discount_to_clear(
            Decimal("50"), Decimal("10"), 40, Decimal("-1.5"), Decimal("50"))
        assert discount == Decimal("0")

    def test_a_more_responsive_product_needs_a_smaller_cut(self) -> None:
        """The elasticity has to actually move the answer.

        If a measured -3 produced the same discount as an assumed -1.5, the whole
        measurement exercise would be decoration.
        """
        args = (Decimal("200"), Decimal("2.5"), 40)
        stubborn = MarkdownService._discount_to_clear(
            *args, Decimal("-0.8"), Decimal("90"))
        responsive = MarkdownService._discount_to_clear(
            *args, Decimal("-3"), Decimal("90"))
        assert responsive < stubborn


class TestElasticityRefusesToGuess:
    async def test_too_little_history_returns_the_assumption_labelled(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="EL-NONE", quantity="600", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="عميل المرونة", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        measured = await ElasticityService(db_session).measure(ASSUMED_ELASTICITY)
        assert measured.source == "assumed"
        assert measured.value == ASSUMED_ELASTICITY
        assert measured.observations < MIN_OBSERVATIONS

        plan = await MarkdownService(db_session).plan(horizon_days=60)
        assert plan.elasticity.source == "assumed"
        # And it says so on the row, in the manager's own language, next to the
        # discount it produced — a guess is allowed, a guess in disguise is not.
        assert "مرونة مفترضة" in row_for(plan, "EL-NONE").reason

    async def test_enough_real_offers_replace_the_assumption(
        self, client: AsyncClient, db_session
    ) -> None:
        """Five past markdowns, each with sales either side, become one number."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        for index in range(MIN_OBSERVATIONS):
            sku = f"EL-{index}"
            warehouse_id, product = await expiring_stock(
                client, admin, sku=sku, quantity="1000", expiry_days=300)
            customer_id = await create_customer(
                client, admin, name=f"عميل {sku}", credit_limit="900000")
            # A 7-day offer 20 days ago, with the 7 days before it as the control.
            db_session.add(ProductOffer(
                product_id=product["id"],
                discount_percent=Decimal("20"),
                starts_on=date.today() - timedelta(days=20),
                ends_on=date.today() - timedelta(days=14),
                note="عرض سابق",
            ))
            await db_session.commit()
            await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                               product["id"], [24], "10")   # before: 10 units
            await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                               product["id"], [17], "15")   # during: 15 units

        measured = await ElasticityService(db_session).measure(ASSUMED_ELASTICITY)
        assert measured.source == "measured"
        assert measured.observations == MIN_OBSERVATIONS
        # ln(15/10) / ln(0.8)
        expected = math.log(1.5) / math.log(0.8)
        assert abs(float(measured.value) - expected) < 0.01

    async def test_a_two_day_offer_is_not_evidence(
        self, client: AsyncClient, db_session
    ) -> None:
        """Short windows measure the weekend, not the price.

        The sales below are deliberately shaped into a perfectly plausible reading —
        10 units before, 15 during, an elasticity of -1.82 that would sail through
        every other filter. The only thing standing between it and the catalogue's
        discount depth is the length rule, which is what this pins.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        for index in range(MIN_OBSERVATIONS):
            sku = f"BRIEF-{index}"
            warehouse_id, product = await expiring_stock(
                client, admin, sku=sku, quantity="1000", expiry_days=300)
            customer_id = await create_customer(
                client, admin, name=f"عميل {sku}", credit_limit="900000")
            db_session.add(ProductOffer(
                product_id=product["id"],
                discount_percent=Decimal("20"),
                starts_on=date.today() - timedelta(days=20),
                ends_on=date.today() - timedelta(days=19),
                note="عرض قصير",
            ))
            await db_session.commit()
            await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                               product["id"], [21], "10")   # control window
            await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                               product["id"], [20], "15")   # inside the short offer

        measured = await ElasticityService(db_session).measure(ASSUMED_ELASTICITY)
        assert measured.source == "assumed"
        assert measured.observations == 0


class TestApplyingThePlan:
    async def test_it_creates_an_offer_that_expires_with_its_batch(
        self, client: AsyncClient, db_session
    ) -> None:
        """An offer outliving its batch discounts fresh goods that never needed it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="APPLY-1", quantity="600", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="عميل التطبيق", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        service = MarkdownService(db_session)
        row = row_for(await service.plan(horizon_days=60), "APPLY-1")
        created, skipped, notes = await service.apply([row.batch_id], user_id=None)
        assert (created, skipped) == (1, 0), notes

        offer = (await db_session.execute(
            select(ProductOffer).where(ProductOffer.product_id == product["id"])
        )).scalar_one()
        assert offer.discount_percent == row.discount_percent
        assert offer.ends_on == row.expiry_date

    async def test_it_refuses_the_rows_that_are_not_markdowns(
        self, client: AsyncClient, db_session
    ) -> None:
        """A push needs a phone call and a write-off needs an accountant.

        Turning either into a silent discount is the engine pretending it solved
        something — and on a write-off row it would discount stock nobody buys at
        any price, converting a known loss into a smaller known loss plus a lie.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await expiring_stock(client, admin, sku="NOPE-1", quantity="150")

        service = MarkdownService(db_session)
        row = row_for(await service.plan(horizon_days=60), "NOPE-1")
        assert row.action == "write_off"

        created, skipped, notes = await service.apply([row.batch_id], user_id=None)
        assert (created, skipped) == (0, 1)
        assert "لا ينطبق عليه خصم" in notes[0]
        assert not (await db_session.execute(select(ProductOffer))).scalars().all()

    async def test_it_will_not_stack_a_second_offer_on_a_discounted_product(
        self, client: AsyncClient, db_session
    ) -> None:
        """Two live offers on one product is two prices for one thing.

        `create_invoice` reads the offers back to price the line, so a duplicate is
        not a cosmetic problem — it is an ambiguous bill.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="TWICE-1", quantity="600", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="عميل التكرار", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        service = MarkdownService(db_session)
        row = row_for(await service.plan(horizon_days=60), "TWICE-1")
        assert (await service.apply([row.batch_id], user_id=None))[0] == 1

        created, _, notes = await service.apply([row.batch_id], user_id=None)
        assert created == 0
        assert "عرض ساري بالفعل" in notes[0]
        offers = (await db_session.execute(
            select(ProductOffer).where(ProductOffer.product_id == product["id"])
        )).scalars().all()
        assert len(offers) == 1

    async def test_an_already_discounted_batch_says_so_on_the_next_plan(
        self, client: AsyncClient, db_session
    ) -> None:
        """Otherwise the same batch is proposed again every morning.

        The stock is still at risk, so the row belongs on the list — but the depth
        beside it was computed from a sales rate the running discount is already
        changing, and re-applying it only earns a rejection. The screen reads this
        field to drop the tick box.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="AGAIN-1", quantity="600", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="عميل التكرار الثاني", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        service = MarkdownService(db_session)
        row = row_for(await service.plan(horizon_days=60), "AGAIN-1")
        assert row.active_offer_percent is None
        await service.apply([row.batch_id], user_id=None)

        after = row_for(await service.plan(horizon_days=60), "AGAIN-1")
        assert after.active_offer_percent == row.discount_percent

    async def test_the_depth_is_recomputed_from_the_stock_as_it_stands(
        self, client: AsyncClient, db_session
    ) -> None:
        """The browser does not get to name the discount.

        Apply takes batch ids and nothing else. If it accepted a percentage from the
        page, a stale screen — or anyone with the developer console — would be
        setting the price a customer is charged.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="FRESH-1", quantity="600", expiry_days=40)
        customer_id = await create_customer(
            client, admin, name="عميل الحساب", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        service = MarkdownService(db_session)
        row = row_for(await service.plan(horizon_days=60), "FRESH-1")
        # Ask for a shallower cap than the plan was drawn with; the offer must obey
        # the cap in force at the moment of application.
        await service.apply([row.batch_id], user_id=None, max_discount=Decimal("10"))

        offer = (await db_session.execute(
            select(ProductOffer).where(ProductOffer.product_id == product["id"])
        )).scalar_one()
        assert offer.discount_percent == Decimal("10.00")
        assert offer.discount_percent < row.discount_percent


class TestItSpeaksArabic:
    """Counted nouns, because "تم إنشاء 1 عرضاً" tells a user who this was built for.

    Arabic inflects a noun by its count, and an f-string does not. Every message
    below eleven reads as broken without this.
    """

    def test_the_offer_count_is_inflected(self) -> None:
        from app.api.v1.inventory import _offers

        assert _offers(1) == "عرض واحد"
        assert _offers(2) == "عرضين"
        assert _offers(3) == "3 عروض"
        assert _offers(10) == "10 عروض"
        assert _offers(11) == "11 عرضاً"


class TestTheEndpoint:
    async def test_the_plan_is_gated_on_the_offers_permission(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/v1/inventory/markdown-plan")
        assert response.status_code == 401

    async def test_it_returns_totals_and_rows(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await expiring_stock(client, admin, sku="HTTP-1", quantity="150",
                             expiry_days=30, unit_cost="12")

        response = await client.get(
            "/api/v1/inventory/markdown-plan?horizon_days=60", headers=admin)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["elasticity_source"] == "assumed"
        assert Decimal(data["stock_at_risk"]) >= Decimal("1800")
        row = next(item for item in data["items"] if item["sku"] == "HTTP-1")
        assert row["action"] == "write_off"
        assert row["buyers"] == []


class TestTheCeilingIsCompanyPolicy:
    """How deep a discount may go is not the browser's decision.

    The cap started life as a query parameter defaulting to 50, which meant the
    deepest markdown the engine could ever propose — on prices customers are
    actually charged — was whatever number last arrived in a query string. It is now
    a company setting, and a request may only ask for something gentler.
    """

    async def test_a_request_deeper_than_policy_is_clamped(
        self, client: AsyncClient, db_session
    ) -> None:
        from app.services.settings.settings_service import SettingsService

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        company = await SettingsService(db_session).get_company_settings()
        company.markdown_max_discount_percent = Decimal("15")
        await db_session.commit()

        warehouse_id, product = await expiring_stock(
            client, admin, sku="CAP-1", quantity="900", expiry_days=30)
        customer_id = await create_customer(
            client, admin, name="عميل السقف", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        # Asking for 90% must not get 90%.
        response = await client.get(
            "/api/v1/inventory/markdown-plan",
            headers=admin, params={"horizon_days": 60, "max_discount": "90"})
        assert response.status_code == 200, response.text
        row = next(
            item for item in response.json()["data"]["items"]
            if item["sku"] == "CAP-1"
        )
        assert Decimal(row["discount_percent"]) == Decimal("15.00")

    async def test_a_shallower_request_is_honoured(
        self, client: AsyncClient, db_session
    ) -> None:
        """Policy is a ceiling, not a target — a manager may still go gentler."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await expiring_stock(
            client, admin, sku="CAP-2", quantity="900", expiry_days=30)
        customer_id = await create_customer(
            client, admin, name="عميل السقف الثاني", credit_limit="900000")
        await sell_on_days(client, admin, db_session, customer_id, warehouse_id,
                           product["id"], [7 * (i + 1) for i in range(10)], "5")

        response = await client.get(
            "/api/v1/inventory/markdown-plan",
            headers=admin, params={"horizon_days": 60, "max_discount": "8"})
        row = next(
            item for item in response.json()["data"]["items"]
            if item["sku"] == "CAP-2"
        )
        assert Decimal(row["discount_percent"]) == Decimal("8.00")
