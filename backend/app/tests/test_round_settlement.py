"""Integration tests for closing a salesman's round (تسوية جولة المندوب).

The properties under test are the ones that make the close worth having: cash
must reach the drawer before a round can be signed off, a stock difference must
never pass silently, and the figures recorded at sign-off must be a snapshot
rather than a live view that drifts afterwards.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    TEST_STORE_PASSWORD,
    login,
)
from app.tests.test_cashier import collect
from app.tests.test_field_sync import (
    assign_van,
    load_van,
    own_customer,
    post_sync,
    sale,
    salesman_id,
)
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer
from app.tests.test_stocktakes import open_count, save_count


async def open_round(
    client: AsyncClient, headers: dict[str, str], warehouse_id: int, **extra
) -> dict:
    body = {"warehouse_id": warehouse_id}
    body.update(extra)
    response = await client.post("/api/v1/sales/rounds", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def position(
    client: AsyncClient, headers: dict[str, str], warehouse_id: int
) -> dict:
    response = await client.get(
        f"/api/v1/sales/rounds/position?warehouse_id={warehouse_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def settle(
    client: AsyncClient, headers: dict[str, str], settlement_id: int, **body
) -> tuple[int, dict]:
    """Returns (status_code, payload) so refusals can be asserted on directly."""
    response = await client.post(
        f"/api/v1/sales/rounds/{settlement_id}/settle", headers=headers, json=body
    )
    return response.status_code, response.json()


async def a_van_with_one_cash_sale(
    client: AsyncClient, admin: dict[str, str], db_session: AsyncSession
) -> tuple[int, int, dict]:
    """A loaded van, one synced cash sale off it. Returns (van_id, product_id, invoice)."""
    main_id = await create_warehouse(client, admin, "الرئيسي")
    product = await create_product(client, admin, "RS-1", warehouse_id=main_id)
    await receive(client, admin, product["id"], main_id, "MAIN-1", 200, "500")
    van_id = await assign_van(client, admin, db_session)
    await load_van(client, admin, product["id"], van_id, "80")
    customer_id = await own_customer(client, admin, db_session, "بقالة الجولة")

    salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
    await post_sync(
        client,
        salesman,
        documents=[
            sale("rs-uuid-0001-0000000000", product["id"], "10", customer_id=customer_id)
        ],
    )
    invoices = (
        await client.get("/api/v1/sales/invoices", headers=admin)
    ).json()["data"]
    return van_id, product["id"], invoices[0]


class TestOpeningARound:
    async def test_a_fixed_warehouse_cannot_have_a_round(
        self, client: AsyncClient
    ) -> None:
        """Settlement is about vans; a building does not go anywhere."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "مستودع ثابت")
        response = await client.post(
            "/api/v1/sales/rounds", headers=admin, json={"warehouse_id": main_id}
        )
        assert response.status_code == 400
        assert "مركبة" in response.json()["message"]

    async def test_an_unassigned_van_cannot_have_a_round(
        self, client: AsyncClient
    ) -> None:
        """Without a driver there is nobody to settle with."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        created = await client.post(
            "/api/v1/inventory/warehouses",
            headers=admin,
            json={"name": "مركبة بلا مندوب", "is_vehicle": True},
        )
        van_id = created.json()["data"]["id"]
        response = await client.post(
            "/api/v1/sales/rounds", headers=admin, json={"warehouse_id": van_id}
        )
        assert response.status_code == 400
        assert "غير مسندة" in response.json()["message"]

    async def test_only_one_round_open_per_van(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Otherwise two half-closed days could exist for one vehicle at once."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id = await assign_van(client, admin, db_session)
        await open_round(client, admin, van_id)

        response = await client.post(
            "/api/v1/sales/rounds", headers=admin, json={"warehouse_id": van_id}
        )
        assert response.status_code == 400
        assert "جولة مفتوحة" in response.json()["message"]

    async def test_a_salesman_cannot_settle_their_own_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Separation of duties: selling and signing off are different jobs."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id = await assign_van(client, admin, db_session)
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.post(
            "/api/v1/sales/rounds", headers=salesman, json={"warehouse_id": van_id}
        )
        assert response.status_code == 403


class TestTheCashGate:
    async def test_uncollected_cash_blocks_the_close(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point: a round is not closed while the money is in a pocket."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        settlement = await open_round(client, admin, van_id)

        state = await position(client, admin, van_id)
        assert state["invoice_count"] == 1
        assert Decimal(state["cash_outstanding_total"]) == Decimal(invoice["total"])
        assert state["can_settle"] is False
        assert any("لم يُحصَّل" in b for b in state["blockers"])

        status, body = await settle(client, admin, settlement["id"])
        assert status == 400
        assert "لم يُحصَّل" in body["message"]

    async def test_closes_once_the_cashier_has_the_money(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        settlement = await open_round(client, admin, van_id)

        await collect(client, admin, invoice["id"], invoice["total"])

        state = await position(client, admin, van_id)
        assert Decimal(state["cash_outstanding_total"]) == Decimal("0")
        assert state["can_settle"] is True
        assert state["blockers"] == []

        status, body = await settle(client, admin, settlement["id"])
        assert status == 200, body
        closed = body["data"]
        assert closed["status"] == "settled"
        assert closed["settled_at"] is not None
        assert closed["invoice_count"] == 1
        assert Decimal(closed["cash_collected_total"]) == Decimal(invoice["total"])
        assert Decimal(closed["cash_outstanding_total"]) == Decimal("0")

    async def test_partial_collection_still_blocks(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Half the money is not the money."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        settlement = await open_round(client, admin, van_id)

        half = (Decimal(invoice["total"]) / 2).quantize(Decimal("0.01"))
        await collect(client, admin, invoice["id"], str(half))

        state = await position(client, admin, van_id)
        assert Decimal(state["cash_outstanding_total"]) > 0
        status, _ = await settle(client, admin, settlement["id"])
        assert status == 400

    async def test_credit_sales_are_not_the_salesmans_to_hand_over(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A credit sale is the customer's debt, chased through their account.

        Counting it as cash owed tonight would make any round containing one
        impossible to close — which is most rounds in a wholesale business.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "RS-CR", warehouse_id=main_id)
        await receive(client, admin, product["id"], main_id, "MAIN-1", 200, "500")
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "80")
        # A credit limit is required, or the invoice is refused for exceeding it —
        # a rejection the sync reports per document rather than raising.
        customer_id = await create_customer(
            client,
            admin,
            "بقالة الآجل",
            credit_limit="5000",
            salesman_id=await salesman_id(db_session),
        )

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        synced = await post_sync(
            client,
            salesman,
            documents=[
                sale(
                    "rs-uuid-credit-000000",
                    product["id"],
                    "5",
                    customer_id=customer_id,
                    payment_method="credit",
                )
            ],
        )
        # Assert the sale actually landed. Without this the test would pass
        # vacuously on a rejected document, which is how the first version of it
        # reported a zero credit total and looked like a service bug.
        assert synced["created_count"] == 1, synced["results"]
        settlement = await open_round(client, admin, van_id)

        state = await position(client, admin, van_id)
        assert Decimal(state["credit_sales_total"]) > 0
        # Nothing is owed to the drawer, so the round closes with no collection.
        assert Decimal(state["cash_outstanding_total"]) == Decimal("0")
        status, body = await settle(client, admin, settlement["id"])
        assert status == 200, body
        assert Decimal(body["data"]["credit_sales_total"]) > 0


class TestTheVarianceGate:
    async def test_a_difference_without_a_reason_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A shortfall may be accepted, but never silently."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, product_id, invoice = await a_van_with_one_cash_sale(
            client, admin, db_session
        )
        await collect(client, admin, invoice["id"], invoice["total"])
        settlement = await open_round(client, admin, van_id)

        # Count the van two units short of what the books expect and post it.
        stocktake = await open_count(client, admin, van_id)
        expected = Decimal(stocktake["lines"][0]["expected_quantity"])
        await save_count(client, admin, stocktake, str(expected - 2))
        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text

        status, body = await settle(
            client, admin, settlement["id"], stocktake_id=stocktake["id"]
        )
        assert status == 400
        assert "سبب" in body["message"]

        # With a reason, the same close succeeds and keeps the difference on record.
        status, body = await settle(
            client,
            admin,
            settlement["id"],
            stocktake_id=stocktake["id"],
            notes="كسر عبوتين أثناء النقل",
        )
        assert status == 200, body
        closed = body["data"]
        # The goods were received without a cost, so the difference has no *value*
        # — but two units are genuinely missing. The record must say so, and the
        # round must not read as balanced just because the money side is zero.
        assert Decimal(closed["stock_variance_qty"]) == Decimal("-2")
        assert Decimal(closed["stock_variance_value"]) == Decimal("0.00")
        assert closed["is_balanced"] is False
        assert "كسر" in closed["notes"]

    async def test_an_unposted_count_cannot_be_linked(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Linking a count that has not settled its differences would record a
        variance the stock has not actually taken."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])
        settlement = await open_round(client, admin, van_id)

        stocktake = await open_count(client, admin, van_id)  # left counting
        status, body = await settle(
            client, admin, settlement["id"], stocktake_id=stocktake["id"]
        )
        assert status == 400
        assert "لم يُرحَّل" in body["message"]


class TestLifecycle:
    async def test_a_settled_round_cannot_be_settled_again(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])
        settlement = await open_round(client, admin, van_id)

        status, _ = await settle(client, admin, settlement["id"])
        assert status == 200
        status, body = await settle(client, admin, settlement["id"])
        assert status == 400
        assert "غير مفتوحة" in body["message"]

    async def test_cancelling_frees_the_van_for_a_new_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id = await assign_van(client, admin, db_session)
        settlement = await open_round(client, admin, van_id)

        cancelled = await client.post(
            f"/api/v1/sales/rounds/{settlement['id']}/cancel", headers=admin
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "cancelled"

        # The van is free again — the partial unique index only guards open rounds.
        await open_round(client, admin, van_id)

    async def test_a_settled_round_cannot_be_cancelled(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """It is a signed record, not a draft."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])
        settlement = await open_round(client, admin, van_id)
        await settle(client, admin, settlement["id"])

        response = await client.post(
            f"/api/v1/sales/rounds/{settlement['id']}/cancel", headers=admin
        )
        assert response.status_code == 400

    async def test_the_snapshot_does_not_drift_after_signing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The figures are what was true at sign-off.

        A later sale off the same van on the same day must not silently rewrite a
        round somebody already signed.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, product_id, invoice = await a_van_with_one_cash_sale(
            client, admin, db_session
        )
        await collect(client, admin, invoice["id"], invoice["total"])
        settlement = await open_round(client, admin, van_id)
        status, body = await settle(client, admin, settlement["id"])
        assert status == 200
        signed_total = Decimal(body["data"]["cash_sales_total"])
        assert body["data"]["invoice_count"] == 1

        # Another sale lands afterwards.
        customer_id = await own_customer(client, admin, db_session, "بقالة متأخّرة")
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        await post_sync(
            client,
            salesman,
            documents=[
                sale("rs-uuid-late-00000000", product_id, "3", customer_id=customer_id)
            ],
        )

        stored = (
            await client.get("/api/v1/sales/rounds", headers=admin)
        ).json()["data"]
        settled_row = next(r for r in stored if r["id"] == settlement["id"])
        assert settled_row["invoice_count"] == 1
        assert Decimal(settled_row["cash_sales_total"]) == signed_total


