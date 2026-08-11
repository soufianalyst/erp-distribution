"""collection activities, and an age-based credit block

Aging reports said who owed what; nothing recorded the chase. Measured before
building: 114,668 sits past 90 days across 189 invoices, while the 31-60 and 61-90
buckets hold 4,086 between them — debt here is either paid quickly or abandoned.

The credit *block* is the other half. Every one of the worst debtors is under their
25,000 limit, so the limit was never going to stop this: it measures size, never age.
One customer chain is 367 days overdue and was sold to on credit two days ago.

Revision ID: 23bca4cb97f0
Revises: ef9dbc60d0c9
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "23bca4cb97f0"
down_revision: Union[str, None] = "ef9dbc60d0c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLLECTION_OUTCOME = postgresql.ENUM(
    "promised", "paid", "no_answer", "refused", "disputed", "note",
    name="collectionoutcome",
)


def upgrade() -> None:
    bind = op.get_bind()
    COLLECTION_OUTCOME.create(bind, checkfirst=True)

    op.create_table(
        "collection_activities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "customer_id", sa.Integer(), sa.ForeignKey("customers.id"),
            nullable=False, index=True,
        ),
        sa.Column(
            "outcome",
            postgresql.ENUM(
                "promised", "paid", "no_answer", "refused", "disputed", "note",
                name="collectionoutcome", create_type=False,
            ),
            nullable=False,
        ),
        # Nullable, not zero-defaulted: "no promise" and "promised nothing" differ,
        # and a zero would read as a kept promise the moment any payment arrived.
        sa.Column("promised_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("promised_on", sa.Date(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )

    # 0 disables the block. Defaulted off rather than on, because switching it on is
    # a commercial decision that stops sales, and a migration is not the place to
    # make one on somebody's behalf.
    op.add_column(
        "company_settings",
        sa.Column(
            "credit_block_after_days", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("company_settings", "credit_block_after_days")
    op.drop_table("collection_activities")
    COLLECTION_OUTCOME.drop(op.get_bind(), checkfirst=True)
