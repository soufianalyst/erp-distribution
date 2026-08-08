"""money owed back to a customer after a return

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CREDIT_RESOLUTION = postgresql.ENUM(
    "pending", "refunded", "credited", name="creditresolution"
)


def upgrade() -> None:
    CREDIT_RESOLUTION.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "customer_credits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("return_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "resolution",
            postgresql.ENUM(
                "pending",
                "refunded",
                "credited",
                name="creditresolution",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoices.id"]),
        sa.ForeignKeyConstraint(["return_id"], ["sales_returns.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_credits_customer_id", "customer_credits", ["customer_id"])
    op.create_index("ix_customer_credits_invoice_id", "customer_credits", ["invoice_id"])
    op.create_index("ix_customer_credits_return_id", "customer_credits", ["return_id"])

    # One credit per return, so the same over-collection cannot be refunded once and
    # then also left on account. Enforced here rather than only in the service
    # because the check and the insert are separate statements: two clicks arriving
    # together would both pass an application-level test.
    op.create_index(
        "uq_customer_credits_per_return",
        "customer_credits",
        ["return_id"],
        unique=True,
        postgresql_where=sa.text("return_id IS NOT NULL"),
    )

    # Existing over-collections are NOT backfilled.
    #
    # The dev database has two, created by the bug this release fixes: the cashier
    # was asked for the pre-return amount because the amount due ignored returns, so
    # customers were charged more than they owed. Those are real obligations, but
    # each needs a person to decide refund-or-credit, and inventing pending rows for
    # historical invoices would put decisions in a queue with nobody able to
    # remember the circumstances. They remain visible as negative statement balances;
    # settle them by hand.
    #
    # From here on, any return that over-collects raises its own credit row.


def downgrade() -> None:
    op.drop_index("uq_customer_credits_per_return", table_name="customer_credits")
    op.drop_index("ix_customer_credits_return_id", table_name="customer_credits")
    op.drop_index("ix_customer_credits_invoice_id", table_name="customer_credits")
    op.drop_index("ix_customer_credits_customer_id", table_name="customer_credits")
    op.drop_table("customer_credits")
    CREDIT_RESOLUTION.drop(op.get_bind(), checkfirst=True)
