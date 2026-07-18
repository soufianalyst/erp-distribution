"""add stock adjustments

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_adjustments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "expired",
                "damaged",
                "spoiled",
                "count_shortfall",
                "other",
                name="stockadjustmentreason",
            ),
            nullable=False,
        ),
        sa.Column("total_cost", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "stock_adjustment_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("adjustment_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["adjustment_id"], ["stock_adjustments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["product_batches.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_stock_adjustment_lines_adjustment_id"),
        "stock_adjustment_lines",
        ["adjustment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_stock_adjustment_lines_adjustment_id"),
        table_name="stock_adjustment_lines",
    )
    op.drop_table("stock_adjustment_lines")
    op.drop_table("stock_adjustments")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS stockadjustmentreason")
