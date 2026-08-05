"""add salesman round settlements

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-08-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROUND_SETTLEMENT_STATUS = postgresql.ENUM(
    "open", "settled", "cancelled", name="roundsettlementstatus"
)


def upgrade() -> None:
    # create_table would create the enum implicitly, but creating it explicitly
    # first keeps this migration re-runnable after a partial failure.
    ROUND_SETTLEMENT_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "round_settlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("salesman_id", sa.Integer(), nullable=False),
        sa.Column("round_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "open",
                "settled",
                "cancelled",
                name="roundsettlementstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="open",
        ),
        sa.Column("invoice_count", sa.Integer(), nullable=False, server_default="0"),
        # Money columns are NUMERIC, never FLOAT — the same discipline the
        # Decimal-only rule enforces on the Python side.
        sa.Column(
            "cash_sales_total", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "card_sales_total", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "credit_sales_total", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column(
            "cash_collected_total",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cash_outstanding_total",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("stocktake_id", sa.Integer(), nullable=True),
        sa.Column(
            "stock_variance_value",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
        # Units as well as money: the value is zero when a batch has no cost, so
        # money alone cannot tell a balanced round from a short one.
        sa.Column(
            "stock_variance_qty",
            sa.Numeric(14, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("opened_by", sa.Integer(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["salesman_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["stocktake_id"], ["stocktakes.id"]),
        sa.ForeignKeyConstraint(["opened_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["settled_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_round_settlements_warehouse_id", "round_settlements", ["warehouse_id"]
    )
    op.create_index(
        "ix_round_settlements_salesman_id", "round_settlements", ["salesman_id"]
    )
    op.create_index(
        "ix_round_settlements_round_date", "round_settlements", ["round_date"]
    )
    op.create_index(
        "ix_round_settlements_stocktake_id", "round_settlements", ["stocktake_id"]
    )

    # One open round per van at a time. Enforced in the database rather than only
    # in the service, because two devices closing the same day concurrently would
    # otherwise both pass an application-level check and create duplicates.
    # Partial index: settled and cancelled rounds may repeat freely.
    op.execute(
        "CREATE UNIQUE INDEX uq_round_settlements_open_per_van "
        "ON round_settlements (warehouse_id) WHERE status = 'open'"
    )

    # How large a stock difference may be waved through without a supervisor.
    # A default rather than nullable: every install gets a defined policy instead
    # of an ambiguous NULL the service would have to guess at.
    op.add_column(
        "company_settings",
        sa.Column(
            "round_variance_approval_limit",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="50.00",
        ),
    )

    # Repair mis-attributed invoice lines.
    #
    # Until this release, a line recorded the product's *home* warehouse rather
    # than the one the goods actually left. The stock moved correctly — FEFO drew
    # on the right warehouse and the batch on the line proves which — but every
    # van sale was booked against the main store. That makes per-warehouse
    # reporting wrong and makes a van's own round impossible to identify, which
    # is precisely what the settlements added above need to do.
    #
    # The batch is the authority, so it can restate the truth for existing rows.
    # Any install that ever sold from a vehicle has these rows; fixing the code
    # alone would leave the history lying.
    op.execute(
        """
        UPDATE sales_invoice_lines AS l
           SET warehouse_id = b.warehouse_id
          FROM product_batches AS b
         WHERE l.batch_id = b.id
           AND l.warehouse_id IS DISTINCT FROM b.warehouse_id
        """
    )

    # Then restate the invoice *header* from those repaired lines.
    #
    # Repairing the lines alone was not enough, and the gap had teeth: the header
    # is what DeliveryService reads to decide which warehouse a trip ships from,
    # and it refuses an invoice whose warehouse differs from the trip's. A van sale
    # with a stale header would therefore be rejected from its own van's trip and
    # accepted onto the main store's.
    #
    # The rule mirrors `SalesService._resolve_invoice_warehouse` exactly: one
    # warehouse when every line agrees, NULL when they do not. Duplicating the
    # logic in SQL is unavoidable here — a migration cannot call application code
    # that may itself change in a later release.
    op.execute(
        """
        UPDATE sales_invoices AS i
           SET warehouse_id = agreed.warehouse_id
          FROM (
                SELECT invoice_id,
                       CASE WHEN COUNT(DISTINCT warehouse_id) = 1
                            THEN MIN(warehouse_id)
                            ELSE NULL
                       END AS warehouse_id
                  FROM sales_invoice_lines
                 GROUP BY invoice_id
               ) AS agreed
         WHERE i.id = agreed.invoice_id
           AND i.warehouse_id IS DISTINCT FROM agreed.warehouse_id
        """
    )


def downgrade() -> None:
    # The invoice-line repair above is deliberately not reversed. It restated rows
    # to what the batch says actually happened; re-introducing the wrong warehouse
    # would be corrupting data on the way back, and nothing downstream needs the
    # old value. Downgrading removes the settlements feature, not the truth.
    op.drop_column("company_settings", "round_variance_approval_limit")
    op.execute("DROP INDEX IF EXISTS uq_round_settlements_open_per_van")
    op.drop_index("ix_round_settlements_stocktake_id", table_name="round_settlements")
    op.drop_index("ix_round_settlements_round_date", table_name="round_settlements")
    op.drop_index("ix_round_settlements_salesman_id", table_name="round_settlements")
    op.drop_index("ix_round_settlements_warehouse_id", table_name="round_settlements")
    op.drop_table("round_settlements")
    ROUND_SETTLEMENT_STATUS.drop(op.get_bind(), checkfirst=True)
