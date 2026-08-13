"""taxes to show on a المواد المقننة declaration

The register prints as an invoice-shaped document, and which taxes appear on it is
chosen per register rather than fixed. Name and rate are snapshotted the way
`sales_invoice_taxes` snapshots them; the amount deliberately is not, because a
register's goods total moves whenever an invoice behind it is corrected, and a frozen
tax amount would be the only stale figure on an otherwise live document.

Revision ID: 13bba7adee6d
Revises: 1f843840fe9a
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "13bba7adee6d"
down_revision: Union[str, None] = "1f843840fe9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rationed_record_taxes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "record_id", sa.Integer(),
            sa.ForeignKey("rationed_records.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "tax_rate_id", sa.Integer(),
            sa.ForeignKey("tax_rates.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rate", sa.Numeric(6, 3), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rationed_record_taxes")
