"""Pydantic schemas (DTOs) for the audit trail."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.models.audit import AuditAction


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    table_name: str
    record_id: int
    action: AuditAction
    changes: dict
    user_id: int | None
    created_at: datetime
