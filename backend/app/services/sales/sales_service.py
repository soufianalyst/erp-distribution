"""Sales business logic: customers, FEFO invoices, credit control, returns, receipts."""

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.sales import (
    CommissionReportOut,
    CommissionRow,
    CustomerCreate,
    CustomerPaymentCreate,
    CustomerStatementOut,
    CustomerUpdate,
    QuotationConvertIn,
    SalesInvoiceCreate,
    SalesLineIn,
    SalesQuotationCreate,
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
    PriceTier,
    QuotationStatus,
    ReturnReason,
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceTax,
    SalesPaymentMethod,
    SalesQuotation,
    SalesQuotationLine,
    SalesQuotationTax,
    SalesReturn,
    SalesReturnLine,
)
from app.domain.models.settings import TaxRate
from app.domain.models.user import User, UserRole
from app.services.accounting.accounting_service import (
    ACCOUNTS_RECEIVABLE,
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
        self,
        invoice: SalesInvoice,
        data: SalesInvoiceCreate,
        customer: Customer,
        price_overrides: dict[int, Decimal] | None = None,
    ) -> tuple[Decimal, Decimal]:
        """FEFO-allocate the requested lines onto the invoice; returns (subtotal, cost_total).

        One input line becomes one invoice line per allocated batch. `price_overrides`
        (keyed by product_id) is for internal use only — e.g. honoring a quotation's
        frozen price on conversion — and is never accepted from the public API.
        """
        subtotal = Decimal("0")
        cost_total = Decimal("0")
        for line in data.lines:
            product = await self.stock.get_active_product(line.product_id)
            if product.warehouse_id is None:
                raise AppException(
                    400,
                    f"الصنف ({product.name}) غير مرتبط بمستودع؛ "
                    "يرجى تحديد المستودع من صفحة الأصناف أولاً.",
                )
            await self.stock.get_active_warehouse(product.warehouse_id)
            base_quantity = self.stock.to_base_quantity(
                product, line.quantity, line.unit_id
            )
            unit_price = (
                price_overrides[product.id]
                if price_overrides and product.id in price_overrides
                else self.tier_price(product, customer.price_tier)
            )

            allocations = await self.stock.fefo_allocate(
                product.id, product.warehouse_id, base_quantity
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
                        warehouse_id=product.warehouse_id,
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

    @staticmethod
    def _resolve_invoice_warehouse(invoice: SalesInvoice) -> int | None:
        """Single warehouse if every line agrees, else None (mixed-warehouse invoice)."""
        warehouse_ids = {line.warehouse_id for line in invoice.lines}
        return next(iter(warehouse_ids)) if len(warehouse_ids) == 1 else None

    async def _resolve_taxes(self, tax_rate_ids: list[int]) -> list[TaxRate]:
        """Validate and fetch the configured taxes to apply; empty means tax-free.

        Several taxes may be selected at once (e.g. VAT + a local tax); duplicates
        in the input are ignored.
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
    def _apply_taxes(invoice: SalesInvoice, tax_rates: list[TaxRate], subtotal: Decimal) -> Decimal:
        """Snapshot each selected tax onto the invoice; returns their summed amount."""
        total_tax = Decimal("0")
        for tax_rate in tax_rates:
            amount = (subtotal * tax_rate.rate / Decimal("100")).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            invoice.taxes.append(
                SalesInvoiceTax(
                    tax_rate_id=tax_rate.id,
                    name=tax_rate.name,
                    rate=tax_rate.rate,
                    amount=amount,
                )
            )
            total_tax += amount
        return total_tax

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
    ) -> None:
        """Automatic double-entry: receivable vs revenue + VAT, plus COGS when known.

        Every invoice posts as a receivable at creation time regardless of payment
        method — cash/card invoices only actually collect the money once the cashier
        confirms it (see CashierService), which posts its own reclassifying entry.
        """
        await self.accounting.add_entry_no_commit(
            entry_date=invoice.invoice_date,
            description=f"فاتورة مبيعات رقم {invoice.id} للعميل ({customer.name})",
            items=[
                (ACCOUNTS_RECEIVABLE, invoice.total, Decimal("0")),
                (SALES_REVENUE, Decimal("0"), subtotal),
                (VAT, Decimal("0"), invoice.vat_amount),
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
        self,
        data: SalesInvoiceCreate,
        user: User,
        price_overrides: dict[int, Decimal] | None = None,
    ) -> SalesInvoice:
        """Post a sales invoice: FEFO stock deduction, credit-limit check, one transaction."""
        customer = await self.get_customer(data.customer_id)
        if not customer.is_active:
            raise AppException(400, "هذا العميل موقوف ولا يمكن البيع له.")
        self.ensure_customer_access(user, customer)
        tax_rates = await self._resolve_taxes(data.tax_rate_ids)

        invoice = SalesInvoice(
            customer_id=customer.id,
            salesman_id=customer.salesman_id,
            invoice_date=date.today(),
            payment_method=data.payment_method,
            fulfillment=data.fulfillment,
            subtotal=Decimal("0"),
            vat_amount=Decimal("0"),
            total=Decimal("0"),
            notes=data.notes,
            created_by=user.id,
        )

        subtotal, cost_total = await self._build_lines(
            invoice, data, customer, price_overrides
        )
        invoice.warehouse_id = self._resolve_invoice_warehouse(invoice)

        invoice.subtotal = subtotal
        invoice.vat_amount = self._apply_taxes(invoice, tax_rates, subtotal)
        invoice.total = subtotal + invoice.vat_amount

        if data.payment_method == SalesPaymentMethod.CREDIT:
            balance = await self.customer_balance(customer.id)
            self._check_credit_limit(customer, balance, invoice.total, data, user)

        # Cashier gate: cash/card invoices wait unpaid until the cashier collects
        # them (see CashierService); credit invoices are confirmed immediately
        # since they're settled later through the customer's account.
        invoice.paid_amount = Decimal("0")
        invoice.payment_confirmed_at = (
            None
            if data.payment_method in (SalesPaymentMethod.CASH, SalesPaymentMethod.CARD)
            else datetime.now(timezone.utc)
        )

        self.session.add(invoice)
        await self.session.flush()
        await self._post_invoice_entries(invoice, customer, subtotal, cost_total, user)

        # Single commit: stock deduction, the invoice, and its postings succeed or fail together.
        await self.session.commit()
        return await self.get_invoice(invoice.id)

    # --- Quotations ---
    async def _build_quotation_lines(
        self,
        quotation: SalesQuotation,
        data: SalesQuotationCreate,
        customer: Customer,
    ) -> Decimal:
        """Price each requested line at the customer's tier — no stock/batch allocation."""
        subtotal = Decimal("0")
        for line in data.lines:
            product = await self.stock.get_active_product(line.product_id)
            base_quantity = self.stock.to_base_quantity(
                product, line.quantity, line.unit_id
            )
            unit_price = self.tier_price(product, customer.price_tier)
            line_total = (base_quantity * unit_price).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            quotation.lines.append(
                SalesQuotationLine(
                    product_id=product.id,
                    quantity=base_quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                )
            )
            subtotal += line_total
        return subtotal

    @staticmethod
    def _apply_quotation_taxes(
        quotation: SalesQuotation, tax_rates: list[TaxRate], subtotal: Decimal
    ) -> Decimal:
        total_tax = Decimal("0")
        for tax_rate in tax_rates:
            amount = (subtotal * tax_rate.rate / Decimal("100")).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            quotation.taxes.append(
                SalesQuotationTax(
                    tax_rate_id=tax_rate.id,
                    name=tax_rate.name,
                    rate=tax_rate.rate,
                    amount=amount,
                )
            )
            total_tax += amount
        return total_tax

    async def create_quotation(
        self, data: SalesQuotationCreate, user: User
    ) -> SalesQuotation:
        """Price a quote for a customer — no stock deduction or accounting effect."""
        customer = await self.get_customer(data.customer_id)
        if not customer.is_active:
            raise AppException(400, "هذا العميل موقوف ولا يمكن إنشاء عرض سعر له.")
        self.ensure_customer_access(user, customer)
        tax_rates = await self._resolve_taxes(data.tax_rate_ids)

        quotation = SalesQuotation(
            customer_id=customer.id,
            salesman_id=customer.salesman_id,
            quote_date=date.today(),
            valid_until=data.valid_until,
            status=QuotationStatus.DRAFT,
            subtotal=Decimal("0"),
            vat_amount=Decimal("0"),
            total=Decimal("0"),
            notes=data.notes,
            created_by=user.id,
        )
        subtotal = await self._build_quotation_lines(quotation, data, customer)
        quotation.subtotal = subtotal
        quotation.vat_amount = self._apply_quotation_taxes(quotation, tax_rates, subtotal)
        quotation.total = subtotal + quotation.vat_amount

        self.session.add(quotation)
        await self.session.commit()
        return await self.get_quotation(quotation.id)

    async def get_quotation(self, quotation_id: int) -> SalesQuotation:
        result = await self.session.execute(
            select(SalesQuotation)
            .options(
                selectinload(SalesQuotation.lines), selectinload(SalesQuotation.taxes)
            )
            .where(SalesQuotation.id == quotation_id)
        )
        quotation = result.scalar_one_or_none()
        if quotation is None:
            raise AppException(404, "عرض السعر غير موجود.")
        return quotation

    async def list_quotations(
        self, user: User, customer_id: int | None = None
    ) -> list[SalesQuotation]:
        stmt = (
            select(SalesQuotation)
            .options(
                selectinload(SalesQuotation.lines), selectinload(SalesQuotation.taxes)
            )
            .order_by(SalesQuotation.id.desc())
        )
        if not has_permission(user, "sales.all_customers"):
            stmt = stmt.where(SalesQuotation.salesman_id == user.id)
        if customer_id is not None:
            stmt = stmt.where(SalesQuotation.customer_id == customer_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def cancel_quotation(self, quotation_id: int, user: User) -> SalesQuotation:
        quotation = await self.get_quotation(quotation_id)
        customer = await self.get_customer(quotation.customer_id)
        self.ensure_customer_access(user, customer)
        if quotation.status != QuotationStatus.DRAFT:
            raise AppException(400, "لا يمكن إلغاء عرض سعر تم تحويله أو إلغاؤه من قبل.")
        quotation.status = QuotationStatus.CANCELLED
        await self.session.commit()
        return await self.get_quotation(quotation.id)

    async def convert_quotation_to_invoice(
        self, quotation_id: int, data: QuotationConvertIn, user: User
    ) -> SalesInvoice:
        """Turn an accepted quotation into a real invoice, honoring the quoted prices
        exactly — the normal FEFO/credit-limit/accounting path in create_invoice runs
        unchanged, just with each line's price frozen to what was quoted.
        """
        quotation = await self.get_quotation(quotation_id)
        customer = await self.get_customer(quotation.customer_id)
        self.ensure_customer_access(user, customer)
        if quotation.status != QuotationStatus.DRAFT:
            raise AppException(400, "لا يمكن تحويل عرض سعر تم تحويله أو إلغاؤه من قبل.")
        if quotation.valid_until is not None and quotation.valid_until < date.today():
            raise AppException(400, "انتهت صلاحية عرض السعر هذا؛ يرجى إنشاء عرض جديد.")

        invoice_data = SalesInvoiceCreate(
            customer_id=quotation.customer_id,
            payment_method=data.payment_method,
            fulfillment=data.fulfillment,
            tax_rate_ids=[
                t.tax_rate_id for t in quotation.taxes if t.tax_rate_id is not None
            ],
            notes=quotation.notes,
            lines=[
                SalesLineIn(product_id=line.product_id, quantity=line.quantity)
                for line in quotation.lines
            ],
            credit_override=data.credit_override,
        )
        price_overrides = {line.product_id: line.unit_price for line in quotation.lines}
        invoice = await self.create_invoice(invoice_data, user, price_overrides)

        quotation.status = QuotationStatus.CONVERTED
        quotation.converted_invoice_id = invoice.id
        await self.session.commit()
        return invoice

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

        tax_rates = await self._resolve_taxes(data.tax_rate_ids)

        # 3) Reset the document, then rebuild it through the same pipeline as creation.
        invoice.lines.clear()
        invoice.taxes.clear()
        invoice.customer_id = customer.id
        invoice.salesman_id = customer.salesman_id
        invoice.payment_method = data.payment_method
        invoice.fulfillment = data.fulfillment
        if data.fulfillment != FulfillmentType.PICKUP:
            invoice.picked_up_at = None
        invoice.notes = data.notes
        invoice.subtotal = Decimal("0")
        invoice.vat_amount = Decimal("0")
        invoice.total = Decimal("0")
        invoice.paid_amount = Decimal("0")

        subtotal, cost_total = await self._build_lines(invoice, data, customer)
        invoice.warehouse_id = self._resolve_invoice_warehouse(invoice)
        vat_amount = self._apply_taxes(invoice, tax_rates, subtotal)
        total = subtotal + vat_amount

        if data.payment_method == SalesPaymentMethod.CREDIT:
            # The zeroed totals were flushed, so the balance excludes this invoice.
            balance = await self.customer_balance(customer.id)
            self._check_credit_limit(customer, balance, total, data, user)

        invoice.subtotal = subtotal
        invoice.vat_amount = vat_amount
        invoice.total = total
        # Cashier gate resets on edit too: a changed total/method needs re-collecting
        # (or re-confirming) rather than trusting a stale prior confirmation.
        invoice.paid_amount = Decimal("0")
        invoice.payment_confirmed_at = (
            None
            if data.payment_method in (SalesPaymentMethod.CASH, SalesPaymentMethod.CARD)
            else datetime.now(timezone.utc)
        )
        invoice.payment_confirmed_by = None

        await self.session.flush()
        await self._post_invoice_entries(invoice, customer, subtotal, cost_total, user)

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
        if (
            invoice.payment_method != SalesPaymentMethod.CREDIT
            and invoice.payment_confirmed_at is None
        ):
            raise AppException(
                400,
                "لم يتم تحصيل قيمة الفاتورة من الصندوق بعد؛ "
                "يرجى التحصيل من شاشة الصندوق أولاً.",
            )
        invoice.picked_up_at = datetime.now(timezone.utc)
        await self.session.commit()
        return await self.get_invoice(invoice_id)

    async def get_invoice(self, invoice_id: int) -> SalesInvoice:
        result = await self.session.execute(
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines), selectinload(SalesInvoice.taxes)
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
                selectinload(SalesInvoice.lines), selectinload(SalesInvoice.taxes)
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

        # Derive the tax proportionally from the ORIGINAL invoice's own numbers
        # (not any currently-configured rate) — so a return always matches
        # whatever tax was actually charged on that specific invoice, even if
        # tax rates have since changed.
        effective_tax_fraction = (
            invoice.vat_amount / invoice.subtotal
            if invoice.subtotal > 0
            else Decimal("0")
        )
        sales_return.subtotal = subtotal
        sales_return.vat_amount = (
            (subtotal * effective_tax_fraction).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
            if invoice.vat_amount > 0
            else Decimal("0")
        )
        sales_return.total = subtotal + sales_return.vat_amount

        self.session.add(sales_return)
        await self.session.flush()

        # Automatic double-entry: reverse revenue + VAT against the customer's receivable.
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"مرتجع مبيعات رقم {sales_return.id} عن الفاتورة رقم {invoice.id}",
            items=[
                (SALES_RETURNS, subtotal, Decimal("0")),
                (VAT, sales_return.vat_amount, Decimal("0")),
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
            .options(selectinload(SalesReturn.lines))
            .where(SalesReturn.id == sales_return.id)
        )
        return result.scalar_one()

    async def list_returns(
        self, user: User, invoice_id: int | None = None
    ) -> list[SalesReturn]:
        stmt = (
            select(SalesReturn)
            .options(selectinload(SalesReturn.lines))
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
            .options(selectinload(SalesReturn.lines))
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

    async def commission_report(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        salesman_id: int | None = None,
    ) -> CommissionReportOut:
        """Net sales (invoices minus returns, both excluding VAT) per salesman,
        multiplied by their configured commission_rate.
        """
        sales_query = (
            select(
                SalesInvoice.salesman_id,
                func.sum(SalesInvoice.subtotal).label("total_sales"),
            )
            .where(SalesInvoice.salesman_id.is_not(None))
            .group_by(SalesInvoice.salesman_id)
        )
        if date_from is not None:
            sales_query = sales_query.where(SalesInvoice.invoice_date >= date_from)
        if date_to is not None:
            sales_query = sales_query.where(SalesInvoice.invoice_date <= date_to)
        if salesman_id is not None:
            sales_query = sales_query.where(SalesInvoice.salesman_id == salesman_id)
        sales_rows = (await self.session.execute(sales_query)).all()
        sales_by_salesman = {row.salesman_id: row.total_sales for row in sales_rows}

        returns_query = (
            select(
                SalesInvoice.salesman_id,
                func.sum(SalesReturn.subtotal).label("total_returns"),
            )
            .join(SalesInvoice, SalesReturn.invoice_id == SalesInvoice.id)
            .where(SalesInvoice.salesman_id.is_not(None))
            .group_by(SalesInvoice.salesman_id)
        )
        if date_from is not None:
            returns_query = returns_query.where(
                func.date(SalesReturn.created_at) >= date_from
            )
        if date_to is not None:
            returns_query = returns_query.where(
                func.date(SalesReturn.created_at) <= date_to
            )
        if salesman_id is not None:
            returns_query = returns_query.where(
                SalesInvoice.salesman_id == salesman_id
            )
        returns_rows = (await self.session.execute(returns_query)).all()
        returns_by_salesman = {
            row.salesman_id: row.total_returns for row in returns_rows
        }

        salesman_ids = set(sales_by_salesman) | set(returns_by_salesman)
        rows: list[CommissionRow] = []
        total_commission = Decimal("0")
        if salesman_ids:
            users_result = await self.session.execute(
                select(User).where(User.id.in_(salesman_ids))
            )
            users_by_id = {u.id: u for u in users_result.scalars().all()}
            for sid in sorted(salesman_ids):
                salesman = users_by_id.get(sid)
                if salesman is None:
                    continue
                total_sales = sales_by_salesman.get(sid, Decimal("0"))
                total_returns = returns_by_salesman.get(sid, Decimal("0"))
                net_sales = total_sales - total_returns
                commission_amount = (
                    net_sales * salesman.commission_rate / Decimal("100")
                ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                total_commission += commission_amount
                rows.append(
                    CommissionRow(
                        salesman_id=sid,
                        salesman_name=salesman.full_name,
                        total_sales=total_sales,
                        total_returns=total_returns,
                        net_sales=net_sales,
                        commission_rate=salesman.commission_rate,
                        commission_amount=commission_amount,
                    )
                )
        return CommissionReportOut(
            date_from=date_from,
            date_to=date_to,
            rows=rows,
            total_commission=total_commission,
        )