class TestVarianceApproval:
    async def test_a_valued_shortfall_beyond_the_limit_needs_a_supervisor(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The storekeeper counts the van but may not sign off a large shortfall.

        Separation of duties: whoever counted should not be the one who accepts
        what is missing. Below the limit they may close it themselves.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "RS-COST", warehouse_id=main_id)
        # Received *with* a unit cost, so the difference carries a value.
        await client.post(
            "/api/v1/inventory/stock/receive",
            headers=admin,
            json={
                "product_id": product["id"],
                "warehouse_id": main_id,
                "batch_number": "COST-1",
                "expiry_date": str(date.today() + timedelta(days=200)),
                "quantity": "500",
                "unit_cost": "40.00",
            },
        )
        van_id = await assign_van(client, admin, db_session)
        await client.post(
            "/api/v1/inventory/stock/transfer",
            headers=admin,
            json={
                "product_id": product["id"],
                "from_warehouse_id": main_id,
                "to_warehouse_id": van_id,
                "quantity": "80",
            },
        )
        settlement = await open_round(client, admin, van_id)

        # Five units short at 40.00 = 200.00, well past the 50.00 default limit.
        stocktake = await open_count(client, admin, van_id)
        expected = Decimal(stocktake["lines"][0]["expected_quantity"])
        await save_count(client, admin, stocktake, str(expected - 5))
        posted = await client.post(
            f"/api/v1/inventory/stocktakes/{stocktake['id']}/post", headers=admin
        )
        assert posted.status_code == 200, posted.text

        state = await position(client, admin, van_id)
        assert state["variance_needs_approval"] is True

        storekeeper = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        status, body = await settle(
            client,
            storekeeper,
            settlement["id"],
            stocktake_id=stocktake["id"],
            notes="نقص خمس عبوات",
        )
        assert status == 403
        assert "إقرار" in body["message"]

        # The admin holds the approval permission, so the same close succeeds.
        status, body = await settle(
            client,
            admin,
            settlement["id"],
            stocktake_id=stocktake["id"],
            notes="نقص خمس عبوات — أُقرّ بعد المراجعة",
        )
        assert status == 200, body
        assert Decimal(body["data"]["stock_variance_value"]) < 0


