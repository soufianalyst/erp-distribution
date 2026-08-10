"""One page of a list, and the one way to produce it.

Every list endpoint used to return every row it had. That is invisible while a
database is young: journal entries were 3,408 rows and 2 MB after a single seeded
year, served in 429 ms, and the screen that asked for them displays fifteen. The
cost grows with every invoice posted and never comes back down, so this is not a
performance tweak — it is the difference between a system that keeps working in
year three and one that does not.

`data` deliberately becomes an object rather than staying a list. A caller that has
not been updated then fails loudly instead of quietly rendering the first fifty rows
as though they were the whole ledger, which for an accounts screen is the more
dangerous of the two failures.
"""

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

# Fifty is comfortably more than the fifteen a table shows, so ordinary paging costs
# one request per page, while the ceiling keeps a hand-written `?limit=100000` from
# reintroducing exactly the problem this module exists to remove.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page(BaseModel, Generic[T]):
    """A slice of a longer list, plus what the caller needs to walk it.

    `total` is the count *before* the slice — without it a screen cannot say "page 3
    of 40", and the user cannot tell whether they are looking at everything.
    """

    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams:
    """`limit`/`offset` as a FastAPI dependency, declared once.

    A dependency rather than two loose Query arguments so that the bounds are stated
    in a single place: repeating `ge=1, le=200` at each endpoint is how one of them
    eventually gets a different ceiling.
    """

    def __init__(
        self,
        limit: int = Query(
            default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="عدد السجلات في الصفحة"
        ),
        offset: int = Query(default=0, ge=0, description="عدد السجلات المتخطاة"),
    ) -> None:
        self.limit = limit
        self.offset = offset


async def paginate(
    session: AsyncSession, stmt: Select, params: PageParams
) -> tuple[list, int]:
    """Run `stmt` for one page, and count how many rows it would have returned.

    The count strips ORDER BY: sorting a result nobody reads is wasted work, and
    Postgres rejects an ordered subquery ordered by a column the outer count does not
    select. Two queries rather than a window function because the count is cheap
    against an indexed filter and the alternative repeats the sort for every row.
    """
    total = await session.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    )
    result = await session.execute(stmt.limit(params.limit).offset(params.offset))
    return list(result.scalars().unique().all()), int(total or 0)
