"""legacy refs on purchase invoices and supplier payments

The same replay protection the sales side already has (18155dc754fa). Without it a
re-uploaded purchase file would credit every supplier twice, and the second run would
look exactly as successful as the first.

Revision ID: 402085f78341
Revises: 23bca4cb97f0
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "402085f78341"
down_revision: Union[str, None] = "23bca4cb97f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("purchase_invoices", "supplier_payments"):
        op.add_column(
            table,
            # Unique so a repeated import is refused by the database itself, not only
            # by the validator — the validator can be bypassed, a constraint cannot.
            sa.Column("legacy_ref", sa.String(60), nullable=True),
        )
        op.create_index(
            f"ix_{table}_legacy_ref", table, ["legacy_ref"], unique=True
        )


def downgrade() -> None:
    for table in ("purchase_invoices", "supplier_payments"):
        op.drop_index(f"ix_{table}_legacy_ref", table_name=table)
        op.drop_column(table, "legacy_ref")
