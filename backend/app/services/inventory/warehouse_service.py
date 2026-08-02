"""Warehouse management business logic."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.inventory import WarehouseCreate, WarehouseUpdate
from app.core.exceptions import AppException
from app.domain.models.inventory import Warehouse
from app.domain.models.user import User, UserRole


class WarehouseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_by_name(self, name: str) -> Warehouse | None:
        result = await self.session.execute(
            select(Warehouse).where(Warehouse.name == name)
        )
        return result.scalar_one_or_none()

    async def _validate_driver(self, user_id: int | None) -> int | None:
        """Only an active salesman may be given a vehicle — their field app sells
        from it, and that permission belongs to the sales role."""
        if user_id is None:
            return None
        driver = await self.session.get(User, user_id)
        if driver is None or not driver.is_active:
            raise AppException(400, "الموظف المحدد غير موجود أو معطل.")
        if driver.role is not UserRole.SALES:
            raise AppException(400, "لا يمكن إسناد المركبة إلا لموظف مبيعات.")
        return driver.id

    async def create_warehouse(self, data: WarehouseCreate) -> Warehouse:
        if await self._get_by_name(data.name) is not None:
            raise AppException(409, "يوجد مستودع بهذا الاسم من قبل.")
        if data.assigned_to_id is not None and not data.is_vehicle:
            raise AppException(400, "لا يمكن إسناد سائق لمستودع ثابت؛ حدده كمركبة أولاً.")
        warehouse = Warehouse(
            name=data.name,
            location=data.location,
            is_vehicle=data.is_vehicle,
            assigned_to_id=await self._validate_driver(data.assigned_to_id),
        )
        self.session.add(warehouse)
        await self.session.commit()
        await self.session.refresh(warehouse)
        return warehouse

    async def update_warehouse(
        self, warehouse_id: int, data: WarehouseUpdate
    ) -> Warehouse:
        warehouse = await self.session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise AppException(404, "المستودع غير موجود.")
        if data.name is not None and data.name != warehouse.name:
            if await self._get_by_name(data.name) is not None:
                raise AppException(409, "يوجد مستودع بهذا الاسم من قبل.")
            warehouse.name = data.name
        if data.location is not None:
            warehouse.location = data.location
        if data.is_vehicle is not None:
            warehouse.is_vehicle = data.is_vehicle
            # Demoting a vehicle back to a building leaves nobody to drive it.
            if not data.is_vehicle:
                warehouse.assigned_to_id = None
        # Explicit null unassigns; omitting the field leaves the driver alone.
        if "assigned_to_id" in data.model_fields_set:
            if data.assigned_to_id is not None and not warehouse.is_vehicle:
                raise AppException(
                    400, "لا يمكن إسناد سائق لمستودع ثابت؛ حدده كمركبة أولاً."
                )
            warehouse.assigned_to_id = await self._validate_driver(data.assigned_to_id)
        if data.is_active is not None:
            warehouse.is_active = data.is_active
        await self.session.commit()
        await self.session.refresh(warehouse)
        return warehouse

    async def list_warehouses(self) -> list[Warehouse]:
        result = await self.session.execute(select(Warehouse).order_by(Warehouse.id))
        return list(result.scalars().all())
