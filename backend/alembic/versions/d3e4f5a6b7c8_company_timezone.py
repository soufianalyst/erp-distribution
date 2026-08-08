"""the company owns its own day boundary

Revision ID: d3e4f5a6b7c8
Revises: b1c2d3e4f5a6
Create Date: 2026-08-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The cashier's closing report asked for "today" using the server's local date and
    # then searched a window built on UTC midnight. At 01:26 local (UTC+03) that looked
    # between 8 August 00:00 UTC and 9 August 00:00 UTC while the collection just made
    # was stamped 7 August 22:26 UTC — so the report read empty with the cash in the
    # drawer, every day between midnight and 03:00.
    #
    # UTC is the default because it is what the timestamps already are: existing
    # installations keep behaving exactly as they did until someone sets this, and
    # nothing shifts under them silently.
    op.add_column(
        "company_settings",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="UTC",
        ),
    )


def downgrade() -> None:
    op.drop_column("company_settings", "timezone")
