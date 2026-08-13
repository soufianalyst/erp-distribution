"""NIF and NIS on the customer

The المواد المقننة declaration is handed to an authority, and an authority identifies
the recipient by their registration numbers rather than by the name over the shop. So
the customer file now carries both: `tax_number` (رقم التعريف الضريبي — NIF) and
`statistical_number` (رقم التعريف الإحصائي — NIS).

Nullable, because most customers are billed without either and a NOT NULL column here
would be filled with a dash by whoever needed to get past it. Not unique either: a NIF
identifies the legal entity, so two branches of one company legitimately share one, and
a unique index would reject the second branch for being correct.

Revision ID: 7c4e2a91d5b8
Revises: 13bba7adee6d
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c4e2a91d5b8"
down_revision: Union[str, None] = "13bba7adee6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("tax_number", sa.String(50), nullable=True))
    op.add_column(
        "customers", sa.Column("statistical_number", sa.String(50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("customers", "statistical_number")
    op.drop_column("customers", "tax_number")
