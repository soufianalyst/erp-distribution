"""Stock movements: receiving, FEFO allocation, transfers, levels, expiry alerts, and write-offs."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.inventory import (
    NearExpiryOut,
    StockAdjustmentCreate,
    StockLevelOut,
    StockReceiveRequest,
    StockTransferRequest,
    TransferLineOut,
)
from app.core.exceptions import AppException
from app.domain.models.inventory import (
    Product,
    ProductBatch,
    StockAdjustment,
    StockAdjustmentLine,
    Warehouse,
)
from app.services.accounting.accounting_service import (
    DAMAGE_LOSS,
    INVENTORY,
    AccountingService,
)

TWO_PLACES = Decimal("0.01")


class StockService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounting = AccountingService(session)

    async def get_active_product(self, product_id: int) -> Product:
        result = await self.session.execute(
            select(Product)
            .options(selectinload(Product.units))
            .where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise AppException(404, "الصنف غير موجود.")
        if not product.is_active:
            raise AppException(400, "هذا الصنف موقوف ولا يمكن إجراء حركات مخزنية عليه.")
        return product

    async def get_active_warehouse(self, warehouse_id: int) -> Warehouse:
        warehouse = await self.session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise AppException(404, "المستودع غير موجود.")
        if not warehouse.is_active:
            raise AppException(400, "هذا المستودع موقوف ولا يمكن إجراء حركات عليه.")
        return warehouse

    def to_base_quantity(
        self, product: Product, quantity: Decimal, unit_id: int | None
    ) -> Decimal:
        """Convert a quantity in an alternative unit to the product's base unit."""
        if unit_id is None:
            return quantity
        unit = next((u for u in product.units if u.id == unit_id), None)
        if unit is None:
            raise AppException(400, "وحدة القياس المحددة غير معرفة لهذا الصنف.")
        return quantity * unit.factor

    async def add_stock_no_commit(
        self,
        product_id: int,
        warehouse_id: int,
        batch_number: str,
        expiry_date: date,
        base_quantity: Decimal,
        unit_cost: Decimal | None = None,
    ) -> ProductBatch:
        """Upsert a batch WITHOUT committing — callers (receive, purchase invoice) own the transaction.

        Business rule: nothing enters a warehouse without a batch number and a future expiry date.
        """
        if expiry_date <= date.today():
            raise AppException(
                400, "لا يمكن استلام بضاعة منتهية الصلاحية أو تنتهي اليوم."
            )

        result = await self.session.execute(
            select(ProductBatch).where(
                ProductBatch.product_id == product_id,
                ProductBatch.warehouse_id == warehouse_id,
                ProductBatch.batch_number == batch_number,
            )
        )
        batch = result.scalar_one_or_none()

        if batch is not None:
            if batch.expiry_date != expiry_date:
                raise AppException(
                    409, "رقم التشغيلة مسجل من قبل بتاريخ انتهاء مختلف، يرجى التحقق."
                )
            batch.quantity += base_quantity
            if unit_cost is not None:
                batch.unit_cost = unit_cost
        else:
            batch = ProductBatch(
                product_id=product_id,
                warehouse_id=warehouse_id,
                batch_number=batch_number,
                expiry_date=expiry_date,
                quantity=base_quantity,
                unit_cost=unit_cost,
            )
            self.session.add(batch)
        return batch

    async def receive_stock(self, data: StockReceiveRequest) -> ProductBatch:
        """Direct warehouse receipt (outside a purchase invoice), committed immediately."""
        product = await self.get_active_product(data.product_id)
        await self.get_active_warehouse(data.warehouse_id)

        base_quantity = self.to_base_quantity(product, data.quantity, data.unit_id)
        batch = await self.add_stock_no_commit(
            product_id=data.product_id,
            warehouse_id=data.warehouse_id,
            batch_number=data.batch_number,
            expiry_date=data.expiry_date,
            base_quantity=base_quantity,
            unit_cost=data.unit_cost,
        )
        await self.session.commit()
        await self.session.refresh(batch)
        return batch

    async def fefo_allocate(
        self, product_id: int, warehouse_id: int, base_quantity: Decimal
    ) -> list[tuple[ProductBatch, Decimal]]:
        """Pick batches First-Expired-First-Out. Does NOT commit — callers own the transaction.

        Expired batches are excluded; they must go through the damaged-goods flow instead.
        """
        result = await self.session.execute(
            select(ProductBatch)
            .where(
                ProductBatch.product_id == product_id,
                ProductBatch.warehouse_id == warehouse_id,
                ProductBatch.quantity > 0,
                ProductBatch.expiry_date > date.today(),
            )
            .order_by(ProductBatch.expiry_date, ProductBatch.id)
        )
        batches = list(result.scalars().all())

        allocations: list[tuple[ProductBatch, Decimal]] = []
        remaining = base_quantity
        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch.quantity, remaining)
            allocations.append((batch, take))
            remaining -= take

        if remaining > 0:
            available = base_quantity - remaining
            raise AppException(
                400,
                f"الكمية المتوفرة غير كافية، المتاح حالياً: {available} والمطلوب: {base_quantity}.",
            )
        return allocations

    async def transfer_stock(self, data: StockTransferRequest) -> list[TransferLineOut]:
        """Move stock between warehouses FEFO-first, all inside one transaction."""
        if data.from_warehouse_id == data.to_warehouse_id:
            raise AppException(400, "لا يمكن التحويل إلى نفس المستودع.")

        product = await self.get_active_product(data.product_id)
        await self.get_active_warehouse(data.from_warehouse_id)
        await self.get_active_warehouse(data.to_warehouse_id)

        base_quantity = self.to_base_quantity(product, data.quantity, data.unit_id)
        allocations = await self.fefo_allocate(
            data.product_id, data.from_warehouse_id, base_quantity
        )

        moved: list[TransferLineOut] = []
        for source_batch, take in allocations:
            source_batch.quantity -= take

            result = await self.session.execute(
                select(ProductBatch).where(
                    ProductBatch.product_id == data.product_id,
                    ProductBatch.warehouse_id == data.to_warehouse_id,
                    ProductBatch.batch_number == source_batch.batch_number,
                )
            )
            dest_batch = result.scalar_one_or_none()
            if dest_batch is not None:
                dest_batch.quantity += take
            else:
                self.session.add(
                    ProductBatch(
                        product_id=data.product_id,
                        warehouse_id=data.to_warehouse_id,
                        batch_number=source_batch.batch_number,
                        expiry_date=source_batch.expiry_date,
                        quantity=take,
                        unit_cost=source_batch.unit_cost,
                    )
                )
            moved.append(
                TransferLineOut(
                    batch_number=source_batch.batch_number,
                    expiry_date=source_batch.expiry_date,
                    quantity=take,
                )
            )

        # Single commit: either the whole transfer succeeds or none of it does.
        await self.session.commit()
        return moved

    async def list_batches(
        self, product_id: int, warehouse_id: int | None = None
    ) -> list[ProductBatch]:
        await self.get_active_product(product_id)
        stmt = (
            select(ProductBatch)
            .where(ProductBatch.product_id == product_id, ProductBatch.quantity > 0)
            .order_by(ProductBatch.expiry_date, ProductBatch.id)
        )
        if warehouse_id is not None:
            stmt = stmt.where(ProductBatch.warehouse_id == warehouse_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def stock_levels(
        self, product_id: int | None = None, warehouse_id: int | None = None
    ) -> list[StockLevelOut]:
        stmt = (
            select(
                Product.id,
                Product.name,
                Product.base_unit_name,
                Warehouse.id,
                Warehouse.name,
                func.sum(ProductBatch.quantity),
            )
            .join(Product, ProductBatch.product_id == Product.id)
            .join(Warehouse, ProductBatch.warehouse_id == Warehouse.id)
            .where(ProductBatch.quantity > 0)
            .group_by(
                Product.id,
                Product.name,
                Product.base_unit_name,
                Warehouse.id,
                Warehouse.name,
            )
            .order_by(Product.id, Warehouse.id)
        )
        if product_id is not None:
            stmt = stmt.where(ProductBatch.product_id == product_id)
        if warehouse_id is not None:
            stmt = stmt.where(ProductBatch.warehouse_id == warehouse_id)

        result = await self.session.execute(stmt)
        return [
            StockLevelOut(
                product_id=row[0],
                product_name=row[1],
                base_unit_name=row[2],
                warehouse_id=row[3],
                warehouse_name=row[4],
                total_quantity=row[5],
            )
            for row in result.all()
        ]

    async def near_expiry(self, days: int = 30) -> list[NearExpiryOut]:
        """Batches expiring within `days` days — including already-expired stock still on hand."""
        today = date.today()
        threshold = today + timedelta(days=days)
        result = await self.session.execute(
            select(ProductBatch, Product.name, Warehouse.name)
            .join(Product, ProductBatch.product_id == Product.id)
            .join(Warehouse, ProductBatch.warehouse_id == Warehouse.id)
            .where(ProductBatch.quantity > 0, ProductBatch.expiry_date <= threshold)
            .order_by(ProductBatch.expiry_date)
        )
        return [
            NearExpiryOut(
                batch_id=batch.id,
                product_id=batch.product_id,
                product_name=product_name,
                warehouse_id=batch.warehouse_id,
                warehouse_name=warehouse_name,
                batch_number=batch.batch_number,
                expiry_date=batch.expiry_date,
                quantity=batch.quantity,
                days_remaining=(batch.expiry_date - today).days,
            )
            for batch, product_name, warehouse_name in result.all()
        ]

    # --- Stock adjustments (write-offs) ---
    async def create_adjustment(
        self, data: StockAdjustmentCreate, created_by: int | None = None
    ) -> StockAdjustment:
        """Write off damaged/expired/spoiled stock or a physical-count shortfall,
        directly from a specific batch — outside any sale or purchase return.

        Decrease-only: unlike sales/purchase returns there is no restock branch,
        the goods are simply removed from stock.
        """
        adjustment = StockAdjustment(
            reason=data.reason,
            total_cost=Decimal("0"),
            notes=data.notes,
            created_by=created_by,
        )

        total_cost = Decimal("0")
        for line in data.lines:
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is None:
                raise AppException(404, f"التشغيلة رقم {line.batch_id} غير موجودة.")
            product = await self.get_active_product(batch.product_id)

            base_quantity = self.to_base_quantity(product, line.quantity, line.unit_id)
            if base_quantity > batch.quantity:
                raise AppException(
                    400,
                    f"الكمية المطلوب إتلافها من الصنف ({product.name}) أكبر من "
                    f"الرصيد المتاح في هذه التشغيلة ({batch.quantity}).",
                )
            batch.quantity -= base_quantity

            # Batches received directly (outside a purchase invoice) may have no cost.
            unit_cost = batch.unit_cost or Decimal("0")
            line_total = (base_quantity * unit_cost).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            adjustment.lines.append(
                StockAdjustmentLine(
                    product_id=batch.product_id,
                    batch_id=batch.id,
                    warehouse_id=batch.warehouse_id,
                    quantity=base_quantity,
                    unit_cost=unit_cost,
                    line_total=line_total,
                )
            )
            total_cost += line_total

        adjustment.total_cost = total_cost
        self.session.add(adjustment)
        await self.session.flush()

        # Automatic double-entry: only when the write-off has a known cost impact.
        if total_cost > 0:
            await self.accounting.add_entry_no_commit(
                entry_date=date.today(),
                description=f"تعديل/إتلاف مخزون رقم {adjustment.id}",
                items=[
                    (DAMAGE_LOSS, total_cost, Decimal("0")),
                    (INVENTORY, Decimal("0"), total_cost),
                ],
                reference_type="stock_adjustment",
                reference_id=adjustment.id,
                created_by=created_by,
            )

        await self.session.commit()
        result = await self.session.execute(
            select(StockAdjustment)
            .options(selectinload(StockAdjustment.lines))
            .where(StockAdjustment.id == adjustment.id)
        )
        return result.scalar_one()

    async def list_adjustments(self) -> list[StockAdjustment]:
        result = await self.session.execute(
            select(StockAdjustment)
            .options(selectinload(StockAdjustment.lines))
            .order_by(StockAdjustment.id.desc())
        )
        return list(result.scalars().all())
