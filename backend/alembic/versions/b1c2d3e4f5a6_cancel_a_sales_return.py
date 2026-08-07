"""a sales return can be cancelled

Revision ID: b1c2d3e4f5a6
Revises: f0a1b2c3d4e5
Create Date: 2026-08-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETURN_STATUS = postgresql.ENUM("posted", "cancelled", name="returnstatus")


def upgrade() -> None:
    # A credit note entered by mistake had no way back: the goods were already added
    # to stock, the entry posted, the customer credited, and nothing could undo any of
    # it. Damage write-offs have had a cancel from the start; returns did not, which
    # left the one document that moves both stock and money as the only irreversible
    # one.
    RETURN_STATUS.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "sales_returns",
        sa.Column(
            "status",
            postgresql.ENUM("posted", "cancelled", name="returnstatus", create_type=False),
            nullable=False,
            server_default="posted",
        ),
    )
    op.add_column(
        "sales_returns", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sales_returns", sa.Column("cancelled_by", sa.Integer(), nullable=True))
    op.add_column(
        "sales_returns", sa.Column("cancel_reason", sa.String(length=300), nullable=True)
    )
    op.create_foreign_key(
        "fk_sales_returns_cancelled_by", "sales_returns", "users", ["cancelled_by"], ["id"]
    )
    # Everything already recorded stands — the default above says so explicitly
    # rather than leaving the column nullable and ambiguous.


def downgrade() -> None:
    op.drop_constraint("fk_sales_returns_cancelled_by", "sales_returns", type_="foreignkey")
    op.drop_column("sales_returns", "cancel_reason")
    op.drop_column("sales_returns", "cancelled_by")
    op.drop_column("sales_returns", "cancelled_at")
    op.drop_column("sales_returns", "status")
    RETURN_STATUS.drop(op.get_bind(), checkfirst=True)
