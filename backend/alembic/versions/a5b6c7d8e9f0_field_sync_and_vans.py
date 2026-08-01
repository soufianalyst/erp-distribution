"""vans as warehouses, and client uuids for offline field sync

Two changes serving the salesman field app:

* Warehouses can be vehicles assigned to a salesman, so a van reuses batches,
  transfers, FEFO and stocktakes instead of needing a parallel stock concept.
* Customers, sales invoices and quotations can carry a `client_uuid` minted by
  the field app. The unique index is the load-bearing part: it makes replaying a
  sync batch harmless, which is what keeps a flaky connection from creating the
  same invoice twice.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-08-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID_TABLES = ("customers", "sales_invoices", "sales_quotations")


def upgrade() -> None:
    op.add_column(
        "warehouses",
        sa.Column(
            "is_vehicle", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("warehouses", sa.Column("assigned_to_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_warehouses_assigned_to_id"), "warehouses", ["assigned_to_id"]
    )
    op.create_foreign_key(
        "fk_warehouses_assigned_to_id", "warehouses", "users", ["assigned_to_id"], ["id"]
    )

    for table in UUID_TABLES:
        op.add_column(table, sa.Column("client_uuid", sa.String(length=36), nullable=True))
        # Unique, not merely indexed: this is what makes a replayed sync a no-op.
        op.create_index(
            op.f(f"ix_{table}_client_uuid"), table, ["client_uuid"], unique=True
        )


def downgrade() -> None:
    for table in UUID_TABLES:
        op.drop_index(op.f(f"ix_{table}_client_uuid"), table_name=table)
        op.drop_column(table, "client_uuid")

    op.drop_constraint("fk_warehouses_assigned_to_id", "warehouses", type_="foreignkey")
    op.drop_index(op.f("ix_warehouses_assigned_to_id"), table_name="warehouses")
    op.drop_column("warehouses", "assigned_to_id")
    op.drop_column("warehouses", "is_vehicle")
