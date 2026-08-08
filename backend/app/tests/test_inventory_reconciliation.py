"""The inventory account and the goods on the shelf must agree.

Two records describe the same goods: `product_batches.quantity * unit_cost` is
what is physically held, and account 1030 is what the books say it is worth. Every
movement should change both by the same amount, and nothing in the suite was
comparing them — which is how a real gap opened up.

The gap that prompted this: `POST /inventory/stock/receive` changed the quantity and
wrote no journal entry at all, so the books drifted below the shelf by the value of
every direct receipt. The dev database was understated by 8,025.24 and nothing
anywhere would have said so.

These tests run the movements a warehouse actually performs and assert the two
figures move together each time.
"""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.accounting import Account, JournalItem
from app.domain.models.inventory import ProductBatch
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer


async def ledger_inventory(db: AsyncSession) -> Decimal:
    """Balance of account 1030 — what the books say the stock is worth."""
    result = await db.execute(
        select(
            func.coalesce(func.sum(JournalItem.debit), 0)
            - func.coalesce(func.sum(JournalItem.credit), 0)
        )
        .select_from(JournalItem)
        .join(Account, Account.id == JournalItem.account_id)
        .where(Account.code == "1030")
    )
    return Decimal(str(result.scalar_one()))


async def physical_inventory(db: AsyncSession) -> Decimal:
    """Value of what is actually on the shelves."""
    result = await db.execute(
        select(
            func.coalesce(
                func.sum(ProductBatch.quantity * func.coalesce(ProductBatch.unit_cost, 0)),
                0,
            )
        )
    )
    return Decimal(str(result.scalar_one()))


class TestTheBooksMatchTheShelf:
    async def test_a_direct_receipt_posts_its_value(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The bug itself: quantity moved, the ledger did not."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع المطابقة")
        product = await create_product(client, admin, "REC-1", warehouse_id=warehouse_id)

        before_ledger = await ledger_inventory(db_session)
        before_stock = await physical_inventory(db_session)
        # 20 units at a cost of 7 is 140 of value walking through the door.
        await receive(client, admin, product["id"], warehouse_id, "REC-B1", 200, "20",
                      unit_cost="7")
        db_session.expire_all()
        moved_ledger = await ledger_inventory(db_session) - before_ledger
        moved_stock = await physical_inventory(db_session) - before_stock

        assert moved_stock == Decimal("140.00"), moved_stock
        assert moved_ledger == moved_stock, (
            f"a direct receipt moved {moved_stock} of stock but {moved_ledger} of "
            "ledger value — the inventory account is drifting from the shelf"
        )

    async def test_a_receipt_without_a_cost_posts_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Unvalued stock is worth zero in both records, so both stay put."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع بلا تكلفة")
        product = await create_product(client, admin, "NOCOST-1", warehouse_id=warehouse_id)

        before_ledger = await ledger_inventory(db_session)
        await receive(client, admin, product["id"], warehouse_id, "NC-B1", 200, "10")
        db_session.expire_all()
        assert await ledger_inventory(db_session) == before_ledger

    async def test_the_two_agree_across_a_full_working_sequence(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Receive, sell, then take a return — the books track the shelf throughout.

        Checked after every step rather than only at the end: a pair of opposite
        errors would net out over the sequence and hide both.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع التسلسل")
        product = await create_product(client, admin, "SEQ-1", warehouse_id=warehouse_id)
        customer_id = await create_customer(client, admin, "بقالة التسلسل")

        async def drift() -> Decimal:
            db_session.expire_all()
            return await ledger_inventory(db_session) - await physical_inventory(db_session)

        opening = await drift()

        await receive(client, admin, product["id"], warehouse_id, "SEQ-B1", 200, "40",
                      unit_cost="6")
        assert await drift() == opening, "receiving broke the match"

        invoice = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "cash",
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert invoice.status_code == 201, invoice.text
        assert await drift() == opening, "selling broke the match"

        resellable = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice.json()["data"]["id"],
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "3"}],
            },
        )
        assert resellable.status_code == 201, resellable.text
        assert await drift() == opening, "a resellable return broke the match"

        damaged = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice.json()["data"]["id"],
                "reason": "damaged_customer",
                "lines": [{"product_id": product["id"], "quantity": "2"}],
            },
        )
        assert damaged.status_code == 201, damaged.text
        assert await drift() == opening, "a damaged return broke the match"


