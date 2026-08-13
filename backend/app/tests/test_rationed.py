"""المواد المقننة — the register of regulated goods a customer received.

Two claims carry this module, and both are the kind that fail silently.

**It touches nothing.** Regulated goods are charged on the ordinary sales invoice like
anything else, so the register must post no journal entry, move no stock and create no
receivable. A second document that also touched the accounts would double every
regulated sale in the books, and nothing on any screen would look wrong — the trial
balance would still balance. So the tests assert the ledger and the stock are *byte for
byte identical* whether a line is marked or not.

**It follows the invoice.** The register stores no quantities and no prices: a row is a
pointer to an invoice line, and every figure is read through to it. That is what makes a
correction, a cancellation or a return show up here instead of leaving the register
declaring superseded numbers. For a document handed to an authority, being right on the
day it was written and quietly wrong afterwards is the worst failure available, so the
tests drive each of those three events and check the register moved with them.
"""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select

from app.domain.models.accounting import JournalItem
from app.domain.models.inventory import ProductBatch
from app.domain.models.sales import RationedLine, RationedRecord
from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer


async def stocked(client: AsyncClient, admin: dict, sku: str) -> tuple[int, int]:
    warehouse_id = await create_warehouse(client, admin, f"مخزن {sku}")
    product = await create_product(client, admin, sku=sku, warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, f"B-{sku}", 300, "500",
                  unit_cost="6")
    return warehouse_id, product["id"]


async def sell(
    client: AsyncClient, admin: dict, customer_id: int, warehouse_id: int,
    lines: list[dict],
):
    """An ordinary invoice; each line may carry `rationed: True`."""
    return await client.post(
        "/api/v1/sales/invoices",
        headers=admin,
        json={
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "payment_method": "cash",
            "tax_rate_ids": [],
            "lines": lines,
        },
    )


