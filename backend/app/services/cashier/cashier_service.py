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

from sqlalchemy import select
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
from app.domain.models.sales import Customer, SalesInvoice, SalesPaymentMethod
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

    async def list_pending_invoices(self) -> list[SalesInvoice]:
        """Cash/card sales invoices awaiting (full) collection at the register."""
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
        return list(result.scalars().all())

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

        remaining = (invoice.total - invoice.paid_amount).quantize(TWO_PLACES)
        if amount > remaining:
            raise AppException(
                400,
                f"المبلغ المدخل ({amount}) أكبر من المتبقي على الفاتورة ({remaining}).",
            )

        customer = await self.session.get(Customer, invoice.customer_id)

        invoice.paid_amount = invoice.paid_amount + amount
        fully_collected = invoice.paid_amount >= invoice.total
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
