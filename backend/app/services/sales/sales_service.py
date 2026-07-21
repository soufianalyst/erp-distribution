"""Sales business logic: customers, FEFO invoices, credit control, returns, receipts."""

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.sales import (
    CustomerCreate,
    CustomerPaymentCreate,
    CustomerStatementOut,
    CustomerUpdate,
    QuotationCreate,
    SalesInvoiceCreate,
    SalesReturnCreate,
)
from app.core.exceptions import AppException
from app.core.permissions import has_permission
from app.domain.models.accounting import JournalEntry
from app.domain.models.delivery import DeliveryStop, DeliveryTrip
from app.domain.models.inventory import Product, ProductBatch
from app.domain.models.sales import (
    Customer,
    CustomerPayment,
    FulfillmentType,
    InvoiceTaxLine,
    PriceTier,
    QuotationStatus,
    QuotationTaxLine,
    ReturnReason,
    ReturnTaxLine,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPaymentMethod,
    SalesQuotation,
    SalesQuotationLine,
    SalesReturn,
    SalesReturnLine,
    TaxType,
)
from app.domain.models.user import User, UserRole
from app.services.accounting.accounting_service import (
    ACCOUNTS_RECEIVABLE,
    CASH,
    COGS,
    DAMAGE_LOSS,
    INVENTORY,
    SALES_RETURNS,
    SALES_REVENUE,
    VAT,
    AccountingService,
    cash_or_bank,
)
from app.services.inventory.stock_service import StockService

TWO_PLACES = Decimal("0.01")


async def _resolve_tax_types(
    session: AsyncSession, tax_type_ids: list[int]
) -> list[TaxType]:
    """Load and validate active tax types by IDs."""
    if not tax_type_ids:
        return []
    result = await session.execute(
        select(TaxType).where(TaxType.id.in_(tax_type_ids), TaxType.is_active == True)
    )
    tax_types = list(result.scalars().all())
    if len(tax_types) != len(tax_type_ids):
        raise AppException(400, "واحدة أو أكثر من أنواع الضريبة غير موجودة أو غير نشطة.")
    return tax_types


