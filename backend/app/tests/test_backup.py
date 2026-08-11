"""The backup script's judgement, tested without needing Docker.

Two things in `scripts/backup.py` are dangerous enough to test directly.

**The retention policy deletes files.** Every other bug in that script fails loudly
and leaves the data alone; a bug in `expired()` removes the backups. So it is a pure
function over a fabricated year of dumps, and it is tested rather than trusted.

**The verification is the whole point of the script.** It exists because
`backups/erp-before-reseed-20260808-113941.sql` is zero bytes — a real artefact of a
real failure that sat on disk for three days looking like protection. The test below
recreates exactly that file and asserts the script rejects *and deletes* it, because
keeping a broken dump is worse than having none.

Nothing here shells out to Docker. These are the decisions, not the plumbing; the
plumbing is exercised by actually running `--drill`, which restores into a scratch
database and compares row counts.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.backup import (
    KEEP_DAILY,
    MIN_DUMP_BYTES,
    BackupError,
    Dump,
    dumps_in,
    expired,
    missing_tables,
    parse_target,
    verify,
)

TODAY = date(2026, 8, 11)


def dump_at(days_ago: int, hour: int = 3, root: str = "/backups") -> Dump:
    moment = datetime(TODAY.year, TODAY.month, TODAY.day, hour) - timedelta(days=days_ago)
    return Dump(
        path=Path(root) / f"erp-{moment.strftime('%Y%m%d-%H%M%S')}.dump",
        taken_at=moment,
    )


class TestReadingTheTarget:
    def test_it_takes_the_database_from_the_apps_own_url(self) -> None:
        """The same setting the application serves from.

        A backup script with its own copy of the connection details is how a company
        ends up with a year of flawless dumps of a database nobody uses.
        """
        assert parse_target(
            "postgresql+asyncpg://postgres:secret@localhost:5433/erp_desktop"
        ) == ("erp_desktop", "postgres")

    def test_it_handles_a_plain_driverless_url_and_a_query_string(self) -> None:
        assert parse_target("postgresql://erp_user@db.internal:5432/production") == (
            "production", "erp_user")
        assert parse_target(
            "postgresql+psycopg://postgres:p@host/erp?sslmode=require"
        ) == ("erp", "postgres")

    def test_it_refuses_rather_than_guessing(self) -> None:
        """A wrong guess here backs up the wrong thing, silently and forever."""
        with pytest.raises(BackupError):
            parse_target("sqlite:///./local.db")


class TestTheRetentionPolicy:
    def test_a_fortnight_of_dailies_is_kept(self) -> None:
        dumps = [dump_at(day) for day in range(KEEP_DAILY)]
        assert expired(dumps, today=TODAY) == []

    def test_only_the_newest_of_a_day_survives_that_day(self) -> None:
        """Three dumps on one morning are one day's protection, not three."""
        morning, noon, evening = dump_at(3, 6), dump_at(3, 12), dump_at(3, 20)
        released = expired([evening, noon, morning], today=TODAY)
        assert {d.path for d in released} == {morning.path, noon.path}

    def test_beyond_the_dailies_one_per_week_is_kept(self) -> None:
        # Two dumps in the same old week: the newer is the week's keeper.
        older, newer = dump_at(40), dump_at(38)
        released = expired([newer, older, dump_at(0)], today=TODAY)
        assert older.path in {d.path for d in released}
        assert newer.path not in {d.path for d in released}

    def test_dumps_past_the_weekly_horizon_are_released(self) -> None:
        ancient = dump_at(400)
        released = expired([dump_at(0), ancient], today=TODAY)
        assert ancient.path in {d.path for d in released}

    def test_the_newest_dump_is_never_deleted_however_old_it_is(self) -> None:
        """A laptop switched off for four months must not wake and delete its only copy.

        Every calendar rule above would release this file: it is outside the dailies
        and past the weekly horizon. Obeying them literally would leave the business
        with nothing, which is the one outcome a retention policy exists to prevent.
        """
        only = dump_at(400)
        assert expired([only], today=TODAY) == []

    def test_nothing_is_released_from_an_empty_folder(self) -> None:
        assert expired([], today=TODAY) == []

    def test_files_it_did_not_write_are_left_alone(self, tmp_path: Path) -> None:
        """The hand-made reseed snapshots are somebody's deliberate copy.

        They do not match the naming scheme, so they are invisible to both the
        listing and the pruning — a backup script that tidies up files it does not
        understand is a backup script that deletes evidence.
        """
        (tmp_path / "erp-before-reseed-20260808-113952.sql").write_bytes(b"x" * 10)
        (tmp_path / "notes.txt").write_text("keep me")
        (tmp_path / "erp-20260811-030000.dump").write_bytes(b"y" * 10)

        found = dumps_in(tmp_path)
        assert [d.path.name for d in found] == ["erp-20260811-030000.dump"]


class TestVerificationRejectsWhatLooksLikeABackup:
    def test_the_zero_byte_dump_that_started_all_this(self, tmp_path: Path) -> None:
        """Recreates `erp-before-reseed-20260808-113941.sql` exactly.

        pg_dump v14 aborted against the v16 server, the shell had already created the
        file, and the exit status went unread. The file sat there for three days.
        """
        empty = tmp_path / "erp-20260811-064500.dump"
        empty.touch()

        with pytest.raises(BackupError) as raised:
            verify(empty, user="postgres")

        assert "الحجم" in str(raised.value)
        # Deleted, not kept: a file that looks like a backup and is not is the reason
        # nobody notices until the day they need it.
        assert not empty.exists()

    def test_a_suspiciously_small_dump_is_also_refused(self, tmp_path: Path) -> None:
        """A header and nothing else is the shape of most dump failures."""
        stub = tmp_path / "erp-20260811-064501.dump"
        stub.write_bytes(b"PGDMP" + b"\0" * 500)

        with pytest.raises(BackupError):
            verify(stub, user="postgres")
        assert not stub.exists()
        assert MIN_DUMP_BYTES > 500

    def test_a_listing_missing_the_ledger_is_incomplete(self) -> None:
        """Size is not structure.

        A dump can be megabytes and still be missing the journal — a `--table`
        argument in the wrong place is enough — and a backup without the ledger
        cannot reconstruct the accounts.
        """
        listing = "\n".join(
            f"123; 1259 4567 TABLE public {table} postgres"
            for table in ("products", "customers", "sales_invoices")
        )
        absent = missing_tables(listing)
        assert "journal_entries" in absent
        assert "journal_items" in absent
        assert "products" not in absent

    def test_a_complete_listing_passes(self) -> None:
        from scripts.backup import REQUIRED_TABLES

        listing = "\n".join(
            f"123; 1259 4567 TABLE public {table} postgres" for table in REQUIRED_TABLES
        )
        assert missing_tables(listing) == []
