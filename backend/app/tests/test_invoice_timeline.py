"""The invoice tracker, and the four journeys it has to tell the truth about.

A tracker is trusted on sight. Nobody cross-checks it against the warehouse, which
is exactly why a wrong one is worse than none: a shop shown "in transit" for a
parcel sitting at the depot will ring up angry, and the office will believe the
screen over the driver.

An invoice branches twice — collected or delivered, cash or on account — and the
steps genuinely differ on all four paths. These tests walk each one.
"""

from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_CASHIER_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_sales import create_customer, post_invoice, setup_stocked_catalog


async def timeline(client: AsyncClient, headers: dict, invoice_id: int) -> dict:
    response = await client.get(
        f"/api/v1/sales/invoices/{invoice_id}/timeline", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def states(data: dict) -> dict[str, str]:
    return {step["key"]: step["state"] for step in data["steps"]}


def current(data: dict) -> str | None:
    return next((s["key"] for s in data["steps"] if s["state"] == "current"), None)


async def a_cash_invoice(client: AsyncClient, admin: dict, fulfillment: str = "pickup"):
    warehouse_id, product = await setup_stocked_catalog(client, admin)
    customer_id = await create_customer(client, admin, name=f"عميل {fulfillment}",
                                        credit_limit="90000")
    response = await client.post("/api/v1/sales/invoices", headers=admin, json={
        "customer_id": customer_id, "warehouse_id": warehouse_id,
        "payment_method": "cash", "fulfillment": fulfillment, "tax_rate_ids": [],
        "lines": [{"product_id": product["id"], "quantity": "5"}],
    })
    assert response.status_code == 201, response.text
    return response.json()["data"], warehouse_id, customer_id


async def schedule(
    client: AsyncClient, admin: dict, invoice_id: int, warehouse_id: int,
    *, driver: str = "سائق", vehicle: str = "شاحنة", trip_date: str = "2026-08-11",
) -> tuple[int, dict]:
    """Put an invoice on a round: create the trip, add the stop, send it out."""
    trip = await client.post("/api/v1/delivery/trips", headers=admin, json={
        "trip_date": trip_date, "driver_name": driver,
        "vehicle": vehicle, "warehouse_id": warehouse_id,
    })
    assert trip.status_code == 201, trip.text
    trip_id = trip.json()["data"]["id"]

    added = await client.post(
        f"/api/v1/delivery/trips/{trip_id}/invoices", headers=admin,
        json={"invoice_id": invoice_id})
    assert added.status_code == 200, added.text

    dispatched = await client.post(
        f"/api/v1/delivery/trips/{trip_id}/dispatch", headers=admin)
    assert dispatched.status_code == 200, dispatched.text
    return trip_id, dispatched.json()["data"]


async def stop_of(
    client: AsyncClient, admin: dict, trip_id: int, invoice_id: int
) -> int:
    trip = (await client.get(
        f"/api/v1/delivery/trips/{trip_id}", headers=admin)).json()["data"]
    return next(s["id"] for s in trip["stops"] if s["invoice_id"] == invoice_id)


class TestTheCashierGateIsVisible:
    async def test_a_cash_invoice_waits_at_the_till_before_anything_moves(
        self, client: AsyncClient
    ) -> None:
        """The gate is real — `mark_picked_up` refuses until the money is in — so
        the tracker has to show it as the thing standing in the way."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice, _, _ = await a_cash_invoice(client, admin)

        data = await timeline(client, admin, invoice["id"])
        assert states(data)["raised"] == "done"
        assert current(data) == "payment"
        assert "التحصيل" in data["status_label"]
        # And the step after it must not look merely "not yet" — it is blocked.
        handover = next(s for s in data["steps"] if s["key"] == "handover")
        assert "تحصيل" in (handover["detail"] or "")

    async def test_collecting_the_money_advances_the_line(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        invoice, _, _ = await a_cash_invoice(client, admin)

        collected = await client.post(
            f"/api/v1/cashier/invoices/{invoice['id']}/collect",
            headers=cashier, json={"amount": str(invoice["total"])},
        )
        assert collected.status_code == 200, collected.text

        data = await timeline(client, admin, invoice["id"])
        assert states(data)["payment"] == "done"
        assert current(data) == "handover"

    async def test_an_account_sale_walks_straight_past_the_till(
        self, client: AsyncClient
    ) -> None:
        """A credit invoice is released immediately and chased later. Showing it as
        "paid" would tell the customer their debt was settled; showing it as
        "awaiting payment" would block goods the warehouse is free to hand over."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        customer_id = await create_customer(client, admin, name="عميل الحساب",
                                            credit_limit="90000")
        response = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "5",
            payment_method="credit", tax_rate_ids=[])
        assert response.status_code == 201, response.text

        data = await timeline(client, admin, response.json()["data"]["id"])
        payment = next(s for s in data["steps"] if s["key"] == "payment")
        assert payment["state"] == "done"
        assert payment["label"] == "على الحساب"
        assert "المتبقي" in payment["detail"]
        # Released: the next step is the live one, not blocked behind the till.
        # `post_invoice` defaults to delivery, so that next step is scheduling.
        assert current(data) == "scheduled"


