"""Lead time and buffer settings for computed reorder points.

`min_stock_level` is a number somebody typed, and on the seeded database it fires
for no product at all while 329 of 1,060 sit at zero — meaning their first warning
arrives once the shelf is already empty. Replacing it with a computed point needs
three facts the system does not hold: how long a supplier takes, how much cover to
carry, and how often purchasing actually orders.

Lead time is stated rather than measured because there is no purchase-order history
to learn it from, and it lives per supplier as well as company-wide: a local dairy
delivers tomorrow and imported rice takes a month.

Revision ID: 07da8f0e246c
Revises: 18155dc754fa
"""

import sqlalchemy as sa
from alembic import op

revision = "07da8f0e246c"
down_revision = "18155dc754fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_settings",
        sa.Column(
            "default_lead_time_days", sa.Integer(), nullable=False, server_default="7"
        ),
    )
    op.add_column(
        "company_settings",
        sa.Column("safety_stock_days", sa.Integer(), nullable=False, server_default="7"),
    )
    op.add_column(
        "company_settings",
        sa.Column(
            "reorder_review_days", sa.Integer(), nullable=False, server_default="14"
        ),
    )
    op.add_column("suppliers", sa.Column("lead_time_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("suppliers", "lead_time_days")
    op.drop_column("company_settings", "reorder_review_days")
    op.drop_column("company_settings", "safety_stock_days")
    op.drop_column("company_settings", "default_lead_time_days")