class TestFreightLandsOnTheGoods:
    """Shipping paid to bring goods in belongs in what those goods cost.

    The ledger always capitalised it — `INVENTORY, subtotal + shipping_cost` — but it
    was never pushed down onto the batches, so account 1030 held the freight and the
    shelf did not. The two could then only differ, by exactly the freight paid, for as
    long as the stock sat there. On a freshly seeded database that was 4,200.00 of
    shipping and 4,199.77 of difference: the whole discrepancy, one line of missing
    allocation.

    It also understated COGS on every sale of those goods, which quietly overstates
    gross margin — the reconciliation was the symptom, not the damage.
    """

    async def test_freight_reaches_the_shelf(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع الشحن")
        product = await create_product(client, admin, "FRT-1", warehouse_id=warehouse_id)
        supplier = await client.post(
            "/api/v1/purchases/suppliers", headers=admin, json={"name": "مورد الشحن"}
        )
        assert supplier.status_code == 201, supplier.text

        before = await ledger_inventory(db_session) - await physical_inventory(db_session)
        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier.json()["data"]["id"],
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "shipping_cost": "500.00",
                "tax_rate_ids": [],
                "lines": [{
                    "product_id": product["id"], "quantity": "100", "unit_cost": "60",
                    "batch_number": "FRT-B1", "expiry_date": "2027-12-31",
                }],
            },
        )
        assert response.status_code == 201, response.text
        db_session.expire_all()

        # 6,000 of goods + 500 of freight = 6,500 on the shelf and in the books.
        assert await physical_inventory(db_session) - Decimal("0") >= Decimal("6500.00")
        assert (
            await ledger_inventory(db_session) - await physical_inventory(db_session)
        ) == before, "the freight is in the books but not on the shelf"

    async def test_freight_splits_across_lines_by_value_and_sums_exactly(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Three lines that do not divide evenly: the parts must still make the whole."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع التوزيع")
        supplier = (await client.post(
            "/api/v1/purchases/suppliers", headers=admin, json={"name": "مورد التوزيع"}
        )).json()["data"]
        products = [
            await create_product(client, admin, f"SPL-{n}", warehouse_id=warehouse_id)
            for n in range(3)
        ]

        before = await ledger_inventory(db_session) - await physical_inventory(db_session)
        response = await client.post(
            "/api/v1/purchases/invoices",
            headers=admin,
            json={
                "supplier_id": supplier["id"],
                "warehouse_id": warehouse_id,
                "payment_method": "credit",
                "shipping_cost": "100.00",
                "tax_rate_ids": [],
                "lines": [
                    {"product_id": p["id"], "quantity": "3", "unit_cost": "10",
                     "batch_number": f"SPL-B{n}", "expiry_date": "2027-12-31"}
                    for n, p in enumerate(products)
                ],
            },
        )
        assert response.status_code == 201, response.text
        db_session.expire_all()
        # Within a rounding tolerance, not exactly: a batch stores a *per-unit* cost
        # to four decimals, and 100 spread over three lines of 30 cannot be expressed
        # exactly that way. The residue is a hundredth of a cent per line and does not
        # accumulate in one direction. Exactness would need the batch to store value
        # rather than a unit cost, which is a schema change, not a rounding fix.
        assert abs(
            (await ledger_inventory(db_session) - await physical_inventory(db_session))
            - before
        ) <= Decimal("0.01"), "an uneven three-way split lost or invented real money"


class TestTopUpDoesNotRevalueWhatIsAlreadyThere:
    """Receiving more of a batch must not reprice the units already in it.

    Overwriting `unit_cost` revalued the whole batch at the newest price: 100 at 60
    followed by 50 at 80 left a shelf worth 12,000 against a ledger holding 10,000 —
    a 2,000 revaluation with no entry behind it and no report showing it. Weighted
    average keeps the batch worth what was actually paid for its contents.

    Freight allocation makes this more likely, not less: two deliveries of the same
    batch now almost always land at slightly different costs.
    """

    async def test_a_second_delivery_averages_instead_of_overwriting(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع المتوسط")
        product = await create_product(client, admin, "AVG-1", warehouse_id=warehouse_id)

        before = await ledger_inventory(db_session) - await physical_inventory(db_session)
        await receive(client, admin, product["id"], warehouse_id, "AVG-B1", 400, "100",
                      unit_cost="60")
        db_session.expire_all()
        assert await drift_now(db_session) == before

        await receive(client, admin, product["id"], warehouse_id, "AVG-B1", 400, "50",
                      unit_cost="80")
        db_session.expire_all()
        # 10,000 over 150 units is 66.666… — not representable in four decimals, so a
        # half-cent of rounding remains. That is the floor for a per-unit cost; what
        # matters is that the 2,000 revaluation is gone.
        assert abs(await drift_now(db_session) - before) <= Decimal("0.01"), (
            "topping the batch up revalued the units already in it"
        )

        # 100×60 + 50×80 = 10,000 over 150 units = 66.6667 each.
        batch = (await db_session.execute(
            select(ProductBatch).where(ProductBatch.batch_number == "AVG-B1")
        )).scalar_one()
        assert batch.quantity == Decimal("150.000")
        assert batch.unit_cost == Decimal("66.6667"), batch.unit_cost


async def drift_now(db: AsyncSession) -> Decimal:
    return await ledger_inventory(db) - await physical_inventory(db)
