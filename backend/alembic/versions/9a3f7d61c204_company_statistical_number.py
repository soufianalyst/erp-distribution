"""NIS on the company

The company's own رقم التعريف الإحصائي, printed in the header of documents an
authority reads, beside the NIF it already carries as `tax_number`.

Nullable like the rest of the identity block: a company that has not been asked for
its NIS should not have to invent one to save its address.

Revision ID: 9a3f7d61c204
Revises: 7c4e2a91d5b8
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9a3f7d61c204"
down_revision: Union[str, None] = "7c4e2a91d5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "company_settings",
        sa.Column("statistical_number", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("company_settings", "statistical_number")
