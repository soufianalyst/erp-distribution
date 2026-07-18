"""Integration tests for the cashier module: pending cash/card collection gate."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.cashier import CashMovement
from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_CASHIER_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_delivery import create_trip
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    days_from_now,
    receive,
)
from app.tests.test_purchases import create_supplier
from app.tests.test_sales import create_customer, post_invoice


def items_by_code(entry: dict) -> dict[str, tuple[Decimal, Decimal]]:
    return {
        item["account"]["code"]: (as_decimal(item["debit"]), as_decimal(item["credit"]))
        for item in entry["items"]
    }


async def collect(
    client: AsyncClient, headers: dict[str, str], invoice_id: int, amount: str
):
    return await client.post(
        f"/api/v1/cashier/invoices/{invoice_id}/collect",
        headers=headers,
        json={"amount": amount},
    )


class TestCashierGate:
    async def test_pending_list_shows_only_unconfirmed_cash_and_card(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        cash_inv = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
        )
        card_inv = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5", "card"
        )
        credit_inv = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5", "credit"
        )
        assert cash_inv.status_code == 201, cash_inv.text
        assert card_inv.status_code == 201, card_inv.text
        assert credit_inv.status_code == 201, credit_inv.text
        cash_id = cash_inv.json()["data"]["id"]
        card_id = card_inv.json()["data"]["id"]
        credit_id = credit_inv.json()["data"]["id"]

        pending = (
            await client.get("/api/v1/cashier/invoices", headers=admin)
        ).json()["data"]
        pending_ids = {i["id"] for i in pending}
        assert cash_id in pending_ids
        assert card_id in pending_ids
        assert credit_id not in pending_ids

    async def test_full_cash_collection_posts_journal_and_releases_invoice(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice_resp = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
        )
        invoice = invoice_resp.json()["data"]
        assert as_decimal(invoice["paid_amount"]) == Decimal("0")

        # Hidden from delivery before collection.
        summaries = (
            await client.get("/api/v1/delivery/invoices", headers=admin)
        ).json()["data"]
        assert all(s["id"] != invoice["id"] for s in summaries)

        confirmed = await collect(client, admin, invoice["id"], invoice["total"])
        assert confirmed.status_code == 200, confirmed.text
        data = confirmed.json()["data"]
        assert data["payment_confirmed_at"] is not None
        assert as_decimal(data["paid_amount"]) == as_decimal(data["total"])

        # Now visible to delivery.
        summaries = (
            await client.get("/api/v1/delivery/invoices", headers=admin)
        ).json()["data"]
        assert any(s["id"] == invoice["id"] for s in summaries)

        # Journal: Dr cash (1010), Cr receivable (1020) for the invoice total.
        entries = (
            await client.get(
                "/api/v1/accounting/journal-entries",
                headers=admin,
                params={
                    "reference_type": "sales_invoice_payment",
                    "reference_id": invoice["id"],
                },
            )
        ).json()["data"]
        assert len(entries) == 1
        items = items_by_code(entries[0])
        assert items["1010"] == (as_decimal(data["total"]), Decimal("0"))
        assert items["1020"] == (Decimal("0"), as_decimal(data["total"]))

    async def test_partial_collection_stays_pending_and_hidden_from_delivery(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
            )
        ).json()["data"]
        total = as_decimal(invoice["total"])
        half = (total / 2).quantize(Decimal("0.01"))

        partial = await collect(client, admin, invoice["id"], str(half))
        assert partial.status_code == 200, partial.text
        data = partial.json()["data"]
        assert data["payment_confirmed_at"] is None
        assert as_decimal(data["paid_amount"]) == half

        # Still pending, still hidden from delivery.
        pending = (
            await client.get("/api/v1/cashier/invoices", headers=admin)
        ).json()["data"]
        assert any(i["id"] == invoice["id"] for i in pending)
        summaries = (
            await client.get("/api/v1/delivery/invoices", headers=admin)
        ).json()["data"]
        assert all(s["id"] != invoice["id"] for s in summaries)

        # Collecting the remainder completes and releases it.
        remaining = (total - half).quantize(Decimal("0.01"))
        finished = await collect(client, admin, invoice["id"], str(remaining))
        assert finished.status_code == 200, finished.text
        finished_data = finished.json()["data"]
        assert finished_data["payment_confirmed_at"] is not None
        assert as_decimal(finished_data["paid_amount"]) == total

        pending_after = (
            await client.get("/api/v1/cashier/invoices", headers=admin)
        ).json()["data"]
        assert all(i["id"] != invoice["id"] for i in pending_after)
        summaries_after = (
            await client.get("/api/v1/delivery/invoices", headers=admin)
        ).json()["data"]
        assert any(s["id"] == invoice["id"] for s in summaries_after)

        # Two separate journal entries, one per collection event.
        entries = (
            await client.get(
                "/api/v1/accounting/journal-entries",
                headers=admin,
                params={
                    "reference_type": "sales_invoice_payment",
                    "reference_id": invoice["id"],
                },
            )
        ).json()["data"]
        assert len(entries) == 2
        amounts = sorted(
            as_decimal(items_by_code(e)["1010"][0]) for e in entries
        )
        assert amounts == sorted([half, remaining])

    async def test_collection_amount_cannot_exceed_remaining_balance(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
            )
        ).json()["data"]
        too_much = str(as_decimal(invoice["total"]) + Decimal("1"))

        response = await collect(client, admin, invoice["id"], too_much)
        assert response.status_code == 400

    async def test_zero_or_negative_amount_rejected(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
            )
        ).json()["data"]

        assert (await collect(client, admin, invoice["id"], "0")).status_code == 422
        assert (await collect(client, admin, invoice["id"], "-5")).status_code == 422

    async def test_confirm_card_payment_debits_bank_account(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "card"
            )
        ).json()["data"]

        confirmed = await collect(client, admin, invoice["id"], invoice["total"])
        assert confirmed.status_code == 200, confirmed.text

        entries = (
            await client.get(
                "/api/v1/accounting/journal-entries",
                headers=admin,
                params={
                    "reference_type": "sales_invoice_payment",
                    "reference_id": invoice["id"],
                },
            )
        ).json()["data"]
        items = items_by_code(entries[0])
        # Card settles to the bank account (1015), not the cash drawer (1010).
        assert "1010" not in items
        assert as_decimal(items["1015"][0]) == as_decimal(invoice["total"])

    async def test_credit_invoice_confirmed_immediately_and_cannot_be_collected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "credit"
            )
        ).json()["data"]
        assert invoice["payment_confirmed_at"] is not None

        response = await collect(client, admin, invoice["id"], invoice["total"])
        assert response.status_code == 400
        assert "الحسابات" in response.json()["message"]

    async def test_collecting_already_completed_invoice_rejected(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
            )
        ).json()["data"]
        first = await collect(client, admin, invoice["id"], invoice["total"])
        assert first.status_code == 200
        second = await collect(client, admin, invoice["id"], invoice["total"])
        assert second.status_code == 400

    async def test_unconfirmed_cash_invoice_cannot_join_delivery_trip(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
            )
        ).json()["data"]
        trip = await create_trip(client, admin, warehouse_id)

        blocked = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": invoice["id"]},
        )
        assert blocked.status_code == 400
        assert "الصندوق" in blocked.json()["message"]

        await collect(client, admin, invoice["id"], invoice["total"])
        allowed = await client.post(
            f"/api/v1/delivery/trips/{trip['id']}/invoices",
            headers=admin,
            json={"invoice_id": invoice["id"]},
        )
        assert allowed.status_code == 200, allowed.text

    async def test_cashier_role_can_view_and_collect(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
            )
        ).json()["data"]

        listing = await client.get("/api/v1/cashier/invoices", headers=cashier)
        assert listing.status_code == 200

        confirm = await collect(client, cashier, invoice["id"], invoice["total"])
        assert confirm.status_code == 200, confirm.text

    async def test_non_cashier_roles_forbidden(self, client: AsyncClient) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
            )
        ).json()["data"]

        for headers in (sales, store):
            assert (
                await client.get("/api/v1/cashier/invoices", headers=headers)
            ).status_code == 403
            assert (
                await collect(client, headers, invoice["id"], invoice["total"])
            ).status_code == 403

    async def test_pending_invoice_stock_reduced_but_not_yet_sellable_to_delivery(
        self, client: AsyncClient
    ) -> None:
        """Stock still leaves the warehouse at sale time; only visibility is gated."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="5000")

        await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10", "cash"
        )
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("90")


