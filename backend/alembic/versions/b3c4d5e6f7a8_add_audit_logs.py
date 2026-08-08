"""add audit logs

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_name", sa.String(length=100), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column(
            "action",
            sa.Enum("insert", "update", "delete", name="auditaction"),
            nullable=False,
        ),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_logs_table_name"), "audit_logs", ["table_name"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_record_id"), "audit_logs", ["record_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_record_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_table_name"), table_name="audit_logs")
    op.drop_table("audit_logs")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS auditaction")
