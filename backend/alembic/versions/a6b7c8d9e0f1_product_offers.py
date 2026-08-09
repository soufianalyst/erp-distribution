"""temporary markdowns, shown to customers and binding at sale

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A percentage, not a price. Customers buy at three tiers, and a flat offer price
    # would give a retail shop the wholesale number — collapsing the ladder and, at a
    # deep discount, selling below the wholesale price. A percentage comes off
    # whatever that customer already pays.
    op.create_table(
        "product_offers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False),
        # Inclusive both ends: "until the 20th" runs through the 20th.
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "discount_percent > 0 AND discount_percent < 100",
            name="ck_product_offers_percent_range",
        ),
        # A window that ends before it starts would silently never apply, which is
        # worse than being refused: the offer looks set and simply does nothing.
        sa.CheckConstraint("ends_on >= starts_on", name="ck_product_offers_window"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_product_offers_product_id", "product_offers", ["product_id"])
    # Every price lookup asks "is there a live offer for these products today", so the
    # window is indexed alongside the flag rather than filtered in Python.
    op.create_index(
        "ix_product_offers_window",
        "product_offers",
        ["is_active", "starts_on", "ends_on"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_offers_window", table_name="product_offers")
    op.drop_index("ix_product_offers_product_id", table_name="product_offers")
    op.drop_table("product_offers")
