"""support multiple configurable taxes per purchase invoice

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purchase_invoice_taxes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("purchase_invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tax_rate_id",
            sa.Integer(),
            sa.ForeignKey("tax_rates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    )
    op.create_index(
        "ix_purchase_invoice_taxes_invoice_id",
        "purchase_invoice_taxes",
        ["invoice_id"],
    )

    # Backfill: purchase invoices used to carry a free-typed vat_amount with no
    # link to any configured tax type. Turn each non-zero one into a single
    # unlabeled legacy row so the invoice's total keeps reconciling, without
    # pretending we know which tax type or rate it actually was.
    op.execute(
        """
        INSERT INTO purchase_invoice_taxes (invoice_id, tax_rate_id, name, rate, amount)
        SELECT id, NULL, 'ضريبة (مسجلة يدوياً سابقاً)', 0, vat_amount
        FROM purchase_invoices
        WHERE vat_amount > 0
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_invoice_taxes_invoice_id", table_name="purchase_invoice_taxes"
    )
    op.drop_table("purchase_invoice_taxes")
