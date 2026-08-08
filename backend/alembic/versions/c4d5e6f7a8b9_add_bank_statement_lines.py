"""add bank statement lines

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_statement_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("line_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("matched_journal_item_id", sa.Integer(), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_by", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["matched_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["matched_journal_item_id"], ["journal_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("matched_journal_item_id"),
    )


def downgrade() -> None:
    op.drop_table("bank_statement_lines")
