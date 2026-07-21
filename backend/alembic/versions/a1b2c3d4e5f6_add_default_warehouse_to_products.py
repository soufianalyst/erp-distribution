"""add_default_warehouse_to_products

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-18 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('default_warehouse_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'products_default_warehouse_id_fkey',
        'products', 'warehouses',
        ['default_warehouse_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('products_default_warehouse_id_fkey', 'products', type_='foreignkey')
    op.drop_column('products', 'default_warehouse_id')
