"""add stock adjustment cancellation

Revision ID: a8b9c1d2e3f4
Revises: f7a8b9c1d2e3
Create Date: 2026-07-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a8b9c1d2e3f4"
down_revision: Union[str, None] = "f7a8b9c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ADJUSTMENT_STATUS = postgresql.ENUM("posted", "cancelled", name="adjustmentstatus")


def upgrade() -> None:
    # op.add_column does not create the enum type itself, unlike op.create_table.
    ADJUSTMENT_STATUS.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "stock_adjustments",
        sa.Column(
            "status",
            postgresql.ENUM(
                "posted", "cancelled", name="adjustmentstatus", create_type=False
            ),
            nullable=False,
            server_default="posted",
        ),
    )
    op.add_column(
        "stock_adjustments",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stock_adjustments",
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
    )
    op.add_column(
        "stock_adjustments",
        sa.Column("cancel_reason", sa.String(length=300), nullable=True),
    )
    op.create_foreign_key(
        "fk_stock_adjustments_cancelled_by_users",
        "stock_adjustments",
        "users",
        ["cancelled_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_stock_adjustments_cancelled_by_users", "stock_adjustments", type_="foreignkey"
    )
    op.drop_column("stock_adjustments", "cancel_reason")
    op.drop_column("stock_adjustments", "cancelled_by")
    op.drop_column("stock_adjustments", "cancelled_at")
    op.drop_column("stock_adjustments", "status")
    ADJUSTMENT_STATUS.drop(op.get_bind(), checkfirst=True)