class TestOneStepClose:
    async def test_settling_a_van_opens_the_round_if_nobody_did(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The common path: count the van, sign off, done.

        A separate open recorded only a date and a note, so requiring it added a
        step that could be forgotten — and a forgotten open left a day's sales
        unsettled for no visible reason.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])

        assert (await client.get("/api/v1/sales/rounds", headers=admin)).json()["data"] == []

        response = await client.post(
            "/api/v1/sales/rounds/settle-van",
            headers=admin,
            json={"warehouse_id": van_id},
        )
        assert response.status_code == 200, response.text
        closed = response.json()["data"]
        assert closed["status"] == "settled"
        assert closed["invoice_count"] == 1

    async def test_one_step_close_honours_the_cash_gate(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Convenience must not become a way around the gate."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, _ = await a_van_with_one_cash_sale(client, admin, db_session)

        response = await client.post(
            "/api/v1/sales/rounds/settle-van",
            headers=admin,
            json={"warehouse_id": van_id},
        )
        assert response.status_code == 400
        assert "لم يُحصَّل" in response.json()["message"]

    async def test_it_adopts_an_already_open_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Whoever opened it in the morning keeps their record, not a second one."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])
        opened = await open_round(client, admin, van_id, notes="تحميل الصباح")

        response = await client.post(
            "/api/v1/sales/rounds/settle-van",
            headers=admin,
            json={"warehouse_id": van_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["id"] == opened["id"]
        rounds = (await client.get("/api/v1/sales/rounds", headers=admin)).json()["data"]
        assert len(rounds) == 1


class TestTheRecordIsReadable:
    async def test_a_settlement_carries_the_van_and_salesman_names(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Ids are not a report.

        The history table showed blank van and salesman columns until the record
        exposed the names — a settlement identified only by "#1" tells whoever is
        reviewing the day nothing at all.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])

        settled = await client.post(
            "/api/v1/sales/rounds/settle-van", headers=admin, json={"warehouse_id": van_id}
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["data"]["warehouse_name"], "the settle response has no van name"

        rounds = (await client.get("/api/v1/sales/rounds", headers=admin)).json()["data"]
        assert rounds[0]["warehouse_name"]
        assert rounds[0]["salesman_name"]

    async def test_notes_survive_the_close(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A reason nobody can read later is not a reason."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])

        response = await client.post(
            "/api/v1/sales/rounds/settle-van",
            headers=admin,
            json={"warehouse_id": van_id, "notes": "سلّم النقد كاملاً"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["notes"] == "سلّم النقد كاملاً"


class TestReassigningTheVan:
    async def test_an_open_round_keeps_its_own_salesman(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Whose round it is was decided when it opened, not by who drives next.

        Reading the van's *current* assignee instead would hide the open round's
        own sales the moment a vehicle changed hands — the position would query
        the new salesman, find nothing, and let a full day close showing zero.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id, _, invoice = await a_van_with_one_cash_sale(client, admin, db_session)
        await collect(client, admin, invoice["id"], invoice["total"])
        await open_round(client, admin, van_id)

        # Hand the van to somebody else while the round is still open.
        # A vehicle may only be handed to another salesman, so make one.
        created = await client.post(
            "/api/v1/auth/users",
            headers=admin,
            json={
                "username": "salesman2",
                "full_name": "مندوب المبيعات الثاني",
                "password": "Sales2@Test1234",
                "role": "sales",
            },
        )
        assert created.status_code == 201, created.text
        other = created.json()["data"]
        moved = await client.patch(
            f"/api/v1/inventory/warehouses/{van_id}",
            headers=admin,
            json={"assigned_to_id": other["id"]},
        )
        assert moved.status_code == 200, moved.text

        # The round still knows whose day it is, and still sees the day's sale.
        pos = await position(client, admin, van_id)
        assert pos["invoice_count"] == 1
        assert pos["total_sales"] == invoice["total"]
