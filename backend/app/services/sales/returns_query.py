"""One definition of "how much has been credited back" — deliberately only one.

Four places needed this number and three of them had grown their own copy of the
query: the cashier's amount due, the customer statement, the salesman's round
settlement, and the tax report. Each copy was written when its own feature was
built, and each was correct in isolation, which is exactly why the divergence was
invisible — the cashier was fixed, and the round settlement went on blocking forever
because it computed the same figure a second time without the returns term.

So it lives here, and every caller asks. A fifth place that needs it should import
this rather than write `select(func.sum(SalesReturn.total))` again.

`posted()` is the same argument one level down. A cancelled credit note stays in the
table on purpose — the mistake is part of the record — which means every figure
derived from returns has to say it wants only the live ones. There are fourteen such
places, so the condition is written once here and imported, rather than spelled out
fourteen times and forgotten in the fifteenth.
"""

from decimal import Decimal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.sales import ReturnStatus, SalesReturn


def posted() -> ColumnElement[bool]:
    """Only credit notes that still stand.

    Belongs in the WHERE clause of anything that counts returns, sums their money,
    or measures the goods they brought back. The exceptions are the screens that
    exist to show cancellations — `get_return`, `list_returns`, `cancel_return`
    itself — which need to see them.
    """
    return SalesReturn.status == ReturnStatus.POSTED


async def returned_totals(
    session: AsyncSession, invoice_ids: list[int]
) -> dict[int, Decimal]:
    """Credited back per invoice, for the ids given. Missing means nothing returned."""
    if not invoice_ids:
        return {}
    result = await session.execute(
        select(
            SalesReturn.invoice_id,
            func.coalesce(func.sum(SalesReturn.total), 0),
        )
        .where(SalesReturn.invoice_id.in_(invoice_ids), posted())
        .group_by(SalesReturn.invoice_id)
    )
    return {invoice_id: Decimal(str(total)) for invoice_id, total in result.all()}


async def returned_total_for(session: AsyncSession, invoice_id: int) -> Decimal:
    """Credited back against one invoice."""
    return (await returned_totals(session, [invoice_id])).get(
        invoice_id, Decimal("0")
    )
