"""customer portal: orders, order lines, and customer-linked portal accounts

Revision ID: a8c1d2e3f4a5
Revises: d3e4f5a6b7c8
Create Date: 2026-08-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8c1d2e3f4a5"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # The portal role joins the userrole enum (SQLite renders it as VARCHAR and
    # needs nothing; PostgreSQL needs the value added before any row uses it).
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'customer'")

    # --- users.customer_id: portal accounts bound to exactly one customer ---
    # The FK is guarded to PostgreSQL: SQLAlchemy batches an ALTERed constraint
    # by copying whole tables, which meets the six-year-old users<->customers
    # cycle again and SQLite cannot add constraints by ALTER anyway. SQLite
    # databases (dev/tests) build their schema from Base.metadata.create_all,
    # which handles the cycle via the model's use_alter=True.
    op.add_column("users", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_customer_id", "users", ["customer_id"], unique=True)
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_users_customer_id_customers", "users", "customers", ["customer_id"], ["id"]
        )

    # --- customer_orders ---
    # The enum type is created by the status column's own DDL (PostgreSQL's
    # dialect emits CREATE TYPE before CREATE TABLE). An explicit
    # .create(checkfirst=True) is deliberately NOT issued: this alembic build
    # renders it anyway in offline (--sql) mode, duplicating the CREATE TABLE
    # that the column emits next to it.
    op.create_table(
        "customer_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "invoiced",
                "cancelled",
                name="customerorderstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "fulfillment",
            sa.Enum("pickup", "delivery", name="fulfillmenttype", create_type=False),
            nullable=False,
            server_default="delivery",
        ),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("converted_invoice_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_by", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["converted_invoice_id"], ["sales_invoices.id"]),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index(
        "ix_customer_orders_customer_id", "customer_orders", ["customer_id"]
    )

    # --- customer_order_lines ---
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
    op.drop_index("ix_customer_orders_customer_id", table_name="customer_orders")
    op.drop_table("customer_orders")
    if bind.dialect.name == "postgresql":
        # PostgreSQL cannot drop enum values; the harmless type stays behind.
        pass
    if bind.dialect.name == "postgresql":
        op.drop_constraint("fk_users_customer_id_customers", "users", type_="foreignkey")
    op.drop_index("ix_users_customer_id", table_name="users")
    op.drop_column("users", "customer_id")