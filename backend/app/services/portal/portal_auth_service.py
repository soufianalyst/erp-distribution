"""Signing customers in — the authentication half of the portal.

Separate from `AuthService` on purpose. The two look similar enough that merging
them would be tempting, and a shared `authenticate` with a flag deciding which table
to read is precisely the kind of code where a later edit points the customer branch
at `users`. They stay apart.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas.portal import (
    CustomerLoginCreateIn,
    CustomerLoginUpdateIn,
    PortalCustomerOut,
    PortalTokenPair,
)
from app.core.exceptions import AppException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password_or_dummy,
)
from app.domain.models.sales import Customer, CustomerLogin

# A customer typing their own password wrongly five times is having a bad morning;
# a script trying a sixth is not. Long enough to stop guessing, short enough that a
# real shop is not locked out of ordering for the day.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class PortalAuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _by_login_id(self, login_id: str) -> CustomerLogin | None:
        result = await self.session.execute(
            select(CustomerLogin)
            .options(selectinload(CustomerLogin.customer))
            .where(CustomerLogin.login_id == login_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _is_locked(login: CustomerLogin) -> bool:
        """Whether the lockout is still running.

        `locked_until` comes back timezone-aware from Postgres and naive from SQLite,
        which the test suite uses. Comparing the two raises rather than returning a
        wrong answer, so a lockout that worked in tests would have thrown 500s in
        production — or the reverse. Normalising to UTC here settles it in one place.
        """
        if login.locked_until is None:
            return False
        locked_until = login.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        return locked_until > datetime.now(timezone.utc)

    def _issue(self, login: CustomerLogin) -> PortalTokenPair:
        """Mint a pair in the customer realm.

        `sub` is the *customer* id, not the login row's — everything downstream scopes
        by customer, and carrying the login id would mean one more hop that could be
        got wrong. The realm claim is what keeps this from being read as staff.
        """
        subject = str(login.customer_id)
        return PortalTokenPair(
            access_token=create_access_token(subject, "customer", realm="customer"),
            refresh_token=create_refresh_token(subject, "customer", realm="customer"),
            customer=PortalCustomerOut(
                customer_id=login.customer_id,
                name=login.customer.name,
                phone=login.customer.phone,
                address=login.customer.address,
                must_change_password=login.must_change_password,
            ),
        )

    async def authenticate(self, login_id: str, password: str) -> PortalTokenPair:
        """Sign a customer in.

        Every failure answers the same way. Whether the login id exists, whether the
        account is disabled, whether the customer has been deactivated — all of it is
        information a stranger should not be able to collect by trying.
        """
        login = await self._by_login_id(login_id)

        # Pay the bcrypt cost even when there is no such login, so timing does not
        # reveal which identifiers are registered.
        password_ok = verify_password_or_dummy(
            password, login.hashed_password if login else None
        )

        if login is not None and self._is_locked(login):
            raise AppException(
                429,
                "تم إيقاف المحاولات مؤقتاً بعد محاولات دخول خاطئة متكررة، "
                "حاول بعد قليل أو راجع الشركة.",
            )

        if (
            login is None
            or not password_ok
            or not login.is_active
            or not login.customer.is_active
        ):
            if login is not None and not password_ok:
                login.failed_attempts += 1
                if login.failed_attempts >= MAX_FAILED_ATTEMPTS:
                    login.locked_until = datetime.now(timezone.utc) + timedelta(
                        minutes=LOCKOUT_MINUTES
                    )
                    login.failed_attempts = 0
                await self.session.commit()
            raise AppException(401, "بيانات الدخول غير صحيحة.")

        login.failed_attempts = 0
        login.locked_until = None
        login.last_login_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(login)
        return self._issue(login)

    async def refresh(self, refresh_token: str) -> PortalTokenPair:
        """Exchange a customer refresh token for a fresh pair.

        Re-reads the account every time: a login disabled by the office must stop
        working at the next refresh, not at the end of the token's life.
        """
        payload = decode_token(
            refresh_token, expected_type="refresh", expected_realm="customer"
        )
        result = await self.session.execute(
            select(CustomerLogin)
            .options(selectinload(CustomerLogin.customer))
            .where(CustomerLogin.customer_id == int(payload["sub"]))
        )
        login = result.scalar_one_or_none()
        if login is None or not login.is_active or not login.customer.is_active:
            raise AppException(401, "الحساب غير موجود أو موقوف.")
        return self._issue(login)

    async def change_password(
        self, customer_id: int, current_password: str, new_password: str
    ) -> None:
        """Change a customer's own password, clearing the forced-change flag."""
        result = await self.session.execute(
            select(CustomerLogin).where(CustomerLogin.customer_id == customer_id)
        )
        login = result.scalar_one_or_none()
        if login is None:
            raise AppException(404, "الحساب غير موجود.")
        if not verify_password_or_dummy(current_password, login.hashed_password):
            raise AppException(400, "كلمة المرور الحالية غير صحيحة.")
        if current_password == new_password:
            raise AppException(400, "كلمة المرور الجديدة مطابقة للحالية.")
        login.hashed_password = hash_password(new_password)
        login.must_change_password = False
        await self.session.commit()

    # --- Office side ---
    async def create_login(
        self, data: CustomerLoginCreateIn, created_by: int | None
    ) -> CustomerLogin:
        """Give a customer a way in, with a temporary password the office hands over."""
        customer = await self.session.get(Customer, data.customer_id)
        if customer is None:
            raise AppException(404, "العميل غير موجود.")
        if not customer.is_active:
            raise AppException(400, "لا يمكن فتح حساب لعميل موقوف.")

        existing = await self.session.execute(
            select(CustomerLogin).where(
                (CustomerLogin.customer_id == data.customer_id)
                | (CustomerLogin.login_id == data.login_id)
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(
                409, "هذا العميل لديه حساب بالفعل، أو معرّف الدخول مستخدم."
            )

        login = CustomerLogin(
            customer_id=data.customer_id,
            login_id=data.login_id,
            hashed_password=hash_password(data.temporary_password),
            must_change_password=True,
            created_by=created_by,
        )
        self.session.add(login)
        await self.session.commit()
        await self.session.refresh(login)
        return login

    async def update_login(
        self, login_id: int, data: CustomerLoginUpdateIn
    ) -> CustomerLogin:
        """Suspend, restore, or reset a customer's portal access."""
        login = await self.session.get(CustomerLogin, login_id)
        if login is None:
            raise AppException(404, "الحساب غير موجود.")
        if data.is_active is not None:
            login.is_active = data.is_active
        if data.temporary_password is not None:
            login.hashed_password = hash_password(data.temporary_password)
            # A reset is also how a locked-out customer is let back in the same call.
            login.must_change_password = True
            login.failed_attempts = 0
            login.locked_until = None
        await self.session.commit()
        await self.session.refresh(login)
        return login

    async def list_logins(self) -> list[CustomerLogin]:
        result = await self.session.execute(
            select(CustomerLogin)
            .options(selectinload(CustomerLogin.customer))
            .order_by(CustomerLogin.id.desc())
        )
        return list(result.scalars().all())
