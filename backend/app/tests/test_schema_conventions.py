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