class TestCashierDailySummary:
    async def _setup_catalog(self, client: AsyncClient, admin: dict[str, str]):
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "500")
        customer_id = await create_customer(client, admin, credit_limit="50000")
        return warehouse_id, product, customer_id

    async def test_summary_splits_cash_and_card_totals(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, customer_id = await self._setup_catalog(client, admin)

        cash1 = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]
        cash2 = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]
        card1 = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "card"
            )
        ).json()["data"]

        for inv in (cash1, cash2, card1):
            confirmed = await collect(client, admin, inv["id"], inv["total"])
            assert confirmed.status_code == 200, confirmed.text

        summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=admin)
        ).json()["data"]
        assert summary["movement_count"] == 3
        expected_cash = as_decimal(cash1["total"]) + as_decimal(cash2["total"])
        assert as_decimal(summary["cash_in"]) == expected_cash
        assert as_decimal(summary["card_in"]) == as_decimal(card1["total"])
        assert as_decimal(summary["total_in"]) == expected_cash + as_decimal(
            card1["total"]
        )
        assert as_decimal(summary["total_out"]) == Decimal("0")
        assert as_decimal(summary["net"]) == as_decimal(summary["total_in"])
        invoice_ids = {m["reference_id"] for m in summary["movements"]}
        assert invoice_ids == {cash1["id"], cash2["id"], card1["id"]}
        assert all(m["direction"] == "in" for m in summary["movements"])

    async def test_summary_reflects_partial_collection_on_the_day_it_happened(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, customer_id = await self._setup_catalog(client, admin)

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]
        total = as_decimal(invoice["total"])
        half = (total / 2).quantize(Decimal("0.01"))

        await collect(client, admin, invoice["id"], str(half))

        summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=admin)
        ).json()["data"]
        assert summary["movement_count"] == 1
        assert as_decimal(summary["cash_in"]) == half

    async def test_summary_scoped_to_the_confirming_cashier_only(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        warehouse_id, product, customer_id = await self._setup_catalog(client, admin)

        by_admin = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]
        by_cashier = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]

        await collect(client, admin, by_admin["id"], by_admin["total"])
        await collect(client, cashier, by_cashier["id"], by_cashier["total"])

        admin_summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=admin)
        ).json()["data"]
        cashier_summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=cashier)
        ).json()["data"]

        assert {m["reference_id"] for m in admin_summary["movements"]} == {
            by_admin["id"]
        }
        assert {m["reference_id"] for m in cashier_summary["movements"]} == {
            by_cashier["id"]
        }

    async def test_summary_day_filter_excludes_other_days(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product, customer_id = await self._setup_catalog(client, admin)

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]
        await collect(client, admin, invoice["id"], invoice["total"])

        # Push the collection event back to yesterday.
        yesterday = date.today() - timedelta(days=1)
        result = await db_session.execute(
            select(CashMovement).where(CashMovement.reference_id == invoice["id"])
        )
        db_movement = result.scalar_one()
        db_movement.collected_at = datetime.combine(
            yesterday, datetime.min.time(), tzinfo=timezone.utc
        )
        await db_session.commit()

        today_summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=admin)
        ).json()["data"]
        assert today_summary["movement_count"] == 0

        yesterday_summary = (
            await client.get(
                "/api/v1/cashier/daily-summary",
                headers=admin,
                params={"day": yesterday.isoformat()},
            )
        ).json()["data"]
        assert yesterday_summary["movement_count"] == 1
        assert yesterday_summary["movements"][0]["reference_id"] == invoice["id"]


