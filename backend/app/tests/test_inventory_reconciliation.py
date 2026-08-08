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
