"""add driver role

Revision ID: b1d2e3f4a5c6
Revises: aaecbb2f94c2
Create Date: 2026-07-17

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1d2e3f4a5c6"
down_revision: Union[str, None] = "aaecbb2f94c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite stores the enum as VARCHAR; only PostgreSQL needs the type extended.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'driver'")


def downgrade() -> None:
    # PostgreSQL cannot drop enum values; leaving 'driver' in place is harmless.
    pass
