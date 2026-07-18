"""add cashier payment-confirmation gate to purchase invoices

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_invoices",
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "purchase_invoices",
        sa.Column("payment_confirmed_by", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("purchase_invoices") as batch_op:
        batch_op.create_foreign_key(
            "fk_purchase_invoices_payment_confirmed_by",
            "users",
            ["payment_confirmed_by"],
            ["id"],
        )

    # Grandfather existing invoices: the cashier gate is a new workflow going
    # forward only — every purchase invoice created before this migration is
    # treated as already settled so nothing already-received gets blocked.
    op.execute("UPDATE purchase_invoices SET payment_confirmed_at = created_at")

    # SQLite stores the enum as VARCHAR; only PostgreSQL needs the type extended.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE purchasepaymentmethod ADD VALUE IF NOT EXISTS 'card'")


def downgrade() -> None:
    with op.batch_alter_table("purchase_invoices") as batch_op:
        batch_op.drop_constraint(
            "fk_purchase_invoices_payment_confirmed_by", type_="foreignkey"
        )
    op.drop_column("purchase_invoices", "payment_confirmed_by")
    op.drop_column("purchase_invoices", "payment_confirmed_at")
