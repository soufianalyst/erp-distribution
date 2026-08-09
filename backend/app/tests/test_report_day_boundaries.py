"""Reports asked for by day must use the company's day.

Timestamps are UTC; a date typed into a report is local. `func.date(created_at)`
truncates in UTC, so in UTC+03 everything recorded between local midnight and 03:00
falls into the previous day — a credit note raised at 01:00 on the 1st lands in last
month's tax return, and a return at 01:00 lands in yesterday's commission.

This is the same defect that made the cashier's closing report come out empty with
cash in the drawer. It was fixed there and left in four other places, so the guard
below is structural: it fails on the *pattern*, not on one report.
"""

import ast
import pathlib

import pytest
from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, login

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "services"


class TestNoReportTruncatesDatesInUtc:
    def test_no_service_compares_func_date_against_a_date_range(self) -> None:
        """Structural, because the bug is invisible in any single passing test.

        A report written with `func.date(x) >= date_from` returns plausible numbers
        every time. It is only wrong for the few hours after local midnight, which no
        fixture happens to land in — so nothing catches it except a rule against
        writing it.
        """
        offenders: list[str] = []
        for path in SERVICES.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                left = node.left
                if not (
                    isinstance(left, ast.Call)
                    and isinstance(left.func, ast.Attribute)
                    and left.func.attr == "date"
                    and isinstance(left.func.value, ast.Name)
                    and left.func.value.id == "func"
                ):
                    continue
                # Comparing against another column is fine — grouping by calendar day
                # inside one row is not the same as answering "show me 8 August".
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Name) and comparator.id.startswith(
                        ("date_", "day", "from_", "to_")
                    ):
                        offenders.append(
                            f"{path.relative_to(SERVICES)}:{node.lineno} "
                            f"func.date(...) vs {comparator.id}"
                        )
        assert not offenders, (
            "these compare a UTC-truncated date against a local report date; use "
            "business_day.utc_window instead:\n  " + "\n  ".join(offenders)
        )

    def test_the_window_helper_brackets_the_local_day(self) -> None:
        """The arithmetic itself, independent of any report."""
        from datetime import date, timezone

        from app.core.business_day import utc_window

        start, end = utc_window(date(2026, 8, 8), date(2026, 8, 8), "Asia/Riyadh")
        # Riyadh is UTC+03 with no DST: the local day starts at 21:00 the day before.
        assert start.astimezone(timezone.utc).isoformat() == "2026-08-07T21:00:00+00:00"
        assert end.astimezone(timezone.utc).isoformat() == "2026-08-08T21:00:00+00:00"
        # Half-open, so a movement at exactly local midnight belongs to one day only.
        assert start < end

        open_start, open_end = utc_window(date(2026, 8, 8), None, "UTC")
        assert open_start is not None and open_end is None


class TestTheReportsStillAnswer:
    """The windowed queries must return the same shape as before.

    A rewrite that quietly returns nothing would pass the structural guard above
    while breaking every report, so each one is called through the API.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/sales/reports/commissions",
            "/api/v1/accounting/reports/tax-summary",
            "/api/v1/analytics/inventory/damage-report",
        ],
    )
    async def test_a_dated_report_responds(
        self, client: AsyncClient, path: str
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get(
            path, headers=admin, params={"date_from": "2026-01-01", "date_to": "2026-12-31"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"] is not None