async def post_purchase_invoice(
    client: AsyncClient,
    headers: dict[str, str],
    supplier_id: int,
    warehouse_id: int,
    product_id: int,
    payment_method: str = "cash",
):
    return await client.post(
        "/api/v1/purchases/invoices",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "warehouse_id": warehouse_id,
            "payment_method": payment_method,
            "lines": [
                {
                    "product_id": product_id,
                    "batch_number": "PB-CASHIER",
                    "expiry_date": days_from_now(120),
                    "quantity": "10",
                    "unit_cost": "20.00",
                }
            ],
        },
    )


async def pay_purchase(
    client: AsyncClient, headers: dict[str, str], invoice_id: int, amount: str
):
    return await client.post(
        f"/api/v1/cashier/purchases/{invoice_id}/pay",
        headers=headers,
        json={"amount": amount},
    )


async def post_expense(
    client: AsyncClient,
    headers: dict[str, str],
    category_id: int,
    amount: str = "100.00",
    payment_method: str = "cash",
):
    return await client.post(
        "/api/v1/expenses",
        headers=headers,
        json={
            "category_id": category_id,
            "description": "مصروف تجريبي",
            "amount": amount,
            "payment_method": payment_method,
        },
    )


async def pay_expense(
    client: AsyncClient, headers: dict[str, str], expense_id: int, amount: str
):
    return await client.post(
        f"/api/v1/cashier/expenses/{expense_id}/pay",
        headers=headers,
        json={"amount": amount},
    )


