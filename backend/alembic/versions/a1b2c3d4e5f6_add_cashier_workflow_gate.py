"""add cashier payment-confirmation gate and card payment method

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales_invoices",
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sales_invoices",
        sa.Column("payment_confirmed_by", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.create_foreign_key(
            "fk_sales_invoices_payment_confirmed_by", "users", ["payment_confirmed_by"], ["id"]
        )

    # Grandfather existing invoices: the cashier gate is a new workflow going
    # forward only — every invoice created before this migration (cash, card, or
    # already-delivered/picked-up) is treated as already confirmed so nothing
    # already in flight gets silently blocked from delivery/pickup.
    op.execute("UPDATE sales_invoices SET payment_confirmed_at = created_at")

    # SQLite stores the enum as VARCHAR; only PostgreSQL needs the type extended.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE salespaymentmethod ADD VALUE IF NOT EXISTS 'card'")
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'cashier'")


def downgrade() -> None:
    with op.batch_alter_table("sales_invoices") as batch_op:
        batch_op.drop_constraint(
            "fk_sales_invoices_payment_confirmed_by", type_="foreignkey"
        )
    op.drop_column("sales_invoices", "payment_confirmed_by")
    op.drop_column("sales_invoices", "payment_confirmed_at")
    # PostgreSQL cannot drop enum values; leaving 'card'/'cashier' in place is harmless.
