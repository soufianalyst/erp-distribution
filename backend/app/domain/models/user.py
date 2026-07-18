"""User entity and system roles (role = default permission template)."""

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"  # مدير النظام
    STOREKEEPER = "storekeeper"  # أمين المستودع
    SALES = "sales"  # موظف المبيعات / المندوب
    ACCOUNTANT = "accountant"  # المحاسب
    DRIVER = "driver"  # سائق التوصيل
    CASHIER = "cashier"  # أمين الصندوق


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserRole.SALES,
    )
    # Explicit permission codes; NULL means "use the role's default permissions".
    permissions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def effective_permissions(self) -> list[str]:
        """Resolved permissions actually in force for this user."""
        from app.core.permissions import effective_permissions

        return sorted(effective_permissions(self))
