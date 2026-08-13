"""sales invoice lines record the product name they were sold under

An invoice is a financial record, and this one could not say what it sold. The line
stored `product_id` and `batch_number` but not the product's name or unit, so renaming
a product silently rewrote every historical invoice that contained it — and printing
one invoice meant downloading the entire catalogue to look the names up.

`batch_number` was already denormalised onto the line for exactly this reason. These
two columns follow the precedent that was already there.

Backfilled from the current catalogue, which is the best available answer for lines
written before the columns existed: today's name is what those invoices have been
displaying all along, so nothing on screen changes. From here on the name is frozen at
the moment of sale.

Revision ID: 622001ff7397
Revises: 402085f78341
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "622001ff7397"
down_revision: Union[str, None] = "402085f78341"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable first so the backfill has somewhere to write, then tightened: a line
    # that cannot name its product is the bug being fixed, so NULL must not remain
    # reachable once the existing rows are filled.
    op.add_column(
        "sales_invoice_lines", sa.Column("product_name", sa.String(200), nullable=True)
    )
    op.add_column(
        "sales_invoice_lines", sa.Column("unit_name", sa.String(50), nullable=True)
    )

    op.execute(
        """
        UPDATE sales_invoice_lines AS l
           SET product_name = p.name, unit_name = p.base_unit_name
        FROM products AS p
        WHERE p.id = l.product_id
        """
    )
    # A line whose product row has since been deleted has nothing to copy; it keeps a
    # marker rather than a NULL, because "the product this sold is gone" is a fact
    # worth printing and an empty cell is not.
    op.execute(
        """
        UPDATE sales_invoice_lines
           SET product_name = COALESCE(product_name, 'صنف محذوف'),
               unit_name = COALESCE(unit_name, '—')
         WHERE product_name IS NULL OR unit_name IS NULL
        """
    )

    op.alter_column("sales_invoice_lines", "product_name", nullable=False)
    op.alter_column("sales_invoice_lines", "unit_name", nullable=False)


def downgrade() -> None:
    op.drop_column("sales_invoice_lines", "unit_name")
    op.drop_column("sales_invoice_lines", "product_name")
