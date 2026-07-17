"""Purchasing business logic: suppliers, purchase invoices, payments, and statements."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.purchases import (
    PurchaseInvoiceCreate,
    SupplierCreate,
    SupplierPaymentCreate,
    SupplierStatementOut,
    SupplierUpdate,
)
from app.core.exceptions import AppException
from app.domain.models.inventory import Product
from app.domain.models.purchases import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchasePaymentMethod,
    Supplier,
    SupplierPayment,
)
from app.services.accounting.accounting_service import (
    ACCOUNTS_PAYABLE,
    CASH,
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

        invoice = PurchaseInvoice(
            supplier_id=data.supplier_id,
            warehouse_id=data.warehouse_id,
            supplier_invoice_number=data.supplier_invoice_number,
            invoice_date=data.invoice_date or date.today(),
            payment_method=data.payment_method,
            shipping_cost=data.shipping_cost,
            vat_amount=data.vat_amount,
            subtotal=Decimal("0"),
            total=Decimal("0"),
            created_by=created_by,
        )
        invoice.notes = data.notes

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

        invoice.subtotal = subtotal
        invoice.total = subtotal + data.shipping_cost + data.vat_amount
        # Cash invoices are settled on the spot; credit invoices add to the supplier balance.
        invoice.paid_amount = (
            invoice.total
            if data.payment_method == PurchasePaymentMethod.CASH
            else Decimal("0")
        )

        self.session.add(invoice)
        await self.session.flush()

        # Automatic double-entry: goods (incl. shipping) into inventory, VAT recoverable,
        # against cash or the supplier's payable account.
        credit_account = (
            CASH
            if data.payment_method == PurchasePaymentMethod.CASH
            else ACCOUNTS_PAYABLE
        )
        await self.accounting.add_entry_no_commit(
            entry_date=invoice.invoice_date,
            description=f"فاتورة شراء رقم {invoice.id} من المورد ({supplier.name})",
            items=[
                (INVENTORY, subtotal + data.shipping_cost, Decimal("0")),
                (VAT, data.vat_amount, Decimal("0")),
                (credit_account, Decimal("0"), invoice.total),
            ],
            reference_type="purchase_invoice",
            reference_id=invoice.id,
            created_by=created_by,
        )

        await self.session.commit()
        return await self.get_invoice(invoice.id)

    async def get_invoice(self, invoice_id: int) -> PurchaseInvoice:
        result = await self.session.execute(
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.lines))
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
            .options(selectinload(PurchaseInvoice.lines))
            .order_by(PurchaseInvoice.id.desc())
        )
        if supplier_id is not None:
            stmt = stmt.where(PurchaseInvoice.supplier_id == supplier_id)
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
        """Outstanding balance = opening + unpaid invoice amounts - payments made."""
        supplier = await self.get_supplier(supplier_id)

        invoiced = await self.session.execute(
            select(
                func.coalesce(func.sum(PurchaseInvoice.total), 0),
                func.coalesce(func.sum(PurchaseInvoice.paid_amount), 0),
            ).where(PurchaseInvoice.supplier_id == supplier_id)
        )
        total_invoices, paid_on_invoices = invoiced.one()

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
            - Decimal(str(total_payments))
        )

    async def supplier_statement(self, supplier_id: int) -> SupplierStatementOut:
        from app.api.schemas.purchases import (
            PurchaseInvoiceOut,
            SupplierOut,
            SupplierPaymentOut,
        )

        supplier = await self.get_supplier(supplier_id)
        invoices = await self.list_invoices(supplier_id)
        payments_result = await self.session.execute(
            select(SupplierPayment)
            .where(SupplierPayment.supplier_id == supplier_id)
            .order_by(SupplierPayment.id)
        )
        payments = list(payments_result.scalars().all())

        total_invoices = sum((i.total for i in invoices), Decimal("0"))
        total_paid = sum((i.paid_amount for i in invoices), Decimal("0")) + sum(
            (p.amount for p in payments), Decimal("0")
        )
        return SupplierStatementOut(
            supplier=SupplierOut.model_validate(supplier),
            opening_balance=supplier.opening_balance,
            total_invoices=total_invoices,
            total_paid=total_paid,
            balance=supplier.opening_balance + total_invoices - total_paid,
            invoices=[PurchaseInvoiceOut.model_validate(i) for i in invoices],
            payments=[SupplierPaymentOut.model_validate(p) for p in payments],
        )
