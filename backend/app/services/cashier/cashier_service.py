"""Cashier business logic: unified pending queue, polymorphic payments, daily summary."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.domain.models.accounting import JournalEntry
from app.domain.models.expenses import Expense, ExpensePaymentMethod
from app.domain.models.purchases import PurchaseInvoice, PurchasePaymentMethod
from app.domain.models.sales import (
    CashierPayment,
    InvoiceTaxLine,
    SalesInvoice,
    SalesPaymentMethod,
    SalesReturn,
)
from app.services.accounting.accounting_service import (
    ACCOUNTS_PAYABLE,
    ACCOUNTS_RECEIVABLE,
    AccountingService,
    cash_or_bank,
)


class CashierService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounting = AccountingService(session)

    # ------------------------------------------------------------------
    # Pending lists
    # ------------------------------------------------------------------

    async def list_pending_receivables(self) -> list[dict]:
        """Cash sales invoices awaiting collection — company receivables (ذمم العملاء).
        
        Only cash/card invoices appear here. Credit (آجل) invoices bypass the cashier
        and go directly to accounts receivable.
        """
        result = await self.session.execute(
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines),
                selectinload(SalesInvoice.customer),
                selectinload(SalesInvoice.tax_lines).selectinload(
                    InvoiceTaxLine.tax_type
                ),
            )
            .where(
                SalesInvoice.payment_method == SalesPaymentMethod.CASH,
                SalesInvoice.paid_amount < SalesInvoice.total,
            )
            .order_by(SalesInvoice.id.desc())
        )
        invoices = result.scalars().all()
        return [
            {
                "type": "sales",
                "type_label": "مبيعات",
                "account_label": "ذمم العملاء",
                "id": inv.id,
                "date": inv.invoice_date.isoformat(),
                "party_name": inv.customer.name if inv.customer else "",
                "payment_method": inv.payment_method.value,
                "total": inv.total,
                "paid_amount": inv.paid_amount,
                "remaining": inv.total - inv.paid_amount,
            }
            for inv in invoices
        ]

    async def list_pending_payables(self) -> list[dict]:
        """Purchase invoices + expenses awaiting payment — company payables (ذمم الموردين + المصروفات)."""
        purchases_result = await self.session.execute(
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.supplier))
            .where(
                PurchaseInvoice.payment_method == PurchasePaymentMethod.CASH,
                PurchaseInvoice.paid_amount < PurchaseInvoice.total,
            )
            .order_by(PurchaseInvoice.id.desc())
        )
        purchases = [
            {
                "type": "purchase",
                "type_label": "مشتريات",
                "account_label": "ذمم الموردين",
                "id": inv.id,
                "date": inv.invoice_date.isoformat(),
                "party_name": inv.supplier.name if inv.supplier else "",
                "payment_method": inv.payment_method.value,
                "total": inv.total,
                "paid_amount": inv.paid_amount,
                "remaining": inv.total - inv.paid_amount,
            }
            for inv in purchases_result.scalars().all()
        ]

        expenses_result = await self.session.execute(
            select(Expense).where(
                Expense.payment_method == ExpensePaymentMethod.CASH,
                Expense.paid_amount < Expense.amount,
            )
            .order_by(Expense.id.desc())
        )
        expenses = [
            {
                "type": "expense",
                "type_label": "مصاريف",
                "account_label": "ذمم الموردين",
                "id": exp.id,
                "date": exp.expense_date.isoformat(),
                "party_name": exp.payee_name,
                "payment_method": exp.payment_method.value,
                "total": exp.amount,
                "paid_amount": exp.paid_amount,
                "remaining": exp.amount - exp.paid_amount,
            }
            for exp in expenses_result.scalars().all()
        ]

        combined = purchases + expenses
        combined.sort(key=lambda x: (x["date"], x["id"]), reverse=True)
        return combined

    # ------------------------------------------------------------------
    # Receive payment (polymorphic)
    # ------------------------------------------------------------------

    async def receive_payment(
        self,
        reference_type: str,
        reference_id: int,
        amount: Decimal,
        user_id: int | None = None,
    ) -> dict:
        """Record a partial or full payment against any pending source.

        Returns a summary dict with updated paid_amount and total.
        """
        if reference_type == "sales":
            return await self._pay_sales_invoice(reference_id, amount, user_id)
        elif reference_type == "purchase":
            return await self._pay_purchase_invoice(reference_id, amount, user_id)
        elif reference_type == "expense":
            return await self._pay_expense(reference_id, amount, user_id)
        else:
            raise AppException(400, "نوع المصدر غير صحيح.")

    async def _pay_sales_invoice(
        self, invoice_id: int, amount: Decimal, user_id: int | None
    ) -> dict:
        result = await self.session.execute(
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines),
                selectinload(SalesInvoice.customer),
                selectinload(SalesInvoice.tax_lines).selectinload(
                    InvoiceTaxLine.tax_type
                ),
            )
            .where(SalesInvoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise AppException(404, "فاتورة المبيعات غير موجودة.")
        if invoice.paid_amount >= invoice.total:
            raise AppException(400, "الفاتورة مدفوعة بالفعل.")

        returns_result = await self.session.execute(
            select(func.coalesce(func.sum(SalesReturn.total), 0)).where(
                SalesReturn.invoice_id == invoice_id
            )
        )
        returned_total = returns_result.scalar_one()
        effective_total = invoice.total - Decimal(str(returned_total))
        outstanding = effective_total - invoice.paid_amount

        if amount <= 0:
            raise AppException(400, "مبلغ التحصيل يجب أن يكون أكبر من صفر.")
        payment_amount = min(amount, outstanding)
        invoice.paid_amount = invoice.paid_amount + payment_amount

        self.session.add(
            CashierPayment(
                reference_type="sales",
                reference_id=invoice_id,
                amount=payment_amount,
                payment_method=invoice.payment_method.value,
                received_by=user_id,
                payment_date=date.today(),
            )
        )

        credit_account = cash_or_bank(invoice.payment_method.value)
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"تحصيل دفعة فاتورة مبيعات رقم {invoice.id} من العميل ({invoice.customer.name})",
            items=[
                (credit_account, payment_amount, Decimal("0")),
                (ACCOUNTS_RECEIVABLE, Decimal("0"), payment_amount),
            ],
            reference_type="cashier_payment",
            reference_id=invoice.id,
            created_by=user_id,
        )

        await self.session.commit()
        return {
            "total": invoice.total,
            "paid_amount": invoice.paid_amount,
            "remaining": invoice.total - invoice.paid_amount,
        }

    async def _pay_purchase_invoice(
        self, invoice_id: int, amount: Decimal, user_id: int | None
    ) -> dict:
        result = await self.session.execute(
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.supplier))
            .where(PurchaseInvoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise AppException(404, "فاتورة الشراء غير موجودة.")
        if invoice.payment_method != PurchasePaymentMethod.CASH:
            raise AppException(400, "هذه الفاتورة آجلة ولا تمر عبر الصندوق.")
        if invoice.paid_amount >= invoice.total:
            raise AppException(400, "الفاتورة مدفوعة بالفعل.")

        outstanding = invoice.total - invoice.paid_amount
        if amount <= 0:
            raise AppException(400, "مبلغ التحصيل يجب أن يكون أكبر من صفر.")
        payment_amount = min(amount, outstanding)
        invoice.paid_amount = invoice.paid_amount + payment_amount

        self.session.add(
            CashierPayment(
                reference_type="purchase",
                reference_id=invoice_id,
                amount=payment_amount,
                payment_method=invoice.payment_method.value,
                received_by=user_id,
                payment_date=date.today(),
            )
        )

        # Settlement: Cash/Bank DR, Accounts Payable CR (the payable was set at creation).
        debit_account = cash_or_bank(invoice.payment_method.value)
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"صرف دفعة فاتورة شراء رقم {invoice.id} للمورد ({invoice.supplier.name})",
            items=[
                (ACCOUNTS_PAYABLE, payment_amount, Decimal("0")),
                (debit_account, Decimal("0"), payment_amount),
            ],
            reference_type="cashier_payment",
            reference_id=invoice.id,
            created_by=user_id,
        )

        await self.session.commit()
        return {
            "total": invoice.total,
            "paid_amount": invoice.paid_amount,
            "remaining": invoice.total - invoice.paid_amount,
        }

    async def _pay_expense(
        self, expense_id: int, amount: Decimal, user_id: int | None
    ) -> dict:
        result = await self.session.execute(
            select(Expense).where(Expense.id == expense_id)
        )
        expense = result.scalar_one_or_none()
        if expense is None:
            raise AppException(404, "سند المصروف غير موجود.")
        if expense.payment_method != ExpensePaymentMethod.CASH:
            raise AppException(400, "هذا المصروف آجل ولا يمر عبر الصندوق.")
        if expense.paid_amount >= expense.amount:
            raise AppException(400, "المصروف مدفوع بالفعل.")

        outstanding = expense.amount - expense.paid_amount
        if amount <= 0:
            raise AppException(400, "مبلغ التحصيل يجب أن يكون أكبر من صفر.")
        payment_amount = min(amount, outstanding)
        expense.paid_amount = expense.paid_amount + payment_amount

        self.session.add(
            CashierPayment(
                reference_type="expense",
                reference_id=expense_id,
                amount=payment_amount,
                payment_method=expense.payment_method.value,
                received_by=user_id,
                payment_date=date.today(),
            )
        )

        # Settlement: Cash/Bank DR, Accounts Payable CR (the payable was set at creation).
        debit_account = cash_or_bank(expense.payment_method.value)
        await self.accounting.add_entry_no_commit(
            entry_date=date.today(),
            description=f"صرف دفعة مصروف ({expense.payee_name})",
            items=[
                (ACCOUNTS_PAYABLE, payment_amount, Decimal("0")),
                (debit_account, Decimal("0"), payment_amount),
            ],
            reference_type="cashier_payment",
            reference_id=expense.id,
            created_by=user_id,
        )

        await self.session.commit()
        return {
            "total": expense.amount,
            "paid_amount": expense.paid_amount,
            "remaining": expense.amount - expense.paid_amount,
        }

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    async def daily_summary(self, summary_date: date | None = None) -> dict:
        """Daily collection summary for cashier reconciliation."""
        day = summary_date or date.today()

        agg = await self.session.execute(
            select(
                CashierPayment.payment_method,
                CashierPayment.reference_type,
                func.coalesce(func.sum(CashierPayment.amount), 0).label("total"),
                func.count(CashierPayment.id).label("count"),
            )
            .where(CashierPayment.payment_date == day)
            .group_by(CashierPayment.payment_method, CashierPayment.reference_type)
        )

        by_method: dict[str, Decimal] = {}
        by_type: dict[str, dict] = {}
        grand_total = Decimal("0")
        total_count = 0
        for row in agg:
            method = row.payment_method
            ref_type = row.reference_type
            by_method[method] = by_method.get(method, Decimal("0")) + Decimal(
                str(row.total)
            )
            if ref_type not in by_type:
                by_type[ref_type] = {"total": Decimal("0"), "count": 0}
            by_type[ref_type]["total"] += Decimal(str(row.total))
            by_type[ref_type]["count"] += row.count
            grand_total += Decimal(str(row.total))
            total_count += row.count

        # Detailed payment list.
        result = await self.session.execute(
            select(CashierPayment)
            .where(CashierPayment.payment_date == day)
            .order_by(CashierPayment.id.asc())
        )
        payments = result.scalars().all()

        details = []
        for p in payments:
            details.append(
                {
                    "id": p.id,
                    "reference_type": p.reference_type,
                    "reference_id": p.reference_id,
                    "amount": p.amount,
                    "payment_method": p.payment_method,
                }
            )

        return {
            "date": day.isoformat(),
            "grand_total": grand_total,
            "total_count": total_count,
            "by_method": by_method,
            "by_type": by_type,
            "payments": details,
        }