def _compute_tax_lines(
    subtotal: Decimal, tax_types: list[TaxType]
) -> list[tuple[TaxType, Decimal]]:
    """Compute tax amount for each tax type and return (tax_type, amount) pairs."""
    results: list[tuple[TaxType, Decimal]] = []
    for tt in tax_types:
        amount = (subtotal * tt.rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        results.append((tt, amount))
    return results


def _total_tax(tax_amounts: list[tuple[TaxType, Decimal]]) -> Decimal:
    """Sum of all tax amounts."""
    return sum(amount for _, amount in tax_amounts)


class SalesService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stock = StockService(session)
        self.accounting = AccountingService(session)

    # --- Customers ---
    async def get_customer(self, customer_id: int) -> Customer:
        customer = await self.session.get(Customer, customer_id)
        if customer is None:
            raise AppException(404, "العميل غير موجود.")
        return customer

    def ensure_customer_access(self, user: User, customer: Customer) -> None:
        """Users without the all-customers permission only reach their own customers."""
        if has_permission(user, "sales.all_customers"):
            return
        if customer.salesman_id != user.id:
            raise AppException(403, "لا يمكنك التعامل مع عملاء مندوب آخر.")

    async def _get_customer_by_name(self, name: str) -> Customer | None:
        result = await self.session.execute(
            select(Customer).where(Customer.name == name)
        )
        return result.scalar_one_or_none()

    async def create_customer(self, data: CustomerCreate) -> Customer:
        if await self._get_customer_by_name(data.name) is not None:
            raise AppException(409, "يوجد عميل بهذا الاسم من قبل.")
        if data.salesman_id is not None:
            salesman = await self.session.get(User, data.salesman_id)
            if salesman is None or salesman.role != UserRole.SALES:
                raise AppException(400, "المندوب المحدد غير موجود أو ليس موظف مبيعات.")
        customer = Customer(
            name=data.name,
            phone=data.phone,
            address=data.address,
            price_tier=data.price_tier,
            credit_limit=data.credit_limit,
            opening_balance=data.opening_balance,
            salesman_id=data.salesman_id,
        )
        self.session.add(customer)
        await self.session.commit()
        await self.session.refresh(customer)
        return customer

    async def update_customer(self, customer_id: int, data: CustomerUpdate) -> Customer:
        customer = await self.get_customer(customer_id)
        if data.name is not None and data.name != customer.name:
            if await self._get_customer_by_name(data.name) is not None:
                raise AppException(409, "يوجد عميل بهذا الاسم من قبل.")
            customer.name = data.name
        if data.phone is not None:
            customer.phone = data.phone
        if data.address is not None:
            customer.address = data.address
        if data.price_tier is not None:
            customer.price_tier = data.price_tier
        if data.credit_limit is not None:
            customer.credit_limit = data.credit_limit
        if data.salesman_id is not None:
            salesman = await self.session.get(User, data.salesman_id)
            if salesman is None or salesman.role != UserRole.SALES:
                raise AppException(400, "المندوب المحدد غير موجود أو ليس موظف مبيعات.")
            customer.salesman_id = data.salesman_id
        if data.is_active is not None:
            customer.is_active = data.is_active
        if data.tax_exempt is not None:
            customer.tax_exempt = data.tax_exempt
        await self.session.commit()
        await self.session.refresh(customer)
        return customer

    async def list_customers(
        self, user: User, search: str | None = None
    ) -> list[Customer]:
        stmt = select(Customer).order_by(Customer.id)
        if not has_permission(user, "sales.all_customers"):
            stmt = stmt.where(Customer.salesman_id == user.id)
        if search:
            stmt = stmt.where(Customer.name.ilike(f"%{search}%"))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Pricing & balance ---
    @staticmethod
    def tier_price(product: Product, tier: PriceTier) -> Decimal:
        prices = {
            PriceTier.WHOLESALE: product.wholesale_price,
            PriceTier.HALF_WHOLESALE: product.half_wholesale_price,
            PriceTier.RETAIL: product.retail_price,
        }
        return prices[tier]

    async def customer_balance(self, customer_id: int) -> Decimal:
        """Outstanding = opening + unpaid invoice amounts - returns - collections."""
        customer = await self.get_customer(customer_id)

        invoiced = await self.session.execute(
            select(
                func.coalesce(func.sum(SalesInvoice.total), 0),
                func.coalesce(func.sum(SalesInvoice.paid_amount), 0),
            ).where(SalesInvoice.customer_id == customer_id)
        )
        total_invoices, paid_on_invoices = invoiced.one()

        returns = await self.session.execute(
            select(func.coalesce(func.sum(SalesReturn.total), 0)).where(
                SalesReturn.customer_id == customer_id
            )
        )
        total_returns = returns.scalar_one()

        payments = await self.session.execute(
            select(func.coalesce(func.sum(CustomerPayment.amount), 0)).where(
                CustomerPayment.customer_id == customer_id
            )
        )
        total_payments = payments.scalar_one()

        return (
            customer.opening_balance
            + Decimal(str(total_invoices))
            - Decimal(str(paid_on_invoices))
            - Decimal(str(total_returns))
            - Decimal(str(total_payments))
        )

    # --- Sales invoices ---
    async def _build_lines(
        self, invoice: SalesInvoice, data: SalesInvoiceCreate, customer: Customer
    ) -> tuple[Decimal, Decimal]:
        """FEFO-allocate the requested lines onto the invoice; returns (subtotal, cost_total).

        One input line becomes one invoice line per allocated batch.
        Each line carries the warehouse_id from its batch.
        """
        subtotal = Decimal("0")
        cost_total = Decimal("0")
        for line in data.lines:
            product = await self.stock.get_active_product(line.product_id)
            base_quantity = self.stock.to_base_quantity(
                product, line.quantity, line.unit_id
            )
            unit_price = self.tier_price(product, customer.price_tier)

            allocations = await self.stock.fefo_allocate_all(
                product.id, base_quantity
            )
            for batch, take in allocations:
                batch.quantity -= take
                line_total = (take * unit_price).quantize(
                    TWO_PLACES, rounding=ROUND_HALF_UP
                )
                invoice.lines.append(
                    SalesInvoiceLine(
                        product_id=product.id,
                        batch_id=batch.id,
                        batch_number=batch.batch_number,
                        warehouse_id=batch.warehouse_id,
                        quantity=take,
                        unit_price=unit_price,
                        unit_cost=batch.unit_cost,
                        line_total=line_total,
                    )
                )
                subtotal += line_total
                if batch.unit_cost is not None:
                    cost_total += (take * batch.unit_cost).quantize(
                        TWO_PLACES, rounding=ROUND_HALF_UP
                    )
        return subtotal, cost_total

    def _check_credit_limit(
        self,
        customer: Customer,
        balance: Decimal,
        invoice_total: Decimal,
        data: SalesInvoiceCreate,
        user: User,
    ) -> None:
        if balance + invoice_total > customer.credit_limit:
            # Manager approval: overriding needs the dedicated permission.
            if not (
                data.credit_override and has_permission(user, "sales.credit_override")
            ):
                raise AppException(
                    400,
                    "تم تجاوز الحد الائتماني للعميل "
                    f"(الرصيد الحالي: {balance}، الحد: {customer.credit_limit})؛ "
                    "يتطلب البيع الآجل موافقة المدير.",
                )

    async def _post_invoice_entries(
        self,
        invoice: SalesInvoice,
        customer: Customer,
        subtotal: Decimal,
        cost_total: Decimal,
        user: User,
        tax_amounts: list[tuple[TaxType, Decimal]] | None = None,
    ) -> None:
        """Automatic double-entry: receivable vs revenue + tax liabilities, plus COGS when known."""
        # All invoices start as receivable; cash payments are settled later by the cashier.
        debit_account = ACCOUNTS_RECEIVABLE
        # Build credit items: always sales revenue, then one line per tax type.
        credit_items: list[tuple[str, Decimal, Decimal]] = [
            (SALES_REVENUE, Decimal("0"), subtotal),
        ]
        if tax_amounts:
            for tt, amount in tax_amounts:
                credit_items.append((tt.accounting_code, Decimal("0"), amount))
        elif invoice.vat_amount > 0:
            # Fallback for legacy callers that set vat_amount directly.
            credit_items.append((VAT, Decimal("0"), invoice.vat_amount))

        await self.accounting.add_entry_no_commit(
            entry_date=invoice.invoice_date,
            description=f"فاتورة مبيعات رقم {invoice.id} للعميل ({customer.name})",
            items=[
                (debit_account, invoice.total, Decimal("0")),
                *credit_items,
            ],
            reference_type="sales_invoice",
            reference_id=invoice.id,
            created_by=user.id,
        )
        if cost_total > 0:
            await self.accounting.add_entry_no_commit(
                entry_date=invoice.invoice_date,
                description=f"تكلفة البضاعة المباعة لفاتورة المبيعات رقم {invoice.id}",
                items=[
                    (COGS, cost_total, Decimal("0")),
                    (INVENTORY, Decimal("0"), cost_total),
                ],
                reference_type="sales_invoice",
                reference_id=invoice.id,
                created_by=user.id,
            )

    async def create_invoice(
        self, data: SalesInvoiceCreate, user: User
    ) -> SalesInvoice:
        """Post a sales invoice: FEFO stock deduction, credit-limit check, one transaction."""
        customer = await self.get_customer(data.customer_id)
        if not customer.is_active:
            raise AppException(400, "هذا العميل موقوف ولا يمكن البيع له.")
        self.ensure_customer_access(user, customer)

        # Tax-exempt customers get no taxes regardless of selection.
        effective_tax_ids = (
            [] if customer.tax_exempt else data.tax_type_ids
        )
        tax_types = await _resolve_tax_types(self.session, effective_tax_ids)

        invoice = SalesInvoice(
            customer_id=customer.id,
            salesman_id=customer.salesman_id,
            warehouse_id=data.warehouse_id,
            invoice_date=date.today(),
            payment_method=data.payment_method,
            fulfillment=data.fulfillment,
            subtotal=Decimal("0"),
            vat_amount=Decimal("0"),
            total=Decimal("0"),
            notes=data.notes,
            created_by=user.id,
        )

        subtotal, cost_total = await self._build_lines(invoice, data, customer)

        # Compute per-tax-type amounts and build tax lines.
        tax_amounts = _compute_tax_lines(subtotal, tax_types)
        total_tax = _total_tax(tax_amounts)

        invoice.subtotal = subtotal
        invoice.vat_amount = total_tax  # kept for backward compatibility
        invoice.total = subtotal + total_tax

        if data.payment_method == SalesPaymentMethod.CREDIT:
            balance = await self.customer_balance(customer.id)
            self._check_credit_limit(customer, balance, invoice.total, data, user)

        # All invoices start unpaid; cash/card payments are recorded by the cashier module.
        invoice.paid_amount = Decimal("0")

        self.session.add(invoice)
        await self.session.flush()

        # Create tax lines linked to this invoice.
        for tt, amount in tax_amounts:
            self.session.add(
                InvoiceTaxLine(
                    invoice_id=invoice.id,
                    tax_type_id=tt.id,
                    rate_at_time=tt.rate,
                    amount=amount,
                )
            )

        await self._post_invoice_entries(
            invoice, customer, subtotal, cost_total, user, tax_amounts
        )

        # Single commit: stock deduction, the invoice, and its postings succeed or fail together.
        await self.session.commit()
        return await self.get_invoice(invoice.id)

    async def update_invoice(
        self, invoice_id: int, data: SalesInvoiceCreate, user: User
    ) -> SalesInvoice:
        """Manager-only rebuild of a posted invoice, all in ONE transaction.

        Restores the sold quantities to their original batches, replaces the automatic
        journal entries, then re-runs the normal FEFO/credit/posting pipeline with the
        new data. Fails atomically — on any error the original invoice stays intact.
        """
        invoice = await self.get_invoice(invoice_id)

        returns_count = await self.session.execute(
            select(func.count())
            .select_from(SalesReturn)
            .where(SalesReturn.invoice_id == invoice_id)
        )
        if returns_count.scalar_one() > 0:
            raise AppException(
                400, "لا يمكن تعديل فاتورة مسجل عليها مرتجعات؛ عدّل عبر مرتجع جديد."
            )

        customer = await self.get_customer(data.customer_id)
        if not customer.is_active:
            raise AppException(400, "هذا العميل موقوف ولا يمكن البيع له.")
        await self.stock.get_active_warehouse(data.warehouse_id)

        # 1) Give the previously sold quantities back to their original batches.
        for line in invoice.lines:
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is not None:
                batch.quantity += line.quantity

        # 2) Remove the old automatic postings; fresh ones are recorded below.
        old_entries = await self.session.execute(
            select(JournalEntry).where(
                JournalEntry.reference_type == "sales_invoice",
                JournalEntry.reference_id == invoice_id,
            )
        )
        for entry in old_entries.scalars().all():
            await self.session.delete(entry)

        # 3) Remove old tax lines.
        old_tax_lines = await self.session.execute(
            select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == invoice_id)
        )
        for tl in old_tax_lines.scalars().all():
            await self.session.delete(tl)

        # 4) Reset the document, then rebuild it through the same pipeline as creation.
        invoice.lines.clear()
        invoice.customer_id = customer.id
        invoice.salesman_id = customer.salesman_id
        invoice.warehouse_id = data.warehouse_id
        invoice.payment_method = data.payment_method
        invoice.fulfillment = data.fulfillment
        if data.fulfillment != FulfillmentType.PICKUP:
            invoice.picked_up_at = None
        invoice.notes = data.notes
        invoice.subtotal = Decimal("0")
        invoice.vat_amount = Decimal("0")
        invoice.total = Decimal("0")
        invoice.paid_amount = Decimal("0")

        effective_tax_ids = (
            [] if customer.tax_exempt else data.tax_type_ids
        )
        tax_types = await _resolve_tax_types(self.session, effective_tax_ids)

        subtotal, cost_total = await self._build_lines(invoice, data, customer)
        tax_amounts = _compute_tax_lines(subtotal, tax_types)
        total_tax = _total_tax(tax_amounts)
        total = subtotal + total_tax

        if data.payment_method == SalesPaymentMethod.CREDIT:
            # The zeroed totals were flushed, so the balance excludes this invoice.
            balance = await self.customer_balance(customer.id)
            self._check_credit_limit(customer, balance, total, data, user)

        invoice.subtotal = subtotal
        invoice.vat_amount = total_tax
        invoice.total = total
        invoice.paid_amount = Decimal("0")

        await self.session.flush()

        # Create new tax lines.
        for tt, amount in tax_amounts:
            self.session.add(
                InvoiceTaxLine(
                    invoice_id=invoice.id,
                    tax_type_id=tt.id,
                    rate_at_time=tt.rate,
                    amount=amount,
                )
            )

        await self._post_invoice_entries(
            invoice, customer, subtotal, cost_total, user, tax_amounts
        )

        await self.session.commit()
        return await self.get_invoice(invoice.id)

    async def _attach_return_totals(self, invoices: list[SalesInvoice]) -> None:
        """Expose how much of each invoice was credited back via returns."""
        ids = [invoice.id for invoice in invoices]
        if not ids:
            return
        result = await self.session.execute(
            select(
                SalesReturn.invoice_id,
                func.coalesce(func.sum(SalesReturn.total), 0),
            )
            .where(SalesReturn.invoice_id.in_(ids))
            .group_by(SalesReturn.invoice_id)
        )
        totals = {invoice_id: Decimal(str(total)) for invoice_id, total in result.all()}
        for invoice in invoices:
            invoice.returned_total = totals.get(invoice.id, Decimal("0"))

    async def delete_invoice(self, invoice_id: int) -> None:
        """Hard-delete an invoice: restore its stock and drop its journal entries.

        Blocked when returns or delivery trips reference it, so history stays consistent.
        """
        invoice = await self.get_invoice(invoice_id)

        returns_count = await self.session.execute(
            select(func.count())
            .select_from(SalesReturn)
            .where(SalesReturn.invoice_id == invoice_id)
        )
        if returns_count.scalar_one() > 0:
            raise AppException(400, "لا يمكن حذف فاتورة مسجل عليها مرتجعات.")

        stops_count = await self.session.execute(
            select(func.count())
            .select_from(DeliveryStop)
            .join(DeliveryTrip, DeliveryStop.trip_id == DeliveryTrip.id)
            .where(DeliveryStop.invoice_id == invoice_id)
        )
        if stops_count.scalar_one() > 0:
            raise AppException(
                400, "الفاتورة مرتبطة برحلة توزيع؛ أزلها من الرحلة أولاً."
            )

        # Give the sold quantities back to their original batches.
        for line in invoice.lines:
            batch = await self.session.get(ProductBatch, line.batch_id)
            if batch is not None:
                batch.quantity += line.quantity

        # Remove the automatic postings, then the document itself.
        old_entries = await self.session.execute(
            select(JournalEntry).where(
                JournalEntry.reference_type == "sales_invoice",
                JournalEntry.reference_id == invoice_id,
            )
        )
        for entry in old_entries.scalars().all():
            await self.session.delete(entry)

        await self.session.delete(invoice)
        await self.session.commit()

    async def mark_picked_up(self, invoice_id: int) -> SalesInvoice:
        """Hand the goods over at the warehouse counter (pickup invoices only)."""
        invoice = await self.get_invoice(invoice_id)
        if invoice.fulfillment != FulfillmentType.PICKUP:
            raise AppException(
                400, "هذه الفاتورة توصيل للعميل وليست استلاماً من المستودع."
            )
        if invoice.picked_up_at is not None:
            raise AppException(400, "تم تسليم بضاعة هذه الفاتورة من قبل.")
        invoice.picked_up_at = datetime.now(timezone.utc)
        await self.session.commit()
        return await self.get_invoice(invoice_id)

    async def get_invoice(self, invoice_id: int) -> SalesInvoice:
        result = await self.session.execute(
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines),
                selectinload(SalesInvoice.tax_lines).selectinload(InvoiceTaxLine.tax_type),
            )
            .where(SalesInvoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise AppException(404, "فاتورة المبيعات غير موجودة.")
        await self._attach_return_totals([invoice])
        return invoice

    async def list_invoices(
        self, user: User, customer_id: int | None = None
    ) -> list[SalesInvoice]:
        stmt = (
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines),
                selectinload(SalesInvoice.tax_lines).selectinload(InvoiceTaxLine.tax_type),
            )
            .order_by(SalesInvoice.id.desc())
        )
        if not has_permission(user, "sales.all_customers"):
            stmt = stmt.where(SalesInvoice.salesman_id == user.id)
        if customer_id is not None:
            stmt = stmt.where(SalesInvoice.customer_id == customer_id)
        result = await self.session.execute(stmt)
        invoices = list(result.scalars().all())
        await self._attach_return_totals(invoices)
        return invoices

    # --- Returns ---
    async def create_return(self, data: SalesReturnCreate, user: User) -> SalesReturn:
        """Post a sales return; resellable goods go back to their original batches."""
        invoice = await self.get_invoice(data.invoice_id)
        customer = await self.get_customer(invoice.customer_id)
        self.ensure_customer_access(user, customer)

        # Quantities already returned against this invoice, per batch.
        returned_result = await self.session.execute(
            select(
                SalesReturnLine.batch_id,
                func.coalesce(func.sum(SalesReturnLine.quantity), 0),
            )
            .join(SalesReturn, SalesReturnLine.return_id == SalesReturn.id)
            .where(SalesReturn.invoice_id == invoice.id)
            .group_by(SalesReturnLine.batch_id)
        )
        returned_per_batch: dict[int, Decimal] = {
            batch_id: Decimal(str(qty)) for batch_id, qty in returned_result.all()
        }

        sales_return = SalesReturn(
            invoice_id=invoice.id,
            customer_id=customer.id,
            reason=data.reason,
            subtotal=Decimal("0"),
            vat_amount=Decimal("0"),
            total=Decimal("0"),
            notes=data.notes,
            created_by=user.id,
        )

        subtotal = Decimal("0")
        cost_total = Decimal("0")
        for line in data.lines:
            product = await self.stock.get_active_product(line.product_id)
            remaining = self.stock.to_base_quantity(
                product, line.quantity, line.unit_id
            )

            # Walk the invoice lines of this product and give back to their batches in order.
            for inv_line in invoice.lines:
                if inv_line.product_id != line.product_id or remaining <= 0:
                    continue
                already = returned_per_batch.get(inv_line.batch_id, Decimal("0"))
                returnable = inv_line.quantity - already
                if returnable <= 0:
                    continue
                take = min(returnable, remaining)

                if data.reason == ReturnReason.RESELLABLE:
                    batch = await self.session.get(ProductBatch, inv_line.batch_id)
                    if batch is not None:
                        batch.quantity += take

                line_total = (take * inv_line.unit_price).quantize(
                    TWO_PLACES, rounding=ROUND_HALF_UP
                )
                sales_return.lines.append(
                    SalesReturnLine(
                        product_id=line.product_id,
                        batch_id=inv_line.batch_id,
                        quantity=take,
                        unit_price=inv_line.unit_price,
                        line_total=line_total,
                    )
                )
                subtotal += line_total
                if inv_line.unit_cost is not None:
                    cost_total += (take * inv_line.unit_cost).quantize(
                        TWO_PLACES, rounding=ROUND_HALF_UP
                    )
                returned_per_batch[inv_line.batch_id] = already + take
                remaining -= take

            if remaining > 0:
                raise AppException(
                    400,
                    f"الكمية المرتجعة للصنف ({product.name}) أكبر من الكمية المباعة في الفاتورة.",
                )

        sales_return.subtotal = subtotal

        # Inherit tax types from the original invoice's tax lines.
        orig_tax_result = await self.session.execute(
            select(InvoiceTaxLine).where(InvoiceTaxLine.invoice_id == invoice.id)
        )
        orig_tax_lines = list(orig_tax_result.scalars().all())
        total_tax = Decimal("0")
        tax_entries: list[tuple[TaxType, Decimal]] = []

        if orig_tax_lines:
            # Proportional tax: scale each tax by (return_subtotal / invoice_subtotal)
            # when the return doesn't cover the whole invoice.
            ratio = (
                subtotal / invoice.subtotal
                if invoice.subtotal > 0
                else Decimal("1")
            )
            for otl in orig_tax_lines:
                tt = await self.session.get(TaxType, otl.tax_type_id)
                if tt is None:
                    continue
                amt = (otl.amount * ratio).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                total_tax += amt
                tax_entries.append((tt, amt))

        sales_return.vat_amount = total_tax
        sales_return.total = subtotal + total_tax

        self.session.add(sales_return)
        await self.session.flush()

        # Create return tax lines.
        for tt, amt in tax_entries:
            self.session.add(
                ReturnTaxLine(
                    return_id=sales_return.id,
                    tax_type_id=tt.id,
                    rate_at_time=tt.rate,
                    amount=amt,
                )
            )

        # Automatic double-entry: reverse revenue + tax liabilities against the customer's receivable.
        tax_credit_items: list[tuple[str, Decimal, Decimal]] = []
        for tt, amt in tax_entries:
            tax_credit_items.append((tt.accounting_code, amt, Decimal("0")))
        if not tax_entries and sales_return.vat_amount > 0:
            tax_credit_items.append((VAT, sales_return.vat_amount, Decimal("0")))

        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"مرتجع مبيعات رقم {sales_return.id} عن الفاتورة رقم {invoice.id}",
            items=[
                (SALES_RETURNS, subtotal, Decimal("0")),
                *tax_credit_items,
                (ACCOUNTS_RECEIVABLE, Decimal("0"), sales_return.total),
            ],
            reference_type="sales_return",
            reference_id=sales_return.id,
            created_by=user.id,
        )
        # Cost side: resellable goods go back to inventory; damaged goods become a loss.
        if cost_total > 0:
            cost_debit_account = (
                INVENTORY if data.reason == ReturnReason.RESELLABLE else DAMAGE_LOSS
            )
            await self.accounting.add_entry_no_commit(
                entry_date=date.today(),
                description=f"تكلفة مرتجع المبيعات رقم {sales_return.id}",
                items=[
                    (cost_debit_account, cost_total, Decimal("0")),
                    (COGS, Decimal("0"), cost_total),
                ],
                reference_type="sales_return",
                reference_id=sales_return.id,
                created_by=user.id,
            )

        await self.session.commit()
        result = await self.session.execute(
            select(SalesReturn)
            .options(
                selectinload(SalesReturn.lines),
                selectinload(SalesReturn.tax_lines).selectinload(ReturnTaxLine.tax_type),
            )
            .where(SalesReturn.id == sales_return.id)
        )
        return result.scalar_one()

    async def list_returns(
        self, user: User, invoice_id: int | None = None
    ) -> list[SalesReturn]:
        stmt = (
            select(SalesReturn)
            .options(
                selectinload(SalesReturn.lines),
                selectinload(SalesReturn.tax_lines).selectinload(ReturnTaxLine.tax_type),
            )
            .order_by(SalesReturn.id.desc())
        )
        if invoice_id is not None:
            stmt = stmt.where(SalesReturn.invoice_id == invoice_id)
        if not has_permission(user, "sales.all_customers"):
            stmt = stmt.join(Customer, SalesReturn.customer_id == Customer.id).where(
                Customer.salesman_id == user.id
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Customer payments & statement ---
    async def create_payment(
        self, data: CustomerPaymentCreate, user: User
    ) -> CustomerPayment:
        customer = await self.get_customer(data.customer_id)
        self.ensure_customer_access(user, customer)
        balance = await self.customer_balance(customer.id)
        if data.amount > balance:
            raise AppException(
                400, f"مبلغ السند أكبر من رصيد العميل المستحق ({balance})."
            )
        payment = CustomerPayment(
            customer_id=customer.id,
            amount=data.amount,
            payment_date=data.payment_date or date.today(),
            method=data.method,
            reference=data.reference,
            notes=data.notes,
            created_by=user.id,
        )
        self.session.add(payment)
        await self.session.flush()

        # Automatic double-entry: cash/bank in, customer receivable down.
        await self.accounting.add_entry_no_commit(
            entry_date=payment.payment_date,
            description=f"سند قبض رقم {payment.id} من العميل ({customer.name})",
            items=[
                (cash_or_bank(payment.method), payment.amount, Decimal("0")),
                (ACCOUNTS_RECEIVABLE, Decimal("0"), payment.amount),
            ],
            reference_type="customer_payment",
            reference_id=payment.id,
            created_by=user.id,
        )

        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def customer_statement(
        self, customer_id: int, user: User
    ) -> CustomerStatementOut:
        from app.api.schemas.sales import (
            CustomerOut,
            CustomerPaymentOut,
            SalesInvoiceOut,
            SalesReturnOut,
        )

        customer = await self.get_customer(customer_id)
        self.ensure_customer_access(user, customer)

        invoices = await self.list_invoices(user, customer_id)
        returns_result = await self.session.execute(
            select(SalesReturn)
            .options(
                selectinload(SalesReturn.lines),
                selectinload(SalesReturn.tax_lines).selectinload(ReturnTaxLine.tax_type),
            )
            .where(SalesReturn.customer_id == customer_id)
            .order_by(SalesReturn.id)
        )
        returns = list(returns_result.scalars().all())
        payments_result = await self.session.execute(
            select(CustomerPayment)
            .where(CustomerPayment.customer_id == customer_id)
            .order_by(CustomerPayment.id)
        )
        payments = list(payments_result.scalars().all())

        total_invoices = sum((i.total for i in invoices), Decimal("0"))
        total_returns = sum((r.total for r in returns), Decimal("0"))
        total_paid = sum((i.paid_amount for i in invoices), Decimal("0")) + sum(
            (p.amount for p in payments), Decimal("0")
        )
        return CustomerStatementOut(
            customer=CustomerOut.model_validate(customer),
            opening_balance=customer.opening_balance,
            total_invoices=total_invoices,
            total_returns=total_returns,
            total_paid=total_paid,
            balance=customer.opening_balance
            + total_invoices
            - total_returns
            - total_paid,
            invoices=[SalesInvoiceOut.model_validate(i) for i in invoices],
            returns=[SalesReturnOut.model_validate(r) for r in returns],
            payments=[CustomerPaymentOut.model_validate(p) for p in payments],
        )

    # --- Quotations ---
    async def create_quotation(
        self, data: QuotationCreate, user: User
    ) -> SalesQuotation:
        customer = await self.get_customer(data.customer_id)
        if not customer.is_active:
            raise AppException(400, "هذا العميل موقوف ولا يمكن إعداد عرض أسعار له.")
        await self.stock.get_active_warehouse(data.warehouse_id)

        effective_tax_ids = (
            [] if customer.tax_exempt else data.tax_type_ids
        )
        tax_types = await _resolve_tax_types(self.session, effective_tax_ids)

        subtotal = Decimal("0")
        quotation = SalesQuotation(
            customer_id=customer.id,
            salesman_id=customer.salesman_id,
            warehouse_id=data.warehouse_id,
            quotation_date=date.today(),
            valid_until=data.valid_until,
            status=QuotationStatus.DRAFT,
            subtotal=Decimal("0"),
            vat_amount=Decimal("0"),
            total=Decimal("0"),
            notes=data.notes,
            created_by=user.id,
        )

        for line in data.lines:
            product = await self.stock.get_active_product(line.product_id)
            unit_price = line.unit_price if line.unit_price > 0 else self.tier_price(product, customer.price_tier)
            line_total = (line.quantity * unit_price).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            quotation.lines.append(
                SalesQuotationLine(
                    product_id=product.id,
                    product_name=line.product_name or product.name,
                    quantity=line.quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                )
            )
            subtotal += line_total

        tax_amounts = _compute_tax_lines(subtotal, tax_types)
        total_tax = _total_tax(tax_amounts)

        quotation.subtotal = subtotal
        quotation.vat_amount = total_tax
        quotation.total = subtotal + total_tax

        self.session.add(quotation)
        await self.session.flush()

        # Create quotation tax lines.
        for tt, amount in tax_amounts:
            self.session.add(
                QuotationTaxLine(
                    quotation_id=quotation.id,
                    tax_type_id=tt.id,
                    rate_at_time=tt.rate,
                    amount=amount,
                )
            )

        await self.session.commit()

        result = await self.session.execute(
            select(SalesQuotation)
            .options(
                selectinload(SalesQuotation.lines),
                selectinload(SalesQuotation.tax_lines).selectinload(QuotationTaxLine.tax_type),
            )
            .where(SalesQuotation.id == quotation.id)
        )
        return result.scalar_one()

    async def get_quotation(self, quotation_id: int) -> SalesQuotation:
        result = await self.session.execute(
            select(SalesQuotation)
            .options(
                selectinload(SalesQuotation.lines),
                selectinload(SalesQuotation.tax_lines).selectinload(QuotationTaxLine.tax_type),
            )
            .where(SalesQuotation.id == quotation_id)
        )
        quotation = result.scalar_one_or_none()
        if quotation is None:
            raise AppException(404, "عرض الأسعار غير موجود.")
        return quotation

    async def list_quotations(
        self, user: User, customer_id: int | None = None
    ) -> list[SalesQuotation]:
        stmt = (
            select(SalesQuotation)
            .options(
                selectinload(SalesQuotation.lines),
                selectinload(SalesQuotation.tax_lines).selectinload(QuotationTaxLine.tax_type),
            )
            .order_by(SalesQuotation.id.desc())
        )
        if not has_permission(user, "sales.all_customers"):
            stmt = stmt.where(SalesQuotation.salesman_id == user.id)
        if customer_id is not None:
            stmt = stmt.where(SalesQuotation.customer_id == customer_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_quotation_status(
        self, quotation_id: int, new_status: QuotationStatus
    ) -> SalesQuotation:
        quotation = await self.get_quotation(quotation_id)
        valid_transitions = {
            QuotationStatus.DRAFT: {QuotationStatus.SENT},
            QuotationStatus.SENT: {QuotationStatus.ACCEPTED, QuotationStatus.REJECTED},
            QuotationStatus.ACCEPTED: {QuotationStatus.CONVERTED},
        }
        allowed = valid_transitions.get(quotation.status, set())
        if new_status not in allowed:
            raise AppException(
                400,
                f"لا يمكن تغيير الحالة من {quotation.status.value} إلى {new_status.value}.",
            )
        quotation.status = new_status
        await self.session.commit()

        result = await self.session.execute(
            select(SalesQuotation)
            .options(selectinload(SalesQuotation.lines))
            .where(SalesQuotation.id == quotation.id)
        )
        return result.scalar_one()

    async def convert_to_invoice(
        self,
        quotation_id: int,
        payment_method: SalesPaymentMethod,
        user: User,
    ) -> SalesInvoice:
        """Convert an accepted quotation to a FEFO sales invoice in one transaction."""
        quotation = await self.get_quotation(quotation_id)
        if quotation.status != QuotationStatus.ACCEPTED:
            raise AppException(
                400, "يمكن تحويل العرض فقط إذا كان حالتها مقبولة."
            )

        # Build invoice lines from the quotation lines, respecting FEFO.
        invoice = SalesInvoice(
            customer_id=quotation.customer_id,
            salesman_id=quotation.salesman_id,
            warehouse_id=quotation.warehouse_id,
            invoice_date=date.today(),
            payment_method=payment_method,
            fulfillment=FulfillmentType.DELIVERY,
            subtotal=Decimal("0"),
            vat_amount=Decimal("0"),
            total=Decimal("0"),
            notes=f"تحويل من عرض الأسعار رقم {quotation.id}",
            created_by=user.id,
        )

        subtotal = Decimal("0")
        cost_total = Decimal("0")
        for qline in quotation.lines:
            product = await self.stock.get_active_product(qline.product_id)
            allocations = await self.stock.fefo_allocate_all(
                product.id, qline.quantity
            )
            for batch, take in allocations:
                batch.quantity -= take
                line_total = (take * qline.unit_price).quantize(
                    TWO_PLACES, rounding=ROUND_HALF_UP
                )
                invoice.lines.append(
                    SalesInvoiceLine(
                        product_id=product.id,
                        batch_id=batch.id,
                        batch_number=batch.batch_number,
                        warehouse_id=batch.warehouse_id,
                        quantity=take,
                        unit_price=qline.unit_price,
                        unit_cost=batch.unit_cost,
                        line_total=line_total,
                    )
                )
                subtotal += line_total
                if batch.unit_cost is not None:
                    cost_total += (take * batch.unit_cost).quantize(
                        TWO_PLACES, rounding=ROUND_HALF_UP
                    )

        # Inherit tax types from the quotation's tax lines.
        qtax_result = await self.session.execute(
            select(QuotationTaxLine).where(
                QuotationTaxLine.quotation_id == quotation.id
            )
        )
        qtax_lines = list(qtax_result.scalars().all())
        tax_amounts: list[tuple[TaxType, Decimal]] = []
        total_tax = Decimal("0")

        if qtax_lines:
            # Proportional scaling: recalculate taxes on the new subtotal.
            for qtl in qtax_lines:
                tt = await self.session.get(TaxType, qtl.tax_type_id)
                if tt is None:
                    continue
                amt = (subtotal * qtl.rate_at_time).quantize(
                    TWO_PLACES, rounding=ROUND_HALF_UP
                )
                tax_amounts.append((tt, amt))
                total_tax += amt

        invoice.subtotal = subtotal
        invoice.vat_amount = total_tax
        invoice.total = subtotal + total_tax

        if payment_method == SalesPaymentMethod.CREDIT:
            customer = await self.get_customer(quotation.customer_id)
            balance = await self.customer_balance(customer.id)
            self._check_credit_limit(
                customer, balance, invoice.total,
                SalesInvoiceCreate(
                    customer_id=customer.id,
                    warehouse_id=invoice.warehouse_id,
                    payment_method=payment_method,
                    lines=[],
                ),
                user,
            )

        invoice.paid_amount = Decimal("0")

        self.session.add(invoice)
        await self.session.flush()

        # Create invoice tax lines.
        for tt, amt in tax_amounts:
            self.session.add(
                InvoiceTaxLine(
                    invoice_id=invoice.id,
                    tax_type_id=tt.id,
                    rate_at_time=tt.rate,
                    amount=amt,
                )
            )

        # Post accounting entries.
        await self._post_invoice_entries(
            invoice,
            await self.get_customer(quotation.customer_id),
            subtotal,
            cost_total,
            user,
            tax_amounts,
        )

        # Mark quotation as converted and link it.
        quotation.status = QuotationStatus.CONVERTED
        quotation.converted_invoice_id = invoice.id

        await self.session.commit()
        return await self.get_invoice(invoice.id)

    async def delete_quotation(self, quotation_id: int) -> None:
        quotation = await self.get_quotation(quotation_id)
        if quotation.status != QuotationStatus.DRAFT:
            raise AppException(400, "يمكن حذف العرض فقط إذا كان في حالة مسودة.")
        await self.session.delete(quotation)
        await self.session.commit()
