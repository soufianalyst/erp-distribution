"""Integration tests for the offline salesman round: van sales, orders, and sync.

The properties under test are the ones a bad connection attacks: replaying a
batch must not duplicate anything, one bad document must not cost the rest of
the round, and a van sale must draw on the van rather than the main warehouse.
"""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.sales import SalesInvoice, SalesInvoiceLine
from app.domain.models.user import User, UserRole
from app.tests.conftest import (
    DEFAULT_TAX_RATE_ID,
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_inventory import (
    as_decimal,
    create_product,
    create_warehouse,
    receive,
)
from app.tests.test_sales import create_customer


async def salesman_id(db_session: AsyncSession) -> int:
    salesman = (
        await db_session.execute(select(User).where(User.role == UserRole.SALES))
    ).scalars().first()
    return salesman.id


async def own_customer(
    client: AsyncClient, admin: dict[str, str], db_session: AsyncSession, name: str
) -> int:
    """A shop on this salesman's round. Unassigned customers belong to nobody,
    and the salesman is barred from invoicing them (see ensure_customer_access).
    """
    return await create_customer(
        client, admin, name, salesman_id=await salesman_id(db_session)
    )


async def assign_van(
    client: AsyncClient, admin: dict[str, str], db_session: AsyncSession, name: str = "مركبة المندوب"
) -> int:
    """Create a vehicle warehouse and hand it to the salesman, the way an admin
    does it from the warehouses page."""
    response = await client.post(
        "/api/v1/inventory/warehouses",
        headers=admin,
        json={
            "name": name,
            "is_vehicle": True,
            "assigned_to_id": await salesman_id(db_session),
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["id"])


async def load_van(
    client: AsyncClient,
    admin: dict[str, str],
    product_id: int,
    van_id: int,
    quantity: str = "100",
    batch: str = "VAN-1",
) -> None:
    """The morning load-out — an ordinary receipt into the van warehouse."""
    await receive(client, admin, product_id, van_id, batch, 200, quantity)


def sale(client_uuid: str, product_id: int, quantity: str, **kwargs) -> dict:
    body = {
        "client_uuid": client_uuid,
        "kind": "van_sale",
        "payment_method": "cash",
        "tax_rate_ids": [DEFAULT_TAX_RATE_ID],
        "lines": [{"product_id": product_id, "quantity": quantity}],
    }
    body.update(kwargs)
    return body


async def post_sync(client: AsyncClient, headers: dict[str, str], **payload) -> dict:
    response = await client.post("/api/v1/sales/field/sync", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def result_for(data: dict, client_uuid: str) -> dict:
    return next(r for r in data["results"] if r["client_uuid"] == client_uuid)


class TestVanSnapshot:
    async def test_van_reports_what_it_carries(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "VAN-A", warehouse_id=main_id)
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "60")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get("/api/v1/sales/field/van", headers=salesman)
        assert response.status_code == 200, response.text
        van = response.json()["data"]
        assert van["warehouse_id"] == van_id
        assert len(van["lines"]) == 1
        assert as_decimal(van["lines"][0]["quantity"]) == Decimal("60")

    async def test_salesman_without_a_van_is_told_so(self, client: AsyncClient) -> None:
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get("/api/v1/sales/field/van", headers=salesman)
        assert response.status_code == 404
        assert "مركبة" in response.json()["message"]


class TestVanSales:
    async def test_van_sale_draws_on_the_van_not_the_warehouse(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point of modelling a van as a warehouse."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "DRAW-1", warehouse_id=main_id)
        await receive(client, admin, product["id"], main_id, "MAIN-1", 200, "500")
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "80")
        customer_id = await own_customer(client, admin, db_session, "بقالة الحي")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(
            client,
            salesman,
            documents=[sale("uuid-sale-1-0000000000", product["id"], "30", customer_id=customer_id)],
        )
        assert data["created_count"] == 1

        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        by_batch = {b["batch_number"]: as_decimal(b["quantity"]) for b in batches}
        # 30 came off the van; the main warehouse is untouched.
        assert by_batch["VAN-1"] == Decimal("50")
        assert by_batch["MAIN-1"] == Decimal("500")

        # And the invoice must *say* so, not merely behave so. The stock moving
        # correctly while the line recorded the product's home warehouse is a real
        # bug this suite once missed: every field sale was attributed to the main
        # store, which silently breaks per-warehouse reporting and made it
        # impossible to tell which invoices belonged to a van's round.
        lines = (
            await db_session.execute(
                select(SalesInvoiceLine).where(
                    SalesInvoiceLine.product_id == product["id"]
                )
            )
        ).scalars().all()
        assert lines, "expected the sale to have produced invoice lines"
        assert {line.warehouse_id for line in lines} == {van_id}

        # And the invoice *header*, not only its lines. DeliveryService reads the
        # header to decide which warehouse a trip ships from, and refuses an
        # invoice whose warehouse differs from the trip's — so a van sale carrying
        # the main store on its header would be rejected from its own van's trip
        # and accepted onto the main store's.
        invoice_ids = {line.invoice_id for line in lines}
        headers = (
            await db_session.execute(
                select(SalesInvoice).where(SalesInvoice.id.in_(invoice_ids))
            )
        ).scalars().all()
        assert {header.warehouse_id for header in headers} == {van_id}

    async def test_selling_more_than_the_van_holds_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "SHORT-1", warehouse_id=main_id)
        # Plenty in the warehouse, little on the van: the van is what counts.
        await receive(client, admin, product["id"], main_id, "MAIN-1", 200, "500")
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "10")
        customer_id = await own_customer(client, admin, db_session, "بقالة الحي")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(
            client,
            salesman,
            documents=[sale("uuid-short-0000000000", product["id"], "40", customer_id=customer_id)],
        )
        assert data["failed_count"] == 1
        assert "الكمية المتوفرة غير كافية" in result_for(data, "uuid-short-0000000000")["message"]

    async def test_order_records_no_stock_movement(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Order taking is the other half: nothing leaves the van."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "ORDER-1", warehouse_id=main_id)
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "50")
        customer_id = await own_customer(client, admin, db_session, "سوبرماركت الطلبات")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(
            client,
            salesman,
            documents=[
                sale("uuid-order-0000000000", product["id"], "25", customer_id=customer_id)
                | {"kind": "order"}
            ],
        )
        assert data["created_count"] == 1
        assert result_for(data, "uuid-order-0000000000")["kind"] == "order"

        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("50")

        # It lands as a quotation for the office to convert and fulfil.
        quotes = (
            await client.get("/api/v1/sales/quotations", headers=admin)
        ).json()["data"]
        assert len(quotes) == 1


