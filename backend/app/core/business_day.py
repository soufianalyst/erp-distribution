"""Where a calendar day starts and ends, for a business that is not in UTC.

Timestamps are stored in UTC, which is right. Reports are asked for by *day*, which
is a local idea. Converting between the two is the whole content of this module, and
getting it wrong is not a rounding error — it silently moves money between days.

The bug that prompted this: the cashier's closing report took "today" from the
server's local calendar and then searched a window built on UTC midnight. At 01:26
local (UTC+03) that asked for movements between 8 August 00:00 **UTC** and 9 August
00:00 UTC, while the collection just made was stamped 7 August 22:26 UTC — an hour
and a half before the window opened. The report read empty with the cash sitting in
the drawer. Every day between 00:00 and 03:00 local, the till could not be closed.

So the day boundary is now the company's own midnight, taken from a configured
timezone rather than from wherever the server happens to be. A cloud host in UTC
must not be able to move a business's day.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Fallback when a company has not chosen a timezone yet. UTC is the honest default:
# it is what the timestamps already are, so nothing is silently shifted.
DEFAULT_TIMEZONE = "UTC"


def resolve(timezone_name: str | None) -> ZoneInfo:
    """The company's timezone, falling back to UTC rather than raising.

    A report is the wrong place to discover that a settings string is unusable — it
    would take down the closing screen over a typo. Validation belongs at the point
    the value is saved, which is what `is_valid` is for.
    """
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def is_valid(timezone_name: str) -> bool:
    """Whether this names a real timezone — used to reject bad input on save."""
    try:
        ZoneInfo(timezone_name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def today_in(timezone_name: str | None) -> date:
    """The date it is *for the business* right now.

    Not `date.today()`: that is the server's date, which is a different thing the
    moment the server is not in the company's timezone.
    """
    return datetime.now(timezone.utc).astimezone(resolve(timezone_name)).date()


def day_bounds(day: date, timezone_name: str | None) -> tuple[datetime, datetime]:
    """The UTC instants bracketing one local calendar day: [start, end).

    Half-open on purpose, so a movement at exactly midnight belongs to one day only.

    The end is the *next local midnight* rather than start + 24h, which matters where
    clocks change: a spring-forward day is 23 hours long and an autumn day 25, and
    adding a fixed day would clip an hour of takings or double-count one.
    """
    tz = resolve(timezone_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
