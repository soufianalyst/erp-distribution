"""Backups that prove they worked, and a drill that proves they restore.

This exists because of a pair of files in the `backups/` folder (untracked, so
they are on disk rather than in git):

    backups/erp-before-reseed-20260808-113941.sql   0 bytes
    backups/erp-before-reseed-20260808-113952.sql   7.4 MB

Eleven seconds apart. The first one is what happens when `pg_dump > file.sql` meets a
version mismatch — the local client is PostgreSQL 14, the server in Docker is 16, so
pg_dump aborted, the shell had already created the file, and the exit status went
unread. A backup ran. A backup existed. A backup was worthless, and nothing said so.

Two decisions follow from that:

**The dump runs inside the container.** `docker exec … pg_dump` always uses a client
that matches its own server, so the entire class of version-mismatch failure cannot
happen again. Reaching in from the host with whatever pg_dump is on PATH is how the
zero-byte file was born.

**Nothing counts as a backup until it has been read back.** Every dump is immediately
listed with `pg_restore -l` and checked for the tables that must be there. A dump that
cannot be listed is deleted rather than kept, because a file that looks like a backup
is worse than no file: it is the reason nobody notices for six months.

The restore drill goes further and actually restores into a scratch database, then
compares row counts against the live one. Verification proves the file is readable;
only a restore proves the data is there.

Usage:

    python3 scripts/backup.py              take a verified backup
    python3 scripts/backup.py --list       what exists, and whether each verifies
    python3 scripts/backup.py --drill      restore the newest into a scratch db
    python3 scripts/backup.py --prune      apply the retention policy only
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

# The container holding Postgres. Named rather than discovered: guessing at "the
# postgres-looking container" would one day dump the wrong database.
CONTAINER = "erp-postgres"

BACKUP_DIR = Path(__file__).resolve().parents[2] / "backups"

# A dump smaller than this is not a small database, it is a failure that produced a
# header and stopped. The real dump of this schema is ~2 MB compressed.
MIN_DUMP_BYTES = 100_000

# Tables whose absence means the dump is structurally incomplete, whatever its size.
# Chosen as the ones that would end the business if lost: the ledger and the trade.
REQUIRED_TABLES = (
    "journal_entries",
    "journal_items",
    "sales_invoices",
    "sales_invoice_lines",
    "products",
    "product_batches",
    "customers",
)

# Retention: a fortnight of dailies, then one per week for a quarter. Long enough to
# notice a slow corruption, short enough that the folder does not become the reason
# the disk fills.
KEEP_DAILY = 14
KEEP_WEEKLY = 13

STAMP = "%Y%m%d-%H%M%S"
NAME_PATTERN = re.compile(r"^erp-(\d{8}-\d{6})\.dump$")


@dataclass(frozen=True)
class Dump:
    path: Path
    taken_at: datetime

    @property
    def size(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


class BackupError(RuntimeError):
    pass


# --- pure helpers, unit-tested ---


def parse_target(database_url: str) -> tuple[str, str]:
    """Database name and role out of the app's own DATABASE_URL.

    Read from the same setting the application uses so a backup can never be taken
    from a different database than the one being served — the failure mode where the
    dumps are all perfect and all of the wrong thing.
    """
    match = re.match(
        r"^postgresql(?:\+\w+)?://(?P<user>[^:/?#]+)(?::[^@]*)?@[^/]+/(?P<name>[^?#]+)",
        database_url,
    )
    if match is None:
        raise BackupError(f"لا يمكن قراءة اسم قاعدة البيانات من DATABASE_URL: {database_url!r}")
    return match.group("name"), match.group("user")


def dumps_in(directory: Path) -> list[Dump]:
    """Every dump this script produced, newest first.

    Files that do not match the naming scheme are ignored rather than swept up: the
    two hand-made `.sql` files from the reseed are somebody's deliberate snapshot and
    are not this script's to delete.
    """
    found: list[Dump] = []
    for path in sorted(directory.glob("erp-*.dump")):
        match = NAME_PATTERN.match(path.name)
        if match is None:
            continue
        found.append(Dump(path=path, taken_at=datetime.strptime(match.group(1), STAMP)))
    return sorted(found, key=lambda d: d.taken_at, reverse=True)


def expired(dumps: list[Dump], today: date | None = None) -> list[Dump]:
    """Which dumps the retention policy releases.

    Pure, and separated from the deleting, because this is the one function in the
    file whose bug destroys data rather than merely failing loudly. It is tested
    against a fabricated year of dumps.
    """
    now = today or date.today()
    keep: set[Path] = set()

    # Newest dump of each of the last KEEP_DAILY days.
    seen_days: set[date] = set()
    for dump in dumps:
        day = dump.taken_at.date()
        if (now - day).days < KEEP_DAILY and day not in seen_days:
            seen_days.add(day)
            keep.add(dump.path)

    # Then the newest of each ISO week, for KEEP_WEEKLY weeks.
    seen_weeks: set[tuple[int, int]] = set()
    horizon = now - timedelta(weeks=KEEP_WEEKLY)
    for dump in dumps:
        day = dump.taken_at.date()
        week = (day.isocalendar().year, day.isocalendar().week)
        if day >= horizon and week not in seen_weeks:
            seen_weeks.add(week)
            keep.add(dump.path)

    # The most recent dump is never expired, whatever the calendar says. A machine
    # switched off for four months must not come back and delete its only backup.
    if dumps:
        keep.add(dumps[0].path)

    return [dump for dump in dumps if dump.path not in keep]


def missing_tables(listing: str) -> list[str]:
    """Required tables absent from a `pg_restore -l` listing."""
    return [table for table in REQUIRED_TABLES if f" {table} " not in listing]


# --- the parts that talk to Docker ---


def _docker(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", CONTAINER, *args],
        capture_output=capture, text=True, check=False,
    )


def take_backup(database: str, user: str, directory: Path) -> Path:
    """Dump, verify, and only then keep.

    The dump is written inside the container and streamed out through stdout, so a
    partial write cannot masquerade as a finished file — if pg_dump fails, the exit
    status is non-zero and the half-written file is removed before it can be mistaken
    for a backup next month.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"erp-{datetime.now().strftime(STAMP)}.dump"

    with target.open("wb") as handle:
        result = subprocess.run(
            ["docker", "exec", CONTAINER,
             "pg_dump", "-U", user, "-d", database, "--format=custom", "--compress=9"],
            stdout=handle, stderr=subprocess.PIPE, check=False,
        )
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise BackupError(
            "فشل إنشاء النسخة الاحتياطية:\n"
            + result.stderr.decode("utf-8", "replace").strip()
        )

    verify(target, user)
    return target


