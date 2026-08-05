"""one active vehicle per salesman

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-08-05

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resolve any salesman already holding more than one active vehicle before the
    # index can exist.
    #
    # This data is ambiguous by nature — the field app has been picking one of the
    # vans arbitrarily — so there is no reading of it that is certainly right. The
    # rule chosen is the least surprising one available: keep the lowest id, which
    # is the longest-standing assignment and the one whose van most likely carries
    # the history, and unassign the rest so an administrator re-assigns
    # deliberately from the warehouses page.
    #
    # Only the *assignment* is cleared. No vehicle is deleted and no stock is
    # touched: whatever sits on those vans stays exactly where it is, because the
    # goods are real regardless of who the record says was driving.
    op.execute(
        """
        UPDATE warehouses
           SET assigned_to_id = NULL
         WHERE is_vehicle
           AND is_active
           AND assigned_to_id IS NOT NULL
           AND id <> (
                 SELECT MIN(keep.id) FROM warehouses AS keep
                  WHERE keep.assigned_to_id = warehouses.assigned_to_id
                    AND keep.is_vehicle
                    AND keep.is_active
               )
        """
    )

    # One active vehicle per salesman, in the database rather than only in the
    # service — two administrators saving the warehouses page at the same moment
    # would otherwise both pass an application-level check.
    #
    # Partial: inactive (retired) vehicles may keep their historical driver, and
    # any number of vans may sit unassigned.
    op.execute(
        "CREATE UNIQUE INDEX uq_warehouses_one_active_van_per_salesman "
        "ON warehouses (assigned_to_id) "
        "WHERE is_vehicle AND is_active AND assigned_to_id IS NOT NULL"
    )


def downgrade() -> None:
    # The unassignments above are deliberately not reversed. They replaced an
    # ambiguous state with a defined one, and restoring the ambiguity would put
    # back the bug this migration exists to remove.
    op.execute("DROP INDEX IF EXISTS uq_warehouses_one_active_van_per_salesman")
