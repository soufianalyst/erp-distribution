"""Warehouse management business logic."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.inventory import WarehouseCreate, WarehouseUpdate
from app.core.exceptions import AppException
from app.domain.models.inventory import Warehouse


class WarehouseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_by_name(self, name: str) -> Warehouse | None:
        result = await self.session.execute(
            select(Warehouse).where(Warehouse.name == name)
        )
        return result.scalar_one_or_none()

    async def create_warehouse(self, data: WarehouseCreate) -> Warehouse:
        if await self._get_by_name(data.name) is not None:
            raise AppException(409, "يوجد مستودع بهذا الاسم من قبل.")
        warehouse = Warehouse(name=data.name, location=data.location)
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
        if data.is_active is not None:
            warehouse.is_active = data.is_active
        await self.session.commit()
        await self.session.refresh(warehouse)
        return warehouse

    async def list_warehouses(self) -> list[Warehouse]:
        result = await self.session.execute(select(Warehouse).order_by(Warehouse.id))
        return list(result.scalars().all())
