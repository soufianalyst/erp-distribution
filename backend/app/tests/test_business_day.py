"""The company's day, not the server's.

Timestamps are stored in UTC. Reports are asked for by *day*, which is local. The
cashier's closing report mixed the two: it took "today" from the server's calendar and
then searched a window built on UTC midnight. On a machine three hours ahead of UTC
that made the report unusable between local midnight and 03:00 — it asked for
8 August 00:00 UTC onwards while the collection just made was stamped 7 August 22:26,
so the screen read zero with the cash in the drawer.

Observed exactly that way: a 500.00 collection at 01:26 local, `movement_count: 0`.

These tests fix the frame. The unit tests below can state the boundary precisely
without depending on what time the suite happens to run — which matters, because the
original defect hid for months by only appearing during three hours of the night.
"""

from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import business_day
from app.domain.models.cashier import CashMovement
from app.domain.models.settings import CompanySettings
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_cashier import collect, post_invoice
from app.tests.test_inventory import create_product, create_warehouse, receive
from app.tests.test_sales import create_customer


class TestDayBounds:
    def test_a_day_east_of_utc_starts_the_evening_before(self) -> None:
        """+03 midnight is 21:00 UTC on the previous date. This is the whole bug."""
        start, end = business_day.day_bounds(date(2026, 8, 8), "Asia/Qatar")
        assert start == datetime(2026, 8, 7, 21, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 8, 8, 21, 0, tzinfo=timezone.utc)

    def test_the_collection_that_went_missing_now_falls_inside_the_day(self) -> None:
        """The real timestamp from the report that read zero."""
        collected_at = datetime(2026, 8, 7, 22, 26, tzinfo=timezone.utc)  # 01:26 local
        start, end = business_day.day_bounds(date(2026, 8, 8), "Asia/Qatar")
        assert start <= collected_at < end

        # And under the old arithmetic it did not, which is why the screen was empty.
        naive_start = datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)
        assert collected_at < naive_start

    def test_a_day_west_of_utc_ends_after_the_next_utc_midnight(self) -> None:
        start, end = business_day.day_bounds(date(2026, 8, 8), "America/New_York")
        assert start == datetime(2026, 8, 8, 4, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)

    def test_utc_is_unchanged(self) -> None:
        """Existing installations keep the behaviour they had, exactly."""
        start, end = business_day.day_bounds(date(2026, 8, 8), "UTC")
        assert start == datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)

    def test_a_spring_forward_day_is_twenty_three_hours(self) -> None:
        """The end is the next local midnight, not start + 24h.

        Adding a fixed day across a clock change would clip an hour of takings off one
        day and count an hour twice on another.
        """
        start, end = business_day.day_bounds(date(2026, 3, 29), "Europe/Amsterdam")
        assert (end - start) == timedelta(hours=23)

    def test_an_autumn_day_is_twenty_five_hours(self) -> None:
        start, end = business_day.day_bounds(date(2026, 10, 25), "Europe/Amsterdam")
        assert (end - start) == timedelta(hours=25)

    def test_days_meet_exactly_with_no_gap_and_no_overlap(self) -> None:
        """Half-open windows: a movement at midnight belongs to one day only."""
        _, first_end = business_day.day_bounds(date(2026, 8, 8), "Asia/Qatar")
        second_start, _ = business_day.day_bounds(date(2026, 8, 9), "Asia/Qatar")
        assert first_end == second_start

    def test_an_unusable_timezone_falls_back_instead_of_breaking_the_screen(
        self,
    ) -> None:
        """A typo in settings must not take down the till.

        Validation belongs where the value is saved; a report is the wrong place to
        discover the problem.
        """
        assert business_day.resolve("Mars/Olympus_Mons").key == "UTC"
        assert business_day.resolve(None).key == "UTC"
        assert business_day.resolve("").key == "UTC"
        assert business_day.is_valid("Asia/Qatar") is True
        assert business_day.is_valid("Mars/Olympus_Mons") is False