async def register(client: AsyncClient, headers: dict, customer_id: int) -> dict:
    response = await client.get(
        f"/api/v1/sales/customers/{customer_id}/rationed", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def ledger_total(db_session) -> Decimal:
    total = await db_session.scalar(
        select(func.coalesce(func.sum(JournalItem.debit + JournalItem.credit), 0))
    )
    return Decimal(str(total or 0))


async def stock_total(db_session) -> Decimal:
    total = await db_session.scalar(
        select(func.coalesce(func.sum(ProductBatch.quantity), 0))
    )
    return Decimal(str(total or 0))


class TestItTouchesNothing:
    """The register is a record, not a document. Nothing it does may reach the books."""

    async def test_marking_a_line_changes_neither_the_ledger_nor_the_stock(
        self, client: AsyncClient, db_session
    ) -> None:
        """Two identical invoices, one marked, and the books must not be able to tell.

        This is the whole safety claim. If marking a line posted anything, every
        regulated sale would be counted twice and the trial balance would still
        balance — which is exactly why it needs asserting rather than assuming.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-1")
        plain_customer = await create_customer(
            client, admin, name="عميل بلا تقنين", credit_limit="90000")
        marked_customer = await create_customer(
            client, admin, name="عميل مع تقنين", credit_limit="90000")

        before_ledger = await ledger_total(db_session)
        before_stock = await stock_total(db_session)
        await sell(client, admin, plain_customer, warehouse_id,
                   [{"product_id": product_id, "quantity": "10"}])
        plain_ledger = await ledger_total(db_session) - before_ledger
        plain_stock = before_stock - await stock_total(db_session)

        before_ledger = await ledger_total(db_session)
        before_stock = await stock_total(db_session)
        await sell(client, admin, marked_customer, warehouse_id,
                   [{"product_id": product_id, "quantity": "10", "rationed": True}])
        marked_ledger = await ledger_total(db_session) - before_ledger
        marked_stock = before_stock - await stock_total(db_session)

        assert marked_ledger == plain_ledger, "the register must post nothing"
        assert marked_stock == plain_stock, "the register must move no stock"
        # And the marked one really is on the register, so this is not passing by
        # doing nothing at all.
        assert (await register(client, admin, marked_customer))["line_count"] == 1

    async def test_the_customer_owes_exactly_the_invoice_and_nothing_more(
        self, client: AsyncClient, db_session
    ) -> None:
        """No receivable of its own: the goods were already billed on the invoice."""
        from app.services.sales.sales_service import SalesService

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-2")
        customer_id = await create_customer(
            client, admin, name="عميل الرصيد", credit_limit="90000")

        response = await sell(
            client, admin, customer_id, warehouse_id,
            [{"product_id": product_id, "quantity": "8", "rationed": True}])
        invoice = response.json()["data"]

        balance = await SalesService(db_session).customer_balance(customer_id)
        # A cash invoice is unpaid until the cashier collects it, so the balance is
        # the invoice total — not twice it.
        assert balance == Decimal(str(invoice["total"]))

    async def test_the_register_reports_a_value_not_an_amount_due(
        self, client: AsyncClient
    ) -> None:
        """Wording matters on a screen an accountant reads.

        The total is what the goods were worth, not what is owed for them — that was
        settled on the invoice — and the schema field is named `total_value` for that
        reason.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-3")
        customer_id = await create_customer(
            client, admin, name="عميل القيمة", credit_limit="90000")
        await sell(client, admin, customer_id, warehouse_id,
                   [{"product_id": product_id, "quantity": "5", "rationed": True}])

        data = await register(client, admin, customer_id)
        assert "total_value" in data
        assert Decimal(data["total_value"]) > 0


class TestOnlySelectedLines:
    async def test_only_the_marked_lines_are_filed(
        self, client: AsyncClient
    ) -> None:
        """The point of the feature: some items on an invoice, not all of them."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, regulated = await stocked(client, admin, "RAT-YES")
        _, ordinary = await stocked(client, admin, "RAT-NO")
        customer_id = await create_customer(
            client, admin, name="عميل الانتقاء", credit_limit="90000")

        response = await sell(
            client, admin, customer_id, warehouse_id,
            [
                {"product_id": regulated, "quantity": "4", "rationed": True},
                {"product_id": ordinary, "quantity": "7"},
            ])
        assert response.status_code == 201, response.text
        assert len(response.json()["data"]["lines"]) == 2

        data = await register(client, admin, customer_id)
        assert data["line_count"] == 1
        assert data["entries"][0]["product_id"] == regulated
        assert Decimal(data["entries"][0]["quantity"]) == Decimal("4.000")

    async def test_a_line_split_across_batches_is_filed_whole(
        self, client: AsyncClient
    ) -> None:
        """FEFO splits one requested line into several invoice lines.

        The flag is on what the user asked for, not on what FEFO produced, so filing
        only the first allocation would under-declare a product drawn from two lots —
        and the shortfall would look like a data-entry slip rather than a bug.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التشغيلات")
        product = await create_product(
            client, admin, sku="RAT-SPLIT", warehouse_id=warehouse_id)
        # Two lots, and a sale larger than either: FEFO must use both.
        await receive(client, admin, product["id"], warehouse_id, "LOT-A", 100, "6",
                      unit_cost="5")
        await receive(client, admin, product["id"], warehouse_id, "LOT-B", 200, "10",
                      unit_cost="5")
        customer_id = await create_customer(
            client, admin, name="عميل التشغيلات", credit_limit="90000")

        response = await sell(
            client, admin, customer_id, warehouse_id,
            [{"product_id": product["id"], "quantity": "9", "rationed": True}])
        assert response.status_code == 201, response.text
        assert len(response.json()["data"]["lines"]) == 2, "FEFO should have split it"

        data = await register(client, admin, customer_id)
        assert data["line_count"] == 2
        assert Decimal(data["total_quantity"]) == Decimal("9.000")


class TestItFollowsTheInvoice:
    """The register holds pointers, so the invoice stays the only copy of the numbers."""

    async def test_correcting_the_invoice_corrects_the_register(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-EDIT")
        customer_id = await create_customer(
            client, admin, name="عميل التصحيح", credit_limit="90000")

        invoice_id = (await sell(
            client, admin, customer_id, warehouse_id,
            [{"product_id": product_id, "quantity": "10", "rationed": True}]
        )).json()["data"]["id"]
        assert Decimal((await register(client, admin, customer_id))["total_quantity"]) \
            == Decimal("10.000")

        edited = await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=admin,
            json={
                "customer_id": customer_id, "warehouse_id": warehouse_id,
                "payment_method": "cash", "tax_rate_ids": [],
                "lines": [
                    {"product_id": product_id, "quantity": "6", "rationed": True}
                ],
            })
        assert edited.status_code == 200, edited.text

        data = await register(client, admin, customer_id)
        assert Decimal(data["total_quantity"]) == Decimal("6.000")
        assert data["line_count"] == 1

    async def test_unmarking_on_edit_removes_it_from_the_register(
        self, client: AsyncClient
    ) -> None:
        """Editing the invoice and dropping the flag is how a mistake gets undone."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-UNMARK")
        customer_id = await create_customer(
            client, admin, name="عميل الإلغاء", credit_limit="90000")

        invoice_id = (await sell(
            client, admin, customer_id, warehouse_id,
            [{"product_id": product_id, "quantity": "10", "rationed": True}]
        )).json()["data"]["id"]

        edited = await client.put(
            f"/api/v1/sales/invoices/{invoice_id}",
            headers=admin,
            json={
                "customer_id": customer_id, "warehouse_id": warehouse_id,
                "payment_method": "cash", "tax_rate_ids": [],
                "lines": [{"product_id": product_id, "quantity": "10"}],
            })
        assert edited.status_code == 200, edited.text

        assert (await register(client, admin, customer_id))["line_count"] == 0

    async def test_deleting_the_invoice_empties_the_register(
        self, client: AsyncClient
    ) -> None:
        """An entry for goods on a cancelled invoice is a claim about a sale that did
        not happen — worse than no entry, because it would be declared."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-DEL")
        customer_id = await create_customer(
            client, admin, name="عميل الحذف", credit_limit="90000")

        invoice_id = (await sell(
            client, admin, customer_id, warehouse_id,
            [{"product_id": product_id, "quantity": "10", "rationed": True}]
        )).json()["data"]["id"]
        assert (await register(client, admin, customer_id))["line_count"] == 1

        deleted = await client.delete(
            f"/api/v1/sales/invoices/{invoice_id}", headers=admin)
        assert deleted.status_code == 200, deleted.text

        assert (await register(client, admin, customer_id))["line_count"] == 0

    async def test_a_return_reduces_the_declared_quantity(
        self, client: AsyncClient
    ) -> None:
        """A shop that took ten sacks and sent two back received eight.

        Eight is what the declaration has to say, and the register reads it live rather
        than needing anyone to remember to amend it.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-RET")
        customer_id = await create_customer(
            client, admin, name="عميل المرتجع", credit_limit="90000")

        invoice_id = (await sell(
            client, admin, customer_id, warehouse_id,
            [{"product_id": product_id, "quantity": "10", "rationed": True}]
        )).json()["data"]["id"]

        returned = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product_id, "quantity": "2"}],
            })
        assert returned.status_code == 201, returned.text

        entry = (await register(client, admin, customer_id))["entries"][0]
        assert Decimal(entry["quantity"]) == Decimal("10.000")
        assert Decimal(entry["returned_quantity"]) == Decimal("2.000")
        assert Decimal(entry["net_quantity"]) == Decimal("8.000")


class TestOneOpenRegisterPerCustomer:
    async def test_a_second_invoice_joins_the_same_open_register(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-ACC")
        customer_id = await create_customer(
            client, admin, name="عميل التجميع", credit_limit="90000")

        for quantity in ("3", "4"):
            await sell(client, admin, customer_id, warehouse_id,
                       [{"product_id": product_id, "quantity": quantity,
                         "rationed": True}])

        data = await register(client, admin, customer_id)
        assert data["line_count"] == 2
        assert Decimal(data["total_quantity"]) == Decimal("7.000")

    async def test_the_database_refuses_a_second_open_register(
        self, client: AsyncClient, db_session
    ) -> None:
        """The rule lives in a partial unique index, not in the service remembering.

        Two invoices for one customer landing together would otherwise both look up
        "the open register", both find none, and both create one.
        """
        import pytest
        from sqlalchemy.exc import IntegrityError

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id = await create_customer(
            client, admin, name="عميل السجل الواحد", credit_limit="90000")

        db_session.add(RationedRecord(customer_id=customer_id))
        await db_session.flush()
        db_session.add(RationedRecord(customer_id=customer_id))
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_closing_opens_the_next_one_immediately(
        self, client: AsyncClient
    ) -> None:
        """There is always exactly one open register, so a tag a second later has
        somewhere to go."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-CLOSE")
        customer_id = await create_customer(
            client, admin, name="عميل الإقفال", credit_limit="90000")
        await sell(client, admin, customer_id, warehouse_id,
                   [{"product_id": product_id, "quantity": "5", "rationed": True}])

        opened = await register(client, admin, customer_id)
        closed = await client.post(
            f"/api/v1/sales/rationed/{opened['record_id']}/close",
            headers=admin, json={"notes": "إقرار شهر أغسطس"})
        assert closed.status_code == 200, closed.text
        body = closed.json()["data"]
        assert body["closed"]["is_open"] is False
        assert body["closed"]["notes"] == "إقرار شهر أغسطس"
        assert body["new_record_id"] != opened["record_id"]

        # The customer's current register is the new, empty one.
        fresh = await register(client, admin, customer_id)
        assert fresh["record_id"] == body["new_record_id"]
        assert fresh["line_count"] == 0
        assert fresh["is_open"] is True

        # And the closed one is still readable, with its lines, for printing.
        history = (await client.get(
            f"/api/v1/sales/customers/{customer_id}/rationed/history",
            headers=admin)).json()["data"]
        assert [r["id"] for r in history] == [opened["record_id"]]

    async def test_an_empty_register_cannot_be_closed(
        self, client: AsyncClient
    ) -> None:
        """A declaration with no lines is not a record of anything, and in the history
        it would read as a month the customer took nothing."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id = await create_customer(
            client, admin, name="عميل الفارغ", credit_limit="90000")
        empty = await register(client, admin, customer_id)

        response = await client.post(
            f"/api/v1/sales/rationed/{empty['record_id']}/close",
            headers=admin, json={})
        assert response.status_code == 400
        assert "فارغ" in response.json()["message"]

    async def test_a_closed_register_cannot_be_closed_twice(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-TWICE")
        customer_id = await create_customer(
            client, admin, name="عميل مرتين", credit_limit="90000")
        await sell(client, admin, customer_id, warehouse_id,
                   [{"product_id": product_id, "quantity": "5", "rationed": True}])
        record_id = (await register(client, admin, customer_id))["record_id"]

        assert (await client.post(
            f"/api/v1/sales/rationed/{record_id}/close",
            headers=admin, json={})).status_code == 200
        again = await client.post(
            f"/api/v1/sales/rationed/{record_id}/close", headers=admin, json={})
        assert again.status_code == 400


class TestUntagging:
    async def test_a_line_can_be_removed_from_an_open_register(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-RM")
        customer_id = await create_customer(
            client, admin, name="عميل الحذف اليدوي", credit_limit="90000")
        await sell(client, admin, customer_id, warehouse_id,
                   [{"product_id": product_id, "quantity": "5", "rationed": True}])

        entry = (await register(client, admin, customer_id))["entries"][0]
        removed = await client.delete(
            f"/api/v1/sales/rationed/lines/{entry['line_id']}", headers=admin)
        assert removed.status_code == 200, removed.text
        assert (await register(client, admin, customer_id))["line_count"] == 0

    async def test_a_closed_register_is_not_editable(
        self, client: AsyncClient
    ) -> None:
        """Its copy has been printed and declared; a silent removal would leave the
        paper and the system disagreeing about what an authority was told."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-FROZEN")
        customer_id = await create_customer(
            client, admin, name="عميل المقفل", credit_limit="90000")
        await sell(client, admin, customer_id, warehouse_id,
                   [{"product_id": product_id, "quantity": "5", "rationed": True}])

        opened = await register(client, admin, customer_id)
        entry = opened["entries"][0]
        await client.post(
            f"/api/v1/sales/rationed/{opened['record_id']}/close",
            headers=admin, json={})

        response = await client.delete(
            f"/api/v1/sales/rationed/lines/{entry['line_id']}", headers=admin)
        assert response.status_code == 400
        assert "مقفل" in response.json()["message"]

    async def test_the_same_invoice_line_cannot_be_filed_twice(
        self, client: AsyncClient, db_session
    ) -> None:
        """On a monthly declaration a duplicated line is an overstatement nobody could
        explain afterwards, so the database refuses it."""
        import pytest
        from sqlalchemy.exc import IntegrityError

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product_id = await stocked(client, admin, "RAT-DUP")
        customer_id = await create_customer(
            client, admin, name="عميل التكرار", credit_limit="90000")
        await sell(client, admin, customer_id, warehouse_id,
                   [{"product_id": product_id, "quantity": "5", "rationed": True}])

        entry = (await register(client, admin, customer_id))["entries"][0]
        record_id = (await register(client, admin, customer_id))["record_id"]

        db_session.add(
            RationedLine(
                record_id=record_id, sales_invoice_line_id=entry["line_id"]
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


class TestWhoMaySeeAndChangeIt:
    async def test_a_rep_may_look_but_not_close(
        self, client: AsyncClient
    ) -> None:
        """He answers for what his shop took; he does not decide what gets declared."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        me = (await client.get("/api/v1/auth/me", headers=sales)).json()["data"]

        warehouse_id, product_id = await stocked(client, admin, "RAT-PERM")
        customer_id = await create_customer(
            client, admin, name="عميل المندوب", credit_limit="90000",
            salesman_id=me["id"])
        await sell(client, admin, customer_id, warehouse_id,
                   [{"product_id": product_id, "quantity": "5", "rationed": True}])

        seen = await client.get(
            f"/api/v1/sales/customers/{customer_id}/rationed", headers=sales)
        assert seen.status_code == 200, seen.text
        record_id = seen.json()["data"]["record_id"]

        refused = await client.post(
            f"/api/v1/sales/rationed/{record_id}/close", headers=sales, json={})
        assert refused.status_code == 403

        entry = seen.json()["data"]["entries"][0]
        also_refused = await client.delete(
            f"/api/v1/sales/rationed/lines/{entry['line_id']}", headers=sales)
        assert also_refused.status_code == 403

    async def test_it_needs_a_login(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/sales/customers/1/rationed")
        assert response.status_code == 401
