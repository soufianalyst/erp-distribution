"""What a customer may read about their own account.

Everything here takes `customer_id` from the caller, and every caller is a portal
route that got it from the token — never from the request. That is the whole of the
isolation story on this side; there is no `ensure_access` to forget to call because
there is no way to name another customer in the first place.

The numbers are not recomputed here. The statement comes from
`SalesService.statement_data`, the same gathering the office screen uses, because a
customer and a salesman looking at the same balance and seeing different figures is
the one failure a statement cannot survive.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.portal import (
    InvoiceDetailOut,
    InvoiceLineOut,
    InvoiceSummaryOut,
    InvoiceTaxOut,
    PortalPaymentOut,
    PortalProfileUpdateIn,
    PortalReturnOut,
    PortalStatementOut,
)
from app.core.exceptions import AppException
from app.domain.models.inventory import Product
from app.domain.models.sales import Customer, SalesInvoice
from app.services.sales.sales_service import SalesService


def _summary(invoice: SalesInvoice) -> InvoiceSummaryOut:
    """Project one invoice down to what its customer may see.

    Written out field by field rather than `model_validate`: the invoice lines carry
    `unit_cost` beside `unit_price`, and a schema that inherited from the internal one
    would start leaking our margin the first time someone added a field.
    """
    amount_due = invoice.total - invoice.paid_amount
    return InvoiceSummaryOut(
        id=invoice.id,
        invoice_date=invoice.invoice_date,
        total=invoice.total,
        paid_amount=invoice.paid_amount,
        amount_due=amount_due,
        payment_method=invoice.payment_method.value,
        is_settled=amount_due <= Decimal("0"),
    )


class PortalDataService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def statement(self, customer_id: int) -> PortalStatementOut:
        """The customer's own account: what was invoiced, returned, and paid."""
        data = await SalesService(self.session).statement_data(customer_id)
        return PortalStatementOut(
            opening_balance=data.customer.opening_balance,
            total_invoices=data.total_invoices,
            total_returns=data.total_returns,
            total_paid=data.total_paid,
            balance=data.balance,
            invoices=[_summary(i) for i in data.invoices],
            returns=[
                PortalReturnOut(
                    id=r.id,
                    invoice_id=r.invoice_id,
                    date=r.created_at,
                    total=r.total,
                    reason=r.reason.value if hasattr(r.reason, "value") else r.reason,
                )
                for r in data.returns
            ],
            payments=[
                PortalPaymentOut(
                    id=p.id,
                    payment_date=p.payment_date,
                    amount=p.amount,
                    method=p.method.value if hasattr(p.method, "value") else p.method,
                    reference=p.reference,
                )
                for p in data.payments
            ],
        )

    async def invoices(self, customer_id: int) -> list[InvoiceSummaryOut]:
        """Every invoice issued to this customer, newest first."""
        result = await self.session.execute(
            select(SalesInvoice)
            .where(SalesInvoice.customer_id == customer_id)
            .order_by(SalesInvoice.id.desc())
        )
        return [_summary(i) for i in result.scalars().all()]

    async def invoice(self, customer_id: int, invoice_id: int) -> InvoiceDetailOut:
        """One invoice in full — but only if it is this customer's.

        The customer id is part of the lookup rather than checked afterwards. A
        forgotten check is a silent leak; a missing WHERE clause is a visible bug, and
        anyway the answer to "someone else's invoice" and "no such invoice" should be
        the same 404 either way.
        """
        result = await self.session.execute(
            select(SalesInvoice)
            .options(
                selectinload(SalesInvoice.lines), selectinload(SalesInvoice.taxes)
            )
            .where(
                SalesInvoice.id == invoice_id,
                SalesInvoice.customer_id == customer_id,
            )
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise AppException(404, "الفاتورة غير موجودة.")

        names = dict(
            (
                await self.session.execute(
                    select(Product.id, Product.name).where(
                        Product.id.in_([line.product_id for line in invoice.lines])
                    )
                )
            ).all()
        )
        summary = _summary(invoice)
        return InvoiceDetailOut(
            **summary.model_dump(),
            subtotal=invoice.subtotal,
            discount_amount=invoice.discount_amount,
            vat_amount=invoice.vat_amount,
            lines=[
                InvoiceLineOut(
                    product_name=names.get(line.product_id, "—"),
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_total=line.line_total,
                )
                for line in invoice.lines
            ],
            taxes=[
                InvoiceTaxOut(name=t.name, rate=t.rate, amount=t.amount)
                for t in invoice.taxes
            ],
        )

    async def update_profile(
        self, customer_id: int, data: PortalProfileUpdateIn
    ) -> Customer:
        """Let a customer correct their own phone and address.

        Only fields the caller actually sent are touched, so sending just a phone
        does not blank the address.
        """
        customer = await self.session.get(Customer, customer_id)
        if customer is None:
            raise AppException(404, "العميل غير موجود.")
        changes = data.model_dump(exclude_unset=True)
        if "phone" in changes:
            customer.phone = changes["phone"]
        if "address" in changes:
            customer.address = changes["address"]
        await self.session.commit()
        await self.session.refresh(customer)
        return customer
