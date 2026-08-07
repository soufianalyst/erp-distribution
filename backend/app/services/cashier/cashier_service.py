"""Cashier business logic: the till handles money IN (sales collections) and
money OUT (purchase invoice and expense disbursements).

Business rule: credit sales/purchases settle later through the customer's or
supplier's account and never appear here. Cash/card documents sit here — price
visible — until the cashier actually moves the money. A document may be settled
in installments (partial payments); it only releases (sales: to delivery/pickup)
once the full amount has moved.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.cashier import (
    CashierDailySummaryOut,
    PendingPayableOut,
)
from app.core.exceptions import AppException
from app.domain.models.cashier import CashMovement
from app.domain.models.expenses import Expense, ExpenseCategory
from app.domain.models.purchases import PurchaseInvoice, PurchasePaymentMethod, Supplier
from app.domain.models.sales import (
    CreditResolution,
    Customer,
    CustomerCredit,
    SalesInvoice,
    SalesPaymentMethod,
    SalesReturn,
)
from app.domain.models.user import User
from app.services.accounting.accounting_service import (
    ACCOUNTS_PAYABLE,
    ACCOUNTS_RECEIVABLE,
    AccountingService,
    cash_or_bank,
)

TWO_PLACES = Decimal("0.01")


class CashierService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounting = AccountingService(session)

    # --- Sales collections (money IN) ---
    async def _get_invoice(self, invoice_id: int) -> SalesInvoice:
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
        return invoice

    async def returned_totals(self, invoice_ids: list[int]) -> dict[int, Decimal]:
        """How much has been credited back per invoice via sales returns.

        Read live rather than stored on the invoice, because the invoice is an
        issued document and must not be rewritten. Its `total` is what was billed;
        what is still *owed* is a derived figure, and this is the missing term.
        """
        if not invoice_ids:
            return {}
        result = await self.session.execute(
            select(
                SalesReturn.invoice_id,
                func.coalesce(func.sum(SalesReturn.total), 0),
            )
            .where(SalesReturn.invoice_id.in_(invoice_ids))
            .group_by(SalesReturn.invoice_id)
        )
        return {
            invoice_id: Decimal(str(total)) for invoice_id, total in result.all()
        }

    async def net_due(self, invoice: SalesInvoice) -> Decimal:
        """What the customer still owes on this invoice, after returns.

            due = billed − credited back − already paid

        This is the whole of the returns fix. An invoice for 100 with 30 returned
        must ask the cashier for 70, and previously asked for 100: `remaining` was
        `total - paid_amount` with no term for returns at all. The consequences were
        not cosmetic — collecting the correct 70 never satisfied
        `paid_amount >= total`, so the invoice was never confirmed, never left the
        cashier's queue, and never became deliverable. The only way to close it was
        to charge the customer 30 they did not owe, which is exactly how the
        negative customer balances in the dev database were produced.

        Deriving the figure rather than editing the invoice keeps the document, its
        posted journal entries and the filed tax period all intact — and the
        customer statement already nets returns, so reducing `invoice.total` would
        have subtracted them twice.
        """
        returned = (await self.returned_totals([invoice.id])).get(
            invoice.id, Decimal("0")
        )
        return (invoice.total - returned - invoice.paid_amount).quantize(TWO_PLACES)

    async def list_pending_invoices(self) -> list[SalesInvoice]:
        """Cash/card sales invoices awaiting (full) collection at the register.

        Anything already settled net of returns is filtered out here as well as by
        the confirmation flag, so an invoice returned in full stops being asked for
        even if nobody ever collected a riyal against it.
        """
        result = await self.session.execute(
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines), selectinload(SalesInvoice.taxes)
            )
            .where(
                SalesInvoice.payment_method.in_(
                    [SalesPaymentMethod.CASH, SalesPaymentMethod.CARD]
                ),
                SalesInvoice.payment_confirmed_at.is_(None),
            )
            .order_by(SalesInvoice.id)
        )
        invoices = list(result.scalars().all())
        returned = await self.returned_totals([i.id for i in invoices])
        pending = []
        for invoice in invoices:
            credited = returned.get(invoice.id, Decimal("0"))
            # Expose the net so the till shows what to actually take.
            invoice.returned_total = credited
            invoice.amount_due = (
                invoice.total - credited - invoice.paid_amount
            ).quantize(TWO_PLACES)
            if invoice.amount_due > 0:
                pending.append(invoice)
        return pending

    async def collect_payment(
        self, invoice_id: int, amount: Decimal, user: User
    ) -> SalesInvoice:
        """Cashier action: record a cash/card collection (full or partial)."""
        invoice = await self._get_invoice(invoice_id)
        if invoice.payment_method == SalesPaymentMethod.CREDIT:
            raise AppException(
                400, "فواتير الحساب الآجل تُحصّل عبر الحسابات وليس الصندوق."
            )
        if invoice.payment_confirmed_at is not None:
            raise AppException(400, "تم تحصيل قيمة هذه الفاتورة بالكامل من قبل.")

        returned = (await self.returned_totals([invoice.id])).get(
            invoice.id, Decimal("0")
        )
        net_billed = (invoice.total - returned).quantize(TWO_PLACES)
        remaining = (net_billed - invoice.paid_amount).quantize(TWO_PLACES)
        if remaining <= 0:
            # Fully returned, or already settled net of returns. Nothing is owed, so
            # asking for money would be wrong; the caller is told rather than
            # silently accepted.
            raise AppException(
                400,
                f"لا يوجد مبلغ مستحقّ على هذه الفاتورة "
                f"(الإجمالي {invoice.total}، المرتجعات {returned}، "
                f"المحصَّل {invoice.paid_amount}).",
            )
        if amount > remaining:
            raise AppException(
                400,
                f"المبلغ المدخل ({amount}) أكبر من المتبقي على الفاتورة ({remaining})."
                + (
                    f" الإجمالي {invoice.total} ناقص مرتجعات {returned}."
                    if returned > 0
                    else ""
                ),
            )

        customer = await self.session.get(Customer, invoice.customer_id)

        invoice.paid_amount = invoice.paid_amount + amount
        # Settled against what is actually owed, not what was originally billed.
        fully_collected = invoice.paid_amount >= net_billed
        if fully_collected:
            invoice.payment_confirmed_at = datetime.now(timezone.utc)
            invoice.payment_confirmed_by = user.id

        self.session.add(
            CashMovement(
                direction="in",
                reference_type="sales_invoice",
                reference_id=invoice.id,
                party_id=invoice.customer_id,
                amount=amount,
                method=invoice.payment_method.value,
                collected_by=user.id,
            )
        )

        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=(
                f"تحصيل صندوق {'(كامل)' if fully_collected else '(جزئي)'} "
                f"لفاتورة مبيعات رقم {invoice.id} من العميل "
                f"({customer.name if customer else invoice.customer_id})"
            ),
            items=[
                (cash_or_bank(invoice.payment_method.value), amount, Decimal("0")),
                (ACCOUNTS_RECEIVABLE, Decimal("0"), amount),
            ],
            reference_type="sales_invoice_payment",
            reference_id=invoice.id,
            created_by=user.id,
        )

        await self.session.commit()
        return await self._get_invoice(invoice.id)

    # --- Purchase invoices & expenses (money OUT) ---
    async def _get_purchase_invoice(self, invoice_id: int) -> PurchaseInvoice:
        result = await self.session.execute(
            select(PurchaseInvoice)
            .options(
                selectinload(PurchaseInvoice.lines),
                selectinload(PurchaseInvoice.taxes),
            )
            .where(PurchaseInvoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise AppException(404, "فاتورة الشراء غير موجودة.")
        return invoice

    async def pay_purchase_invoice(
        self, invoice_id: int, amount: Decimal, user: User
    ) -> PurchaseInvoice:
        """Cashier action: pay a supplier out of the register (full or partial)."""
        invoice = await self._get_purchase_invoice(invoice_id)
        if invoice.payment_method == PurchasePaymentMethod.CREDIT:
            raise AppException(
                400, "فواتير الشراء الآجلة تُسدد عبر كشف حساب المورد وليس الصندوق."
            )
        if invoice.payment_confirmed_at is not None:
            raise AppException(400, "تم سداد قيمة هذه الفاتورة بالكامل من قبل.")

        remaining = (invoice.total - invoice.paid_amount).quantize(TWO_PLACES)
        if amount > remaining:
            raise AppException(
                400,
                f"المبلغ المدخل ({amount}) أكبر من المتبقي على الفاتورة ({remaining}).",
            )

        supplier = await self.session.get(Supplier, invoice.supplier_id)

        invoice.paid_amount = invoice.paid_amount + amount
        fully_paid = invoice.paid_amount >= invoice.total
        if fully_paid:
            invoice.payment_confirmed_at = datetime.now(timezone.utc)
            invoice.payment_confirmed_by = user.id

        self.session.add(
            CashMovement(
                direction="out",
                reference_type="purchase_invoice",
                reference_id=invoice.id,
                party_id=invoice.supplier_id,
                amount=amount,
                method=invoice.payment_method.value,
                collected_by=user.id,
            )
        )

        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=(
                f"سداد صندوق {'(كامل)' if fully_paid else '(جزئي)'} "
                f"لفاتورة شراء رقم {invoice.id} للمورد "
                f"({supplier.name if supplier else invoice.supplier_id})"
            ),
            items=[
                (ACCOUNTS_PAYABLE, amount, Decimal("0")),
                (cash_or_bank(invoice.payment_method.value), Decimal("0"), amount),
            ],
            reference_type="purchase_invoice_payment",
            reference_id=invoice.id,
            created_by=user.id,
        )

        await self.session.commit()
        return await self._get_purchase_invoice(invoice.id)

    async def pay_expense(self, expense_id: int, amount: Decimal, user: User) -> Expense:
        """Cashier action: disburse an expense out of the register (full or partial)."""
        expense = await self.session.get(Expense, expense_id)
        if expense is None:
            raise AppException(404, "المصروف غير موجود.")
        if expense.payment_confirmed_at is not None:
            raise AppException(400, "تم سداد قيمة هذا المصروف بالكامل من قبل.")

        remaining = (expense.amount - expense.paid_amount).quantize(TWO_PLACES)
        if amount > remaining:
            raise AppException(
                400,
                f"المبلغ المدخل ({amount}) أكبر من المتبقي على المصروف ({remaining}).",
            )

        expense.paid_amount = expense.paid_amount + amount
        fully_paid = expense.paid_amount >= expense.amount
        if fully_paid:
            expense.payment_confirmed_at = datetime.now(timezone.utc)
            expense.payment_confirmed_by = user.id

        self.session.add(
            CashMovement(
                direction="out",
                reference_type="expense",
                reference_id=expense.id,
                party_id=None,
                amount=amount,
                method=expense.payment_method.value,
                collected_by=user.id,
            )
        )

        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=(
                f"سداد صندوق {'(كامل)' if fully_paid else '(جزئي)'} "
                f"لمصروف رقم {expense.id}: {expense.description}"
            ),
            items=[
                (ACCOUNTS_PAYABLE, amount, Decimal("0")),
                (cash_or_bank(expense.payment_method.value), Decimal("0"), amount),
            ],
            reference_type="expense_payment",
            reference_id=expense.id,
            created_by=user.id,
        )

        await self.session.commit()
        await self.session.refresh(expense)
        return expense


    async def refund_customer_credit(
        self, credit_id: int, user: User, method: str = "cash"
    ) -> CustomerCredit:
        """Hand a customer's credit back over the counter.

        The one path here that moves money. Crediting a balance to the account posts
        nothing — receivables already carry it — but paying cash out reduces the
        drawer, so it goes through a CashMovement like every other disbursement and
        lands in the day-close where the till is reconciled. A refund that bypassed
        that would make the drawer disagree with the books by exactly the amount
        handed over.

        Debit receivables, credit cash: the customer's account returns to zero and the
        obligation is discharged.
        """
        credit = await self.session.get(CustomerCredit, credit_id)
        if credit is None:
            raise AppException(404, "المبلغ المستحقّ للعميل غير موجود.")
        if credit.resolution is CreditResolution.REFUNDED:
            raise AppException(400, "تم ردّ هذا المبلغ نقداً من قبل.")
        if credit.resolution is CreditResolution.CREDITED:
            raise AppException(
                400, "هذا المبلغ مُسجَّل كرصيد في حساب العميل ولا يُردّ نقداً."
            )
        if credit.resolution is not CreditResolution.AWAITING_REFUND:
            # The till pays what was decided, and does not decide. Otherwise the
            # cashier could refund a credit nobody chose to refund.
            raise AppException(
                400,
                "لم يُتَّخذ قرار بردّ هذا المبلغ نقداً بعد؛ يُحدَّد القرار من شاشة "
                "المبيعات أولاً.",
            )

        credit.resolution = CreditResolution.REFUNDED
        credit.resolved_at = datetime.now(timezone.utc)
        credit.resolved_by = user.id

        self.session.add(
            CashMovement(
                direction="out",
                reference_type="customer_credit",
                reference_id=credit.id,
                party_id=credit.customer_id,
                amount=credit.amount,
                method=method,
                collected_by=user.id,
            )
        )
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=(
                f"ردّ نقدي للعميل عن مرتجع الفاتورة رقم {credit.invoice_id}"
            ),
            items=[
                (ACCOUNTS_RECEIVABLE, credit.amount, Decimal("0")),
                (cash_or_bank(method), Decimal("0"), credit.amount),
            ],
            reference_type="customer_credit",
            reference_id=credit.id,
            created_by=user.id,
        )
        await self.session.commit()
        await self.session.refresh(credit)
        return credit

    async def list_pending_payables(self) -> list[PendingPayableOut]:
        """Cash/card purchase invoices and expenses awaiting disbursement."""
        payables: list[PendingPayableOut] = []

        invoices_result = await self.session.execute(
            select(PurchaseInvoice, Supplier.name)
            .join(Supplier, PurchaseInvoice.supplier_id == Supplier.id)
            .where(
                PurchaseInvoice.payment_method.in_(
                    [PurchasePaymentMethod.CASH, PurchasePaymentMethod.CARD]
                ),
                PurchaseInvoice.payment_confirmed_at.is_(None),
            )
        )
        for invoice, supplier_name in invoices_result.all():
            payables.append(
                PendingPayableOut(
                    payable_type="purchase_invoice",
                    id=invoice.id,
                    date=invoice.invoice_date,
                    description=f"فاتورة شراء من المورد ({supplier_name})",
                    payment_method=invoice.payment_method.value,
                    total=invoice.total,
                    paid_amount=invoice.paid_amount,
                    remaining=invoice.total - invoice.paid_amount,
                )
            )

        expenses_result = await self.session.execute(
            select(Expense, ExpenseCategory.name)
            .join(ExpenseCategory, Expense.category_id == ExpenseCategory.id)
            .where(Expense.payment_confirmed_at.is_(None))
        )
        for expense, category_name in expenses_result.all():
            payables.append(
                PendingPayableOut(
                    payable_type="expense",
                    id=expense.id,
                    date=expense.created_at.date(),
                    description=f"{category_name} — {expense.description}",
                    payment_method=expense.payment_method.value,
                    total=expense.amount,
                    paid_amount=expense.paid_amount,
                    remaining=expense.amount - expense.paid_amount,
                )
            )

        payables.sort(key=lambda p: p.date)
        return payables

    # --- Daily summary (close-the-day reconciliation) ---
    async def daily_summary(
        self, user: User, day: date | None = None
    ) -> CashierDailySummaryOut:
        """Everything this cashier personally moved on a given day — money in and
        out — to reconcile and close the register.
        """
        target_day = day or date.today()
        start = datetime.combine(target_day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        result = await self.session.execute(
            select(CashMovement)
            .where(
                CashMovement.collected_by == user.id,
                CashMovement.collected_at >= start,
                CashMovement.collected_at < end,
            )
            .order_by(CashMovement.collected_at)
        )
        movements = list(result.scalars().all())

        def total_for(direction: str, method: str) -> Decimal:
            """Sum the day's movements in one direction and payment method."""
            return sum(
                (
                    m.amount
                    for m in movements
                    if m.direction == direction and m.method == method
                ),
                Decimal("0"),
            )

        cash_in = total_for("in", "cash")
        card_in = total_for("in", "card")
        cash_out = total_for("out", "cash")
        card_out = total_for("out", "card")
        total_in = cash_in + card_in
        total_out = cash_out + card_out

        return CashierDailySummaryOut(
            day=target_day,
            cashier_id=user.id,
            cashier_name=user.full_name,
            total_in=total_in,
            total_out=total_out,
            net=total_in - total_out,
            cash_in=cash_in,
            card_in=card_in,
            cash_out=cash_out,
            card_out=card_out,
            movement_count=len(movements),
            movements=movements,
        )
