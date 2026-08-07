"""Every module that computes money from a sale must subtract the credit notes.

Four places needed "how much has been credited back" and three had grown their own
copy of the query. Each was right when written, which is why the divergence stayed
invisible: the cashier's amount due was fixed, and the round settlement went on
blocking forever because it recalculated the same figure without the returns term.

The two found by walking outwards from a return, both measured before being fixed:

* The tax report summed SalesInvoiceTax and never subtracted return VAT. Sell 1,000
  with 160 of tax, take the whole lot back, and it still declared 160 — the company
  would file and pay tax on sales that no longer existed.
* The round settlement computed the drawer's due from gross invoice totals, so a
  partly-returned van sale left cash outstanding that nobody owed. The round could
  never close, and the cashier could not collect it either because their own gate
  correctly refuses money that is not due.

These tests are the boundary. A fifth module that needs the figure should import
services/sales/returns_query rather than write the sum again.
"""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tests.conftest import (
    DEFAULT_TAX_RATE_ID,
    TEST_ADMIN_PASSWORD,
    TEST_CASHIER_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer


class TestTheTaxReportCreditsReturns:
    async def test_a_full_return_cancels_the_tax_it_collected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع الضريبة")
        product = await create_product(client, admin, "TAX-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "TAX-B1", 200, "20")
        customer_id = await create_customer(
            client, admin, "بقالة الضريبة", credit_limit="99999"
        )

        async def collected() -> Decimal:
            response = await client.get(
                "/api/v1/accounting/reports/tax-summary", headers=admin
            )
            assert response.status_code == 200, response.text
            return Decimal(response.json()["data"]["total_collected"])

        before = await collected()
        invoice = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert invoice.status_code == 201, invoice.text
        after_sale = await collected()
        assert after_sale > before, "the sale should have added output tax"

        credited = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice.json()["data"]["id"],
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        assert credited.status_code == 201, credited.text
        assert await collected() == before, (
            "returning everything must leave no tax declared — otherwise the company "
            "pays tax on sales that were entirely reversed"
        )

    async def test_a_partial_return_credits_only_its_share(
        self, client: AsyncClient
    ) -> None:
        """40% back means 40% of the tax credited, not all of it and not none."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مستودع الجزئي")
        product = await create_product(
            client, admin, "TAX-2", warehouse_id=warehouse_id
        )
        await receive(client, admin, product["id"], warehouse_id, "TAX-B2", 200, "20")
        customer_id = await create_customer(
            client, admin, "بقالة الجزئي", credit_limit="99999"
        )

        async def collected() -> Decimal:
            response = await client.get(
                "/api/v1/accounting/reports/tax-summary", headers=admin
            )
            return Decimal(response.json()["data"]["total_collected"])

        before = await collected()
        invoice = await client.post(
            "/api/v1/sales/invoices",
            headers=admin,
            json={
                "customer_id": customer_id,
                "payment_method": "credit",
                "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
                "lines": [{"product_id": product["id"], "quantity": "10"}],
            },
        )
        sale_tax = Decimal(invoice.json()["data"]["vat_amount"])
        await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice.json()["data"]["id"],
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "4"}],
            },
        )
        net = await collected() - before
        expected = (sale_tax * Decimal("0.6")).quantize(Decimal("0.01"))
        assert net == expected, f"declared {net}, expected {expected} (60% of the sale)"


class TestTheRoundSettlementNetsReturns:
    async def test_a_returned_van_sale_does_not_block_the_close(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The round must close on what is actually owed, not the gross total.

        Before this, the cashier collected the correct net amount and the round still
        reported the difference as uncollected cash — an amount nobody owed and the
        cashier was rightly refusing to take. A permanent deadlock.
        """
        from app.tests.test_field_sync import (
            assign_van,
            load_van,
            own_customer,
            post_sync,
            sale,
        )

        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(
            client, admin, "RND-1", warehouse_id=main_id
        )
        await receive(client, admin, product["id"], main_id, "RND-B1", 200, "100")
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "40")
        customer_id = await own_customer(client, admin, db_session, "بقالة الجولة")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        synced = await post_sync(
            client,
            salesman,
            documents=[
                sale("rnd-uuid-0001-000000", product["id"], "5", customer_id=customer_id,
                     tax_rate_ids=[])
            ],
        )
        assert synced["created_count"] == 1, synced
        invoice_id = synced["results"][0]["server_id"]

        detail = (await client.get(f"/api/v1/sales/invoices/{invoice_id}", headers=admin)).json()["data"]
        gross = Decimal(detail["total"])

        returned = await client.post(
            "/api/v1/sales/returns",
            headers=admin,
            json={
                "invoice_id": invoice_id,
                "reason": "resellable",
                "lines": [{"product_id": product["id"], "quantity": "2"}],
            },
        )
        assert returned.status_code == 201, returned.text
        credited = Decimal(returned.json()["data"]["total"])
        net = gross - credited

        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        collect = await client.post(
            f"/api/v1/cashier/invoices/{invoice_id}/collect",
            headers=cashier,
            json={"amount": str(net)},
        )
        assert collect.status_code == 200, collect.text

        position = await client.get(
            "/api/v1/sales/rounds/position", headers=admin,
            params={"warehouse_id": van_id},
        )
        data = position.json()["data"]
        assert Decimal(data["total_sales"]) == net, (
            f"round reports {data['total_sales']} of sales, net of returns is {net}"
        )
        assert Decimal(data["cash_outstanding_total"]) == Decimal("0"), (
            f"round still wants {data['cash_outstanding_total']} that nobody owes"
        )
        assert data["can_settle"] is True, data["blockers"]

        settled = await client.post(
            "/api/v1/sales/rounds/settle-van", headers=admin,
            json={"warehouse_id": van_id},
        )
        assert settled.status_code == 200, settled.text


def test_only_one_definition_of_the_returned_total() -> None:
    """Guards the consolidation itself.

    The bug existed because three services each summed SalesReturn.total for
    themselves. Fixing two of them and leaving the third is what produced the
    round-settlement deadlock, so the shape is worth forbidding rather than just
    fixing again.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "services"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "returns_query.py":
            continue
        text = path.read_text(encoding="utf-8")
        # The distinctive marker of the duplicated concept, and nothing wider.
        #
        # Two earlier versions of this check were too coarse and taught me something
        # each time. Matching any `func.sum(SalesReturn.total)` flagged four
        # legitimate aggregations — by customer, by salesman, by month — which are
        # different questions with different answers. Then matching that plus
        # `SalesReturn.invoice_id` anywhere in the file still flagged sales_service,
        # because one file can hold both shapes in separate queries.
        #
        # Grouping by invoice_id is what only the shared helper should do.
        if "group_by(SalesReturn.invoice_id)" in text:
            offenders.append(str(path.relative_to(root)))
    assert not offenders, (
        f"{offenders} sum SalesReturn.total per invoice; import "
        "services/sales/returns_query instead so every module agrees"
    )


def test_every_query_over_returns_excludes_the_cancelled_ones() -> None:
    """A cancelled credit note must be invisible to every figure derived from returns.

    It stays in the table deliberately — the mistake is part of the record — which
    means the exclusion is not automatic. Fourteen queries across five services ask
    about returns: the invoice's credited total, the customer balance, the tax
    report, the picking list, six analytics figures, and the guards that refuse to
    edit or over-return an invoice. Miss one and a cancelled note goes on reducing a
    balance, or goes on blocking an edit, forever.

    That is the same shape as the bug this file's other guard exists for, one level
    down, so it gets the same treatment: `posted()` is written once and every query
    has to say it. This check reads the AST rather than grepping, because the thing
    it must be sure of is *which function* a query lives in.
    """
    import ast
    import pathlib

    # The screens whose whole job is to show cancellations, plus the cancel itself,
    # which has to find the note in order to reverse it.
    ALLOWED_TO_SEE_CANCELLED = {"get_return", "list_returns", "cancel_return"}

    root = pathlib.Path(__file__).resolve().parents[1] / "services"
    offenders: list[str] = []
    checked = 0

    for path in sorted(root.rglob("*.py")):
        if path.name == "returns_query.py":  # where posted() is defined
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in ALLOWED_TO_SEE_CANCELLED:
                continue
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            queries_returns = False
            for stmt in ast.walk(node):
                if not isinstance(stmt, (ast.Assign, ast.Expr, ast.Return, ast.AugAssign)):
                    continue
                inner = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)}
                if "select" in inner and "SalesReturn" in inner:
                    queries_returns = True
                    break
            if not queries_returns:
                continue
            checked += 1
            if "posted" not in names:
                offenders.append(f"{path.relative_to(root)}::{node.name}")

    assert checked >= 8, (
        f"only {checked} functions matched — the check stopped finding the queries "
        "it is supposed to guard, so it is no longer guarding anything"
    )
    assert not offenders, (
        "these query sales returns without excluding cancelled ones — add "
        f"posted() from services/sales/returns_query to the WHERE clause: {offenders}"
    )
