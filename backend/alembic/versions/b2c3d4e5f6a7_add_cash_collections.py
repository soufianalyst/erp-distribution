"""add cash_collections table for partial cashier payments

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cash_collections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("sales_invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column(
            "collected_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_cash_collections_invoice_id", "cash_collections", ["invoice_id"]
    )

    # Backfill: invoices that were already cashier-confirmed under the previous
    # single-shot flow (payment_confirmed_by set, not the mass-grandfathered
    # historical rows which have no collector) become one full collection event.
    op.execute(
        """
        INSERT INTO cash_collections
            (invoice_id, customer_id, amount, method, collected_by, collected_at)
        SELECT id, customer_id, paid_amount, payment_method, payment_confirmed_by,
               payment_confirmed_at
        FROM sales_invoices
        WHERE payment_confirmed_by IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_cash_collections_invoice_id", table_name="cash_collections")
    op.drop_table("cash_collections")
