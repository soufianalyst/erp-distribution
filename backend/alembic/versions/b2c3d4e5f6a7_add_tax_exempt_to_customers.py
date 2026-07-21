"""add tax_exempt to customers

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("tax_exempt", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("customers", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.drop_column("customers", "is_active")
    op.drop_column("customers", "tax_exempt")
