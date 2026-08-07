"""separate the decision to refund from the refund itself

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-08-05

"""

from typing import Sequence, Union

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deciding to hand cash back and actually handing it over are two acts, usually
    # by two people. Collapsing them into one state made the refund unreachable: the
    # decision marked the credit refunded, and the till then refused to pay because
    # it was already refunded. Found by walking the flow end to end.
    op.execute("ALTER TYPE creditresolution ADD VALUE IF NOT EXISTS 'awaiting_refund'")


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum type. Rows sitting in the new
    # state are moved back to 'pending' so the column stays readable by older code;
    # the label itself remains, harmlessly unused.
    op.execute(
        "UPDATE customer_credits SET resolution = 'pending' "
        "WHERE resolution = 'awaiting_refund'"
    )