class TestOfflineCustomers:
    async def test_customer_created_offline_is_resolved_into_the_sale(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The ordering guarantee: the shop only exists on the device until now."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "NEWC-1", warehouse_id=main_id)
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "50")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(
            client,
            salesman,
            customers=[
                {
                    "client_uuid": "uuid-cust-1-0000000000",
                    "name": "بقالة جديدة في الجولة",
                    "phone": "0790000000",
                }
            ],
            documents=[
                sale("uuid-sale-1-0000000000", product["id"], "5", customer_uuid="uuid-cust-1-0000000000")
            ],
        )
        assert data["failed_count"] == 0
        customer_result = result_for(data, "uuid-cust-1-0000000000")
        sale_result = result_for(data, "uuid-sale-1-0000000000")
        assert customer_result["status"] == "created"
        assert sale_result["status"] == "created"

        invoice = (
            await client.get(
                f"/api/v1/sales/invoices/{sale_result['server_id']}", headers=admin
            )
        ).json()["data"]
        assert invoice["customer_id"] == customer_result["server_id"]

    async def test_name_clash_is_reported_not_merged(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Head office added the same shop while the salesman was offline. Only a
        human can tell a real duplicate from two shops sharing a name."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await own_customer(client, admin, db_session, "بقالة مكررة")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(
            client,
            salesman,
            customers=[{"client_uuid": "uuid-dup-0000000000", "name": "بقالة مكررة"}],
        )
        assert data["failed_count"] == 1
        assert result_for(data, "uuid-dup-0000000000")["status"] == "failed"
        assert "بهذا الاسم" in result_for(data, "uuid-dup-0000000000")["message"]

    async def test_a_sale_whose_customer_failed_is_also_reported(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "ORPH-1", warehouse_id=main_id)
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "50")
        await own_customer(client, admin, db_session, "بقالة مكررة")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(
            client,
            salesman,
            customers=[{"client_uuid": "uuid-dup-0000000000", "name": "بقالة مكررة"}],
            documents=[
                sale("uuid-orphan-0000000000", product["id"], "5", customer_uuid="uuid-dup-0000000000")
            ],
        )
        assert data["failed_count"] == 2
        assert "تعذّر تحديد العميل" in result_for(data, "uuid-orphan-0000000000")["message"]


