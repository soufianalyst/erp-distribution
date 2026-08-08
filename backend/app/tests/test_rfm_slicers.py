"""Filtering the two RFM reports: customers by product, products by customer.

RFM answers "who matters" and "what matters". Unfiltered, both answer it across the
whole business, which is the wrong grain for two questions a distributor asks daily:
*who buys this product* (before pushing a promotion or dropping the line), and *what
does this customer buy* (before a rep walks in with a suggestion).

The filters have to narrow all three scores together. A report that answered "who buys
olive oil" with the date each customer last bought *anything* would be worse than no
filter at all, because it looks right. So the tests below check recency and frequency
alongside the money, and check the money is netted by returns of the same product.

They also pin the window bug the filter work uncovered: the outer join let sales older
than the rolling window into the frequency and the money while the recency correctly
ignored them, so a product could read "never sold" and still carry revenue.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_analytics import backdate_invoice
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    receive,
)
from app.tests.test_sales import create_customer, post_invoice


async def _customer_rfm(client, headers, product_id=None):
    params = {} if product_id is None else {"product_id": product_id}
    response = await client.get(
        "/api/v1/analytics/customers/rfm", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _product_rfm(client, headers, customer_id=None):
    params = {} if customer_id is None else {"customer_id": customer_id}
    response = await client.get(
        "/api/v1/analytics/products/rfm", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _row(rows, key, value):
    return next(r for r in rows if r[key] == value)


class TestCustomerRfmByProduct:
    async def test_all_three_scores_narrow_to_the_chosen_product(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The money, the count and the date must all describe the same product.

        Set up so a wrong implementation is visibly wrong: the customer bought the
        target product once, long ago, and something else twice, recently. Anything
        that leaks the other product shows frequency 3 or a recency near zero.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التصفية")
        target = await create_product(
            client, admin, "SLICE-TARGET", warehouse_id=warehouse_id
        )
        other = await create_product(
            client, admin, "SLICE-OTHER", warehouse_id=warehouse_id
        )
        await receive(client, admin, target["id"], warehouse_id, "ST-1", 200, "500")
        await receive(client, admin, other["id"], warehouse_id, "SO-1", 200, "500")
        customer_id = await create_customer(
            client, admin, name="عميل التصفية", credit_limit="99999"
        )

        old = await post_invoice(
            client, admin, customer_id, warehouse_id, target["id"], "10", "credit"
        )
        assert old.status_code == 201, old.text
        await backdate_invoice(
            db_session, old.json()["data"]["id"], date.today() - timedelta(days=120)
        )
        for _ in range(2):
            recent = await post_invoice(
                client, admin, customer_id, warehouse_id, other["id"], "5", "credit"
            )
            assert recent.status_code == 201, recent.text

        unfiltered = _row(
            await _customer_rfm(client, admin), "customer_id", customer_id
        )
        assert unfiltered["frequency"] == 3
        assert unfiltered["recency_days"] == 0

        filtered = _row(
            await _customer_rfm(client, admin, target["id"]),
            "customer_id",
            customer_id,
        )
        assert filtered["frequency"] == 1, "counted invoices without the product"
        assert filtered["recency_days"] == 120, "dated the wrong purchase"
        assert as_decimal(filtered["monetary"]) > 0
        assert as_decimal(filtered["monetary"]) < as_decimal(unfiltered["monetary"])

    async def test_a_customer_who_never_bought_it_stays_in_the_list_at_zero(
        self, client: AsyncClient
    ) -> None:
        """Filtered by product, the report is also the prospect list."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن الاستهداف")
        sold = await create_product(client, admin, "PROS-A", warehouse_id=warehouse_id)
        never = await create_product(client, admin, "PROS-B", warehouse_id=warehouse_id)
        await receive(client, admin, sold["id"], warehouse_id, "PA-1", 200, "100")
        await receive(client, admin, never["id"], warehouse_id, "PB-1", 200, "100")
        customer_id = await create_customer(
            client, admin, name="عميل مستهدف", credit_limit="9999"
        )
        await post_invoice(
            client, admin, customer_id, warehouse_id, sold["id"], "5", "credit"
        )

        rows = await _customer_rfm(client, admin, never["id"])
        row = _row(rows, "customer_id", customer_id)
        assert row["frequency"] == 0
        assert row["recency_days"] is None
        assert as_decimal(row["monetary"]) == Decimal("0")
        assert row["segment"] == "لم يشترِ بعد"

    async def test_a_return_of_that_product_reduces_that_product_s_value(
        self, client: AsyncClient
    ) -> None:
        """Returns must net on the same basis as the sales they reverse.

        Crediting a whole invoice against one product's revenue would let a customer
        who returned an unrelated item look like they had never bought this one.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن مرتجع التصفية")
        target = await create_product(
            client, admin, "SR-TARGET", warehouse_id=warehouse_id
        )
        other = await create_product(
            client, admin, "SR-OTHER", warehouse_id=warehouse_id
        )
        await receive(client, admin, target["id"], warehouse_id, "SRT-1", 200, "200")
        await receive(client, admin, other["id"], warehouse_id, "SRO-1", 200, "200")
        customer_id = await create_customer(
            client, admin, name="عميل مرتجع التصفية", credit_limit="99999"
        )

        target_invoice = await post_invoice(
            client, admin, customer_id, warehouse_id, target["id"], "10", "credit"
        )
        other_invoice = await post_invoice(
            client, admin, customer_id, warehouse_id, other["id"], "10", "credit"
        )
        before = as_decimal(
            _row(
                await _customer_rfm(client, admin, target["id"]),
                "customer_id",
                customer_id,
            )["monetary"]
        )

        # Return the OTHER product: the target's figure must not move.
        unrelated = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": other_invoice.json()["data"]["id"],
                "reason": "resellable",
                "lines": [{"product_id": other["id"], "quantity": "4"}],
            },
        )
        assert unrelated.status_code == 201, unrelated.text
        unchanged = as_decimal(
            _row(
                await _customer_rfm(client, admin, target["id"]),
                "customer_id",
                customer_id,
            )["monetary"]
        )
        assert unchanged == before, "an unrelated return moved this product's value"

        # Return the target: now it must drop.
        own = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": target_invoice.json()["data"]["id"],
                "reason": "resellable",
                "lines": [{"product_id": target["id"], "quantity": "4"}],
            },
        )
        assert own.status_code == 201, own.text
        after = as_decimal(
            _row(
                await _customer_rfm(client, admin, target["id"]),
                "customer_id",
                customer_id,
            )["monetary"]
        )
        assert after < before


class TestProductRfmByCustomer:
    async def test_sales_narrow_to_the_customer_but_stock_does_not(
        self, client: AsyncClient
    ) -> None:
        """Stock and expiry describe the warehouse, not the customer.

        Scoping them to a customer would be meaningless — there is one shelf — and
        would quietly turn the waste-risk view into nonsense.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن عميل واحد")
        product = await create_product(
            client, admin, "CUSTFILTER-1", warehouse_id=warehouse_id
        )
        await receive(client, admin, product["id"], warehouse_id, "CF-1", 200, "500")
        mine = await create_customer(
            client, admin, name="عميل مرصود", credit_limit="99999"
        )
        theirs = await create_customer(
            client, admin, name="عميل آخر", credit_limit="99999"
        )

        await post_invoice(
            client, admin, mine, warehouse_id, product["id"], "10", "credit"
        )
        for _ in range(3):
            await post_invoice(
                client, admin, theirs, warehouse_id, product["id"], "10", "credit"
            )

        everyone = _row(await _product_rfm(client, admin), "product_id", product["id"])
        just_mine = _row(
            await _product_rfm(client, admin, mine), "product_id", product["id"]
        )

        assert everyone["frequency"] == 4
        assert just_mine["frequency"] == 1, "counted another customer's lines"
        assert as_decimal(just_mine["monetary"]) < as_decimal(everyone["monetary"])
        # The shelf is the same shelf either way.
        assert just_mine["stock_on_hand"] == everyone["stock_on_hand"]
        assert just_mine["nearest_expiry_days"] == everyone["nearest_expiry_days"]

    async def test_a_product_this_customer_never_bought_stays_at_zero(
        self, client: AsyncClient
    ) -> None:
        """That list is the cross-sell list, so it must not be filtered away."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن البيع المتقاطع")
        bought = await create_product(
            client, admin, "XSELL-A", warehouse_id=warehouse_id
        )
        unbought = await create_product(
            client, admin, "XSELL-B", warehouse_id=warehouse_id
        )
        await receive(client, admin, bought["id"], warehouse_id, "XA-1", 200, "100")
        await receive(client, admin, unbought["id"], warehouse_id, "XB-1", 200, "100")
        customer_id = await create_customer(
            client, admin, name="عميل البيع المتقاطع", credit_limit="9999"
        )
        await post_invoice(
            client, admin, customer_id, warehouse_id, bought["id"], "5", "credit"
        )

        rows = await _product_rfm(client, admin, customer_id)
        row = _row(rows, "product_id", unbought["id"])
        assert row["frequency"] == 0
        assert row["recency_days"] is None
        assert as_decimal(row["monetary"]) == Decimal("0")
        assert row["segment"] == "لم يُباع بعد"
        # But its stock is still reported, which is what makes it worth pitching.
        assert as_decimal(row["stock_on_hand"]) > 0


class TestTheRollingWindowAppliesToEveryScore:
    async def test_a_sale_older_than_the_window_counts_nowhere(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The bug: recency ignored pre-window sales, frequency and money did not.

        An outer join keeps its left rows, so an invoice line whose invoice failed the
        window condition survived with a NULL invoice and its `line_total` was summed
        anyway. The giveaway in the dev database was a product reading "لم يُباع بعد"
        with no recency at all while carrying 802.50 and a frequency of 1.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن النافذة")
        product = await create_product(
            client, admin, "WINDOW-1", warehouse_id=warehouse_id
        )
        await receive(client, admin, product["id"], warehouse_id, "W-1", 900, "500")
        customer_id = await create_customer(
            client, admin, name="عميل النافذة", credit_limit="99999"
        )

        sale = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
        )
        assert sale.status_code == 201, sale.text
        await backdate_invoice(
            db_session, sale.json()["data"]["id"], date.today() - timedelta(days=500)
        )

        row = _row(await _product_rfm(client, admin), "product_id", product["id"])
        assert row["recency_days"] is None
        assert row["frequency"] == 0, "a pre-window sale was counted"
        assert as_decimal(row["monetary"]) == Decimal("0"), (
            "a pre-window sale still carried revenue — the segment says never sold "
            "while the money says otherwise"
        )
        assert row["segment"] == "لم يُباع بعد"

    async def test_the_same_holds_for_the_customer_report(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن نافذة العميل")
        product = await create_product(
            client, admin, "WINDOW-2", warehouse_id=warehouse_id
        )
        await receive(client, admin, product["id"], warehouse_id, "W2-1", 900, "500")
        customer_id = await create_customer(
            client, admin, name="عميل نافذة قديمة", credit_limit="99999"
        )
        sale = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
        )
        await backdate_invoice(
            db_session, sale.json()["data"]["id"], date.today() - timedelta(days=500)
        )

        for product_id in (None, product["id"]):
            row = _row(
                await _customer_rfm(client, admin, product_id),
                "customer_id",
                customer_id,
            )
            assert row["frequency"] == 0
            assert as_decimal(row["monetary"]) == Decimal("0")


class TestBothReportsAgree:
    async def test_one_customer_one_product_reads_the_same_from_either_side(
        self, client: AsyncClient
    ) -> None:
        """Cross-check the two filters against each other.

        The customer report filtered by product and the product report filtered by
        customer are computing the same quantity from opposite directions. If they
        disagree, at least one of them is wrong, and this catches it without either
        having to be trusted on its own.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التقاطع")
        product = await create_product(
            client, admin, "CROSS-1", warehouse_id=warehouse_id
        )
        await receive(client, admin, product["id"], warehouse_id, "CR-1", 200, "500")
        customer_id = await create_customer(
            client, admin, name="عميل التقاطع", credit_limit="99999"
        )
        for _ in range(2):
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "7", "credit"
            )

        from_customers = _row(
            await _customer_rfm(client, admin, product["id"]),
            "customer_id",
            customer_id,
        )
        from_products = _row(
            await _product_rfm(client, admin, customer_id),
            "product_id",
            product["id"],
        )

        assert as_decimal(from_customers["monetary"]) == as_decimal(
            from_products["monetary"]
        )
        assert from_customers["recency_days"] == from_products["recency_days"]
