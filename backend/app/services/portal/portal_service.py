"""Customer portal service: everything a customer can do through their own
login, plus the staff-side conversion of portal orders into real invoices.

Every read resolves the customer from the *authenticated user's* link
(users.customer_id) — a client never supplies a customer id, so one portal
account can only ever see its own data.

Prices are intentionally absent from the portal's data surface. The only place
this module touches money is the credit guard, which estimates the order at the
customer's own price tier *internally* to decide whether to accept it — the
estimate is used to gate, never returned to the customer.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.portal import CatalogItemOut, PortalOrderCreate
from app.api.schemas.sales import SalesInvoiceCreate, SalesLineIn
from app.core.exceptions import AppException
from app.domain.models.inventory import Product, ProductBatch, Warehouse
from app.domain.models.sales import (
    Customer,
    CustomerOrder,
    CustomerOrderLine,
    CustomerOrderStatus,
    FulfillmentType,
)
from app.domain.models.user import User, UserRole
from app.services.sales.sales_service import SalesService


class PortalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sales = SalesService(session)

    # --- Identity: the customer behind a portal account ---
    async def _linked_customer(self, user: User) -> Customer:
        """The customer this portal account is bound to, or a hard 403.

        The binding is set once by staff (users.customer_id) and never derived
        from request input, so the scoping below cannot be re-targeted.
        """
        if user.role != UserRole.CUSTOMER or user.customer_id is None:
            raise AppException(403, "حساب العميل غير مرتبط بأي سجل عميل.")
        customer = await self.session.get(Customer, user.customer_id)
        if customer is None or not customer.is_active:
            raise AppException(403, "حساب العميل موقوف.")
        return customer

    async def linked_customer(self, user: User) -> Customer:
        """Public alias for the portal routes' statement/invoice scoping."""
        return await self._linked_customer(user)

    # --- Catalog: quantity only, never a price ---
    async def catalog(self, user: User) -> list[CatalogItemOut]:
        """Every active product's on-hand quantity; no prices.

        Products with no stock anywhere are still listed with zero quantity so
        the customer sees them greyed out rather than wondering whether the
        product vanished. Stock from vehicle warehouses (vans on the road) is
        not sellable through the portal, so it is excluded.
        """
        rows = await self.session.execute(
            select(
                Product.id,
                Product.name,
                Product.sku,
                Product.base_unit_name,
                func.coalesce(func.sum(ProductBatch.quantity), 0),
            )
            .outerjoin(
                ProductBatch,
                (ProductBatch.product_id == Product.id)
                & (ProductBatch.quantity > 0),
            )
            .outerjoin(Warehouse, Warehouse.id == ProductBatch.warehouse_id)
            .where(
                Product.is_active.is_(True),
                (Warehouse.id.is_(None)) | (Warehouse.is_vehicle.is_(False)),
            )
            .group_by(Product.id, Product.name, Product.sku, Product.base_unit_name)
            .order_by(Product.name)
        )
        product_totals = {row[0]: Decimal(str(row[4])) for row in rows.all()}

        # Warehouse split for the chosen warehouse hint — vans excluded.
        split = await self.session.execute(
            select(
                ProductBatch.product_id,
                Warehouse.id,
                Warehouse.name,
                func.coalesce(func.sum(ProductBatch.quantity), 0),
            )
            .join(Warehouse, Warehouse.id == ProductBatch.warehouse_id)
            .where(
                ProductBatch.quantity > 0,
                Warehouse.is_vehicle.is_(False),
            )
            .group_by(ProductBatch.product_id, Warehouse.id, Warehouse.name)
        )
        per_warehouse = {}
        for row in split.all():
            per_warehouse.setdefault(row[0], []).append(
                (row[1], row[2], Decimal(str(row[3])))
            )

        products = await self.session.execute(
            select(Product).where(Product.is_active.is_(True)).order_by(Product.name)
        )
        items = []
        for product in products.scalars().all():
            total = product_totals.get(product.id, Decimal("0"))
            rows = per_warehouse.get(product.id, [])
            if rows:
                for warehouse_id, warehouse_name, qty in rows:
                    items.append(
                        CatalogItemOut(
                            product_id=product.id,
                            product_name=product.name,
                            sku=product.sku,
                            base_unit_name=product.base_unit_name,
                            warehouse_id=warehouse_id,
                            warehouse_name=warehouse_name,
                            available_quantity=qty,
                            in_stock=True,
                        )
                    )
            else:
                items.append(
                    CatalogItemOut(
                        product_id=product.id,
                        product_name=product.name,
                        sku=product.sku,
                        base_unit_name=product.base_unit_name,
                        warehouse_id=None,
                        warehouse_name=None,
                        available_quantity=total,
                        in_stock=total > 0,
                    )
                )
        return items

    # --- Orders ---
    async def _get_order_or_404(self, order_id: int) -> CustomerOrder:
        result = await self.session.execute(
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.lines))
            .where(CustomerOrder.id == order_id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise AppException(404, "الطلب غير موجود.")
        return order

    async def _hydrate(self, orders: list[CustomerOrder]) -> None:
        """Attach product names, warehouse names, and running quantities."""
        product_ids = {line.product_id for o in orders for line in o.lines}
        if product_ids:
            products = await self.session.execute(
                select(Product.id, Product.name).where(Product.id.in_(product_ids))
            )
            names = {row[0]: row[1] for row in products.all()}
        else:
            names = {}
        warehouse_ids = {o.warehouse_id for o in orders if o.warehouse_id}
        if warehouse_ids:
            warehouses = await self.session.execute(
                select(Warehouse.id, Warehouse.name).where(Warehouse.id.in_(warehouse_ids))
            )
            wnames = {row[0]: row[1] for row in warehouses.all()}
        else:
            wnames = {}
        customer_ids = {o.customer_id for o in orders}
        if customer_ids:
            customers = await self.session.execute(
                select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids))
            )
            cnames = {row[0]: row[1] for row in customers.all()}
        else:
            cnames = {}
        for order in orders:
            order.warehouse_name = wnames.get(order.warehouse_id)
            order.customer_name = cnames.get(order.customer_id)
            for line in order.lines:
                line.product_name = names.get(line.product_id)

    async def list_orders(self, user: User) -> list[CustomerOrder]:
        customer = await self._linked_customer(user)
        result = await self.session.execute(
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.lines))
            .where(CustomerOrder.customer_id == customer.id)
            .order_by(CustomerOrder.id.desc())
        )
        orders = list(result.scalars().all())
        await self._hydrate(orders)
        return orders

    async def place_order(self, user: User, data: PortalOrderCreate) -> CustomerOrder:
        """File a pending order after checking quantities and credit.

        The only money involved here is the credit gate: the order is estimated
        at the customer's own price tier internally, and refused when the
        estimate plus the outstanding balance would exceed the credit limit.
        The customer never sees the estimate or any price.
        """
        customer = await self._linked_customer(user)

        products: dict[int, Product] = {}
        for line in data.lines:
            if line.product_id in products:
                raise AppException(400, "لا يمكن تكرار نفس الصنف في الطلب الواحد.")
            product = await self.session.get(Product, line.product_id)
            if product is None or not product.is_active:
                raise AppException(400, "أحد الأصناف المطلوبة غير متاح.")
            products[line.product_id] = product

        if data.warehouse_id is not None:
            warehouse = await self.session.get(Warehouse, data.warehouse_id)
            if warehouse is None or warehouse.is_vehicle:
                raise AppException(400, "المستودع المحدد غير متاح للطلبات.")

        # Credit guard: estimate at the customer's price tier and refuse when the
        # combined exposure would exceed the limit. A zero limit means "no limit
        # configured" — staff confirmations enforce the real credit rules through
        # the normal invoice pipeline. Overriding stays with staff — the portal
        # never carries the credit_override flag.
        if customer.credit_limit > 0:
            balance = await self.sales.customer_balance(customer.id)
            estimate = Decimal("0")
            for line in data.lines:
                product = products[line.product_id]
                price = self._price_for(product, customer)
                estimate += line.quantity * price
            if balance + estimate > customer.credit_limit:
                raise AppException(
                    400,
                    "لا يمكن تقديم الطلب: تجاوز الحد الائتماني للعميل "
                    f"(الرصيد الحالي: {balance}، الحد: {customer.credit_limit}).",
                )

        order = CustomerOrder(
            customer_id=customer.id,
            order_date=date.today(),
            status=CustomerOrderStatus.PENDING,
            fulfillment=data.fulfillment,
            warehouse_id=data.warehouse_id,
            notes=data.notes,
            created_by=user.id,
        )
        self.session.add(order)
        await self.session.flush()

        for line in data.lines:
            self.session.add(
                CustomerOrderLine(
                    order_id=order.id,
                    product_id=line.product_id,
                    quantity=line.quantity,
                )
            )
        await self.session.commit()
        return await self.get_order(order.id, user)

    @staticmethod
    def _price_for(product: Product, customer: Customer) -> Decimal:
        """The customer's tier price — used ONLY for the internal credit estimate."""
        tier = customer.price_tier.value if hasattr(customer.price_tier, "value") else str(customer.price_tier)
        if tier == "retail":
            return product.retail_price
        if tier == "half_wholesale":
            return product.half_wholesale_price
        return product.wholesale_price

    async def get_order(self, order_id: int, user: User) -> CustomerOrder:
        customer = await self._linked_customer(user)
        order = await self._get_order_or_404(order_id)
        if order.customer_id != customer.id:
            raise AppException(403, "هذا الطلب ليس لك.")
        await self._hydrate([order])
        return order

    async def cancel_order(
        self, order_id: int, user: User, reason: str | None
    ) -> CustomerOrder:
        customer = await self._linked_customer(user)
        order = await self._get_order_or_404(order_id)
        if order.customer_id != customer.id:
            raise AppException(403, "هذا الطلب ليس لك.")
        if order.status != CustomerOrderStatus.PENDING:
            raise AppException(400, "لا يمكن إلغاء طلب تم تأكيده أو تحويله من قبل.")
        order.status = CustomerOrderStatus.CANCELLED
        order.cancelled_by = user.id
        order.cancelled_at = datetime.now(timezone.utc)
        order.cancel_reason = reason
        await self.session.commit()
        await self._hydrate([order])
        return order

    # --- Staff: pending orders and conversion --------------------------------
    async def staff_list_pending(self, user: User | None = None) -> list[CustomerOrder]:
        """Every pending order, oldest first — the sales team's confirmation queue."""
        result = await self.session.execute(
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.lines))
            .where(CustomerOrder.status == CustomerOrderStatus.PENDING)
            .order_by(CustomerOrder.id)
        )
        return list(result.scalars().all())

    async def staff_confirm(
        self,
        order_id: int,
        payment_method: str,
        credit_override: bool,
        user: User,
    ) -> CustomerOrder:
        """Turn a pending order into a real invoice via the normal sales pipeline.

        FEFO allocation, the credit-limit check, and the automatic journal
        entries all run inside SalesService.create_invoice in one transaction,
        exactly as for a counter sale.
        """
        order = await self._get_order_or_404(order_id)
        if order.status != CustomerOrderStatus.PENDING:
            raise AppException(400, "الطلب ليس في حالة الانتظار بعد.")
        customer = await self.session.get(Customer, order.customer_id)
        if customer is None or not customer.is_active:
            raise AppException(400, "العميل موقوف ولا يمكن تحويل الطلب له.")

        from app.api.schemas.sales import SalesPaymentMethod

        invoice_data = SalesInvoiceCreate(
            customer_id=customer.id,
            payment_method=SalesPaymentMethod(payment_method),
            fulfillment=order.fulfillment,
            tax_rate_ids=[],
            notes=order.notes,
            lines=[
                SalesLineIn(product_id=line.product_id, quantity=line.quantity)
                for line in order.lines
            ],
            credit_override=credit_override,
        )
        invoice = await self.sales.create_invoice(invoice_data, user)

        order.status = CustomerOrderStatus.INVOICED
        order.converted_invoice_id = invoice.id
        order.confirmed_by = user.id
        order.confirmed_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self._hydrate([order])
        return order