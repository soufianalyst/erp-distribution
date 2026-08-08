"""stock quantity may never go negative

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-05

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A backstop, not the fix.
    #
    # The fix for concurrent oversell is the row lock in
    # StockService.fefo_allocate. But fifteen places in the services read a batch
    # quantity, change it in Python and write it back, and only the two that go
    # through FEFO are covered by that lock. Returns, damage, stocktake postings,
    # purchase edits and transfers each carry the same shape.
    #
    # This constraint does not make those places correct. What it does is take away
    # their ability to fail *quietly*: a lost update that drives a quantity below
    # zero now aborts the transaction instead of writing a number nobody checks.
    # Given the choice between an error a storekeeper reports and a stock figure
    # that is wrong for three weeks, the error is worth far more.
    #
    # It cannot catch everything. A lost update that leaves stock overstated but
    # still positive passes this check — which is precisely why the lock, and not
    # the constraint, is the actual remedy.
    op.execute(
        "ALTER TABLE product_batches "
        "ADD CONSTRAINT ck_product_batches_quantity_non_negative "
        "CHECK (quantity >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE product_batches "
        "DROP CONSTRAINT IF EXISTS ck_product_batches_quantity_non_negative"
    )
