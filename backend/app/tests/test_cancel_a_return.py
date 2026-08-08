"""A credit note entered by mistake has to have a way back.

Every other document that moves stock or money could be corrected — an invoice can be
edited or deleted, a damage write-off cancelled, a stocktake voided. The sales return
could not. Once recorded it was final: the goods were back on the shelf, the credit
note posted to the ledger, and the customer's balance reduced, with no path to undo any
of it. The only remedy was a second, opposite return, which is not the same thing —
it leaves two wrong documents in the record instead of one corrected one.

Cancelled rather than deleted, for a reason that matters at the counter: a customer
statement where a line simply disappeared is one nobody can explain to the customer.

The refusals are the interesting part. Cancelling has to take goods back out of stock
and reverse the ledger, and there are two states where doing so would create a worse
problem than the one being fixed — the customer already holding refunded cash, and the
returned goods already sold to somebody else.
"""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_CASHIER_PASSWORD,
    login,
)
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer


async def _batch_quantity(client, headers, product_id) -> Decimal:
    response = await client.get(
        f"/api/v1/inventory/products/{product_id}/batches", headers=headers
    )
    assert response.status_code == 200, response.text
    return sum(Decimal(b["quantity"]) for b in response.json()["data"])


async def _balance(client, headers, customer_id) -> Decimal:
    response = await client.get(
        f"/api/v1/sales/customers/{customer_id}/statement", headers=headers
    )
    assert response.status_code == 200, response.text
    return Decimal(str(response.json()["data"]["balance"]))


async def _setup(client, headers, tag, quantity="30"):
    warehouse_id = await create_warehouse(client, headers, f"مستودع {tag}")
    product = await create_product(
        client, headers, f"CXL-{tag}", warehouse_id=warehouse_id
    )
    await receive(
        client, headers, product["id"], warehouse_id, f"CXL-B-{tag}", 200, quantity
    )
    customer_id = await create_customer(
        client, headers, f"عميل {tag}", credit_limit="99999"
    )
    return warehouse_id, product, customer_id


