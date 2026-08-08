"""Audit trail endpoints: a read-only view of the automatically-populated audit_logs table."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.audit import AuditLogOut
from app.api.schemas.common import APIResponse
from app.db.session import get_db
from app.domain.models.audit import AuditAction
from app.services.audit.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit"])

audit_view = Depends(require_permissions("audit.view"))


@router.get(
    "/logs",
    response_model=APIResponse[list[AuditLogOut]],
    dependencies=[audit_view],
)
async def list_logs(
    table_name: str | None = Query(default=None, description="اسم الجدول"),
    record_id: int | None = Query(default=None, description="رقم السجل"),
    action: AuditAction | None = Query(default=None, description="نوع العملية"),
    user_id: int | None = Query(default=None, description="المستخدم"),
    date_from: date | None = Query(default=None, description="بداية الفترة"),
    date_to: date | None = Query(default=None, description="نهاية الفترة"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[AuditLogOut]]:
    """عرض سجل تتبع العمليات (من أنشأ/عدّل/حذف ماذا ومتى)."""
    logs = await AuditService(db).list_logs(
        table_name, record_id, action, user_id, date_from, date_to
    )
    return APIResponse(data=[AuditLogOut.model_validate(entry) for entry in logs])


@router.get(
    "/tables",
    response_model=APIResponse[list[str]],
    dependencies=[audit_view],
)
async def list_tables(db: AsyncSession = Depends(get_db)) -> APIResponse[list[str]]:
    """أسماء الجداول التي لها حركات مسجلة، لاستخدامها في تصفية السجل."""
    tables = await AuditService(db).list_tables()
    return APIResponse(data=tables)
