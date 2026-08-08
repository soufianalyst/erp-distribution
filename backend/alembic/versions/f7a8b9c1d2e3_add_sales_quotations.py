"""add sales quotations

Revision ID: f7a8b9c1d2e3
Revises: e6f7a8b9c1d2
Create Date: 2026-07-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c1d2e3"
down_revision: Union[str, None] = "e6f7a8b9c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUOTATION_STATUS = postgresql.ENUM(
    "draft", "converted", "cancelled", name="quotationstatus"
)


def upgrade() -> None:
    bind = op.get_bind()
    QUOTATION_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "sales_quotations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "salesman_id", sa.Integer(), sa.ForeignKey("users.id"), index=True
        ),
        sa.Column("quote_date", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft", "converted", "cancelled", name="quotationstatus", create_type=False
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("vat_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("notes", sa.String(300), nullable=True),
        sa.Column(
            "converted_invoice_id",
            sa.Integer(),
            sa.ForeignKey("sales_invoices.id"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "sales_quotation_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "quotation_id",
            sa.Integer(),
            sa.ForeignKey("sales_quotations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
    )

    op.create_table(
        "sales_quotation_taxes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "quotation_id",
            sa.Integer(),
            sa.ForeignKey("sales_quotations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "tax_rate_id",
            sa.Integer(),
            sa.ForeignKey("tax_rates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sales_quotation_taxes")
    op.drop_table("sales_quotation_lines")
    op.drop_table("sales_quotations")
    QUOTATION_STATUS.drop(op.get_bind(), checkfirst=True)
