"""Dashboard alerts: what needs attention right now, across every module.

Deliberately not under /analytics — that router requires analytics.view, while
alerts are for everyone who logs in. Each group is instead filtered by the
permission needed to act on it, inside the service.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas.analytics import AlertsOut
from app.api.schemas.common import APIResponse
from app.db.session import get_db
from app.domain.models.user import User
from app.services.analytics.alerts_service import AlertsService

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=APIResponse[AlertsOut])
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[AlertsOut]:
    """التنبيهات التي تحتاج إجراءً الآن — كل مستخدم يرى ما يستطيع التعامل معه فقط."""
    alerts = await AlertsService(db).alerts(current_user)
    return APIResponse(data=alerts)
