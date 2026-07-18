"""add product barcode

Revision ID: d5e6f7a8b9c1
Revises: c4d5e6f7a8b9
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c1"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("barcode", sa.String(length=50), nullable=True))
    op.create_index(
        op.f("ix_products_barcode"), "products", ["barcode"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_products_barcode"), table_name="products")
    op.drop_column("products", "barcode")
