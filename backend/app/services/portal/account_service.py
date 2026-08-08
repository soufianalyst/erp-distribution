"""Portal account management: binding a customer to a CUSTOMER-role login.

Staff create these accounts; there is deliberately no self-registration. The
password hash and the user-customer binding live on the users table, and the
one-customer-to-one-account rule is enforced by the unique constraint on
users.customer_id plus username uniqueness.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.portal import PortalAccountCreate, PortalAccountUpdate
from app.core.exceptions import AppException
from app.core.security import hash_password
from app.domain.models.sales import Customer
from app.domain.models.user import User, UserRole


class PortalAccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _customer_or_404(self, customer_id: int) -> Customer:
        customer = await self.session.get(Customer, customer_id)
        if customer is None:
            raise AppException(404, "العميل غير موجود.")
        return customer

    async def _by_customer(self, customer_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.customer_id == customer_id)
        )
        return result.scalar_one_or_none()

    async def _by_username(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get(self, customer_id: int) -> dict | None:
        """The account bound to this customer, or None when none exists yet."""
        account = await self._by_customer(customer_id)
        if account is None:
            return None
        return {
            "customer_id": customer_id,
            "username": account.username,
            "is_active": account.is_active,
        }

    async def create(
        self, customer_id: int, data: PortalAccountCreate
    ) -> dict:
        """Create the customer's portal login, or replace an existing one.

        A customer gets exactly one portal account. Recreating simply updates
        username/password rather than erroring, which is the forgiving behaviour
        a counter clerk wants when re-issuing an account.
        """
        customer = await self._customer_or_404(customer_id)
        existing = await self._by_customer(customer_id)
        username_user = await self._by_username(data.username)
        if username_user is not None and username_user.id != (
            existing.id if existing else None
        ):
            raise AppException(409, "اسم المستخدم مستخدم من قبل.")

        if existing is not None:
            existing.username = data.username
            existing.hashed_password = hash_password(data.password)
            existing.is_active = True
            existing.full_name = f"عميل: {customer.name}"
            await self.session.commit()
            return {"customer_id": customer_id, "username": data.username}

        account = User(
            username=data.username,
            full_name=f"عميل: {customer.name}",
            hashed_password=hash_password(data.password),
            role=UserRole.CUSTOMER,
            customer_id=customer.id,
        )
        self.session.add(account)
        await self.session.commit()
        return {"customer_id": customer_id, "username": data.username}

    async def update(
        self, customer_id: int, data: PortalAccountUpdate
    ) -> dict:
        """Reset the account's password, or enable/disable the portal login."""
        customer = await self._customer_or_404(customer_id)
        account = await self._by_customer(customer_id)
        if account is None:
            raise AppException(404, "لا يوجد حساب بوابة لهذا العميل بعد.")
        if data.is_active is not None:
            account.is_active = data.is_active
        if data.password is not None:
            account.hashed_password = hash_password(data.password)
        await self.session.commit()
        return {
            "customer_id": customer_id,
            "username": account.username,
            "is_active": account.is_active,
        }