"""add purchase orders

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORDER_STATUS = postgresql.ENUM(
    "draft",
    "sent",
    "partially_received",
    "received",
    "cancelled",
    name="purchaseorderstatus",
)


def upgrade() -> None:
    # op.create_table would create the enum implicitly, but the column default
    # below references it, so create it up front and reuse it.
    ORDER_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft",
                "sent",
                "partially_received",
                "received",
                "cancelled",
                name="purchaseorderstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_purchase_orders_supplier_id"),
        "purchase_orders",
        ["supplier_id"],
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "received_quantity",
            sa.Numeric(14, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("unit_cost", sa.Numeric(12, 4), nullable=False),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"], ["purchase_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_purchase_order_lines_order_id"),
        "purchase_order_lines",
        ["order_id"],
    )

    # Links a received delivery back to the order it fulfils.
    op.add_column(
        "purchase_invoices",
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_purchase_invoices_purchase_order_id"),
        "purchase_invoices",
        ["purchase_order_id"],
    )
    op.create_foreign_key(
        "fk_purchase_invoices_purchase_order_id",
        "purchase_invoices",
        "purchase_orders",
        ["purchase_order_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_purchase_invoices_purchase_order_id",
        "purchase_invoices",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_purchase_invoices_purchase_order_id"), table_name="purchase_invoices"
    )
    op.drop_column("purchase_invoices", "purchase_order_id")

    op.drop_index(
        op.f("ix_purchase_order_lines_order_id"), table_name="purchase_order_lines"
    )
    op.drop_table("purchase_order_lines")
    op.drop_index(op.f("ix_purchase_orders_supplier_id"), table_name="purchase_orders")
    op.drop_table("purchase_orders")
    ORDER_STATUS.drop(op.get_bind(), checkfirst=True)
