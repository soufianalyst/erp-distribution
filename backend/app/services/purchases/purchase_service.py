"""Purchasing business logic: suppliers, purchase invoices, payments, and statements."""

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.purchases import (
    PurchaseInvoiceCreate,
    PurchaseReturnCreate,
    SupplierCreate,
    SupplierPaymentCreate,
    SupplierStatementOut,
    SupplierUpdate,
)
from app.core.exceptions import AppException
from app.domain.models.accounting import JournalEntry
from app.domain.models.inventory import Product, ProductBatch
from app.domain.models.purchases import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseInvoiceTax,
    PurchasePaymentMethod,
    PurchaseReturn,
    PurchaseReturnLine,
    Supplier,
    SupplierPayment,
)
from app.domain.models.settings import TaxRate
from app.services.accounting.accounting_service import (
    ACCOUNTS_PAYABLE,
    INVENTORY,
    VAT,
    AccountingService,
    cash_or_bank,
)
from app.services.inventory.stock_service import StockService

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


class PurchaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stock = StockService(session)
        self.accounting = AccountingService(session)

    # --- Suppliers ---
    async def _get_supplier_by_name(self, name: str) -> Supplier | None:
        result = await self.session.execute(
            select(Supplier).where(Supplier.name == name)
        )
        return result.scalar_one_or_none()

    async def get_supplier(self, supplier_id: int) -> Supplier:
        supplier = await self.session.get(Supplier, supplier_id)
        if supplier is None:
            raise AppException(404, "المورد غير موجود.")
        return supplier

    async def create_supplier(self, data: SupplierCreate) -> Supplier:
        if await self._get_supplier_by_name(data.name) is not None:
            raise AppException(409, "يوجد مورد بهذا الاسم من قبل.")
        supplier = Supplier(
            name=data.name,
            phone=data.phone,
            address=data.address,
            opening_balance=data.opening_balance,
        )
        self.session.add(supplier)
        await self.session.commit()
        await self.session.refresh(supplier)
        return supplier

    async def update_supplier(self, supplier_id: int, data: SupplierUpdate) -> Supplier:
        supplier = await self.get_supplier(supplier_id)
        if data.name is not None and data.name != supplier.name:
            if await self._get_supplier_by_name(data.name) is not None:
                raise AppException(409, "يوجد مورد بهذا الاسم من قبل.")
            supplier.name = data.name
        if data.phone is not None:
            supplier.phone = data.phone
        if data.address is not None:
            supplier.address = data.address
        if data.is_active is not None:
            supplier.is_active = data.is_active
        await self.session.commit()
        await self.session.refresh(supplier)
        return supplier

    async def list_suppliers(self, search: str | None = None) -> list[Supplier]:
        stmt = select(Supplier).order_by(Supplier.id)
        if search:
            stmt = stmt.where(Supplier.name.ilike(f"%{search}%"))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Purchase invoices ---
    async def _resolve_taxes(self, tax_rate_ids: list[int]) -> list[TaxRate]:
        """Validate and fetch the configured taxes to apply; empty means tax-free.

        Several taxes may be selected at once; duplicates in the input are ignored.
        """
        taxes: list[TaxRate] = []
        seen: set[int] = set()
        for tax_rate_id in tax_rate_ids:
            if tax_rate_id in seen:
                continue
            seen.add(tax_rate_id)
            tax_rate = await self.session.get(TaxRate, tax_rate_id)
            if tax_rate is None or not tax_rate.is_active:
                raise AppException(400, "إحدى الضرائب المحددة غير موجودة أو غير مفعّلة.")
            taxes.append(tax_rate)
        return taxes

    @staticmethod
    def _apply_taxes(
        invoice: PurchaseInvoice, tax_rates: list[TaxRate], subtotal: Decimal
    ) -> Decimal:
        """Snapshot each selected tax onto the invoice; returns their summed amount."""
        total_tax = Decimal("0")
        for tax_rate in tax_rates:
            amount = (subtotal * tax_rate.rate / Decimal("100")).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            invoice.taxes.append(
                PurchaseInvoiceTax(
                    tax_rate_id=tax_rate.id,
                    name=tax_rate.name,
                    rate=tax_rate.rate,
                    amount=amount,
                )
            )
            total_tax += amount
        return total_tax

    async def _build_lines(
        self, invoice: PurchaseInvoice, data: PurchaseInvoiceCreate
    ) -> Decimal:
        """Enter each line's goods into stock (upserting batches); returns the subtotal."""
        subtotal = Decimal("0")
        for line in data.lines:
            product = await self.session.execute(
                select(Product)
                .options(selectinload(Product.units))
                .where(Product.id == line.product_id)
            )
            product_obj = product.scalar_one_or_none()
            if product_obj is None:
                raise AppException(404, f"الصنف رقم {line.product_id} غير موجود.")
            if not product_obj.is_active:
                raise AppException(
                    400, f"الصنف ({product_obj.name}) موقوف ولا يمكن شراؤه."
                )

            # Convert quantity and cost to the base unit; line total stays exact.
            base_quantity = self.stock.to_base_quantity(
                product_obj, line.quantity, line.unit_id
            )
            line_total = (line.quantity * line.unit_cost).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            base_unit_cost = (
                (line_total / base_quantity).quantize(
                    FOUR_PLACES, rounding=ROUND_HALF_UP
                )
                if base_quantity > 0
                else Decimal("0")
            )

            batch = await self.stock.add_stock_no_commit(
                product_id=line.product_id,
                warehouse_id=data.warehouse_id,
                batch_number=line.batch_number,
                expiry_date=line.expiry_date,
                base_quantity=base_quantity,
                unit_cost=base_unit_cost,
            )
            # Flush so new batches get their id without ending the transaction.
            await self.session.flush()

            invoice.lines.append(
                PurchaseInvoiceLine(
                    product_id=line.product_id,
                    batch_id=batch.id,
                    batch_number=line.batch_number,
                    expiry_date=line.expiry_date,
                    quantity=base_quantity,
                    unit_cost=base_unit_cost,
                    line_total=line_total,
                )
            )
            subtotal += line_total
        return subtotal

    async def create_invoice(
        self, data: PurchaseInvoiceCreate, created_by: int | None = None
    ) -> PurchaseInvoice:
        """Post a purchase invoice and enter its goods into stock — all in ONE transaction.

        If any line fails (unknown product, expired goods, batch conflict), nothing is saved.
        """
        supplier = await self.get_supplier(data.supplier_id)
        if not supplier.is_active:
            raise AppException(400, "هذا المورد موقوف ولا يمكن الشراء منه.")
        await self.stock.get_active_warehouse(data.warehouse_id)
        tax_rates = await self._resolve_taxes(data.tax_rate_ids)

        invoice = PurchaseInvoice(
            supplier_id=data.supplier_id,
            warehouse_id=data.warehouse_id,
            supplier_invoice_number=data.supplier_invoice_number,
            invoice_date=data.invoice_date or date.today(),
            payment_method=data.payment_method,
            shipping_cost=data.shipping_cost,
            vat_amount=Decimal("0"),
            subtotal=Decimal("0"),
            total=Decimal("0"),
            created_by=created_by,
        )
        invoice.notes = data.notes

        subtotal = await self._build_lines(invoice, data)

        invoice.subtotal = subtotal
        invoice.vat_amount = self._apply_taxes(invoice, tax_rates, subtotal)
        invoice.total = subtotal + data.shipping_cost + invoice.vat_amount
        # Cashier gate: cash/card invoices wait unpaid until the cashier actually
        # pays the supplier (see CashierService.pay_purchase_invoice); credit
        # invoices are confirmed immediately since they settle later via the
        # supplier's account.
        invoice.paid_amount = Decimal("0")
        invoice.payment_confirmed_at = (
            None
            if data.payment_method
            in (PurchasePaymentMethod.CASH, PurchasePaymentMethod.CARD)
            else datetime.now(timezone.utc)
        )

        self.session.add(invoice)
        await self.session.flush()
        await self._post_invoice_entries(invoice, supplier, subtotal, created_by)

        await self.session.commit()
        return await self.get_invoice(invoice.id)

    async def _post_invoice_entries(
        self,
        invoice: PurchaseInvoice,
        supplier: Supplier,
        subtotal: Decimal,
        created_by: int | None,
    ) -> None:
        """Automatic double-entry: goods (incl. shipping) into inventory, VAT
        recoverable, against the supplier's payable account.

        Every invoice posts as a payable at creation regardless of payment method
        — cash/card invoices only actually pay out once the cashier disburses it
        (see CashierService.pay_purchase_invoice), which posts its own entry.
        """
        await self.accounting.add_entry_no_commit(
            entry_date=invoice.invoice_date,
            description=f"فاتورة شراء رقم {invoice.id} من المورد ({supplier.name})",
            items=[
                (INVENTORY, subtotal + invoice.shipping_cost, Decimal("0")),
                (VAT, invoice.vat_amount, Decimal("0")),
                (ACCOUNTS_PAYABLE, Decimal("0"), invoice.total),
            ],
            reference_type="purchase_invoice",
            reference_id=invoice.id,
            created_by=created_by,
        )

    async def update_invoice(
        self, invoice_id: int, data: PurchaseInvoiceCreate, updated_by: int | None = None
    ) -> PurchaseInvoice:
        """Manager-only rebuild of a posted purchase invoice, all in ONE transaction.

        Reverses the previously received quantities from their batches, replaces the
        automatic journal entries, then re-runs the normal receiving/posting pipeline
        with the new data. Fails atomically — on any error the original invoice stays intact.
        Blocked when any received quantity has already been sold, since reversing it
        would drive stock negative.
        """
        invoice = await self.get_invoice(invoice_id)

        supplier = await self.get_supplier(data.supplier_id)
        if not supplier.is_active:
            raise AppException(400, "هذا المورد موقوف ولا يمكن الشراء منه.")
        await self.stock.get_active_warehouse(data.warehouse_id)
        tax_rates = await self._resolve_taxes(data.tax_rate_ids)

        # 1) Reverse the previously received quantities; block if some was already sold.
        for line in invoice.lines:
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is not None:
                if batch.quantity < line.quantity:
                    raise AppException(
                        400,
                        "لا يمكن تعديل الفاتورة؛ تم بيع جزء من هذه البضاعة بالفعل.",
                    )
                batch.quantity -= line.quantity

        # 2) Remove the old automatic postings; fresh ones are recorded below.
        old_entries = await self.session.execute(
            select(JournalEntry).where(
                JournalEntry.reference_type == "purchase_invoice",
                JournalEntry.reference_id == invoice_id,
            )
        )
        for entry in old_entries.scalars().all():
            await self.session.delete(entry)

        # 3) Reset the document, then rebuild it through the same pipeline as creation.
        invoice.lines.clear()
        invoice.taxes.clear()
        invoice.supplier_id = data.supplier_id
        invoice.warehouse_id = data.warehouse_id
        invoice.supplier_invoice_number = data.supplier_invoice_number
        invoice.invoice_date = data.invoice_date or date.today()
        invoice.payment_method = data.payment_method
        invoice.shipping_cost = data.shipping_cost
        invoice.notes = data.notes
        invoice.subtotal = Decimal("0")
        invoice.vat_amount = Decimal("0")
        invoice.total = Decimal("0")
        invoice.paid_amount = Decimal("0")

        subtotal = await self._build_lines(invoice, data)

        invoice.subtotal = subtotal
        invoice.vat_amount = self._apply_taxes(invoice, tax_rates, subtotal)
        invoice.total = subtotal + data.shipping_cost + invoice.vat_amount
        # Cashier gate resets on edit too: a changed total/method needs
        # re-paying (or re-confirming) rather than trusting a stale confirmation.
        invoice.paid_amount = Decimal("0")
        invoice.payment_confirmed_at = (
            None
            if data.payment_method
            in (PurchasePaymentMethod.CASH, PurchasePaymentMethod.CARD)
            else datetime.now(timezone.utc)
        )
        invoice.payment_confirmed_by = None

        await self.session.flush()
        await self._post_invoice_entries(invoice, supplier, subtotal, updated_by)

        await self.session.commit()
        return await self.get_invoice(invoice.id)

    async def delete_invoice(self, invoice_id: int) -> None:
        """Hard-delete a purchase invoice: reverse its stock and drop its journal entries.

        Blocked when any received quantity has already been sold, since reversing it
        would drive stock negative.
        """
        invoice = await self.get_invoice(invoice_id)

        for line in invoice.lines:
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is not None and batch.quantity < line.quantity:
                raise AppException(
                    400, "لا يمكن حذف الفاتورة؛ تم بيع جزء من هذه البضاعة بالفعل."
                )

        for line in invoice.lines:
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is not None:
                batch.quantity -= line.quantity

        old_entries = await self.session.execute(
            select(JournalEntry).where(
                JournalEntry.reference_type == "purchase_invoice",
                JournalEntry.reference_id == invoice_id,
            )
        )
        for entry in old_entries.scalars().all():
            await self.session.delete(entry)

        await self.session.delete(invoice)
        await self.session.commit()

    async def get_invoice(self, invoice_id: int) -> PurchaseInvoice:
        result = await self.session.execute(
            select(PurchaseInvoice)
            .options(
                selectinload(PurchaseInvoice.lines), selectinload(PurchaseInvoice.taxes)
            )
            .where(PurchaseInvoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise AppException(404, "فاتورة الشراء غير موجودة.")
        return invoice

    async def list_invoices(
        self, supplier_id: int | None = None
    ) -> list[PurchaseInvoice]:
        stmt = (
            select(PurchaseInvoice)
            .options(
                selectinload(PurchaseInvoice.lines), selectinload(PurchaseInvoice.taxes)
            )
            .order_by(PurchaseInvoice.id.desc())
        )
        if supplier_id is not None:
            stmt = stmt.where(PurchaseInvoice.supplier_id == supplier_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Purchase returns ---
    async def create_return(
        self, data: PurchaseReturnCreate, created_by: int | None = None
    ) -> PurchaseReturn:
        """Post a purchase return: goods always leave the warehouse back to the
        supplier, regardless of reason (unlike sales returns, there is no
        "resellable" branch — see PurchaseReturnReason)."""
        invoice = await self.get_invoice(data.invoice_id)
        supplier = await self.get_supplier(invoice.supplier_id)

        # Quantities already returned against this invoice, per batch.
        returned_result = await self.session.execute(
            select(
                PurchaseReturnLine.batch_id,
                func.coalesce(func.sum(PurchaseReturnLine.quantity), 0),
            )
            .join(PurchaseReturn, PurchaseReturnLine.return_id == PurchaseReturn.id)
            .where(PurchaseReturn.invoice_id == invoice.id)
            .group_by(PurchaseReturnLine.batch_id)
        )
        returned_per_batch: dict[int, Decimal] = {
            batch_id: Decimal(str(qty)) for batch_id, qty in returned_result.all()
        }

        purchase_return = PurchaseReturn(
            invoice_id=invoice.id,
            supplier_id=supplier.id,
            reason=data.reason,
            subtotal=Decimal("0"),
            vat_amount=Decimal("0"),
            total=Decimal("0"),
            notes=data.notes,
            created_by=created_by,
        )

        subtotal = Decimal("0")
        for line in data.lines:
            product = await self.stock.get_active_product(line.product_id)
            remaining = self.stock.to_base_quantity(
                product, line.quantity, line.unit_id
            )

            # Walk the invoice lines of this product and take back from their batches in order.
            for inv_line in invoice.lines:
                if inv_line.product_id != line.product_id or remaining <= 0:
                    continue
                already = returned_per_batch.get(inv_line.batch_id, Decimal("0"))
                returnable = inv_line.quantity - already
                if returnable <= 0:
                    continue
                take = min(returnable, remaining)

                batch = await self.session.get(ProductBatch, inv_line.batch_id)
                if batch is not None:
                    if batch.quantity < take:
                        raise AppException(
                            400,
                            f"لا يمكن إرجاع هذه الكمية من الصنف ({product.name})؛ "
                            "جزء منها تم بيعه بالفعل.",
                        )
                    batch.quantity -= take

                line_total = (take * inv_line.unit_cost).quantize(
                    TWO_PLACES, rounding=ROUND_HALF_UP
                )
                purchase_return.lines.append(
                    PurchaseReturnLine(
                        product_id=line.product_id,
                        batch_id=inv_line.batch_id,
                        quantity=take,
                        unit_cost=inv_line.unit_cost,
                        line_total=line_total,
                    )
                )
                subtotal += line_total
                returned_per_batch[inv_line.batch_id] = already + take
                remaining -= take

            if remaining > 0:
                raise AppException(
                    400,
                    f"الكمية المرتجعة للصنف ({product.name}) أكبر من الكمية المستلمة في الفاتورة.",
                )

        # Derive the tax proportionally from the ORIGINAL invoice's own numbers
        # (not any currently-configured rate), same convention as sales returns.
        effective_tax_fraction = (
            invoice.vat_amount / invoice.subtotal if invoice.subtotal > 0 else Decimal("0")
        )
        purchase_return.subtotal = subtotal
        purchase_return.vat_amount = (
            (subtotal * effective_tax_fraction).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            if invoice.vat_amount > 0
            else Decimal("0")
        )
        purchase_return.total = subtotal + purchase_return.vat_amount

        self.session.add(purchase_return)
        await self.session.flush()

        # Automatic double-entry: reverse inventory + VAT against the supplier's payable.
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"مرتجع مشتريات رقم {purchase_return.id} عن الفاتورة رقم {invoice.id}",
            items=[
                (ACCOUNTS_PAYABLE, purchase_return.total, Decimal("0")),
                (INVENTORY, Decimal("0"), subtotal),
                (VAT, Decimal("0"), purchase_return.vat_amount),
            ],
            reference_type="purchase_return",
            reference_id=purchase_return.id,
            created_by=created_by,
        )

        await self.session.commit()
        result = await self.session.execute(
            select(PurchaseReturn)
            .options(selectinload(PurchaseReturn.lines))
            .where(PurchaseReturn.id == purchase_return.id)
        )
        return result.scalar_one()

    async def list_returns(
        self, invoice_id: int | None = None
    ) -> list[PurchaseReturn]:
        stmt = (
            select(PurchaseReturn)
            .options(selectinload(PurchaseReturn.lines))
            .order_by(PurchaseReturn.id.desc())
        )
        if invoice_id is not None:
            stmt = stmt.where(PurchaseReturn.invoice_id == invoice_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Payments & statement ---
    async def create_payment(
        self, data: SupplierPaymentCreate, created_by: int | None = None
    ) -> SupplierPayment:
        supplier = await self.get_supplier(data.supplier_id)
        balance = await self.supplier_balance(supplier.id)
        if data.amount > balance:
            raise AppException(
                400, f"مبلغ السند أكبر من رصيد المورد المستحق ({balance})."
            )
        payment = SupplierPayment(
            supplier_id=data.supplier_id,
            amount=data.amount,
            payment_date=data.payment_date or date.today(),
            method=data.method,
            reference=data.reference,
            notes=data.notes,
            created_by=created_by,
        )
        self.session.add(payment)
        await self.session.flush()

        # Automatic double-entry: settle the supplier's payable from cash/bank.
        await self.accounting.add_entry_no_commit(
            entry_date=payment.payment_date,
            description=f"سند صرف رقم {payment.id} للمورد ({supplier.name})",
            items=[
                (ACCOUNTS_PAYABLE, payment.amount, Decimal("0")),
                (cash_or_bank(payment.method), Decimal("0"), payment.amount),
            ],
            reference_type="supplier_payment",
            reference_id=payment.id,
            created_by=created_by,
        )

        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def supplier_balance(self, supplier_id: int) -> Decimal:
        """Outstanding = opening + unpaid invoice amounts - returns - payments made."""
        supplier = await self.get_supplier(supplier_id)

        invoiced = await self.session.execute(
            select(
                func.coalesce(func.sum(PurchaseInvoice.total), 0),
                func.coalesce(func.sum(PurchaseInvoice.paid_amount), 0),
            ).where(PurchaseInvoice.supplier_id == supplier_id)
        )
        total_invoices, paid_on_invoices = invoiced.one()

        returns = await self.session.execute(
            select(func.coalesce(func.sum(PurchaseReturn.total), 0)).where(
                PurchaseReturn.supplier_id == supplier_id
            )
        )
        total_returns = returns.scalar_one()

        payments = await self.session.execute(
            select(func.coalesce(func.sum(SupplierPayment.amount), 0)).where(
                SupplierPayment.supplier_id == supplier_id
            )
        )
        total_payments = payments.scalar_one()

        return (
            supplier.opening_balance
            + Decimal(str(total_invoices))
            - Decimal(str(paid_on_invoices))
            - Decimal(str(total_returns))
            - Decimal(str(total_payments))
        )

    async def supplier_statement(self, supplier_id: int) -> SupplierStatementOut:
        from app.api.schemas.purchases import (
            PurchaseInvoiceOut,
            PurchaseReturnOut,
            SupplierOut,
            SupplierPaymentOut,
        )

        supplier = await self.get_supplier(supplier_id)
        invoices = await self.list_invoices(supplier_id)
        returns_result = await self.session.execute(
            select(PurchaseReturn)
            .options(selectinload(PurchaseReturn.lines))
            .where(PurchaseReturn.supplier_id == supplier_id)
            .order_by(PurchaseReturn.id)
        )
        returns = list(returns_result.scalars().all())
        payments_result = await self.session.execute(
            select(SupplierPayment)
            .where(SupplierPayment.supplier_id == supplier_id)
            .order_by(SupplierPayment.id)
        )
        payments = list(payments_result.scalars().all())

        total_invoices = sum((i.total for i in invoices), Decimal("0"))
        total_returns = sum((r.total for r in returns), Decimal("0"))
        total_paid = sum((i.paid_amount for i in invoices), Decimal("0")) + sum(
            (p.amount for p in payments), Decimal("0")
        )
        return SupplierStatementOut(
            supplier=SupplierOut.model_validate(supplier),
            opening_balance=supplier.opening_balance,
            total_invoices=total_invoices,
            total_returns=total_returns,
            total_paid=total_paid,
            balance=supplier.opening_balance
            + total_invoices
            - total_returns
            - total_paid,
            invoices=[PurchaseInvoiceOut.model_validate(i) for i in invoices],
            returns=[PurchaseReturnOut.model_validate(r) for r in returns],
            payments=[SupplierPaymentOut.model_validate(p) for p in payments],
        )
