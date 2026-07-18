"""generalize cash_collections into a bidirectional cash_movements ledger

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cash_movements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("reference_type", sa.String(length=30), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("party_id", sa.Integer(), nullable=True),
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
        "ix_cash_movements_reference", "cash_movements", ["reference_type", "reference_id"]
    )

    # Every existing collection was a sales-invoice inflow.
    op.execute(
        """
        INSERT INTO cash_movements
            (direction, reference_type, reference_id, party_id, amount, method,
             collected_by, collected_at)
        SELECT 'in', 'sales_invoice', invoice_id, customer_id, amount, method,
               collected_by, collected_at
        FROM cash_collections
        """
    )

    op.drop_index("ix_cash_collections_invoice_id", table_name="cash_collections")
    op.drop_table("cash_collections")


def downgrade() -> None:
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
    op.execute(
        """
        INSERT INTO cash_collections
            (invoice_id, customer_id, amount, method, collected_by, collected_at)
        SELECT reference_id, party_id, amount, method, collected_by, collected_at
        FROM cash_movements
        WHERE reference_type = 'sales_invoice' AND direction = 'in'
        """
    )
    op.drop_index("ix_cash_movements_reference", table_name="cash_movements")
    op.drop_table("cash_movements")