async def _sell(client, headers, customer_id, product_id, quantity, method="credit"):
    response = await client.post(
        "/api/v1/sales/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "payment_method": method,
            "fulfillment": "pickup",
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _give_back(client, headers, invoice_id, product_id, quantity,
                     reason="resellable"):
    response = await client.post(
        "/api/v1/sales/returns",
        headers=headers,
        json={
            "invoice_id": invoice_id,
            "reason": reason,
            "lines": [{"product_id": product_id, "quantity": quantity}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestCancellingPutsEverythingBack:
    async def test_stock_balance_and_ledger_all_return_to_where_they_were(
        self, client: AsyncClient
    ) -> None:
        """The whole point: after cancelling, nothing anywhere remembers the return."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "back")

        invoice = await _sell(client, admin, customer_id, product["id"], "10")
        stock_after_sale = await _batch_quantity(client, admin, product["id"])
        balance_after_sale = await _balance(client, admin, customer_id)

        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "4"
        )
        assert await _batch_quantity(client, admin, product["id"]) == (
            stock_after_sale + 4
        )
        assert await _balance(client, admin, customer_id) < balance_after_sale

        cancelled = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel",
            headers=admin,
            json={"cancel_reason": "سُجّل على الفاتورة الخطأ"},
        )
        assert cancelled.status_code == 200, cancelled.text
        body = cancelled.json()["data"]
        assert body["status"] == "cancelled"
        assert body["cancel_reason"] == "سُجّل على الفاتورة الخطأ"
        assert body["cancelled_at"] is not None

        assert await _batch_quantity(client, admin, product["id"]) == stock_after_sale
        assert await _balance(client, admin, customer_id) == balance_after_sale

        # And it is gone from the movements the statement lists, not just from the
        # total underneath them. A statement whose lines do not add up to its own
        # balance is the one thing that cannot be explained to a customer.
        statement = await client.get(
            f"/api/v1/sales/customers/{customer_id}/statement", headers=admin
        )
        assert statement.status_code == 200, statement.text
        assert not [
            r
            for r in statement.json()["data"]["returns"]
            if r["id"] == sales_return["id"]
        ], "the cancelled credit note is still listed as a movement"

    async def test_the_invoice_is_owed_in_full_again(self, client: AsyncClient) -> None:
        """The cashier must collect the whole amount once the credit note is void."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "due")

        invoice = await _sell(
            client, admin, customer_id, product["id"], "10", method="cash"
        )
        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "4"
        )

        async def amount_due():
            response = await client.get(
                "/api/v1/cashier/invoices", headers=cashier
            )
            assert response.status_code == 200, response.text
            rows = [r for r in response.json()["data"] if r["id"] == invoice["id"]]
            return Decimal(str(rows[0]["amount_due"])) if rows else Decimal("0")

        netted = await amount_due()
        assert netted < Decimal(str(invoice["total"]))

        cancelled = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert cancelled.status_code == 200, cancelled.text
        assert await amount_due() == Decimal(str(invoice["total"]))

    async def test_the_trial_balance_still_balances(self, client: AsyncClient) -> None:
        """The reversal is a real journal entry, not a deletion of the original."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "ledger")

        invoice = await _sell(client, admin, customer_id, product["id"], "10")
        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "4"
        )
        cancelled = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert cancelled.status_code == 200, cancelled.text

        report = await client.get(
            "/api/v1/accounting/reports/trial-balance", headers=admin
        )
        assert report.status_code == 200, report.text
        assert report.json()["data"]["is_balanced"] is True

        entries = await client.get(
            "/api/v1/accounting/journal-entries",
            headers=admin,
            params={"reference_type": "sales_return_cancel"},
        )
        assert entries.status_code == 200, entries.text
        assert entries.json()["data"], "the reversal left no journal entry behind"

    async def test_the_invoice_can_be_edited_again(self, client: AsyncClient) -> None:
        """A return blocks editing its invoice. A cancelled one must stop blocking."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "edit")

        invoice = await _sell(client, admin, customer_id, product["id"], "10")
        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "2"
        )

        payload = {
            "customer_id": customer_id,
            "payment_method": "credit",
            "fulfillment": "pickup",
            "lines": [{"product_id": product["id"], "quantity": "8"}],
        }
        blocked = await client.put(
            f"/api/v1/sales/invoices/{invoice['id']}", headers=admin, json=payload
        )
        assert blocked.status_code == 400, blocked.text

        cancelled = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert cancelled.status_code == 200, cancelled.text

        allowed = await client.put(
            f"/api/v1/sales/invoices/{invoice['id']}", headers=admin, json=payload
        )
        assert allowed.status_code == 200, allowed.text


class TestWhatCancellingRefuses:
    async def test_it_refuses_a_second_time(self, client: AsyncClient) -> None:
        """Reversing twice would take the same goods out of stock twice."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "twice")

        invoice = await _sell(client, admin, customer_id, product["id"], "10")
        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "4"
        )
        first = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert first.status_code == 200, first.text
        stock = await _batch_quantity(client, admin, product["id"])

        second = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert second.status_code == 400, second.text
        assert "ملغى من قبل" in second.json()["message"]
        assert await _batch_quantity(client, admin, product["id"]) == stock

    async def test_it_refuses_once_the_customer_has_been_paid_the_refund(
        self, client: AsyncClient
    ) -> None:
        """The customer is holding the cash.

        Undoing the credit note here would quietly turn a correction into a debt the
        customer was never told about. Getting the money back is a conversation, not
        a database write, so the system refuses and says why.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "refunded")

        invoice = await _sell(
            client, admin, customer_id, product["id"], "10", method="cash"
        )
        collected = await client.post(
            f"/api/v1/cashier/invoices/{invoice['id']}/collect",
            headers=cashier,
            json={"amount": str(invoice["total"])},
        )
        assert collected.status_code == 200, collected.text

        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "3"
        )
        credit_id = sales_return["pending_credit_id"]
        assert credit_id is not None, "a paid invoice must raise the refund question"

        resolved = await client.post(
            f"/api/v1/sales/credits/{credit_id}/resolve",
            headers=admin,
            json={"resolution": "refunded"},
        )
        assert resolved.status_code == 200, resolved.text
        paid = await client.post(
            f"/api/v1/cashier/customer-credits/{credit_id}/refund", headers=cashier
        )
        assert paid.status_code == 200, paid.text

        refused = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert refused.status_code == 400, refused.text
        assert "ردّ مبلغ" in refused.json()["message"]

    async def test_it_allows_cancelling_while_the_refund_is_still_only_a_decision(
        self, client: AsyncClient
    ) -> None:
        """Chosen but not yet paid is still undoable — and the claim goes with it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "awaiting")

        invoice = await _sell(
            client, admin, customer_id, product["id"], "10", method="cash"
        )
        await client.post(
            f"/api/v1/cashier/invoices/{invoice['id']}/collect",
            headers=cashier,
            json={"amount": str(invoice["total"])},
        )
        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "3"
        )
        credit_id = sales_return["pending_credit_id"]
        await client.post(
            f"/api/v1/sales/credits/{credit_id}/resolve",
            headers=admin,
            json={"resolution": "refunded"},
        )

        cancelled = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert cancelled.status_code == 200, cancelled.text

        pending = await client.get("/api/v1/sales/credits", headers=admin)
        assert pending.status_code == 200, pending.text
        assert not [
            c for c in pending.json()["data"] if c["id"] == credit_id
        ], "the cancelled note left its refund claim standing"

    async def test_it_refuses_when_the_returned_goods_have_been_sold_again(
        self, client: AsyncClient
    ) -> None:
        """A resellable return put the goods back on the shelf and they left again.

        Taking out stock that is no longer there is the negative-quantity case the
        database now rejects outright, so it is caught here with an explanation
        instead of an integrity error.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product, customer_id = await _setup(client, admin, "resold", quantity="14")

        invoice = await _sell(client, admin, customer_id, product["id"], "10")
        sales_return = await _give_back(
            client, admin, invoice["id"], product["id"], "4"
        )
        # 14 − 10 + 4 = 8 on the shelf; sell every one of them.
        await _sell(client, admin, customer_id, product["id"], "8")
        assert await _batch_quantity(client, admin, product["id"]) == Decimal("0")

        refused = await client.post(
            f"/api/v1/sales/returns/{sales_return['id']}/cancel", headers=admin
        )
        assert refused.status_code == 400, refused.text
        assert "بِيعت البضاعة بعد إرجاعها" in refused.json()["message"]
        # And nothing was half-done on the way to refusing.
        assert await _batch_quantity(client, admin, product["id"]) == Decimal("0")
        report = await client.get(
            "/api/v1/accounting/reports/trial-balance", headers=admin
        )
        assert report.json()["data"]["is_balanced"] is True


class TestWhoMayCancel:
    async def test_a_salesman_may_not_cancel_his_own_credit_note(
        self, client: AsyncClient
    ) -> None:
        """Separation of duties: whoever books a return must not also void it.

        The permission sits with the accountant, for the same reason the person who
        counts stock is not the person who approves the count.
        """
        from app.core.permissions import ROLE_DEFAULT_PERMISSIONS

        assert "sales.returns_cancel" not in ROLE_DEFAULT_PERMISSIONS["sales"]
        assert "sales.returns_cancel" in ROLE_DEFAULT_PERMISSIONS["accountant"]
