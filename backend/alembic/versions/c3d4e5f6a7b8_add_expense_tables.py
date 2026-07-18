"""add expense categories and expenses tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("expense_categories.id"),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("payment_method", sa.String(length=10), nullable=False),
        sa.Column(
            "paid_amount", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "payment_confirmed_by",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_expenses_category_id", "expenses", ["category_id"])

    # Seed the new general operating-expenses account and relabel the payables
    # account now that it covers supplier AND expense payables, not just suppliers
    # (same relabeling pattern used earlier when VAT became "any configured tax").
    op.execute(
        """
        INSERT INTO accounts (code, name, type, is_system, is_active)
        SELECT '5020', 'مصاريف تشغيلية عامة', 'expense', 1, 1
        WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE code = '5020')
        """
    )
    op.execute("UPDATE accounts SET name = 'ذمم دائنة' WHERE code = '2010'")


def downgrade() -> None:
    op.drop_index("ix_expenses_category_id", table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("expense_categories")
