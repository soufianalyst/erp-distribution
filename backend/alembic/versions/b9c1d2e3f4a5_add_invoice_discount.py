"""add sales invoice discount and contra-revenue account

Revision ID: b9c1d2e3f4a5
Revises: a8b9c1d2e3f4
Create Date: 2026-08-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c1d2e3f4a5"
down_revision: Union[str, None] = "a8b9c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales_invoices",
        sa.Column(
            "discount_amount",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
    )

    # Contra-revenue account for discounts granted. Seeded here so existing
    # installations get it without needing the chart of accounts re-created.
    # Booleans are written as true/false: Postgres rejects integer literals.
    op.execute(
        """
        INSERT INTO accounts (code, name, type, is_system, is_active)
        SELECT '4030', 'خصم مسموح به', 'revenue', true, true
        WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE code = '4030')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM accounts WHERE code = '4030'")
    op.drop_column("sales_invoices", "discount_amount")