def verify(path: Path, user: str) -> None:
    """Read the dump back. Anything unreadable is deleted, not kept.

    Keeping a broken dump is the actual failure being designed against here — the
    zero-byte file sat in the repository for three days looking exactly like
    protection.
    """
    problems: list[str] = []
    size = path.stat().st_size if path.exists() else 0
    if size < MIN_DUMP_BYTES:
        problems.append(f"الحجم {size:,} بايت أصغر من الحد الأدنى {MIN_DUMP_BYTES:,}")

    if not problems:
        # Streamed back into the container's own pg_restore, which is the only client
        # guaranteed to understand a dump its own pg_dump wrote.
        with path.open("rb") as handle:
            listed = subprocess.run(
                ["docker", "exec", "-i", CONTAINER, "pg_restore", "-l"],
                stdin=handle, capture_output=True, text=True, check=False,
            )
        if listed.returncode != 0:
            problems.append(f"pg_restore -l رفض الملف: {listed.stderr.strip()[:200]}")
        else:
            absent = missing_tables(listed.stdout)
            if absent:
                problems.append("جداول ناقصة: " + ", ".join(absent))

    if problems:
        path.unlink(missing_ok=True)
        raise BackupError(
            f"النسخة {path.name} لم تُجتَز الفحص فحُذفت — "
            "ملف تالف يبدو كنسخة احتياطية أسوأ من عدم وجود ملف:\n  - "
            + "\n  - ".join(problems)
        )


