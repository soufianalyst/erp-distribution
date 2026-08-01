"""add stocktakes (physical inventory counts)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STOCKTAKE_STATUS = postgresql.ENUM(
    "counting",
    "posted",
    "cancelled",
    name="stocktakestatus",
)


def upgrade() -> None:
    # The status column below carries a server default that references the enum,
    # so create the type up front rather than letting create_table infer it.
    STOCKTAKE_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "stocktakes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("count_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "counting",
                "posted",
                "cancelled",
                name="stocktakestatus",
                create_type=False,
            ),
            nullable=False,
            server_default="counting",
        ),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column(
            "net_value", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_stocktakes_warehouse_id"), "stocktakes", ["warehouse_id"]
    )

    op.create_table(
        "stocktake_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stocktake_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.String(length=50), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(14, 3), nullable=False),
        # Nullable on purpose: NULL means "not counted yet", 0 means "counted, none found".
        sa.Column("counted_quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit_cost", sa.Numeric(12, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["stocktake_id"], ["stocktakes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["product_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_stocktake_lines_stocktake_id"), "stocktake_lines", ["stocktake_id"]
    )

    # Ledger account for count differences (see accounting_service). The enum is
    # stored by value, hence lowercase 'expense'.
    op.execute(
        """
        INSERT INTO accounts (code, name, type, is_system, is_active)
        SELECT '5040', 'فروقات الجرد (عجز وزيادة)', 'expense', true, true
        WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE code = '5040')
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM accounts WHERE code = '5040'")
    op.drop_index(
        op.f("ix_stocktake_lines_stocktake_id"), table_name="stocktake_lines"
    )
    op.drop_table("stocktake_lines")
    op.drop_index(op.f("ix_stocktakes_warehouse_id"), table_name="stocktakes")
    op.drop_table("stocktakes")
    STOCKTAKE_STATUS.drop(op.get_bind(), checkfirst=True)
