"""Markdowns: shown to the customer, and binding when the invoice is raised.

The portal shows no prices — except on a discounted line, where "was 12.00, now 9.60"
is the whole point. That exception creates the obligation this file exists to hold:
**the price a shop was shown must be the price it is charged.** A discount that only
affects the display is a way to quote one number and bill another.

The second thing under test is the tier ladder. The discount is a percentage of each
customer's own price, not a flat figure, so a retail shop and a wholesale shop see
different numbers and neither crosses the other.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_SALES_PASSWORD, login
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_portal_account import ready_portal_customer
from app.tests.test_sales import create_customer, post_invoice


async def make_offer(client: AsyncClient, admin: dict, product_id: int,
                     percent: str = "20", days: int = 30) -> dict:
    response = await client.post("/api/v1/inventory/offers", headers=admin, json={
        "product_id": product_id,
        "discount_percent": percent,
        "starts_on": str(date.today()),
        "ends_on": str(date.today() + timedelta(days=days)),
        "note": "قرب انتهاء الصلاحية",
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def stocked(
    client: AsyncClient, admin: dict, sku: str, unit_cost: str | None = None
) -> tuple[int, dict]:
    """Warehouse + product + 200 units expiring in 120 days.

    `unit_cost` is the *cost*, not the quantity — the receive helper takes
    (batch, expiry_days, quantity), and reading 200 as a cost is a mistake this
    signature now makes hard.
    """
    warehouse_id = await create_warehouse(client, admin, f"مخزن {sku}")
    product = await create_product(client, admin, sku=sku, warehouse_id=warehouse_id)
    await receive(client, admin, product["id"], warehouse_id, f"B-{sku}", 120, "200",
                  unit_cost=unit_cost)
    return warehouse_id, product


class TestThePriceShownIsThePriceCharged:
    async def test_the_invoice_uses_the_offer_price(
        self, client: AsyncClient
    ) -> None:
        """The promise. Without this the whole feature is a lie told politely."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await stocked(client, admin, "OFFER-001")
        customer_id = await create_customer(client, admin, name="بقالة العرض",
                                            credit_limit="100000")
        await make_offer(client, admin, product["id"], percent="25")

        invoiced = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "10",
            tax_rate_ids=[])
        assert invoiced.status_code == 201, invoiced.text
        line = invoiced.json()["data"]["lines"][0]

        # 10.50 wholesale less 25% = 7.875 -> 7.88 at two places.
        assert Decimal(str(line["unit_price"])) == Decimal("7.88")

    async def test_the_catalogue_and_the_invoice_agree(
        self, client: AsyncClient
    ) -> None:
        """Read the number as the shop reads it, then buy, then compare.

        Comparing the two rather than asserting a constant is what makes this survive
        a change to the rounding or the tier: if they ever diverge the test fails
        without anyone having to predict how.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await stocked(client, admin, "AGREE-001")
        customer_id, portal = await ready_portal_customer(
            client, admin, "بقالة الاتفاق", "0506000001")
        await make_offer(client, admin, product["id"], percent="15")

        catalogue = (await client.get(
            "/api/v1/portal/catalog", headers=portal,
            params={"search": product["name"]})).json()["data"]
        offered = next(i for i in catalogue if i["product_id"] == product["id"])
        assert offered["price_now"] is not None
        assert Decimal(str(offered["price_now"])) < Decimal(str(offered["price_before"]))

        invoiced = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "4",
            tax_rate_ids=[])
        assert invoiced.status_code == 201, invoiced.text
        charged = Decimal(str(invoiced.json()["data"]["lines"][0]["unit_price"]))

        assert charged == Decimal(str(offered["price_now"])), (
            "the shop was shown one price and billed another"
        )

    async def test_an_expired_offer_stops_applying(
        self, client: AsyncClient
    ) -> None:
        """A window that has closed must return the price to normal, silently."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await stocked(client, admin, "ENDED-001")
        customer_id = await create_customer(client, admin, name="بقالة المنتهي",
                                            credit_limit="100000")
        offer = await make_offer(client, admin, product["id"], percent="30")

        ended = await client.post(
            f"/api/v1/inventory/offers/{offer['id']}/end", headers=admin)
        assert ended.status_code == 200, ended.text

        invoiced = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "3",
            tax_rate_ids=[])
        assert Decimal(str(invoiced.json()["data"]["lines"][0]["unit_price"])) == (
            Decimal("10.50")
        )


class TestTheTierLadderSurvives:
    async def test_each_tier_gets_the_discount_off_its_own_price(
        self, client: AsyncClient
    ) -> None:
        """Why this is a percentage and not a flat price.

        A single offer price would hand a retail shop the wholesale figure — and at a
        deep enough discount, less than wholesale. Off each customer's own price, the
        ordering is preserved.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await stocked(client, admin, "TIER-001")
        wholesale = await create_customer(client, admin, name="جملة", credit_limit="90000")
        retail = await create_customer(client, admin, name="تجزئة",
                                       price_tier="retail", credit_limit="90000")
        await make_offer(client, admin, product["id"], percent="20")

        w = await post_invoice(client, admin, wholesale, warehouse_id,
                               product["id"], "2", tax_rate_ids=[])
        r = await post_invoice(client, admin, retail, warehouse_id,
                               product["id"], "2", tax_rate_ids=[])
        w_price = Decimal(str(w.json()["data"]["lines"][0]["unit_price"]))
        r_price = Decimal(str(r.json()["data"]["lines"][0]["unit_price"]))

        # 10.50 and 12.00 less 20%.
        assert w_price == Decimal("8.40")
        assert r_price == Decimal("9.60")
        assert w_price < r_price, "the discount flattened the tier ladder"


class TestWhoMaySetAPrice:
    async def test_a_salesman_cannot_create_an_offer(
        self, client: AsyncClient
    ) -> None:
        """Discounting is a pricing decision, not stock housekeeping."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await stocked(client, admin, "PERM-001")
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)

        refused = await client.post("/api/v1/inventory/offers", headers=salesman, json={
            "product_id": product["id"],
            "discount_percent": "50",
            "starts_on": str(date.today()),
            "ends_on": str(date.today() + timedelta(days=7)),
        })
        assert refused.status_code == 403, refused.text

    async def test_the_office_is_told_when_a_discount_goes_below_cost(
        self, client: AsyncClient
    ) -> None:
        """Below cost can beat a write-off — but it must be a decision, not a slip."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        # Bought at 20 a unit against a 10.50 wholesale price — already underwater,
        # so any discount is deeper still and the flag must say so.
        _, product = await stocked(client, admin, "COST-001", unit_cost="20")
        offer = await make_offer(client, admin, product["id"], percent="10")
        assert offer["below_cost"] is True
        assert Decimal(str(offer["unit_cost"])) > Decimal(str(offer["offer_price"]))

    async def test_an_offer_that_already_ended_is_refused(
        self, client: AsyncClient
    ) -> None:
        """It would be accepted by the database and then do nothing, which looks
        exactly like a broken feature."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, product = await stocked(client, admin, "PAST-001")
        refused = await client.post("/api/v1/inventory/offers", headers=admin, json={
            "product_id": product["id"],
            "discount_percent": "10",
            "starts_on": str(date.today() - timedelta(days=30)),
            "ends_on": str(date.today() - timedelta(days=1)),
        })
        assert refused.status_code == 400, refused.text
