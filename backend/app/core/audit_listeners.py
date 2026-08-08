"""Automatic, system-wide audit logging.

A single SQLAlchemy session hook records every insert/update/delete across the
whole database (except audit_logs itself) into the audit_logs table — nothing
for individual services to remember to call. Registered once at import time
(imported from main.py) on the base `Session` class, so it applies to every
session in the process, including the app's own and every test session.

New rows don't have a primary key yet in before_flush, so inserts are staged
in before_flush and turned into AuditLog rows in after_flush once the id is
populated; SQLAlchemy explicitly supports adding new objects during
after_flush (it triggers one more internal flush for them).
"""

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.audit_context import current_user_id
from app.domain.models.audit import AuditAction, AuditLog

_PENDING_INSERTS_KEY = "_pending_audit_inserts"


def _is_audited(obj: object) -> bool:
    return getattr(obj, "__tablename__", None) != AuditLog.__tablename__


def _serialize(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _column_snapshot(obj: object) -> dict:
    return {
        attr.key: _serialize(getattr(obj, attr.key))
        for attr in obj.__mapper__.column_attrs
    }


@event.listens_for(Session, "before_flush")
def _audit_before_flush(session: Session, _flush_context: object, _instances: object) -> None:
    user_id = current_user_id.get()

    # Snapshot these session collections to plain lists first: session.add()
    # below mutates session.new, and iterating a collection while it changes
    # size raises RuntimeError.
    new_objects = [o for o in session.new if _is_audited(o)]
    dirty_objects = [o for o in session.dirty if _is_audited(o)]
    deleted_objects = [o for o in session.deleted if _is_audited(o)]

    session.info.setdefault(_PENDING_INSERTS_KEY, []).extend(new_objects)

    for obj in dirty_objects:
        insp = inspect(obj)
        changes: dict = {}
        for attr in obj.__mapper__.column_attrs:
            history = insp.attrs[attr.key].history
            if not history.has_changes():
                continue
            old_value = history.deleted[0] if history.deleted else None
            new_value = history.added[0] if history.added else getattr(obj, attr.key)
            changes[attr.key] = [_serialize(old_value), _serialize(new_value)]
        if not changes:
            continue
        session.add(
            AuditLog(
                table_name=obj.__tablename__,
                record_id=obj.id,
                action=AuditAction.UPDATE,
                changes=changes,
                user_id=user_id,
            )
        )

    for obj in deleted_objects:
        session.add(
            AuditLog(
                table_name=obj.__tablename__,
                record_id=obj.id,
                action=AuditAction.DELETE,
                changes=_column_snapshot(obj),
                user_id=user_id,
            )
        )


@event.listens_for(Session, "after_flush")
def _audit_after_flush(session: Session, _flush_context: object) -> None:
    pending = session.info.pop(_PENDING_INSERTS_KEY, [])
    if not pending:
        return
    user_id = current_user_id.get()
    for obj in pending:
        session.add(
            AuditLog(
                table_name=obj.__tablename__,
                record_id=obj.id,
                action=AuditAction.INSERT,
                changes=_column_snapshot(obj),
                user_id=user_id,
            )
        )