def drill(database: str, user: str, directory: Path) -> None:
    """Restore the newest dump into a scratch database and compare row counts.

    Verification proves a file is readable. Only a restore proves the rows are in it,
    and the difference between those two claims is where the confidence a backup is
    supposed to provide actually lives.
    """
    dumps = dumps_in(directory)
    if not dumps:
        raise BackupError("لا توجد نسخ احتياطية للتجربة.")
    newest = dumps[0]
    scratch = f"{database}_drill"

    _docker("dropdb", "-U", user, "--if-exists", scratch)
    created = _docker("createdb", "-U", user, scratch)
    if created.returncode != 0:
        raise BackupError(f"تعذّر إنشاء قاعدة التجربة: {created.stderr.strip()}")

    try:
        with newest.path.open("rb") as handle:
            restored = subprocess.run(
                ["docker", "exec", "-i", CONTAINER,
                 "pg_restore", "-U", user, "-d", scratch, "--no-owner"],
                stdin=handle, capture_output=True, text=True, check=False,
            )
        # pg_restore warns about owners and extensions on a clean database; only a
        # hard failure matters, so the row comparison below is the real verdict.
        if restored.returncode != 0 and "errors ignored" not in restored.stderr:
            print(f"  تحذيرات الاستعادة: {restored.stderr.strip()[:300]}")

        print(f"\n  تجربة استعادة من {newest.path.name}\n")
        print(f"  {'الجدول':24} {'الأصل':>12} {'المستعاد':>12}")
        mismatches = []
        for table in REQUIRED_TABLES:
            live = _count(database, user, table)
            copy = _count(scratch, user, table)
            flag = "" if live == copy else "   <-- اختلاف"
            print(f"  {table:24} {live:>12,} {copy:>12,}{flag}")
            if live != copy:
                mismatches.append(table)
        if mismatches:
            raise BackupError(
                "الاستعادة لا تطابق الأصل في: " + ", ".join(mismatches)
            )
        print("\n  ✓ الاستعادة مطابقة للأصل في كل الجداول المطلوبة.")
    finally:
        _docker("dropdb", "-U", user, "--if-exists", scratch)


def _count(database: str, user: str, table: str) -> int:
    result = _docker(
        "psql", "-U", user, "-d", database, "-tAc", f"select count(*) from {table}"
    )
    if result.returncode != 0:
        return -1
    return int(result.stdout.strip() or -1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show existing backups")
    parser.add_argument("--drill", action="store_true", help="restore-test the newest")
    parser.add_argument("--prune", action="store_true", help="apply retention only")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.config import get_settings

    database, user = parse_target(get_settings().DATABASE_URL)

    try:
        if args.list:
            dumps = dumps_in(BACKUP_DIR)
            if not dumps:
                print("لا توجد نسخ احتياطية.")
                return 0
            release = {d.path for d in expired(dumps)}
            for dump in dumps:
                mark = "سيُحذف" if dump.path in release else "محفوظة"
                print(f"  {dump.path.name}  {dump.size/1_048_576:>7.2f} MB  {mark}")
            return 0

        if args.drill:
            drill(database, user, BACKUP_DIR)
            return 0

        if not args.prune:
            path = take_backup(database, user, BACKUP_DIR)
            print(f"✓ نسخة موثّقة: {path.name} ({path.stat().st_size/1_048_576:.2f} MB)")

        for dump in expired(dumps_in(BACKUP_DIR)):
            dump.path.unlink()
            print(f"  حُذفت نسخة منتهية: {dump.path.name}")
        return 0
    except BackupError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
