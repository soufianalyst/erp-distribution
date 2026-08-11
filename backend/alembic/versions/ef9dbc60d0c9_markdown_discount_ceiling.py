"""markdown discount ceiling as company policy

The deepest markdown the clearance engine may propose. It was a query parameter with
a default of 50, which meant the ceiling on a price the customer actually pays was
whatever the browser last sent.

Revision ID: ef9dbc60d0c9
Revises: 07da8f0e246c
Create Date: 2026-08-11
"""

from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "ef9dbc60d0c9"
down_revision = "07da8f0e246c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_settings",
        sa.Column(
            "markdown_max_discount_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="50",
        ),
    )


def downgrade() -> None:
    op.drop_column("company_settings", "markdown_max_discount_percent")
