"""Read access to the automatically-populated audit trail (see app/core/audit_listeners.py)."""

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.audit import AuditAction, AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_logs(
        self,
        table_name: str | None = None,
        record_id: int | None = None,
        action: AuditAction | None = None,
        user_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.id.desc())
        if table_name is not None:
            stmt = stmt.where(AuditLog.table_name == table_name)
        if record_id is not None:
            stmt = stmt.where(AuditLog.record_id == record_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if date_from is not None:
            stmt = stmt.where(
                AuditLog.created_at
                >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
            )
        if date_to is not None:
            stmt = stmt.where(
                AuditLog.created_at
                <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_tables(self) -> list[str]:
        """Distinct table names seen so far, for the frontend's filter dropdown."""
        result = await self.session.execute(
            select(AuditLog.table_name).distinct().order_by(AuditLog.table_name)
        )
        return [row[0] for row in result.all()]
