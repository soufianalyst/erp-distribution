"""Stock movements: receiving, FEFO allocation, transfers, levels, expiry alerts, and write-offs."""

from datetime import date, datetime, timedelta, timezone
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
    AdjustmentStatus,
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

    async def reorder_suggestions(self) -> list["ReorderSuggestionOut"]:
        """Active products worth reordering: out of stock, or at/below their minimum.

        Deliberately an OUTER join from products: an inner join on batches — the
        way `stock_levels` works — hides products with no stock at all, which are
        exactly the ones most in need of ordering.
        """
        from app.api.schemas.purchases import ReorderSuggestionOut

        stock = func.coalesce(func.sum(ProductBatch.quantity), 0).label("stock")
        stmt = (
            select(
                Product.id,
                Product.sku,
                Product.name,
                Product.base_unit_name,
                Product.min_stock_level,
                stock,
            )
            .outerjoin(
                ProductBatch,
                (ProductBatch.product_id == Product.id) & (ProductBatch.quantity > 0),
            )
            .where(Product.is_active.is_(True))
            .group_by(
                Product.id,
                Product.sku,
                Product.name,
                Product.base_unit_name,
                Product.min_stock_level,
            )
            .having(stock <= Product.min_stock_level)
            .order_by(stock, Product.name)
        )
        rows = (await self.session.execute(stmt)).all()
        if not rows:
            return []

        # Latest known purchase cost per product, to pre-fill an order line.
        costs = await self.session.execute(
            select(ProductBatch.product_id, ProductBatch.unit_cost)
            .where(
                ProductBatch.product_id.in_([r[0] for r in rows]),
                ProductBatch.unit_cost.is_not(None),
            )
            .order_by(ProductBatch.product_id, ProductBatch.id.desc())
        )
        last_cost: dict[int, Decimal] = {}
        for product_id, unit_cost in costs.all():
            last_cost.setdefault(product_id, unit_cost)

        return [
            ReorderSuggestionOut(
                product_id=row[0],
                sku=row[1],
                name=row[2],
                base_unit_name=row[3],
                current_stock=Decimal(str(row[5])),
                min_stock_level=row[4],
                shortfall=max(row[4] - Decimal(str(row[5])), Decimal("0")),
                out_of_stock=Decimal(str(row[5])) <= 0,
                last_unit_cost=last_cost.get(row[0]),
            )
            for row in rows
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
        return await self.get_adjustment(adjustment.id)

    @staticmethod
    def _adjustment_loads():
        """Eager-load everything the log and the printed report read, so the
        line label properties never trigger a lazy load on a closed session.
        """
        return selectinload(StockAdjustment.lines).options(
            selectinload(StockAdjustmentLine.product),
            selectinload(StockAdjustmentLine.batch),
            selectinload(StockAdjustmentLine.warehouse),
        )

    async def get_adjustment(self, adjustment_id: int) -> StockAdjustment:
        result = await self.session.execute(
            select(StockAdjustment)
            .options(self._adjustment_loads())
            .where(StockAdjustment.id == adjustment_id)
        )
        adjustment = result.scalar_one_or_none()
        if adjustment is None:
            raise AppException(404, "سجل تعديل/إتلاف المخزون غير موجود.")
        return adjustment

    async def list_adjustments(self) -> list[StockAdjustment]:
        result = await self.session.execute(
            select(StockAdjustment)
            .options(self._adjustment_loads())
            .order_by(StockAdjustment.id.desc())
        )
        return list(result.scalars().all())

    async def cancel_adjustment(
        self,
        adjustment_id: int,
        cancel_reason: str | None = None,
        cancelled_by: int | None = None,
    ) -> StockAdjustment:
        """Undo a write-off entered by mistake: the goods go back to their original
        batch and the loss posting is reversed, in one transaction.

        The record is kept and marked cancelled rather than deleted, so the
        original mistake stays auditable.
        """
        adjustment = await self.get_adjustment(adjustment_id)
        if adjustment.status == AdjustmentStatus.CANCELLED:
            raise AppException(400, "هذا السجل ملغى من قبل.")

        for line in adjustment.lines:
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is None:
                raise AppException(
                    400,
                    "لا يمكن الإلغاء لأن إحدى التشغيلات الأصلية غير موجودة.",
                )
            batch.quantity += line.quantity

        # Mirror image of the original posting: the loss is undone and the
        # inventory value is restored.
        if adjustment.total_cost > 0:
            await self.accounting.add_entry_no_commit(
                entry_date=date.today(),
                description=f"إلغاء تعديل/إتلاف مخزون رقم {adjustment.id}",
                items=[
                    (INVENTORY, adjustment.total_cost, Decimal("0")),
                    (DAMAGE_LOSS, Decimal("0"), adjustment.total_cost),
                ],
                reference_type="stock_adjustment_cancel",
                reference_id=adjustment.id,
                created_by=cancelled_by,
            )

        adjustment.status = AdjustmentStatus.CANCELLED
        adjustment.cancelled_at = datetime.now(timezone.utc)
        adjustment.cancelled_by = cancelled_by
        adjustment.cancel_reason = cancel_reason

        await self.session.commit()
        return await self.get_adjustment(adjustment.id)