class TestCashierPayables:
    async def test_cash_purchase_invoice_pending_until_paid(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        supplier_id = await create_supplier(client, admin)

        invoice = (
            await post_purchase_invoice(
                client, admin, supplier_id, warehouse_id, product["id"], "cash"
            )
        ).json()["data"]
        assert as_decimal(invoice["paid_amount"]) == Decimal("0")
        assert invoice["payment_confirmed_at"] is None

        payables = (
            await client.get("/api/v1/cashier/payables", headers=admin)
        ).json()["data"]
        match = next(
            p
            for p in payables
            if p["payable_type"] == "purchase_invoice" and p["id"] == invoice["id"]
        )
        assert as_decimal(match["remaining"]) == as_decimal(invoice["total"])

        paid = await pay_purchase(client, admin, invoice["id"], invoice["total"])
        assert paid.status_code == 200, paid.text
        assert paid.json()["data"]["payment_confirmed_at"] is not None

        payables_after = (
            await client.get("/api/v1/cashier/payables", headers=admin)
        ).json()["data"]
        assert all(
            not (p["payable_type"] == "purchase_invoice" and p["id"] == invoice["id"])
            for p in payables_after
        )

        # Journal: Dr payable (2010), Cr cash (1010) for the invoice total.
        entries = (
            await client.get(
                "/api/v1/accounting/journal-entries",
                headers=admin,
                params={
                    "reference_type": "purchase_invoice_payment",
                    "reference_id": invoice["id"],
                },
            )
        ).json()["data"]
        items = items_by_code(entries[0])
        assert items["2010"] == (as_decimal(invoice["total"]), Decimal("0"))
        assert items["1010"] == (Decimal("0"), as_decimal(invoice["total"]))

    async def test_partial_purchase_payment_stays_pending(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        supplier_id = await create_supplier(client, admin)

        invoice = (
            await post_purchase_invoice(
                client, admin, supplier_id, warehouse_id, product["id"], "cash"
            )
        ).json()["data"]
        total = as_decimal(invoice["total"])
        half = (total / 2).quantize(Decimal("0.01"))

        partial = await pay_purchase(client, admin, invoice["id"], str(half))
        assert partial.status_code == 200
        assert partial.json()["data"]["payment_confirmed_at"] is None

        remainder = (total - half).quantize(Decimal("0.01"))
        finished = await pay_purchase(client, admin, invoice["id"], str(remainder))
        assert finished.status_code == 200
        assert finished.json()["data"]["payment_confirmed_at"] is not None

    async def test_credit_purchase_invoice_cannot_be_paid_from_cashier(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        supplier_id = await create_supplier(client, admin)

        invoice = (
            await post_purchase_invoice(
                client, admin, supplier_id, warehouse_id, product["id"], "credit"
            )
        ).json()["data"]
        assert invoice["payment_confirmed_at"] is not None

        response = await pay_purchase(client, admin, invoice["id"], invoice["total"])
        assert response.status_code == 400

    async def test_expense_pending_until_paid_then_released(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        category = await client.post(
            "/api/v1/expenses/categories", headers=admin, json={"name": "مصاريف الصندوق"}
        )
        category_id = category.json()["data"]["id"]

        expense = (
            await post_expense(client, admin, category_id, amount="200.00")
        ).json()["data"]
        assert expense["payment_confirmed_at"] is None

        paid = await pay_expense(client, admin, expense["id"], "200.00")
        assert paid.status_code == 200, paid.text
        assert paid.json()["data"]["payment_confirmed_at"] is not None

        entries = (
            await client.get(
                "/api/v1/accounting/journal-entries",
                headers=admin,
                params={
                    "reference_type": "expense_payment",
                    "reference_id": expense["id"],
                },
            )
        ).json()["data"]
        items = items_by_code(entries[0])
        assert items["2010"] == (Decimal("200.00"), Decimal("0"))
        assert items["1010"] == (Decimal("0"), Decimal("200.00"))

    async def test_payables_list_unifies_purchases_and_expenses(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        supplier_id = await create_supplier(client, admin)
        category = await client.post(
            "/api/v1/expenses/categories", headers=admin, json={"name": "بند مشترك"}
        )
        category_id = category.json()["data"]["id"]

        invoice = (
            await post_purchase_invoice(
                client, admin, supplier_id, warehouse_id, product["id"]
            )
        ).json()["data"]
        expense = (await post_expense(client, admin, category_id)).json()["data"]

        payables = (
            await client.get("/api/v1/cashier/payables", headers=admin)
        ).json()["data"]
        types_ids = {(p["payable_type"], p["id"]) for p in payables}
        assert ("purchase_invoice", invoice["id"]) in types_ids
        assert ("expense", expense["id"]) in types_ids

    async def test_cashier_role_can_pay_payables_but_not_others(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        sales = await login(client, "salesman", TEST_SALES_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        supplier_id = await create_supplier(client, admin)

        invoice = (
            await post_purchase_invoice(
                client, admin, supplier_id, warehouse_id, product["id"]
            )
        ).json()["data"]

        denied = await pay_purchase(client, sales, invoice["id"], invoice["total"])
        assert denied.status_code == 403

        allowed = await pay_purchase(client, cashier, invoice["id"], invoice["total"])
        assert allowed.status_code == 200, allowed.text

    async def test_net_daily_summary_reflects_in_and_out(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "B-1", 180, "100")
        customer_id = await create_customer(client, admin, credit_limit="50000")
        supplier_id = await create_supplier(client, admin)

        sale = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]
        await collect(client, admin, sale["id"], sale["total"])

        purchase = (
            await post_purchase_invoice(
                client, admin, supplier_id, warehouse_id, product["id"], "cash"
            )
        ).json()["data"]
        await pay_purchase(client, admin, purchase["id"], purchase["total"])

        summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=admin)
        ).json()["data"]
        assert as_decimal(summary["total_in"]) == as_decimal(sale["total"])
        assert as_decimal(summary["total_out"]) == as_decimal(purchase["total"])
        assert as_decimal(summary["net"]) == as_decimal(sale["total"]) - as_decimal(
            purchase["total"]
        )
        directions = {m["reference_type"]: m["direction"] for m in summary["movements"]}
        assert directions["sales_invoice"] == "in"
        assert directions["purchase_invoice"] == "out"