class TestReplaySafety:
    async def test_resending_the_whole_round_creates_nothing_new(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The property that makes offline safe: a lost response must not cost a
        second invoice when the app retries."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "REPLAY-1", warehouse_id=main_id)
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "100")

        payload = dict(
            customers=[{"client_uuid": "uuid-cust-1-0000000000", "name": "بقالة الإعادة"}],
            documents=[
                sale("uuid-sale-1-0000000000", product["id"], "10", customer_uuid="uuid-cust-1-0000000000"),
                sale("uuid-order-1-0000000000", product["id"], "7", customer_uuid="uuid-cust-1-0000000000")
                | {"kind": "order"},
            ],
        )

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        first = await post_sync(client, salesman, **payload)
        assert first["created_count"] == 3
        assert first["duplicate_count"] == 0

        second = await post_sync(client, salesman, **payload)
        assert second["created_count"] == 0
        assert second["duplicate_count"] == 3
        assert all(r["status"] == "duplicate" for r in second["results"])
        # And the replay reports the same ids the first attempt produced.
        for uuid in ("uuid-cust-1-0000000000", "uuid-sale-1-0000000000", "uuid-order-1-0000000000"):
            assert result_for(second, uuid)["server_id"] == result_for(first, uuid)["server_id"]

        invoices = (await client.get("/api/v1/sales/invoices", headers=admin)).json()["data"]["items"]
        assert len(invoices) == 1
        customers = (await client.get("/api/v1/sales/customers", headers=admin)).json()["data"]
        assert len([c for c in customers if c["name"] == "بقالة الإعادة"]) == 1
        # Stock moved once, not twice.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("90")


