"""purchase, order and return lines name their product too

Sales invoice lines got this in 622001ff7397. These four tables have the same gap for
the same reason, and it is what still forced the purchases screen to download the whole
catalogue: three separate tables were rendered with
`products.find(p => p.id === line.product_id)?.name`, so no amount of typeahead in the
entry forms would have removed the fetch while the *display* tables needed every id
resolved.

Same treatment, same reasoning: a document that borrows its description from a mutable
table is a document that changes when somebody renames a product.

Revision ID: 3d3822054244
Revises: 622001ff7397
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "3d3822054244"
down_revision: Union[str, None] = "622001ff7397"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "purchase_invoice_lines",
    "purchase_order_lines",
    "purchase_return_lines",
    "sales_return_lines",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table, sa.Column("product_name", sa.String(200), nullable=True)
        )
        op.execute(
            f"""
            UPDATE {table} AS l
               SET product_name = p.name
              FROM products AS p
             WHERE p.id = l.product_id
            """
        )
        # A line whose product row is gone keeps a marker rather than a NULL: "the
        # product this sold has been deleted" is a fact worth printing, and an empty
        # cell is not.
        op.execute(
            f"""
            UPDATE {table}
               SET product_name = 'صنف محذوف'
             WHERE product_name IS NULL
            """
        )
        op.alter_column(table, "product_name", nullable=False)


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "product_name")
