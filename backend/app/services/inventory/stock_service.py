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
    StocktakeCountsIn,
    StocktakeCreate,
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
    Stocktake,
    StocktakeLine,
    StocktakeStatus,
    Warehouse,
)
from app.services.accounting.accounting_service import (
    DAMAGE_LOSS,
    INVENTORY,
    STOCKTAKE_VARIANCE,
    AccountingService,
)

TWO_PLACES = Decimal("0.01")


class StockService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounting = AccountingService(session)

    async def get_active_product(self, product_id: int) -> Product:
        """Fetch a product with its units, refusing one that has been stopped.

        Centralised so no movement — sale, transfer, write-off — can quietly
        operate on a discontinued item.
        """
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
        """Fetch a warehouse, refusing one that has been deactivated."""
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

    async def lock_batches_in_order(self, pairs: set[tuple[int, int]]) -> None:
        """Take the row locks a multi-line document needs, in a fixed global order.

        Locks acquired in different orders deadlock: a document touching products
        [9, 4] and another touching [4, 9] each end up holding what the other is
        waiting for. Sorting by product id means every document in the system
        acquires its locks in the same sequence, so one simply waits for the other
        and neither dies.

        One statement per product rather than one combined query, because
        PostgreSQL locks rows as it produces them and an `ORDER BY` on a combined
        query is no guarantee of lock order — the planner may sort after locking.
        Separate statements make the ordering ours to control.

        Called before allocation. The `FOR UPDATE` inside fefo_allocate then re-locks
        rows this session already holds, which costs nothing.
        """
        for product_id, warehouse_id in sorted(pairs):
            await self.session.execute(
                select(ProductBatch.id)
                .where(
                    ProductBatch.product_id == product_id,
                    ProductBatch.warehouse_id == warehouse_id,
                    ProductBatch.quantity > 0,
                )
                .order_by(ProductBatch.id)
                .with_for_update()
            )

    async def fefo_allocate(
        self, product_id: int, warehouse_id: int, base_quantity: Decimal
    ) -> list[tuple[ProductBatch, Decimal]]:
        """Pick batches First-Expired-First-Out. Does NOT commit — callers own the transaction.

        Expired batches are excluded; they must go through the damaged-goods flow instead.

        The rows are locked (`FOR UPDATE`), and that is not optional. Without it
        this method was the site of a demonstrated stock-corrupting race: the read
        here, the `quantity -= take` the caller performs in Python, and the UPDATE
        at commit form a read-modify-write, and PostgreSQL's default READ COMMITTED
        lets two sessions both read 100, both compute 90, and both write 90. Four
        salesmen invoicing the same product at the same instant sold 120 units out
        of 100 and left the batch reading 70; a single unit in stock was sold to
        four different customers, with no error raised to anyone.

        Note the direction of the damage, which is what made it dangerous: the
        absolute write leaves stock *overstated*, never negative. Nothing fails and
        no number looks wrong — the system simply believes it still holds goods it
        has already sold, until a stocktake weeks later books the difference as a
        shortfall and somebody is suspected of theft.

        Locking makes each session wait its turn and then re-read. PostgreSQL
        re-evaluates this WHERE clause after the lock is granted, so a batch another
        session has just emptied drops out of the result and allocation moves to the
        next batch or refuses honestly.
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
            .with_for_update()
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
        """Batches of a product holding stock, soonest to expire first (FEFO order)."""
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
        """Quantity on hand per product and warehouse.

        Inner-joins batches, so a product with no stock anywhere does not appear —
        see `reorder_suggestions` when the zero-stock ones are what you want.
        """
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
        """Fetch one write-off with its lines, or raise a 404."""
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
        """All stock write-offs, newest first."""
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

    # --- Stocktakes (physical counts) ---
    async def get_stocktake(self, stocktake_id: int) -> Stocktake:
        """Fetch a count sheet with its lines and deliveries, or raise a 404."""
        result = await self.session.execute(
            select(Stocktake)
            .options(
                selectinload(Stocktake.warehouse),
                selectinload(Stocktake.lines).selectinload(StocktakeLine.product),
            )
            .where(Stocktake.id == stocktake_id)
        )
        stocktake = result.scalar_one_or_none()
        if stocktake is None:
            raise AppException(404, "عملية الجرد غير موجودة.")
        return stocktake

    async def list_stocktakes(
        self,
        warehouse_id: int | None = None,
        status: StocktakeStatus | None = None,
    ) -> list[Stocktake]:
        """Stocktakes, newest first, optionally filtered by warehouse or status."""
        stmt = (
            select(Stocktake)
            .options(
                selectinload(Stocktake.warehouse),
                selectinload(Stocktake.lines).selectinload(StocktakeLine.product),
            )
            .order_by(Stocktake.id.desc())
        )
        if warehouse_id is not None:
            stmt = stmt.where(Stocktake.warehouse_id == warehouse_id)
        if status is not None:
            stmt = stmt.where(Stocktake.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def open_stocktake(
        self, data: StocktakeCreate, created_by: int | None = None
    ) -> Stocktake:
        """Open a count for one warehouse, snapshotting the expected quantities.

        Only batches currently holding stock are put on the sheet: goods found in
        a batch the books show as empty need a receipt, not a count correction.
        """
        warehouse = await self.get_active_warehouse(data.warehouse_id)

        # One open count per warehouse: two concurrent sheets would each hold a
        # stale snapshot and the second to post would undo the first.
        existing = await self.session.execute(
            select(Stocktake.id).where(
                Stocktake.warehouse_id == data.warehouse_id,
                Stocktake.status == StocktakeStatus.COUNTING,
            )
        )
        open_id = existing.scalars().first()
        if open_id is not None:
            raise AppException(
                409,
                f"يوجد جرد مفتوح لهذا المستودع (رقم {open_id})؛ "
                "أكمله أو ألغِه قبل بدء جرد جديد.",
            )

        batches = await self.session.execute(
            select(ProductBatch)
            .options(selectinload(ProductBatch.product))
            .where(
                ProductBatch.warehouse_id == data.warehouse_id,
                ProductBatch.quantity > 0,
            )
            .join(Product, ProductBatch.product_id == Product.id)
            .order_by(Product.name, ProductBatch.expiry_date)
        )
        rows = list(batches.scalars().all())
        if not rows:
            raise AppException(400, "لا يوجد مخزون في هذا المستودع لجرده.")

        stocktake = Stocktake(
            warehouse_id=warehouse.id,
            count_date=data.count_date or date.today(),
            status=StocktakeStatus.COUNTING,
            notes=data.notes,
            net_value=Decimal("0"),
            created_by=created_by,
        )
        for batch in rows:
            stocktake.lines.append(
                StocktakeLine(
                    product_id=batch.product_id,
                    batch_id=batch.id,
                    batch_number=batch.batch_number,
                    expiry_date=batch.expiry_date,
                    expected_quantity=batch.quantity,
                    counted_quantity=None,
                    unit_cost=batch.unit_cost or Decimal("0"),
                )
            )

        self.session.add(stocktake)
        await self.session.commit()
        return await self.get_stocktake(stocktake.id)

    async def save_counts(
        self, stocktake_id: int, data: StocktakeCountsIn
    ) -> Stocktake:
        """Record counted quantities. Saved in batches as the aisles are walked,
        so a long count is never lost, and re-counting a line just overwrites it.
        """
        stocktake = await self.get_stocktake(stocktake_id)
        if stocktake.status is not StocktakeStatus.COUNTING:
            raise AppException(400, "لا يمكن تعديل الكميات بعد تثبيت الجرد أو إلغائه.")

        lines_by_id = {line.id: line for line in stocktake.lines}
        for count in data.counts:
            line = lines_by_id.get(count.line_id)
            if line is None:
                raise AppException(400, "أحد السطور لا ينتمي إلى هذا الجرد.")
            line.counted_quantity = count.counted_quantity

        await self.session.commit()
        return await self.get_stocktake(stocktake.id)

    async def post_stocktake(
        self, stocktake_id: int, posted_by: int | None = None
    ) -> Stocktake:
        """Settle the counted differences against stock and the ledger, atomically.

        Applies each variance as a *delta* to the batch rather than overwriting the
        quantity outright: stock may legitimately have moved between counting and
        posting (a sale, a transfer), and a delta preserves those movements while
        still correcting what the count found.

        Uncounted lines are left alone — an unvisited shelf is not a shortfall.
        """
        stocktake = await self.get_stocktake(stocktake_id)
        if stocktake.status is not StocktakeStatus.COUNTING:
            raise AppException(400, "تم تثبيت هذا الجرد أو إلغاؤه من قبل.")
        if stocktake.counted_line_count == 0:
            raise AppException(400, "أدخل الكميات الفعلية لسطر واحد على الأقل أولاً.")

        shortfall_value = Decimal("0")
        surplus_value = Decimal("0")
        for line in stocktake.lines:
            variance = line.variance
            if variance == 0:
                continue
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is None:
                raise AppException(
                    404, f"التشغيلة ({line.batch_number}) لم تعد موجودة."
                )
            if batch.quantity + variance < 0:
                raise AppException(
                    400,
                    f"لا يمكن تسوية الصنف ({line.product_name}) في التشغيلة "
                    f"({line.batch_number}): الرصيد الحالي {batch.quantity} "
                    "وسيصبح سالباً بعد التسوية؛ أعد الجرد.",
                )
            batch.quantity += variance
            if variance < 0:
                shortfall_value += -line.variance_value
            else:
                surplus_value += line.variance_value

        net_value = surplus_value - shortfall_value
        stocktake.net_value = net_value
        stocktake.status = StocktakeStatus.POSTED
        stocktake.posted_at = datetime.now(timezone.utc)
        stocktake.posted_by = posted_by
        await self.session.flush()

        # One netted entry per count. Costs are unknown for batches received
        # outside a purchase invoice, so a count can move quantities without
        # moving any value — in which case there is nothing to post.
        if net_value != 0:
            items = (
                [
                    (INVENTORY, net_value, Decimal("0")),
                    (STOCKTAKE_VARIANCE, Decimal("0"), net_value),
                ]
                if net_value > 0
                else [
                    (STOCKTAKE_VARIANCE, -net_value, Decimal("0")),
                    (INVENTORY, Decimal("0"), -net_value),
                ]
            )
            await self.accounting.add_entry_no_commit(
                entry_date=stocktake.count_date,
                description=(
                    f"تسوية جرد رقم {stocktake.id} — مستودع "
                    f"({stocktake.warehouse_name})"
                ),
                items=items,
                reference_type="stocktake",
                reference_id=stocktake.id,
                created_by=posted_by,
            )

        await self.session.commit()
        return await self.get_stocktake(stocktake.id)

    async def cancel_stocktake(
        self, stocktake_id: int, cancel_reason: str | None = None
    ) -> Stocktake:
        """Abandon a count. Nothing to reverse: a count only touches stock when posted."""
        stocktake = await self.get_stocktake(stocktake_id)
        if stocktake.status is StocktakeStatus.POSTED:
            raise AppException(
                400, "تم تثبيت هذا الجرد؛ صحّح الفروقات بجرد جديد أو بتعديل مخزون."
            )
        if stocktake.status is StocktakeStatus.CANCELLED:
            raise AppException(400, "هذا الجرد ملغى من قبل.")

        stocktake.status = StocktakeStatus.CANCELLED
        stocktake.cancelled_at = datetime.now(timezone.utc)
        stocktake.cancel_reason = cancel_reason
        await self.session.commit()
        return await self.get_stocktake(stocktake.id)