class TestTheTwoJourneysDiffer:
    async def test_a_counter_collection_has_three_stops(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice, _, _ = await a_cash_invoice(client, admin, "pickup")
        data = await timeline(client, admin, invoice["id"])

        assert [s["key"] for s in data["steps"]] == ["raised", "payment", "handover"]
        assert data["shipped_via"] == "استلام من المستودع"
        # Nothing to promise about a date the customer chooses themselves.
        assert data["expected"] is None

    async def test_a_delivery_has_five_and_names_no_trip_yet(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice, _, _ = await a_cash_invoice(client, admin, "delivery")
        data = await timeline(client, admin, invoice["id"])

        assert [s["key"] for s in data["steps"]] == [
            "raised", "payment", "scheduled", "transit", "delivered",
        ]
        assert "لم تُجدول" in data["shipped_via"]

    async def test_handing_the_goods_over_completes_a_pickup(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        invoice, _, _ = await a_cash_invoice(client, admin, "pickup")
        await client.post(
            f"/api/v1/cashier/invoices/{invoice['id']}/collect",
            headers=cashier, json={"amount": str(invoice["total"])})

        handed = await client.post(
            f"/api/v1/sales/invoices/{invoice['id']}/pickup", headers=admin)
        assert handed.status_code == 200, handed.text

        data = await timeline(client, admin, invoice["id"])
        assert all(s["state"] == "done" for s in data["steps"])
        assert current(data) is None
        assert data["status_label"] == "تم الاستلام"


class TestADeliveryOnTheRoad:
    async def test_scheduling_and_delivering_walk_the_line_forwards(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        invoice, warehouse_id, _ = await a_cash_invoice(client, admin, "delivery")
        await client.post(
            f"/api/v1/cashier/invoices/{invoice['id']}/collect",
            headers=cashier, json={"amount": str(invoice["total"])})

        trip_id, _ = await schedule(
            client, admin, invoice["id"], warehouse_id,
            driver="سائق التتبع", vehicle="شاحنة 9", trip_date="2026-08-11")

        data = await timeline(client, admin, invoice["id"])
        assert states(data)["scheduled"] == "done"
        assert data["shipped_via"] == "شاحنة 9"
        assert data["expected"] == "2026-08-11"

        stop_id = await stop_of(client, admin, trip_id, invoice["id"])
        marked = await client.post(
            f"/api/v1/delivery/trips/{trip_id}/stops/{stop_id}/status",
            headers=admin, json={"status": "delivered"})
        assert marked.status_code == 200, marked.text

        done = await timeline(client, admin, invoice["id"])
        assert states(done)["delivered"] == "done"
        assert done["status_label"] == "تم التسليم"

    async def test_a_failed_attempt_stops_the_line_instead_of_pretending(
        self, client: AsyncClient
    ) -> None:
        """The case a tracker most wants to gloss over.

        Goods back at the depot are not "on the way". Marking the step failed —
        and leaving nothing after it as "current" — is the difference between a
        screen that reports and a screen that reassures.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        cashier = await login(client, "cashier", TEST_CASHIER_PASSWORD)
        invoice, warehouse_id, _ = await a_cash_invoice(client, admin, "delivery")
        await client.post(
            f"/api/v1/cashier/invoices/{invoice['id']}/collect",
            headers=cashier, json={"amount": str(invoice["total"])})

        trip_id, _ = await schedule(client, admin, invoice["id"], warehouse_id)
        stop_id = await stop_of(client, admin, trip_id, invoice["id"])
        failed = await client.post(
            f"/api/v1/delivery/trips/{trip_id}/stops/{stop_id}/status",
            headers=admin, json={"status": "failed", "notes": "المحل مغلق"})
        assert failed.status_code == 200, failed.text

        data = await timeline(client, admin, invoice["id"])
        assert states(data)["transit"] == "failed"
        assert states(data)["delivered"] == "pending"
        assert current(data) is None, "خطوة بعد الفشل ظهرت كأن الرحلة مستمرة"
        assert "تعذّر" in data["status_label"]
        assert "المحل مغلق" in next(
            s for s in data["steps"] if s["key"] == "transit")["detail"]


class TestWhoMayLook:
    async def test_a_salesman_cannot_track_another_reps_invoice(
        self, client: AsyncClient
    ) -> None:
        """Same rule as viewing the invoice — the tracker must not be a side door
        around it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        invoice, _, _ = await a_cash_invoice(client, admin, "pickup")
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)

        refused = await client.get(
            f"/api/v1/sales/invoices/{invoice['id']}/timeline", headers=salesman)
        assert refused.status_code == 403
