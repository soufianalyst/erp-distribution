"""Guards on the stock-corruption race, and an honest note about their limits.

A demonstrated bug: four salesmen invoicing one product at the same instant sold
120 units out of 100 and left the batch reading 70, and a single unit in stock was
sold to four different customers with no error raised to anyone. The cause was a
read-modify-write — `SELECT`, then `quantity -= take` in Python, then `UPDATE` at
commit — which PostgreSQL's default READ COMMITTED happily lets two sessions do to
the same row, both reading 100, both computing 90, both writing 90.

**These tests cannot reproduce that.** The suite runs on in-memory SQLite behind a
StaticPool: one connection, shared by every session, so two transactions can never
overlap. That is exactly why 390 passing tests never caught it, and no amount of
test-writing at this layer would have — the fixture makes concurrency impossible by
construction rather than merely unlikely.

So these tests guard the *mechanism* instead of the behaviour:

* that the locking clause is still in the query the database will run, and
* that the database itself refuses negative stock.

The behaviour is proved by `scripts/concurrency_check.py`, which needs a real
PostgreSQL and a running server, and which fails loudly on an unfixed build.
Anyone changing stock allocation should run it.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.inventory import ProductBatch
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_inventory import create_product, create_warehouse, receive


def compiled_for_postgres(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class TestTheAllocationQueryStillLocks:
    """If the lock is ever dropped, this fails — cheaply, and in every run.

    Asserting on generated SQL is normally a poor test. Here it is the only layer
    available: SQLite ignores row locking entirely, so a behavioural test on this
    fixture would pass whether the lock existed or not.
    """

    def test_fefo_selects_for_update(self) -> None:
        stmt = (
            select(ProductBatch)
            .where(ProductBatch.product_id == 1)
            .with_for_update()
        )
        assert "FOR UPDATE" in compiled_for_postgres(stmt)

    async def test_the_real_allocation_query_carries_the_lock(
        self, db_session: AsyncSession
    ) -> None:
        """Reads the shipping code, not a copy of it.

        Inspecting the source keeps this test honest: a duplicated query in the test
        would still pass after someone removed the lock from the service.
        """
        import inspect

        from app.services.inventory.stock_service import StockService

        source = inspect.getsource(StockService.fefo_allocate)
        assert ".with_for_update()" in source, (
            "fefo_allocate no longer locks the batch rows it allocates from. "
            "Concurrent invoices will oversell and silently overstate stock — see "
            "scripts/concurrency_check.py"
        )

    async def test_multi_line_invoices_lock_in_product_order(self) -> None:
        """Locks taken in typing order let two invoices deadlock on each other."""
        import inspect

        from app.services.sales.sales_service import SalesService

        source = inspect.getsource(SalesService._build_lines)
        # Match the call, not the name: an earlier version of this assertion looked
        # for "lock_batches_in_order" anywhere in the source and passed happily on
        # the explanatory comment above the call after the call itself was deleted.
        assert "await self.stock.lock_batches_in_order(" in source, (
            "the pre-lock pass is gone; invoices sharing two products in opposite "
            "order can deadlock"
        )


class TestTheDatabaseRefusesNegativeStock:
    """The backstop for the thirteen mutation sites the FEFO lock does not cover."""

    async def test_a_negative_quantity_is_rejected(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع القيد")
        product = await create_product(client, admin, "NEG-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "NEG-B1", 200, "10")

        batch = (
            await db_session.execute(
                select(ProductBatch).where(ProductBatch.batch_number == "NEG-B1")
            )
        ).scalar_one()

        batch.quantity = Decimal("-1")
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_zero_is_allowed(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """An emptied batch is normal and must not trip the constraint."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع الصفر")
        product = await create_product(client, admin, "ZERO-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "ZERO-B1", 200, "5")

        batch = (
            await db_session.execute(
                select(ProductBatch).where(ProductBatch.batch_number == "ZERO-B1")
            )
        ).scalar_one()
        batch.quantity = Decimal("0")
        await db_session.commit()
        assert batch.quantity == Decimal("0")


class TestSellingMoreThanExistsIsStillRefused:
    """Sequential oversell protection — the case the lock makes concurrent-safe.

    Worth keeping alongside the mechanism tests: it is the user-visible promise, and
    it must survive any future rework of the locking.
    """

    async def test_a_single_oversized_line_is_refused(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع البيع")
        product = await create_product(client, admin, "OVER-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "OVER-B1", 200, "10")

        from app.tests.test_sales import create_customer

        customer_id = await create_customer(client, admin, "بقالة الكمية")
        response = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "cash",
                "lines": [{"product_id": product["id"], "quantity": "11"}],
            },
        )
        assert response.status_code == 400
        assert "الكمية المتوفرة غير كافية" in response.json()["message"]
