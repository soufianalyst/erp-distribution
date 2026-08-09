"""Read access to the automatically-populated audit trail (see app/core/audit_listeners.py)."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import business_day
from app.domain.models.audit import AuditAction, AuditLog
from app.services.settings.settings_service import SettingsService


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
        """Audit entries, newest first, filtered by table, record, user or action."""
        stmt = select(AuditLog).order_by(AuditLog.id.desc())
        if table_name is not None:
            stmt = stmt.where(AuditLog.table_name == table_name)
        if record_id is not None:
            stmt = stmt.where(AuditLog.record_id == record_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        # Same shape as the cashier's closing report had: a date the user typed on a
        # local calendar, matched against UTC timestamps. "Show me 8 August" would then
        # miss the first hours of that morning and include the previous evening.
        if date_from is not None or date_to is not None:
            company = await SettingsService(self.session).get_company_settings()
            start, end = business_day.utc_window(date_from, date_to, company.timezone)
            if start is not None:
                stmt = stmt.where(AuditLog.created_at >= start)
            if end is not None:
                # Exclusive upper bound at the next local midnight, so the whole of the
                # closing day is included without depending on microsecond precision.
                stmt = stmt.where(AuditLog.created_at < end)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_tables(self) -> list[str]:
        """Distinct table names seen so far, for the frontend's filter dropdown."""
        result = await self.session.execute(
            select(AuditLog.table_name).distinct().order_by(AuditLog.table_name)
        )
        return [row[0] for row in result.all()]
