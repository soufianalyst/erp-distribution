"""support multiple taxes per invoice and tax rate deletion

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_invoice_taxes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("sales_invoices.id", ondelete="CASCADE"),
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
        "ix_sales_invoice_taxes_invoice_id",
        "sales_invoice_taxes",
        ["invoice_id"],
    )

    # Backfill: every invoice that previously carried a single tax_rate_id
    # becomes one row here, snapshotting the tax's current name/rate and the
    # amount actually charged (invoice.vat_amount) — historical invoices keep
    # showing exactly what they always showed.
    op.execute(
        """
        INSERT INTO sales_invoice_taxes (invoice_id, tax_rate_id, name, rate, amount)
        SELECT si.id, si.tax_rate_id, tr.name, tr.rate, si.vat_amount
        FROM sales_invoices si
        JOIN tax_rates tr ON tr.id = si.tax_rate_id
        WHERE si.tax_rate_id IS NOT NULL
        """
    )

    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.drop_constraint("fk_sales_invoices_tax_rate_id", type_="foreignkey")
        batch_op.drop_column("tax_rate_id")


def downgrade() -> None:
    op.add_column(
        "sales_invoices",
        sa.Column("tax_rate_id", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.create_foreign_key(
            "fk_sales_invoices_tax_rate_id", "tax_rates", ["tax_rate_id"], ["id"]
        )

    # Best-effort: restore the first applied tax per invoice (an invoice that
    # had several taxes loses all but one on downgrade — acceptable for a
    # rollback path).
    op.execute(
        """
        UPDATE sales_invoices
        SET tax_rate_id = (
            SELECT sit.tax_rate_id
            FROM sales_invoice_taxes sit
            WHERE sit.invoice_id = sales_invoices.id
            ORDER BY sit.id
            LIMIT 1
        )
        """
    )

    op.drop_index("ix_sales_invoice_taxes_invoice_id", table_name="sales_invoice_taxes")
    op.drop_table("sales_invoice_taxes")
