"""customers can ask for goods, before anyone prices them

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # `fulfillmenttype` already exists — sales invoices use it. Creating the status
    # type explicitly with checkfirst, then referencing both with create_type=False,
    # is the pattern this project settled on after `op.create_table` re-issued
    # CREATE TYPE for an existing enum and failed on Postgres.
    status_type = postgresql.ENUM(
        "pending",
        "confirmed",
        "invoiced",
        "cancelled",
        name="customerorderstatus",
    )
    if bind.dialect.name == "postgresql":
        status_type.create(bind, checkfirst=True)

    def status_column() -> sa.types.TypeEngine:
        if bind.dialect.name == "postgresql":
            return postgresql.ENUM(
                "pending",
                "confirmed",
                "invoiced",
                "cancelled",
                name="customerorderstatus",
                create_type=False,
            )
        return sa.Enum(
            "pending", "confirmed", "invoiced", "cancelled",
            name="customerorderstatus",
        )

    def fulfillment_column() -> sa.types.TypeEngine:
        if bind.dialect.name == "postgresql":
            return postgresql.ENUM(
                "pickup", "delivery", name="fulfillmenttype", create_type=False
            )
        return sa.Enum("pickup", "delivery", name="fulfillmenttype")

    # An order carries quantities and no money. Pricing happens once, when the office
    # turns it into an invoice; a total stored here would be a second opinion about
    # what a sale is worth.
    op.create_table(
        "customer_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column(
            "status", status_column(), nullable=False, server_default="pending"
        ),
        sa.Column(
            "fulfillment",
            fulfillment_column(),
            nullable=False,
            server_default="delivery",
        ),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoices.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index(
        "ix_customer_orders_customer_id", "customer_orders", ["customer_id"]
    )
    op.create_index("ix_customer_orders_invoice_id", "customer_orders", ["invoice_id"])

    op.create_table(
        "customer_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"], ["customer_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
    )
    op.create_index(
        "ix_customer_order_lines_order_id", "customer_order_lines", ["order_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_customer_order_lines_order_id", table_name="customer_order_lines")
    op.drop_table("customer_order_lines")
    op.drop_index("ix_customer_orders_invoice_id", table_name="customer_orders")
    op.drop_index("ix_customer_orders_customer_id", table_name="customer_orders")
    op.drop_table("customer_orders")
    if bind.dialect.name == "postgresql":
        # `fulfillmenttype` is left alone — sales invoices still use it.
        postgresql.ENUM(name="customerorderstatus").drop(bind, checkfirst=True)