class TestTheClosingReportHonoursTheCompanyDay:
    async def test_a_collection_after_local_midnight_lands_on_the_local_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """End to end, with the company three hours ahead of UTC.

        The movement is stamped 22:26 UTC — late evening in UTC, but 01:26 the next
        morning for the company. The report for the company's date must contain it, and
        the report for the UTC date must not.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id = await create_warehouse(client, admin, "مخزن التوقيت")
        product = await create_product(client, admin, "TZ-1", warehouse_id=warehouse_id)
        await receive(client, admin, product["id"], warehouse_id, "TZB-1", 200, "100")
        customer_id = await create_customer(
            client, admin, name="عميل التوقيت", credit_limit="9999"
        )

        company = (await db_session.execute(select(CompanySettings))).scalar_one_or_none()
        if company is None:  # first read creates it; force it via the API
            await client.get("/api/v1/settings/company", headers=admin)
            company = (await db_session.execute(select(CompanySettings))).scalar_one()
        company.timezone = "Asia/Qatar"
        await db_session.commit()

        invoice = (
            await post_invoice(
                client, admin, customer_id, warehouse_id, product["id"], "5", "cash"
            )
        ).json()["data"]
        await collect(client, admin, invoice["id"], invoice["total"])

        # Stamp it at the exact instant that used to disappear.
        movement = (
            await db_session.execute(
                select(CashMovement).where(
                    CashMovement.reference_id == invoice["id"],
                    CashMovement.reference_type == "sales_invoice",
                )
            )
        ).scalar_one()
        movement.collected_at = datetime(2026, 8, 7, 22, 26, tzinfo=timezone.utc)
        await db_session.commit()

        local_day = (
            await client.get(
                "/api/v1/cashier/daily-summary",
                headers=admin,
                params={"day": "2026-08-08"},
            )
        ).json()["data"]
        assert local_day["movement_count"] == 1, (
            "the collection is missing from the company's own day — the report is "
            "still building its window on UTC midnight"
        )

        utc_day = (
            await client.get(
                "/api/v1/cashier/daily-summary",
                headers=admin,
                params={"day": "2026-08-07"},
            )
        ).json()["data"]
        assert utc_day["movement_count"] == 0, (
            "the collection is being counted on the UTC date as well — a day it does "
            "not belong to for this company"
        )

    async def test_the_reported_day_is_the_company_s_today(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """With no day given, the report must say which day it is showing — and it has
        to be the company's, not the machine's."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await client.get("/api/v1/settings/company", headers=admin)
        company = (await db_session.execute(select(CompanySettings))).scalar_one()
        company.timezone = "Pacific/Kiritimati"  # UTC+14, ahead of everywhere
        await db_session.commit()

        summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=admin)
        ).json()["data"]
        assert summary["day"] == business_day.today_in("Pacific/Kiritimati").isoformat()


class TestChoosingTheCompanyTimezone:
    async def test_the_picker_offers_zones_with_their_current_offset(
        self, client: AsyncClient
    ) -> None:
        """Offsets are derived, not stored: a region that changes its rules would
        otherwise be shown a stale number forever."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/settings/timezones", headers=admin)
        assert response.status_code == 200, response.text
        zones = response.json()["data"]
        assert zones, "the picker would be empty"
        by_name = {z["name"]: z for z in zones}
        assert "UTC" in by_name and by_name["UTC"]["utc_offset"] == "+00:00"
        assert by_name["Asia/Riyadh"]["utc_offset"] == "+03:00"
        assert all(z["label"] for z in zones), "every zone needs an Arabic label"

    async def test_an_unknown_zone_is_refused_at_the_point_of_saving(
        self, client: AsyncClient
    ) -> None:
        """The only place a human is present to correct it.

        Letting it through would surface as an empty closing report instead, which
        looks like lost money rather than a typo.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        current = (
            await client.get("/api/v1/settings/company", headers=admin)
        ).json()["data"]

        refused = await client.put(
            "/api/v1/settings/company",
            headers=admin,
            json={
                "name": current["name"],
                "currency_code": current["currency_code"],
                "currency_symbol": current["currency_symbol"],
                "timezone": "Mars/Olympus_Mons",
            },
        )
        assert refused.status_code == 400, refused.text
        assert "المنطقة الزمنية" in refused.json()["message"]

        unchanged = (
            await client.get("/api/v1/settings/company", headers=admin)
        ).json()["data"]
        assert unchanged["timezone"] == current["timezone"]

    async def test_saving_a_zone_moves_the_reported_day(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        current = (
            await client.get("/api/v1/settings/company", headers=admin)
        ).json()["data"]
        payload = {
            "name": current["name"],
            "currency_code": current["currency_code"],
            "currency_symbol": current["currency_symbol"],
        }

        saved = await client.put(
            "/api/v1/settings/company",
            headers=admin,
            json={**payload, "timezone": "Pacific/Kiritimati"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["timezone"] == "Pacific/Kiritimati"

        summary = (
            await client.get("/api/v1/cashier/daily-summary", headers=admin)
        ).json()["data"]
        assert summary["day"] == business_day.today_in("Pacific/Kiritimati").isoformat()
