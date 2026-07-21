"""add_purchase_returns_and_stock_adjustments

Revision ID: f1a2b3c4d5e6
Revises: e7094678ec0c
Create Date: 2026-07-18 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e7094678ec0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Purchase returns
    op.create_table('purchase_returns',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.Integer(), nullable=False),
    sa.Column('supplier_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Enum('defective', 'wrong_item', 'excess', 'quality', name='purchasereturnreason'), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('vat_amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['purchase_invoices.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_purchase_returns_invoice_id'), 'purchase_returns', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_purchase_returns_supplier_id'), 'purchase_returns', ['supplier_id'], unique=False)

    op.create_table('purchase_return_lines',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('return_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.ForeignKeyConstraint(['return_id'], ['purchase_returns.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['batch_id'], ['product_batches.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_purchase_return_lines_return_id'), 'purchase_return_lines', ['return_id'], unique=False)

    # Stock adjustments
    op.create_table('stock_adjustments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('warehouse_id', sa.Integer(), nullable=False),
    sa.Column('adjustment_type', sa.Enum('increase', 'decrease', name='adjustmenttype'), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('adjustment_date', sa.Date(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stock_adjustments_warehouse_id'), 'stock_adjustments', ['warehouse_id'], unique=False)

    op.create_table('stock_adjustment_lines',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('adjustment_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('notes', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['adjustment_id'], ['stock_adjustments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stock_adjustment_lines_adjustment_id'), 'stock_adjustment_lines', ['adjustment_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stock_adjustment_lines_adjustment_id'), table_name='stock_adjustment_lines')
    op.drop_table('stock_adjustment_lines')
    op.drop_index(op.f('ix_stock_adjustments_warehouse_id'), table_name='stock_adjustments')
    op.drop_table('stock_adjustments')
    op.execute("DROP TYPE IF EXISTS adjustmenttype")
    op.drop_index(op.f('ix_purchase_return_lines_return_id'), table_name='purchase_return_lines')
    op.drop_table('purchase_return_lines')
    op.drop_index(op.f('ix_purchase_returns_supplier_id'), table_name='purchase_returns')
    op.drop_index(op.f('ix_purchase_returns_invoice_id'), table_name='purchase_returns')
    op.drop_table('purchase_returns')
    op.execute("DROP TYPE IF EXISTS purchasereturnreason")
