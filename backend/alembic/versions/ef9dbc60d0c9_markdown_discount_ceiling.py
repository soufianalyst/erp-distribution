"""markdown discount ceiling as company policy

The deepest markdown the clearance engine may propose. It was a query parameter with
a default of 50, which meant the ceiling on a price the customer actually pays was
whatever the browser last sent.

Revision ID: ef9dbc60d0c9
Revises: 07da8f0e246c
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Annotated exactly like every other migration in this folder: the convention test
# that walks the chain matches on `revision: str = "..."`, so a bare assignment makes
# a revision invisible to it — and the next migration to point here looks dangling.
revision: str = "ef9dbc60d0c9"
down_revision: Union[str, None] = "07da8f0e246c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
