"""add_warehouse_id_to_sales_invoice_line

Revision ID: 0d62568dc739
Revises: b1d2e3f4a5c6
Create Date: 2026-07-17 18:09:14.812221

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d62568dc739'
down_revision: Union[str, None] = 'b1d2e3f4a5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Add warehouse_id as nullable first.
    op.add_column('sales_invoice_lines', sa.Column('warehouse_id', sa.Integer(), nullable=True))
    # 2) Backfill existing lines from their parent invoice's warehouse_id.
    op.execute("""
        UPDATE sales_invoice_lines
        SET warehouse_id = si.warehouse_id
        FROM sales_invoices si
        WHERE sales_invoice_lines.invoice_id = si.id
    """)
    # 3) Now make it NOT NULL.
    op.alter_column('sales_invoice_lines', 'warehouse_id', nullable=False)
    # 4) Add FK constraint.
    op.create_foreign_key(None, 'sales_invoice_lines', 'warehouses', ['warehouse_id'], ['id'])
    # 5) Make invoice-level warehouse_id nullable.
    op.alter_column('sales_invoices', 'warehouse_id',
               existing_type=sa.INTEGER(),
               nullable=True)


def downgrade() -> None:
    op.alter_column('sales_invoices', 'warehouse_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_constraint(None, 'sales_invoice_lines', type_='foreignkey')
    op.drop_column('sales_invoice_lines', 'warehouse_id')
