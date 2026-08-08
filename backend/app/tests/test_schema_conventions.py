"""Structural checks on the ORM metadata itself.

These tests assert conventions rather than behaviour, and they exist because of a
bug the behavioural suite could not have caught. The round-settlement status
column was declared without `values_callable`, so SQLAlchemy sent the enum
*member name* ("OPEN") while the Postgres type created by the migration held the
lowercase *values* ("open"). Every insert failed — but only against a migrated
database. The test suite builds its schema from this same metadata, so the type
and the parameter agreed with each other and disagreed only with production.

A test that reads the metadata directly closes that gap for the whole class of
mistake, not just the one column that had it.
"""

from decimal import Decimal

import sqlalchemy as sa

from app.db.base import Base


def _enum_columns() -> list[tuple[str, str, sa.Enum]]:
    return [
        (table.name, column.name, column.type)
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, sa.Enum)
    ]


class TestEnumColumns:
    def test_every_enum_column_persists_values_not_member_names(self) -> None:
        """The labels stored in the database must be the Python enum's values.

        Migrations in this project spell their enum labels in lowercase because
        that is what the enum values are. A column that skips `values_callable`
        silently switches to the uppercase member names and breaks against any
        database built by those migrations.
        """
        offenders = []
        for table_name, column_name, enum_type in _enum_columns():
            python_enum = enum_type.enum_class
            if python_enum is None:  # a plain list of strings, nothing to align
                continue
            expected = [member.value for member in python_enum]
            if list(enum_type.enums) != expected:
                offenders.append(
                    f"{table_name}.{column_name}: stores {list(enum_type.enums)} "
                    f"but the enum's values are {expected} — add "
                    f"values_callable=lambda e: [m.value for m in e]"
                )
        assert not offenders, "\n".join(offenders)

    def test_enum_columns_name_their_postgres_type(self) -> None:
        """An unnamed type gets one derived from the column, which migrations cannot
        reference reliably."""
        unnamed = [
            f"{table}.{column}"
            for table, column, enum_type in _enum_columns()
            if not enum_type.name
        ]
        assert not unnamed, f"enum columns without an explicit name: {unnamed}"


class TestMoneyColumns:
    def test_no_money_column_uses_float(self) -> None:
        """Prices, quantities and totals are Decimal end to end.

        This is the project's oldest hard rule and the one whose violation is
        hardest to notice: a FLOAT column accepts every write and only reveals
        itself as a few piastres of drift months later.
        """
        floats = [
            f"{table.name}.{column.name}"
            for table in Base.metadata.sorted_tables
            for column in table.columns
            if isinstance(column.type, (sa.Float, sa.REAL))
        ]
        assert not floats, f"floating-point columns found: {floats}"

    def test_numeric_columns_declare_a_scale(self) -> None:
        """An unscaled NUMERIC stores whatever it is handed, so two writes of the
        same amount can compare unequal."""
        unscaled = [
            f"{table.name}.{column.name}"
            for table in Base.metadata.sorted_tables
            for column in table.columns
            if isinstance(column.type, sa.Numeric)
            and not isinstance(column.type, sa.Float)
            and column.type.scale is None
        ]
        assert not unscaled, f"NUMERIC columns without a scale: {unscaled}"


def test_decimal_is_the_money_type() -> None:
    """A canary for the rule itself: floats cannot represent these amounts."""
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
    assert 0.1 + 0.2 != 0.3


class TestMigrationIdentifiers:
    """Revision ids in this project are hand-written pseudo-hashes, and they collide.

    Adding `a1b2c3d4e5f6` for the return-cancel migration silently reused the id of
    the cashier-gate migration from months earlier, and Alembic answered with
    "Cycle is detected in revisions" listing all twenty-four — a message that says
    nothing about which two clashed. Cheap to check, unpleasant to diagnose.
    """

    def test_no_two_migrations_share_a_revision_id(self) -> None:
        import pathlib
        import re
        from collections import Counter

        versions = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
        ids: list[tuple[str, str]] = []
        for path in sorted(versions.glob("*.py")):
            match = re.search(r'^revision: str = "([^"]+)"', path.read_text(encoding="utf-8"), re.M)
            if match:
                ids.append((match.group(1), path.name))
        counts = Counter(rev for rev, _ in ids)
        duplicates = {
            rev: [name for r, name in ids if r == rev]
            for rev, n in counts.items()
            if n > 1
        }
        assert not duplicates, f"duplicate revision ids: {duplicates}"

    def test_every_down_revision_points_at_something(self) -> None:
        """A typo in down_revision produces the same unhelpful cycle error."""
        import pathlib
        import re

        versions = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
        known, edges = set(), []
        for path in sorted(versions.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            rev = re.search(r'^revision: str = "([^"]+)"', text, re.M)
            down = re.search(r'^down_revision: Union\[str, None\] = "([^"]+)"', text, re.M)
            if rev:
                known.add(rev.group(1))
            if down:
                edges.append((down.group(1), path.name))
        dangling = [(d, name) for d, name in edges if d not in known]
        assert not dangling, f"down_revision values with no matching revision: {dangling}"


class TestCashMovementKinds:
    """Every kind of movement the cashier can create must be representable.

    `CashierService` writes four `reference_type` values; the output schema listed
    three. The customer-refund path was added to the service without widening the
    Literal, so the closing report answered 500 on any day a refund had been paid —
    and it stayed hidden because the report's day window was broken too, and never
    looked at the day the refunds were on. Two bugs covering for each other.

    Reading both sides and comparing them is cheap; noticing by hand is evidently not.
    """

    def test_the_schema_covers_every_reference_type_the_service_writes(self) -> None:
        import ast
        import pathlib
        import typing

        from app.api.schemas.cashier import CashMovementOut

        service = (
            pathlib.Path(__file__).resolve().parents[1]
            / "services"
            / "cashier"
            / "cashier_service.py"
        )
        tree = ast.parse(service.read_text(encoding="utf-8"))

        # Only the reference_type of an actual CashMovement(...) construction; the
        # journal entries alongside them use their own, unrelated vocabulary.
        written: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CashMovement"
            ):
                for keyword in node.keywords:
                    if keyword.arg == "reference_type" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        written.add(keyword.value.value)

        assert written, "found no CashMovement constructions — the check went blind"

        allowed = set(
            typing.get_args(CashMovementOut.model_fields["reference_type"].annotation)
        )
        missing = written - allowed
        assert not missing, (
            f"CashierService writes {sorted(missing)} but CashMovementOut does not "
            "allow it — the daily summary will fail validation on any day one occurs"
        )
