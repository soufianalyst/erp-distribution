"""customers get their own way in, separate from staff

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The first table in this system that a person outside the company can reach.
    #
    # Deliberately not rows in `users`: staff and customers would then be separated
    # by a single `role` column, and one permissive default anywhere in the
    # permission catalogue would hand a shop owner the run of the business. Two
    # tables cannot be confused by a default.
    #
    # Tokens now carry a `realm` claim for the same reason at the other end — both
    # tables number their rows from 1, so without it customer 7's token would resolve
    # to user 7.
    op.create_table(
        "customer_logins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        # Phone or email, whichever the office hands out. One opaque identifier: a
        # grocery is reached by phone and an office by email, and the system has no
        # business insisting on either.
        sa.Column("login_id", sa.String(length=120), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        # Issued as a temporary password; the portal refuses everything else until it
        # is changed. No mail or SMS gateway is configured, so an emailed invite link
        # would be a feature that silently never arrives.
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        # Lockout state lives in the row, not in memory: a restart must not reset an
        # attack, and several workers must not each grant a fresh set of guesses.
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        # One login per customer, and a login id that cannot be shared: both are
        # uniqueness the database enforces rather than the service remembering to.
        sa.UniqueConstraint("customer_id", name="uq_customer_logins_customer"),
        sa.UniqueConstraint("login_id", name="uq_customer_logins_login_id"),
    )
    op.create_index(
        "ix_customer_logins_customer_id", "customer_logins", ["customer_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_customer_logins_customer_id", table_name="customer_logins")
    op.drop_table("customer_logins")
