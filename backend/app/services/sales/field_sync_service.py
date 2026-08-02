"""Upload of a salesman's round from the offline field app.

Three properties matter more than anything else here, because the caller is a
phone on a bad connection that may resend the same batch several times:

* **Idempotent.** Every item carries a client_uuid minted before it left the
  device. Anything already stored is reported as a duplicate, never repeated —
  so a lost response cannot turn one sale into two.
* **Ordered.** Customers are handled first, because an invoice from the round
  may name a shop that only exists on the device; the invoice then resolves its
  buyer through that same uuid.
* **Partial.** One rejected document (credit limit, van out of stock) must not
  cost the salesman the rest of the day's work, so each is committed on its own
  and failures come back per item for the app to keep queued.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.sales import (
    CustomerCreate,
    FieldCustomerIn,
    FieldDocumentIn,
    FieldSyncIn,
    FieldSyncItemOut,
    FieldSyncOut,
    FieldVanOut,
    FieldVanStockLineOut,
    QuotationLineIn,
    SalesInvoiceCreate,
    SalesQuotationCreate,
)
from app.core.exceptions import AppException
from app.domain.models.inventory import Product, ProductBatch, Warehouse
from app.domain.models.sales import Customer, SalesInvoice, SalesQuotation
from app.domain.models.user import User, UserRole
from app.services.sales.sales_service import SalesService


class FieldSyncService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sales = SalesService(session)

    # --- The salesman's van ---
    async def get_van(self, user: User) -> Warehouse:
        """The vehicle assigned to this salesman, or a 404 telling them to ask for one."""
        result = await self.session.execute(
            select(Warehouse).where(
                Warehouse.assigned_to_id == user.id,
                Warehouse.is_vehicle.is_(True),
                Warehouse.is_active.is_(True),
            )
        )
        van = result.scalars().first()
        if van is None:
            raise AppException(
                404,
                "لا توجد مركبة مسندة إليك؛ اطلب من المدير إسناد مركبة لحسابك "
                "قبل البيع من السيارة.",
            )
        return van

    async def van_snapshot(self, user: User) -> FieldVanOut:
        """What the van is carrying — cached by the app for offline checks."""
        van = await self.get_van(user)
        result = await self.session.execute(
            select(
                Product.id,
                Product.sku,
                Product.name,
                Product.base_unit_name,
                ProductBatch.quantity,
            )
            .join(ProductBatch, ProductBatch.product_id == Product.id)
            .where(
                ProductBatch.warehouse_id == van.id,
                ProductBatch.quantity > 0,
            )
            .order_by(Product.name)
        )
        # Batches roll up per product: the salesman sells products, and FEFO
        # picks the batch for them at posting time.
        totals: dict[int, FieldVanStockLineOut] = {}
        for product_id, sku, name, base_unit_name, quantity in result.all():
            line = totals.get(product_id)
            if line is None:
                totals[product_id] = FieldVanStockLineOut(
                    product_id=product_id,
                    sku=sku,
                    name=name,
                    base_unit_name=base_unit_name,
                    quantity=quantity,
                )
            else:
                line.quantity += quantity
        return FieldVanOut(
            warehouse_id=van.id,
            warehouse_name=van.name,
            lines=list(totals.values()),
        )

    # --- Sync ---
    async def sync(self, data: FieldSyncIn, user: User) -> FieldSyncOut:
        """Upload a whole round: new shops first, then the sales and orders naming them."""
        results: list[FieldSyncItemOut] = []
        # Maps a customer created on the device to its real id, so documents in
        # the same batch can find their buyer.
        uuid_to_customer_id: dict[str, int] = {}

        for incoming in data.customers:
            results.append(
                await self._sync_customer(incoming, user, uuid_to_customer_id)
            )

        for document in data.documents:
            results.append(
                await self._sync_document(document, user, uuid_to_customer_id)
            )

        return FieldSyncOut(
            created_count=sum(1 for r in results if r.status == "created"),
            duplicate_count=sum(1 for r in results if r.status == "duplicate"),
            failed_count=sum(1 for r in results if r.status == "failed"),
            results=results,
        )

    async def _sync_customer(
        self,
        incoming: FieldCustomerIn,
        user: User,
        uuid_to_customer_id: dict[str, int],
    ) -> FieldSyncItemOut:
        existing = await self.session.execute(
            select(Customer).where(Customer.client_uuid == incoming.client_uuid)
        )
        already = existing.scalar_one_or_none()
        if already is not None:
            uuid_to_customer_id[incoming.client_uuid] = already.id
            return FieldSyncItemOut(
                client_uuid=incoming.client_uuid,
                kind="customer",
                status="duplicate",
                server_id=already.id,
                message="مسجّل مسبقاً.",
            )

        try:
            customer = await self.sales.create_customer(
                CustomerCreate(
                    name=incoming.name,
                    phone=incoming.phone,
                    address=incoming.address,
                    price_tier=incoming.price_tier,
                    # A shop signed up on someone's round belongs to that round.
                    # Without this the salesman could register a customer and
                    # then be barred from invoicing them moments later.
                    salesman_id=user.id if user.role == UserRole.SALES else None,
                )
            )
            customer.client_uuid = incoming.client_uuid
            await self.session.commit()
        except AppException as error:
            await self.session.rollback()
            # A rollback expires every object the session had loaded, including
            # the caller — reload it so the rest of the round can still post.
            await self.session.refresh(user)
            # A name clash usually means head office added the same shop while
            # the salesman was offline. Reported rather than merged: only a human
            # can tell a genuine duplicate from two shops sharing a name.
            return FieldSyncItemOut(
                client_uuid=incoming.client_uuid,
                kind="customer",
                status="failed",
                message=error.message,
            )

        uuid_to_customer_id[incoming.client_uuid] = customer.id
        return FieldSyncItemOut(
            client_uuid=incoming.client_uuid,
            kind="customer",
            status="created",
            server_id=customer.id,
            message=f"تم تسجيل العميل ({customer.name}).",
        )

    async def _sync_document(
        self,
        document: FieldDocumentIn,
        user: User,
        uuid_to_customer_id: dict[str, int],
    ) -> FieldSyncItemOut:
        model = SalesInvoice if document.kind == "van_sale" else SalesQuotation
        existing = await self.session.execute(
            select(model).where(model.client_uuid == document.client_uuid)
        )
        already = existing.scalar_one_or_none()
        if already is not None:
            return FieldSyncItemOut(
                client_uuid=document.client_uuid,
                kind=document.kind,
                status="duplicate",
                server_id=already.id,
                message=f"مسجّل مسبقاً برقم {already.id}.",
            )

        customer_id = document.customer_id or uuid_to_customer_id.get(
            document.customer_uuid or ""
        )
        if customer_id is None:
            # Either the customer failed above, or the app sent neither id.
            return FieldSyncItemOut(
                client_uuid=document.client_uuid,
                kind=document.kind,
                status="failed",
                message="تعذّر تحديد العميل؛ تحقق من تسجيل العميل أولاً.",
            )

        try:
            if document.kind == "van_sale":
                van = await self.get_van(user)
                invoice = await self.sales.create_invoice(
                    SalesInvoiceCreate(
                        customer_id=customer_id,
                        payment_method=document.payment_method,
                        tax_rate_ids=document.tax_rate_ids,
                        notes=document.notes,
                        lines=document.lines,
                        collectable_amount=document.collectable_amount,
                    ),
                    user,
                    # Goods leave the van, not the product's home warehouse.
                    source_warehouse_id=van.id,
                    client_uuid=document.client_uuid,
                )
                return FieldSyncItemOut(
                    client_uuid=document.client_uuid,
                    kind="van_sale",
                    status="created",
                    server_id=invoice.id,
                    message=f"صدرت فاتورة بيع رقم {invoice.id}.",
                )

            quotation = await self.sales.create_quotation(
                SalesQuotationCreate(
                    customer_id=customer_id,
                    tax_rate_ids=document.tax_rate_ids,
                    notes=document.notes,
                    # Same shape as a sales line, but a distinct type: rebuild
                    # rather than pass the objects straight through.
                    lines=[
                        QuotationLineIn(
                            product_id=line.product_id,
                            quantity=line.quantity,
                            unit_id=line.unit_id,
                        )
                        for line in document.lines
                    ],
                ),
                user,
                client_uuid=document.client_uuid,
            )
            return FieldSyncItemOut(
                client_uuid=document.client_uuid,
                kind="order",
                status="created",
                server_id=quotation.id,
                message=f"سُجّل الطلب رقم {quotation.id} بانتظار التجهيز.",
            )
        except AppException as error:
            # Discard this document's partial work only; the rest of the round
            # has already been committed and stays in place. Reload the caller,
            # which the rollback expired along with everything else.
            await self.session.rollback()
            await self.session.refresh(user)
            return FieldSyncItemOut(
                client_uuid=document.client_uuid,
                kind=document.kind,
                status="failed",
                message=error.message,
            )
