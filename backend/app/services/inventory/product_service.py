"""Product catalog business logic (products and their units of measure)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.inventory import ProductCreate, ProductUpdate
from app.core.exceptions import AppException
from app.domain.models.inventory import Product, ProductUnit, Warehouse


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_product(self, product_id: int) -> Product:
        result = await self.session.execute(
            select(Product)
            .options(selectinload(Product.units))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise AppException(404, "الصنف غير موجود.")
        return product

    async def _get_active_warehouse(self, warehouse_id: int) -> Warehouse:
        warehouse = await self.session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise AppException(404, "المستودع المحدد غير موجود.")
        if not warehouse.is_active:
            raise AppException(400, "هذا المستودع موقوف ولا يمكن ربط أصناف به.")
        return warehouse

    async def create_product(self, data: ProductCreate) -> Product:
        existing = await self.session.execute(
            select(Product).where(Product.sku == data.sku)
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(409, "يوجد صنف بنفس رمز الصنف (SKU) من قبل.")

        unit_names = [u.name for u in data.units]
        if len(unit_names) != len(set(unit_names)):
            raise AppException(400, "لا يمكن تكرار اسم وحدة القياس لنفس الصنف.")

        await self._get_active_warehouse(data.warehouse_id)

        product = Product(
            sku=data.sku,
            name=data.name,
            base_unit_name=data.base_unit_name,
            wholesale_price=data.wholesale_price,
            half_wholesale_price=data.half_wholesale_price,
            retail_price=data.retail_price,
            min_stock_level=data.min_stock_level,
            warehouse_id=data.warehouse_id,
            units=[ProductUnit(name=u.name, factor=u.factor) for u in data.units],
        )
        self.session.add(product)
        await self.session.commit()
        return await self.get_product(product.id)

    async def update_product(self, product_id: int, data: ProductUpdate) -> Product:
        product = await self.get_product(product_id)
        if data.name is not None:
            product.name = data.name
        if data.wholesale_price is not None:
            product.wholesale_price = data.wholesale_price
        if data.half_wholesale_price is not None:
            product.half_wholesale_price = data.half_wholesale_price
        if data.retail_price is not None:
            product.retail_price = data.retail_price
        if data.min_stock_level is not None:
            product.min_stock_level = data.min_stock_level
        if data.warehouse_id is not None:
            await self._get_active_warehouse(data.warehouse_id)
            product.warehouse_id = data.warehouse_id
        if data.is_active is not None:
            product.is_active = data.is_active
        await self.session.commit()
        return await self.get_product(product_id)

    async def list_products(self, search: str | None = None) -> list[Product]:
        stmt = select(Product).options(selectinload(Product.units)).order_by(Product.id)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(Product.name.ilike(pattern) | Product.sku.ilike(pattern))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
