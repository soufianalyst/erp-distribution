"""Legacy import references on sales invoices and customer payments.

One nullable column on each does two jobs at once.

It is the duplicate guard: an imported document carries the identifier it had in
the old system, and the unique index makes re-uploading the same spreadsheet an
error rather than a doubled ledger.

It is also the marker that separates history from work. Every cash or card invoice
with no `payment_confirmed_at` appears on the cashier's screen as money to collect
today, and every confirmed or credit invoice appears on the delivery screen as goods
to load. Importing ten thousand historical invoices would bury both worklists in
sales that were settled and delivered years ago. `legacy_ref IS NOT NULL` is how
those two queries now recognise a record as archive rather than a job.

Revision ID: 18155dc754fa
Revises: a6b7c8d9e0f1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "18155dc754fa"
down_revision: Union[str, None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales_invoices", sa.Column("legacy_ref", sa.String(length=60), nullable=True)
    )
    op.create_index(
        "ix_sales_invoices_legacy_ref",
        "sales_invoices",
        ["legacy_ref"],
        unique=True,
    )
    op.add_column(
        "customer_payments", sa.Column("legacy_ref", sa.String(length=60), nullable=True)
    )
    op.create_index(
        "ix_customer_payments_legacy_ref",
        "customer_payments",
        ["legacy_ref"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_customer_payments_legacy_ref", table_name="customer_payments")
    op.drop_column("customer_payments", "legacy_ref")
    op.drop_index("ix_sales_invoices_legacy_ref", table_name="sales_invoices")
    op.drop_column("sales_invoices", "legacy_ref")
