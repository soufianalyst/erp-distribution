"""Request-scoped context used to attribute automatic audit-log entries to a user.

Populated by a best-effort HTTP middleware (see main.py) and read by the
SQLAlchemy session event listeners in app/core/audit_listeners.py — the two
are decoupled since the listeners have no access to the current request.
"""

from contextvars import ContextVar

current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)
