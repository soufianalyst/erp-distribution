"""product home warehouse and invoice line warehouse

Revision ID: c2d3e4f5a6b7
Revises: b1d2e3f4a5c6
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1d2e3f4a5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Each product now has one home warehouse; existing rows start unassigned and
    # must be set once via the products page before they can be sold.
    op.add_column(
        "products",
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("products") as batch_op:
        batch_op.create_foreign_key(
            "fk_products_warehouse_id", "warehouses", ["warehouse_id"], ["id"]
        )

    # Snapshot warehouse per invoice line, backfilled from the batch it was allocated from.
    op.add_column(
        "sales_invoice_lines",
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("sales_invoice_lines") as batch_op:
        batch_op.create_foreign_key(
            "fk_sales_invoice_lines_warehouse_id",
            "warehouses",
            ["warehouse_id"],
            ["id"],
        )
    op.execute(
        """
        UPDATE sales_invoice_lines
        SET warehouse_id = (
            SELECT product_batches.warehouse_id
            FROM product_batches
            WHERE product_batches.id = sales_invoice_lines.batch_id
        )
        """
    )

    # Invoice-level warehouse is now derived (NULL when lines span several warehouses).
    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.alter_column("warehouse_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.alter_column(
            "warehouse_id", existing_type=sa.Integer(), nullable=False
        )

    with op.batch_alter_table("sales_invoice_lines") as batch_op:
        batch_op.drop_constraint(
            "fk_sales_invoice_lines_warehouse_id", type_="foreignkey"
        )
    op.drop_column("sales_invoice_lines", "warehouse_id")

    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_constraint("fk_products_warehouse_id", type_="foreignkey")
    op.drop_column("products", "warehouse_id")
