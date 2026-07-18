"""add configurable tax rates and company settings

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tax_rates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False, unique=True),
        sa.Column("rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "company_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("tagline", sa.String(length=200), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("tax_number", sa.String(length=50), nullable=True),
        sa.Column(
            "currency_code", sa.String(length=10), nullable=False, server_default="SAR"
        ),
        sa.Column(
            "currency_symbol",
            sa.String(length=10),
            nullable=False,
            server_default="ر.س",
        ),
    )

    op.add_column(
        "sales_invoices",
        sa.Column("tax_rate_id", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.create_foreign_key(
            "fk_sales_invoices_tax_rate_id", "tax_rates", ["tax_rate_id"], ["id"]
        )

    # Seed one default tax rate matching the previous hardcoded VAT_RATE (0.16 = 16%)
    # so existing invoicing behavior is unchanged out of the box, just now editable.
    tax_rates_table = sa.table(
        "tax_rates",
        sa.column("name", sa.String),
        sa.column("code", sa.String),
        sa.column("rate", sa.Numeric),
        sa.column("is_active", sa.Boolean),
        sa.column("is_default", sa.Boolean),
    )
    op.bulk_insert(
        tax_rates_table,
        [
            {
                "name": "ضريبة القيمة المضافة",
                "code": "VAT",
                "rate": 16.000,
                "is_active": True,
                "is_default": True,
            }
        ],
    )

    # Seed one company settings row matching the previously hardcoded print header.
    company_table = sa.table(
        "company_settings",
        sa.column("name", sa.String),
        sa.column("tagline", sa.String),
        sa.column("currency_code", sa.String),
        sa.column("currency_symbol", sa.String),
    )
    op.bulk_insert(
        company_table,
        [
            {
                "name": "شركة التوزيع الغذائي",
                "tagline": "بيع وتوزيع المواد الغذائية بالجملة",
                "currency_code": "SAR",
                "currency_symbol": "ر.س",
            }
        ],
    )

    # The "2020" ledger account now represents any configured tax, not
    # specifically VAT — relabel it generically for existing databases.
    op.execute(
        "UPDATE accounts SET name = 'الضريبة المحصلة على المبيعات' WHERE code = '2020'"
    )


def downgrade() -> None:
    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.drop_constraint("fk_sales_invoices_tax_rate_id", type_="foreignkey")
    op.drop_column("sales_invoices", "tax_rate_id")
    op.drop_table("company_settings")
    op.drop_table("tax_rates")
