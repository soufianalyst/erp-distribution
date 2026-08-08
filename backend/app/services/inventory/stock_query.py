"""One definition of "stock we can actually sell".

The FEFO allocator has always known the answer — a batch counts if it still holds
quantity and has not expired — but the predicate lived inline in the allocation
query. The moment a second reader appeared (the customer portal's catalogue, which
tells a shop whether something is worth ordering) that inline copy became a promise
waiting to be broken: a catalogue that counts expired batches advertises goods the
invoice engine will refuse a minute later, and the customer is told the shortage only
after choosing.

So the predicate lives here, and both callers ask for it by name.
"""

from datetime import date

from sqlalchemy import ColumnElement, and_

from app.domain.models.inventory import ProductBatch


def sellable() -> ColumnElement[bool]:
    """Batches that may be allocated to a sale today.

    Expiry is strict: a batch expiring *today* is not sellable. That matches the
    allocator, and for food it is the only defensible reading — a case of yoghurt
    dated today is not something to load onto a van.
    """
    return and_(ProductBatch.quantity > 0, ProductBatch.expiry_date > date.today())
