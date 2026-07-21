"""Product catalog business logic (products and their units of measure)."""

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.inventory import ProductCreate, ProductUpdate
from app.core.exceptions import AppException
from app.domain.models.inventory import Product, ProductUnit


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

    async def create_product(self, data: ProductCreate) -> Product:
        existing = await self.session.execute(
            select(Product).where(Product.sku == data.sku)
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(409, "يوجد صنف بنفس رمز الصنف (SKU) من قبل.")

        unit_names = [u.name for u in data.units]
        if len(unit_names) != len(set(unit_names)):
            raise AppException(400, "لا يمكن تكرار اسم وحدة القياس لنفس الصنف.")

        product = Product(
            sku=data.sku,
            name=data.name,
            base_unit_name=data.base_unit_name,
            wholesale_price=data.wholesale_price,
            half_wholesale_price=data.half_wholesale_price,
            retail_price=data.retail_price,
            min_stock_level=data.min_stock_level,
            default_warehouse_id=data.default_warehouse_id,
            units=[ProductUnit(name=u.name, factor=u.factor) for u in data.units],
        )
        self.session.add(product)
        await self.session.commit()
        return await self.get_product(product.id)

    async def update_product(self, product_id: int, data: ProductUpdate) -> Product:
        product = await self.get_product(product_id)
        if data.sku is not None and data.sku != product.sku:
            dup = await self.session.execute(
                select(Product).where(Product.sku == data.sku, Product.id != product_id)
            )
            if dup.scalar_one_or_none() is not None:
                raise AppException(409, "يوجد صنف بنفس رمز الصنف (SKU) من قبل.")
            product.sku = data.sku
        if data.name is not None:
            product.name = data.name
        if data.base_unit_name is not None:
            product.base_unit_name = data.base_unit_name
        if data.wholesale_price is not None:
            product.wholesale_price = data.wholesale_price
        if data.half_wholesale_price is not None:
            product.half_wholesale_price = data.half_wholesale_price
        if data.retail_price is not None:
            product.retail_price = data.retail_price
        if data.min_stock_level is not None:
            product.min_stock_level = data.min_stock_level
        if "default_warehouse_id" in data.model_fields_set:
            product.default_warehouse_id = data.default_warehouse_id
        if data.is_active is not None:
            product.is_active = data.is_active
        if data.units is not None:
            unit_names = [u.name for u in data.units]
            if len(unit_names) != len(set(unit_names)):
                raise AppException(400, "لا يمكن تكرار اسم وحدة القياس لنفس الصنف.")
            # Bulk-delete existing units, then re-populate.
            await self.session.execute(
                sa_delete(ProductUnit).where(ProductUnit.product_id == product_id)
            )
            await self.session.flush()
            product.units = []
            for u in data.units:
                product.units.append(ProductUnit(name=u.name, factor=u.factor))
        await self.session.commit()
        return await self.get_product(product_id)

    async def delete_product(self, product_id: int) -> None:
        product = await self.get_product(product_id)
        from sqlalchemy import func as sa_func
        from app.domain.models.inventory import ProductBatch

        stock_check = await self.session.execute(
            select(sa_func.coalesce(sa_func.sum(ProductBatch.quantity), 0)).where(
                ProductBatch.product_id == product_id
            )
        )
        total_stock = stock_check.scalar()
        if total_stock > 0:
            raise AppException(
                400, "لا يمكن حذف الصنف لوجود مخزون متبقي في التشغيلات."
            )
        await self.session.delete(product)
        await self.session.commit()

    async def list_products(self, search: str | None = None, is_active: bool | None = None) -> list[Product]:
        stmt = select(Product).options(selectinload(Product.units)).order_by(Product.id)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(Product.name.ilike(pattern) | Product.sku.ilike(pattern))
        if is_active is not None:
            stmt = stmt.where(Product.is_active == is_active)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
