"""المواد المقننة — a per-customer register of regulated goods

Regulated stock is charged on the ordinary sales invoice like anything else. This is
the parallel register of which client took which of those goods, so a monthly
declaration can be produced. It posts nothing and owns no figures: `rationed_lines`
holds pointers to real invoice lines, and every quantity and price shown is read
through to the line, which is what lets the register follow corrections, cancellations
and returns instead of drifting away from them.

Two constraints carry the rules that would otherwise live in hope:

* a partial unique index allowing only one *open* register per customer;
* a unique `sales_invoice_line_id`, so one physical line cannot be declared twice.

Revision ID: 1f843840fe9a
Revises: 3d3822054244
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1f843840fe9a"
down_revision: Union[str, None] = "3d3822054244"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rationed_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "customer_id", sa.Integer(), sa.ForeignKey("customers.id"),
            nullable=False, index=True,
        ),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        # NULL = the customer's current, still-accumulating register.
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
    )
    # Only one open register per customer. Expressed as a partial index because the
    # rule is about open rows only — a customer accumulates any number of closed ones.
    op.create_index(
        "uq_rationed_records_one_open_per_customer",
        "rationed_records",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )

    op.create_table(
        "rationed_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "record_id", sa.Integer(),
            sa.ForeignKey("rationed_records.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        # CASCADE, because an entry for goods on a cancelled invoice is not a record —
        # it is a claim about a sale that did not happen.
        sa.Column(
            "sales_invoice_line_id", sa.Integer(),
            sa.ForeignKey("sales_invoice_lines.id", ondelete="CASCADE"),
            nullable=False, unique=True, index=True,
        ),
        sa.Column(
            "added_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rationed_lines")
    op.drop_index(
        "uq_rationed_records_one_open_per_customer", table_name="rationed_records"
    )
    op.drop_table("rationed_records")
