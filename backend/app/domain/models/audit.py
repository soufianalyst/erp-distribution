"""Audit trail: a system-wide log of every insert/update/delete, populated
automatically by a SQLAlchemy session event listener (see app/core/audit_listeners.py)
rather than by application code."""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditAction(str, enum.Enum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    table_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # insert: {"field": new_value}; update: {"field": [old_value, new_value]}
    # (only changed fields); delete: {"field": last_known_value} for every column.
    changes: Mapped[dict] = mapped_column(JSON, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
