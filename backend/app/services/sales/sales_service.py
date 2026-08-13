"""Sales business logic: customers, FEFO invoices, credit control, returns, receipts."""

from dataclasses import dataclass
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
from app.api.schemas.pagination import PageParams, paginate
from app.core import business_day
from app.core.exceptions import AppException
from app.core.permissions import has_permission
from app.domain.models.accounting import JournalEntry
from app.domain.models.delivery import (
    DeliveryStop,
    DeliveryTrip,
    StopStatus,
    TripStatus,
)
from app.domain.models.inventory import Product, ProductBatch
from app.domain.models.sales import (
    CreditResolution,
    CustomerCredit,
    ReturnStatus,
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
from app.services.sales.returns_query import (
    posted,
    returned_total_for,
    returned_totals,
)
from app.services.accounting.accounting_service import (
    ACCOUNTS_RECEIVABLE,
    COGS,
    DAMAGE_LOSS,
    INVENTORY,
    SALES_DISCOUNT,
    SALES_RETURNS,
    SALES_REVENUE,
    VAT,
    AccountingService,
    cash_or_bank,
)
from app.services.inventory.stock_service import StockService
from app.services.sales.offer_pricing import active_offers, apply_offer

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class StatementData:
    """A customer statement before anyone decides who is reading it.

    Domain objects and totals, no Pydantic. The staff API projects this into
    `CustomerStatementOut` and the customer portal into its own schemas, which show
    the same movements without the credit limit and price tier that belong to the
    office. Both read one set of numbers.
    """

    customer: Customer
    invoices: list[SalesInvoice]
    returns: list[SalesReturn]
    payments: list[CustomerPayment]
    total_invoices: Decimal
    total_returns: Decimal
    total_paid: Decimal
    balance: Decimal


class SalesService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.stock = StockService(session)
        self.accounting = AccountingService(session)

    # --- Customers ---
    async def get_customer(self, customer_id: int) -> Customer:
        """Fetch a customer or raise a 404 with an Arabic message for the UI."""
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
        """Register a customer. Names are unique so the same shop cannot be
        opened twice under two balances, and a named salesman must really be one."""
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
        """Amend a customer's details, price tier, credit limit or active flag."""
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
        """Customers this user may see.

        A salesman is scoped to their own round unless they hold
        `sales.all_customers`; the filter lives here rather than in the route so
        no caller can forget it.
        """
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
        """The unit price for a customer's tier — wholesale, half, or retail."""
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
                SalesReturn.customer_id == customer_id, posted()
            )
        )
        total_returns = returns.scalar_one()

        payments = await self.session.execute(
            select(func.coalesce(func.sum(CustomerPayment.amount), 0)).where(
                CustomerPayment.customer_id == customer_id
            )
        )
        total_payments = payments.scalar_one()

        # Credits already handed back in cash. Without this term the statement and
        # the ledger disagree: refunding posts receivables-debit / cash-credit, so
        # the ledger correctly shows nothing owed, while this formula — which knows
        # only invoices, returns and receipts — kept reporting the customer as a
        # creditor for money they had already been given. Found by refunding one and
        # watching the statement stay at -40.00.
        refunded = await self.session.execute(
            select(func.coalesce(func.sum(CustomerCredit.amount), 0)).where(
                CustomerCredit.customer_id == customer_id,
                CustomerCredit.resolution == CreditResolution.REFUNDED,
            )
        )
        total_refunded = refunded.scalar_one()

        return (
            customer.opening_balance
            + Decimal(str(total_invoices))
            - Decimal(str(paid_on_invoices))
            - Decimal(str(total_returns))
            - Decimal(str(total_payments))
            + Decimal(str(total_refunded))
        )

    # --- Sales invoices ---
    async def _build_lines(
        self,
        invoice: SalesInvoice,
        data: SalesInvoiceCreate,
        customer: Customer,
        price_overrides: dict[int, Decimal] | None = None,
        source_warehouse_id: int | None = None,
    ) -> tuple[Decimal, Decimal]:
        """FEFO-allocate the requested lines onto the invoice; returns (subtotal, cost_total).

        One input line becomes one invoice line per allocated batch. `price_overrides`
        (keyed by product_id) is for internal use only — e.g. honoring a quotation's
        frozen price on conversion — and is never accepted from the public API.

        `source_warehouse_id` overrides where the goods come from: a van sale draws
        on the salesman's own vehicle rather than the product's home warehouse.
        """
        # Take every row lock this invoice needs up front, in product-id order.
        # FEFO locks the batches it allocates from; acquiring those locks in the
        # order the salesman happened to type the lines would let two invoices
        # sharing two products deadlock against each other. See
        # StockService.lock_batches_in_order.
        to_lock: set[tuple[int, int]] = set()
        # One query for the whole invoice rather than one per line.
        offers = await active_offers(
            self.session, [line.product_id for line in data.lines]
        )

        for line in data.lines:
            product = await self.stock.get_active_product(line.product_id)
            if product.warehouse_id is not None or source_warehouse_id is not None:
                to_lock.add(
                    (product.id, source_warehouse_id or product.warehouse_id)
                )
        await self.stock.lock_batches_in_order(to_lock)

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
            # Precedence: an explicit override beats an offer, because a person
            # decided it; an offer beats the tier price, because the customer has
            # already been shown it.
            if price_overrides and product.id in price_overrides:
                unit_price = price_overrides[product.id]
            else:
                unit_price = apply_offer(
                    self.tier_price(product, customer.price_tier),
                    offers.get(product.id),
                )

            allocations = await self.stock.fefo_allocate(
                product.id, source_warehouse_id or product.warehouse_id, base_quantity
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
                        product_name=product.name,
                        unit_name=product.base_unit_name,
                        # Where the goods actually left from, taken from the batch
                        # rather than the product's home warehouse. A van sale
                        # draws on the vehicle, and recording the home warehouse
                        # instead mis-attributed every field sale to the main
                        # store — the stock moved correctly, the attribution lied.
                        # The batch is authoritative because FEFO already chose it
                        # from the right warehouse, and it stays correct even if a
                        # single line were ever filled from more than one place.
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

    @staticmethod
    def _resolve_discount(
        gross: Decimal, collectable_amount: Decimal | None
    ) -> Decimal:
        """Turn a requested collectable amount into a discount off the gross.

        `gross` is goods + tax. Charging less than that records the shortfall as
        a discount; charging more is rejected, since an invoice cannot collect
        more than it bills.
        """
        if collectable_amount is None:
            return Decimal("0")
        collectable = collectable_amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if collectable > gross:
            raise AppException(
                400,
                "المبلغ المطلوب تحصيله أكبر من إجمالي الفاتورة "
                f"({gross}); لا يمكن تحصيل أكثر من قيمة الفاتورة.",
            )
        return (gross - collectable).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

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

    async def _check_overdue_age(
        self, customer: Customer, data: SalesInvoiceCreate, user: User
    ) -> None:
        """Refuse a credit sale to someone sitting on old debt.

        The credit limit cannot do this job. It measures how *much* is owed and has
        nothing to say about how long — so on this book of business a shop 367 days
        overdue for 10,711 passes a 25,000 limit without comment, and was in fact sold
        to on credit two days ago. Every one of the worst debtors is under their limit.

        Off by default (`credit_block_after_days = 0`), because turning it on stops
        sales and that is the owner's decision. Overridable by the same permission and
        the same flag as the limit: a manager approving a credit sale is approving it
        for whichever reason it was blocked, and inventing a second override would
        mean two ways to say the same yes.
        """
        from app.services.settings.settings_service import SettingsService

        threshold = (
            await SettingsService(self.session).get_company_settings()
        ).credit_block_after_days
        if threshold <= 0:
            return

        from app.services.sales.collections_service import CollectionsService

        age = await CollectionsService(self.session).overdue_debt_days(customer.id)
        if age <= threshold:
            return

        if data.credit_override and has_permission(user, "sales.credit_override"):
            return
        raise AppException(
            400,
            f"لدى العميل دين عمره {age} يوماً (الحد المسموح {threshold} يوماً)؛ "
            "البيع الآجل موقوف حتى السداد أو بموافقة المدير.",
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
        # A discount is a debit to contra-revenue, so the entry still balances:
        # receivable + discount == goods + tax.
        items = [
            (ACCOUNTS_RECEIVABLE, invoice.total, Decimal("0")),
            (SALES_REVENUE, Decimal("0"), subtotal),
            (VAT, Decimal("0"), invoice.vat_amount),
        ]
        if invoice.discount_amount > 0:
            items.insert(1, (SALES_DISCOUNT, invoice.discount_amount, Decimal("0")))
        await self.accounting.add_entry_no_commit(
            entry_date=invoice.invoice_date,
            description=f"فاتورة مبيعات رقم {invoice.id} للعميل ({customer.name})",
            items=items,
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
        source_warehouse_id: int | None = None,
        client_uuid: str | None = None,
    ) -> SalesInvoice:
        """Post a sales invoice: FEFO stock deduction, credit-limit check, one transaction.

        `source_warehouse_id` sells from a specific warehouse (a salesman's van);
        `client_uuid` carries the field app's own identifier so replaying a sync
        cannot create the invoice twice.
        """
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
            discount_amount=Decimal("0"),
            total=Decimal("0"),
            notes=data.notes,
            created_by=user.id,
            client_uuid=client_uuid,
        )

        subtotal, cost_total = await self._build_lines(
            invoice, data, customer, price_overrides, source_warehouse_id
        )
        invoice.warehouse_id = self._resolve_invoice_warehouse(invoice)

        invoice.subtotal = subtotal
        invoice.vat_amount = self._apply_taxes(invoice, tax_rates, subtotal)
        gross = subtotal + invoice.vat_amount
        invoice.discount_amount = self._resolve_discount(
            gross, data.collectable_amount
        )
        invoice.total = gross - invoice.discount_amount

        if data.payment_method == SalesPaymentMethod.CREDIT:
            balance = await self.customer_balance(customer.id)
            self._check_credit_limit(customer, balance, invoice.total, data, user)
            await self._check_overdue_age(customer, data, user)

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
        self, data: SalesQuotationCreate, user: User, client_uuid: str | None = None
    ) -> SalesQuotation:
        """Price a quote for a customer — no stock deduction or accounting effect.

        `client_uuid` is set when the quote is an order captured offline in the
        field, so replaying the sync returns the existing one.
        """
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
            client_uuid=client_uuid,
        )
        subtotal = await self._build_quotation_lines(quotation, data, customer)
        quotation.subtotal = subtotal
        quotation.vat_amount = self._apply_quotation_taxes(quotation, tax_rates, subtotal)
        quotation.total = subtotal + quotation.vat_amount

        self.session.add(quotation)
        await self.session.commit()
        return await self.get_quotation(quotation.id)

    async def get_quotation(self, quotation_id: int) -> SalesQuotation:
        """Fetch a quotation with its lines and taxes, or raise a 404."""
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
        """Quotations visible to this user, newest first, optionally per customer."""
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
        """Withdraw a quotation that will not be converted.

        Cancelling never touches stock: a quotation is a price commitment and
        moves nothing until it becomes an invoice.
        """
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
            .where(SalesReturn.invoice_id == invoice_id, posted())
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
            batch = await self.stock.get_batch_locked(line.batch_id)
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
        invoice.discount_amount = Decimal("0")
        invoice.total = Decimal("0")
        invoice.paid_amount = Decimal("0")

        subtotal, cost_total = await self._build_lines(invoice, data, customer)
        invoice.warehouse_id = self._resolve_invoice_warehouse(invoice)
        vat_amount = self._apply_taxes(invoice, tax_rates, subtotal)
        gross = subtotal + vat_amount
        discount = self._resolve_discount(gross, data.collectable_amount)
        total = gross - discount

        if data.payment_method == SalesPaymentMethod.CREDIT:
            # The zeroed totals were flushed, so the balance excludes this invoice.
            balance = await self.customer_balance(customer.id)
            self._check_credit_limit(customer, balance, total, data, user)

        invoice.subtotal = subtotal
        invoice.vat_amount = vat_amount
        invoice.discount_amount = discount
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
        """Set `returned_total` on each invoice for read models.

        Delegated to services/sales/returns_query — this was a fourth private copy of
        the same per-invoice sum, found by the test that forbids exactly that.
        """
        if not invoices:
            return
        totals = await returned_totals(self.session, [i.id for i in invoices])
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
            .where(SalesReturn.invoice_id == invoice_id, posted())
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
            batch = await self.stock.get_batch_locked(line.batch_id)
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


    async def _returned_total_for(self, invoice_id: int) -> Decimal:
        """Everything credited back against one invoice. See services/sales/returns_query."""
        return await returned_total_for(self.session, invoice_id)

    async def list_customer_credits(
        self, resolution: CreditResolution | None = None
    ) -> list[CustomerCredit]:
        """Credits owed back to customers, newest first; pending ones need a decision."""
        stmt = select(CustomerCredit).order_by(CustomerCredit.id.desc())
        if resolution is not None:
            stmt = stmt.where(CustomerCredit.resolution == resolution)
        return list((await self.session.execute(stmt)).scalars().all())

    async def resolve_customer_credit(
        self,
        credit_id: int,
        resolution: CreditResolution,
        user: User,
        notes: str | None = None,
    ) -> CustomerCredit:
        """Settle a credit as a cash refund or as a balance left on account.

        Crediting posts nothing, and that is correct rather than lazy: the invoice
        debited receivables, the payment credited them, and the return credited them
        again, so the account already carries what is owed. Leaving it on account is
        recognising a balance that exists, not creating one.

        A cash refund does move money, and it is not moved here — the till moves it,
        so it goes through the same cash movement and day-close as every other
        disbursement. This marks the decision; `CashierService.refund_customer_credit`
        pays it.
        """
        credit = await self.session.get(CustomerCredit, credit_id)
        if credit is None:
            raise AppException(404, "المبلغ المستحقّ للعميل غير موجود.")
        if credit.resolution is not CreditResolution.PENDING:
            # Resolved once, never twice — otherwise the same 30 is refunded and
            # then also left on account.
            raise AppException(
                400,
                "تمت معالجة هذا المبلغ من قبل ("
                + {
                    CreditResolution.AWAITING_REFUND: "بانتظار الصرف من الصندوق",
                    CreditResolution.REFUNDED: "رُدَّ نقداً",
                    CreditResolution.CREDITED: "رصيد في الحساب",
                }[credit.resolution]
                + ").",
            )
        if resolution not in (CreditResolution.REFUNDED, CreditResolution.CREDITED):
            raise AppException(400, "اختر إمّا الردّ النقدي أو الترك كرصيد في الحساب.")

        # Choosing a refund records the decision and queues it; the till pays it.
        credit.resolution = (
            CreditResolution.AWAITING_REFUND
            if resolution is CreditResolution.REFUNDED
            else resolution
        )
        credit.notes = notes
        credit.resolved_at = datetime.now(timezone.utc)
        credit.resolved_by = user.id
        await self.session.commit()
        await self.session.refresh(credit)
        return credit

    async def get_invoice(self, invoice_id: int) -> SalesInvoice:
        """Fetch an invoice with its lines and applied taxes, or raise a 404."""
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

    async def _invoices_for(
        self,
        customer_id: int | None,
        only_salesman_id: int | None,
        page: PageParams | None = None,
    ) -> tuple[list[SalesInvoice], int]:
        """Invoices newest first, optionally narrowed to one customer or salesman.

        The scoping is expressed as a salesman id rather than a user so callers with
        no staff user — the customer portal — can reach the same query instead of
        writing a near-identical one that forgets `_attach_return_totals`.

        `page=None` means every matching invoice, and it is not an oversight: the
        statement adds invoices up into a balance, and a balance computed from the
        first fifty is a wrong number that looks like a right one. Screens pass a
        page; arithmetic does not. The unpaged path stays bounded by one customer's
        own history, which is a few dozen rows, not the whole book.
        """
        stmt = (
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines), selectinload(SalesInvoice.taxes)
            )
            .order_by(SalesInvoice.id.desc())
        )
        if only_salesman_id is not None:
            stmt = stmt.where(SalesInvoice.salesman_id == only_salesman_id)
        if customer_id is not None:
            stmt = stmt.where(SalesInvoice.customer_id == customer_id)

        if page is None:
            result = await self.session.execute(stmt)
            invoices = list(result.scalars().unique().all())
            total = len(invoices)
        else:
            invoices, total = await paginate(self.session, stmt, page)
        await self._attach_return_totals(invoices)
        return invoices, total

    async def list_invoices(
        self,
        user: User,
        customer_id: int | None = None,
        page: PageParams | None = None,
    ) -> tuple[list[SalesInvoice], int]:
        """Invoices visible to this user, newest first, optionally per customer."""
        return await self._invoices_for(
            customer_id,
            only_salesman_id=(
                None if has_permission(user, "sales.all_customers") else user.id
            ),
            page=page,
        )

    # --- Returns ---
    async def _returned_discount_share(
        self, invoice: SalesInvoice, this_return_subtotal: Decimal
    ) -> Decimal:
        """Portion of the invoice's discount that belongs to the goods being returned.

        Allocated on the running total — the share owed once this return is
        included, minus what earlier returns already took — so a sequence of
        partial returns always sums to exactly the invoice's discount and never
        drifts by rounding.
        """
        if invoice.discount_amount <= 0 or invoice.subtotal <= 0:
            return Decimal("0")

        prior = await self.session.execute(
            select(
                func.coalesce(func.sum(SalesReturn.subtotal), 0),
                func.coalesce(func.sum(SalesReturn.discount_amount), 0),
            ).where(SalesReturn.invoice_id == invoice.id, posted())
        )
        prior_subtotal, prior_discount = prior.one()
        prior_subtotal = Decimal(str(prior_subtotal))
        prior_discount = Decimal(str(prior_discount))

        cumulative_subtotal = prior_subtotal + this_return_subtotal
        target = (
            invoice.discount_amount * cumulative_subtotal / invoice.subtotal
        ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        # Never hand back more discount than the invoice granted.
        target = min(target, invoice.discount_amount)
        return max(target - prior_discount, Decimal("0"))

    async def create_return(self, data: SalesReturnCreate, user: User) -> SalesReturn:
        """Post a sales return; resellable goods go back to their original batches."""
        # Lock the invoice row for the whole of this return.
        #
        # Everything below rests on "how much of this invoice has already been sent
        # back", read a few lines down and then compared against what each line sold.
        # Read without a lock, two returns arriving together each saw nothing returned
        # yet and both passed: proved by firing 6 and 6 at a line of 10, which credited
        # 120 against a 100 invoice and put 12 units back from a sale of 10. Money and
        # stock created out of nothing.
        #
        # Locking the invoice — not the batches, which are locked separately — is what
        # serialises the *decision*. The batch lock added earlier protects the
        # quantities; this protects the entitlement to return them at all.
        locked = await self.session.execute(
            select(SalesInvoice.id)
            .where(SalesInvoice.id == data.invoice_id)
            .with_for_update()
        )
        if locked.scalar_one_or_none() is None:
            raise AppException(404, "فاتورة المبيعات غير موجودة.")

        invoice = await self.get_invoice(data.invoice_id)
        customer = await self.get_customer(invoice.customer_id)
        self.ensure_customer_access(user, customer)

        # A return before the goods leave reduces the picking documents, so the
        # warehouse hands over the right quantity. Once the trip has left, those
        # documents are printed and on the seat beside the driver, and no amount of
        # netting reaches him — he is carrying the original count. Recording the
        # return anyway would credit the customer for goods about to be handed to
        # them, which is the give-away this whole change exists to stop.
        #
        # So it is refused, with the instruction that makes it correct: take the
        # delivery in full, then record the return. That turns it into the
        # after-delivery case, where the goods really do come back and everything
        # already works.
        in_transit = await self.session.execute(
            select(DeliveryTrip.id)
            .join(DeliveryStop, DeliveryStop.trip_id == DeliveryTrip.id)
            .where(
                DeliveryStop.invoice_id == invoice.id,
                DeliveryStop.status == StopStatus.PENDING,
                DeliveryTrip.status == TripStatus.IN_TRANSIT,
            )
            .limit(1)
        )
        if in_transit.scalar_one_or_none() is not None:
            raise AppException(
                400,
                "بضاعة هذه الفاتورة على الطريق مع السائق؛ لا يمكن تسجيل مرتجع الآن. "
                "استلم الكمية كاملة ثم سجّل المرتجع بعد التسليم.",
            )

        # Quantities already returned against this invoice, per batch.
        returned_result = await self.session.execute(
            select(
                SalesReturnLine.batch_id,
                func.coalesce(func.sum(SalesReturnLine.quantity), 0),
            )
            .join(SalesReturn, SalesReturnLine.return_id == SalesReturn.id)
            .where(SalesReturn.invoice_id == invoice.id, posted())
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
                    batch = await self.stock.get_batch_locked(inv_line.batch_id)
                    if batch is not None:
                        batch.quantity += take

                line_total = (take * inv_line.unit_price).quantize(
                    TWO_PLACES, rounding=ROUND_HALF_UP
                )
                sales_return.lines.append(
                    SalesReturnLine(
                        product_id=line.product_id,
                        # From the invoice line: a credit note describes the goods as
                        # the invoice it reverses described them.
                        product_name=inv_line.product_name,
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
        # The customer never paid the discounted portion, so returning goods must
        # not refund it. Share it across returns in proportion to value returned.
        #
        # Computed from the running total rather than this return alone: rounding
        # each return independently could drift, whereas taking
        # (target so far - already allocated) guarantees that returning
        # everything credits exactly what the invoice charged.
        sales_return.discount_amount = await self._returned_discount_share(
            invoice, subtotal
        )
        sales_return.total = (
            subtotal + sales_return.vat_amount - sales_return.discount_amount
        )

        self.session.add(sales_return)
        await self.session.flush()

        # Automatic double-entry: reverse revenue + VAT against the customer's
        # receivable. The discount share is given back to contra-revenue, since
        # that part of the sale was never billed and so is not being credited.
        return_items = [
            (SALES_RETURNS, subtotal, Decimal("0")),
            (VAT, sales_return.vat_amount, Decimal("0")),
            (ACCOUNTS_RECEIVABLE, Decimal("0"), sales_return.total),
        ]
        if sales_return.discount_amount > 0:
            return_items.append(
                (SALES_DISCOUNT, Decimal("0"), sales_return.discount_amount)
            )
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"مرتجع مبيعات رقم {sales_return.id} عن الفاتورة رقم {invoice.id}",
            items=return_items,
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

        # If the return leaves this invoice paid for more than it is now worth, the
        # difference is money owed back to the customer. Record it as a pending
        # decision rather than leaving it as a negative number on a statement: that
        # is how two credit balances sat unnoticed in the dev database, and an
        # obligation nobody is prompted about is an obligation nobody honours.
        #
        # Whether to hand the cash over or leave it on account is a human call, so
        # nothing is chosen here.
        returned_so_far = await self._returned_total_for(invoice.id)
        overpaid = (invoice.paid_amount - (invoice.total - returned_so_far)).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        # Nothing left to deliver? Take the stop off the trip. A driver sent to a
        # customer with an empty picking line is a wasted journey and an invitation
        # to hand over something to justify the visit.
        if await self._returned_total_for(invoice.id) >= invoice.total:
            dropped = await self.session.execute(
                select(DeliveryStop)
                .join(DeliveryTrip, DeliveryTrip.id == DeliveryStop.trip_id)
                .where(
                    DeliveryStop.invoice_id == invoice.id,
                    DeliveryStop.status == StopStatus.PENDING,
                    DeliveryTrip.status == TripStatus.PLANNED,
                )
            )
            for stop in dropped.scalars().all():
                await self.session.delete(stop)

        credit: CustomerCredit | None = None
        if overpaid > 0:
            credit = CustomerCredit(
                customer_id=customer.id,
                invoice_id=invoice.id,
                return_id=sales_return.id,
                amount=overpaid,
                resolution=CreditResolution.PENDING,
            )
            self.session.add(credit)

        await self.session.commit()
        result = await self.session.execute(
            select(SalesReturn)
            .options(selectinload(SalesReturn.lines))
            .where(SalesReturn.id == sales_return.id)
        )
        saved = result.scalar_one()
        # Carry the pending decision back to the caller so the screen can ask.
        if credit is not None:
            await self.session.refresh(credit)
            saved.pending_credit_id = credit.id
            saved.pending_credit_amount = credit.amount
        return saved

    async def cancel_return(
        self, return_id: int, user: User, cancel_reason: str | None = None
    ) -> SalesReturn:
        """Undo a credit note entered by mistake — stock, ledger and credit together.

        Kept and marked cancelled rather than deleted: a credit note that simply
        vanishes leaves a customer statement nobody can explain, and the mistake is
        itself part of the record.

        Three things it refuses, each for a different reason:

        * **Already cancelled** — reversing twice would take the goods out twice.
        * **The refund has been paid** — the customer is holding the cash. Undoing the
          credit note while they keep the money would quietly turn a correction into a
          debt they were never told about. The refund has to be dealt with first, by a
          person, which is deliberately not something this method will decide.
        * **The goods have since been sold** — a resellable return put them back on the
          shelf and they may have left again. Taking out stock that is no longer there
          is exactly the negative-quantity case the database now rejects, so it is
          caught here with an explanation instead of an integrity error.
        """
        # Lock the credit note before reading its status. Two clerks pressing cancel
        # at the same moment would otherwise both see "posted", and the goods would
        # come out of stock twice — the same lost update the batch locks closed
        # elsewhere, one level up.
        locked = await self.session.execute(
            select(SalesReturn.id).where(SalesReturn.id == return_id).with_for_update()
        )
        if locked.scalar_one_or_none() is None:
            raise AppException(404, "مرتجع المبيعات غير موجود.")

        sales_return = await self.get_return(return_id)
        if sales_return.status is ReturnStatus.CANCELLED:
            raise AppException(400, "هذا المرتجع ملغى من قبل.")

        customer = await self.get_customer(sales_return.customer_id)
        self.ensure_customer_access(user, customer)

        credit = (
            await self.session.execute(
                select(CustomerCredit).where(CustomerCredit.return_id == sales_return.id)
            )
        ).scalar_one_or_none()
        if credit is not None and credit.resolution is CreditResolution.REFUNDED:
            raise AppException(
                400,
                f"تم ردّ مبلغ {credit.amount} للعميل نقداً عن هذا المرتجع؛ "
                "لا يمكن إلغاؤه قبل استرجاع المبلغ من العميل وتسجيل ذلك.",
            )

        # Take the goods back out, if they were ever put back.
        cost_total = Decimal("0")
        if sales_return.reason is ReturnReason.RESELLABLE:
            for line in sorted(sales_return.lines, key=lambda ln: ln.batch_id or 0):
                batch = await self.stock.get_batch_locked(line.batch_id)
                if batch is None:
                    raise AppException(400, "تشغيلة المرتجع غير موجودة.")
                if batch.quantity < line.quantity:
                    raise AppException(
                        400,
                        f"لا يمكن إلغاء المرتجع: المتوفر من التشغيلة "
                        f"({batch.batch_number}) هو {batch.quantity} "
                        f"والمطلوب سحبه {line.quantity} — بِيعت البضاعة بعد إرجاعها.",
                    )
                batch.quantity -= line.quantity
        # A return line records what the customer was charged, not what the goods cost
        # us — the cost lives on the invoice line it came from, matched by batch, which
        # is exactly how create_return valued it in the first place. Reversing has to
        # read it from the same place, or the COGS put back differs from the COGS taken
        # out and inventory drifts by the margin.
        invoice = await self.get_invoice(sales_return.invoice_id)
        unit_cost_by_batch = {
            inv_line.batch_id: inv_line.unit_cost
            for inv_line in invoice.lines
            if inv_line.unit_cost is not None
        }
        for line in sales_return.lines:
            unit_cost = unit_cost_by_batch.get(line.batch_id)
            if unit_cost is not None:
                cost_total += (line.quantity * unit_cost).quantize(
                    TWO_PLACES, rounding=ROUND_HALF_UP
                )

        # Mirror of the original postings, in the opposite direction.
        reverse_items = [
            (SALES_RETURNS, Decimal("0"), sales_return.subtotal),
            (VAT, Decimal("0"), sales_return.vat_amount),
            (ACCOUNTS_RECEIVABLE, sales_return.total, Decimal("0")),
        ]
        if sales_return.discount_amount > 0:
            reverse_items.append(
                (SALES_DISCOUNT, sales_return.discount_amount, Decimal("0"))
            )
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"إلغاء مرتجع المبيعات رقم {sales_return.id}",
            items=reverse_items,
            reference_type="sales_return_cancel",
            reference_id=sales_return.id,
            created_by=user.id,
        )
        if cost_total > 0:
            credited_account = (
                INVENTORY
                if sales_return.reason is ReturnReason.RESELLABLE
                else DAMAGE_LOSS
            )
            await self.accounting.add_entry_no_commit(
                entry_date=date.today(),
                description=f"إلغاء تكلفة مرتجع المبيعات رقم {sales_return.id}",
                items=[
                    (COGS, cost_total, Decimal("0")),
                    (credited_account, Decimal("0"), cost_total),
                ],
                reference_type="sales_return_cancel",
                reference_id=sales_return.id,
                created_by=user.id,
            )

        # An unpaid credit is void with the note that caused it.
        if credit is not None:
            await self.session.delete(credit)

        sales_return.status = ReturnStatus.CANCELLED
        sales_return.cancelled_at = datetime.now(timezone.utc)
        sales_return.cancelled_by = user.id
        sales_return.cancel_reason = cancel_reason
        await self.session.commit()
        return await self.get_return(return_id)

    async def get_return(self, return_id: int) -> SalesReturn:
        result = await self.session.execute(
            select(SalesReturn)
            .options(selectinload(SalesReturn.lines))
            .where(SalesReturn.id == return_id)
        )
        sales_return = result.scalar_one_or_none()
        if sales_return is None:
            raise AppException(404, "مرتجع المبيعات غير موجود.")
        return sales_return

    async def list_returns(
        self, user: User, invoice_id: int | None = None
    ) -> list[SalesReturn]:
        """Sales returns, newest first, optionally limited to one invoice."""
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
        """Record a receipt against a customer's balance (سند قبض).

        Refuses more than is outstanding, so an overpayment cannot quietly turn
        into a negative balance that nobody reconciles.
        """
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

    async def statement_data(
        self, customer_id: int, user: User | None = None
    ) -> "StatementData":
        """The movements and totals behind a customer statement, unprojected.

        Split out from `customer_statement` so the customer portal can serve the same
        statement without borrowing the staff schemas, which carry the credit limit
        and price tier. A second gathering of the same rows would be a second
        definition of what a customer owes, and the two would drift — this method
        already carries a scar from exactly that.

        `user` is optional because the portal has no staff user to check against;
        there the caller is the customer themselves and scoping comes from the token.
        """
        customer = await self.get_customer(customer_id)
        if user is not None:
            self.ensure_customer_access(user, customer)

        # Unpaged on purpose — see `_invoices_for`. The totals below are sums over
        # every invoice this customer has, not over a screenful of them.
        if user is None:
            invoices, _ = await self._invoices_for(customer_id, only_salesman_id=None)
        else:
            invoices, _ = await self.list_invoices(user, customer_id)
        returns_result = await self.session.execute(
            select(SalesReturn)
            .options(selectinload(SalesReturn.lines))
            # The statement's own balance excludes cancelled notes, so its lines have
            # to as well — otherwise the movements listed do not add up to the total
            # printed underneath them, which is the one thing a statement must do.
            .where(SalesReturn.customer_id == customer_id, posted())
            .order_by(SalesReturn.id)
        )
        returns = list(returns_result.scalars().all())
        payments_result = await self.session.execute(
            select(CustomerPayment)
            .where(CustomerPayment.customer_id == customer_id)
            .order_by(CustomerPayment.id)
        )
        payments = list(payments_result.scalars().all())

        return StatementData(
            customer=customer,
            invoices=invoices,
            returns=returns,
            payments=payments,
            total_invoices=sum((i.total for i in invoices), Decimal("0")),
            total_returns=sum((r.total for r in returns), Decimal("0")),
            total_paid=sum((i.paid_amount for i in invoices), Decimal("0"))
            + sum((p.amount for p in payments), Decimal("0")),
            # Delegated rather than recomputed. This used to carry its own copy of
            # the formula, so adding refunds to `customer_balance` fixed the number
            # in one place and left the statement — the document actually handed to
            # the customer — still wrong. One balance, one definition.
            balance=await self.customer_balance(customer_id),
        )

    async def customer_statement(
        self, customer_id: int, user: User
    ) -> CustomerStatementOut:
        """Everything owed and paid for one customer: invoices, returns, receipts
        and the resulting balance — the document handed over when settling up."""
        from app.api.schemas.sales import (
            CustomerOut,
            CustomerPaymentOut,
            SalesInvoiceOut,
            SalesReturnOut,
        )

        data = await self.statement_data(customer_id, user)
        return CustomerStatementOut(
            customer=CustomerOut.model_validate(data.customer),
            opening_balance=data.customer.opening_balance,
            total_invoices=data.total_invoices,
            total_returns=data.total_returns,
            total_paid=data.total_paid,
            balance=data.balance,
            invoices=[SalesInvoiceOut.model_validate(i) for i in data.invoices],
            returns=[SalesReturnOut.model_validate(r) for r in data.returns],
            payments=[CustomerPaymentOut.model_validate(p) for p in data.payments],
        )

    async def _company_timezone(self) -> str | None:
        """The company's configured timezone, for turning report dates into windows."""
        from app.services.settings.settings_service import SettingsService

        company = await SettingsService(self.session).get_company_settings()
        return company.timezone

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
            .where(SalesInvoice.salesman_id.is_not(None), posted())
            .group_by(SalesInvoice.salesman_id)
        )
        # The company's day, not UTC's. `func.date()` truncates in UTC, so a credit
        # note raised at 01:00 local was landing in the previous day's commission.
        returns_from, returns_to = business_day.utc_window(
            date_from, date_to, (await self._company_timezone())
        )
        if returns_from is not None:
            returns_query = returns_query.where(SalesReturn.created_at >= returns_from)
        if returns_to is not None:
            returns_query = returns_query.where(SalesReturn.created_at < returns_to)
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