class TestPartialSuccess:
    async def test_one_bad_document_does_not_lose_the_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "PARTIAL-1", warehouse_id=main_id)
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "20")
        customer_id = await own_customer(client, admin, db_session, "بقالة الجولة")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(
            client,
            salesman,
            documents=[
                sale("uuid-ok-1-0000000000", product["id"], "5", customer_id=customer_id),
                # More than the van holds — this one must fail alone.
                sale("uuid-bad-0000000000", product["id"], "999", customer_id=customer_id),
                sale("uuid-ok-2-0000000000", product["id"], "4", customer_id=customer_id),
            ],
        )
        assert data["created_count"] == 2
        assert data["failed_count"] == 1
        assert result_for(data, "uuid-ok-1-0000000000")["status"] == "created"
        assert result_for(data, "uuid-bad-0000000000")["status"] == "failed"
        assert result_for(data, "uuid-ok-2-0000000000")["status"] == "created"

        # The two good sales really persisted: 20 - 5 - 4.
        batches = (
            await client.get(
                f"/api/v1/inventory/products/{product['id']}/batches", headers=admin
            )
        ).json()["data"]
        assert as_decimal(batches[0]["quantity"]) == Decimal("11")

    async def test_retrying_after_a_failure_syncs_only_the_missing_one(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """How the app recovers: the queue is resent once the van is restocked."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        main_id = await create_warehouse(client, admin, "الرئيسي")
        product = await create_product(client, admin, "RETRY-1", warehouse_id=main_id)
        van_id = await assign_van(client, admin, db_session)
        await load_van(client, admin, product["id"], van_id, "10")
        customer_id = await own_customer(client, admin, db_session, "بقالة الإعادة")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        payload = dict(
            documents=[
                sale("uuid-ok-0000000000", product["id"], "4", customer_id=customer_id),
                sale("uuid-later-0000000000", product["id"], "30", customer_id=customer_id),
            ]
        )
        first = await post_sync(client, salesman, **payload)
        assert first["created_count"] == 1
        assert first["failed_count"] == 1

        # Restock the van, then resend the same queue.
        await load_van(client, admin, product["id"], van_id, "50", batch="VAN-2")
        second = await post_sync(client, salesman, **payload)
        assert second["duplicate_count"] == 1  # the one that already landed
        assert second["created_count"] == 1  # the one that can now be served
        assert second["failed_count"] == 0


class TestFieldAccess:
    async def test_storekeeper_cannot_sync_a_round(self, client: AsyncClient) -> None:
        from app.tests.conftest import TEST_STORE_PASSWORD

        store = await login(client, "storekeeper", TEST_STORE_PASSWORD)
        response = await client.post(
            "/api/v1/sales/field/sync", headers=store, json={"customers": [], "documents": []}
        )
        assert response.status_code == 403

    async def test_empty_batch_is_accepted(self, client: AsyncClient) -> None:
        """A round with nothing to report is normal, not an error."""
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        data = await post_sync(client, salesman)
        assert data == {
            "created_count": 0,
            "duplicate_count": 0,
            "failed_count": 0,
            "results": [],
        }


class TestOneVanPerSalesman:
    """A salesman drives one vehicle, and the field app depends on that.

    Found by driving the system end to end rather than by a unit test: a second
    van was assigned to a salesman who already had one — an ordinary mistake, a
    new vehicle with the old one never unassigned — and every field sale silently
    went to whichever van the query happened to return first. The app showed van
    A's stock, the sales came off van B, and the round settled for the van he
    actually drove reported nothing at all.
    """

    async def test_a_second_van_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        first = await assign_van(client, admin, db_session, name="مركبة أولى")

        response = await client.post(
            "/api/v1/inventory/warehouses",
            headers=admin,
            json={
                "name": "مركبة ثانية",
                "is_vehicle": True,
                "assigned_to_id": await salesman_id(db_session),
            },
        )
        assert response.status_code == 400, response.text
        message = response.json()["message"]
        # The message has to name the van already held, or the admin cannot act on it.
        assert "مركبة أولى" in message, message

    async def test_reassigning_by_update_is_refused_too(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The create path is not the only way in."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await assign_van(client, admin, db_session, name="مركبة قائمة")
        spare = await client.post(
            "/api/v1/inventory/warehouses",
            headers=admin,
            json={"name": "مركبة احتياطية", "is_vehicle": True},
        )
        assert spare.status_code == 201, spare.text

        response = await client.patch(
            f"/api/v1/inventory/warehouses/{spare.json()['data']['id']}",
            headers=admin,
            json={"assigned_to_id": await salesman_id(db_session)},
        )
        assert response.status_code == 400, response.text
        assert "مركبة قائمة" in response.json()["message"]

    async def test_saving_the_same_van_unchanged_still_works(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The rule must not fire against the van being edited.

        Re-saving the warehouses form without changing the driver is the most
        ordinary action there is; a guard that rejected it would be worse than the
        bug it fixes.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id = await assign_van(client, admin, db_session)
        rep = await salesman_id(db_session)

        response = await client.patch(
            f"/api/v1/inventory/warehouses/{van_id}",
            headers=admin,
            json={"assigned_to_id": rep, "location": "مسار الشرق"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["assigned_to_id"] == rep

    async def test_a_van_can_be_handed_over_after_unassigning(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The rule constrains, it must not trap: freeing the first van releases him."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        old = await assign_van(client, admin, db_session, name="المركبة القديمة")
        rep = await salesman_id(db_session)
        new = await client.post(
            "/api/v1/inventory/warehouses",
            headers=admin,
            json={"name": "المركبة الجديدة", "is_vehicle": True},
        )
        new_id = new.json()["data"]["id"]

        unassign = await client.patch(
            f"/api/v1/inventory/warehouses/{old}", headers=admin,
            json={"assigned_to_id": None})
        assert unassign.status_code == 200, unassign.text

        handover = await client.patch(
            f"/api/v1/inventory/warehouses/{new_id}", headers=admin,
            json={"assigned_to_id": rep})
        assert handover.status_code == 200, handover.text
        assert handover.json()["data"]["assigned_to_id"] == rep

    async def test_the_field_app_resolves_the_one_van(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """What the whole rule is for: /field/van must name the van he was given."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        van_id = await assign_van(client, admin, db_session, name="مركبة الجولة")

        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)
        van = (await client.get("/api/v1/sales/field/van", headers=salesman)).json()["data"]
        assert van["warehouse_id"] == van_id
