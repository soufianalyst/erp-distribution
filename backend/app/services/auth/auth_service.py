"""Authentication and user management business logic."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import TokenPair, UserCreate, UserOut, UserUpdate
from app.core.exceptions import AppException
from app.core.permissions import ALL_PERMISSIONS
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password_or_dummy,
)
from app.domain.models.user import User, UserRole


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_by_username(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    def _issue_tokens(self, user: User) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(str(user.id), user.role.value, realm="staff"),
            refresh_token=create_refresh_token(str(user.id), user.role.value, realm="staff"),
            user=UserOut.model_validate(user),
        )

    async def authenticate(self, username: str, password: str) -> TokenPair:
        """Sign a user in, returning an access/refresh pair.

    A wrong username and a wrong password fail identically, in the same time, so
    the response cannot be used to enumerate accounts.
    """
        user = await self._get_by_username(username)
        # Same message AND same bcrypt cost for an unknown user as for a wrong
        # password, to avoid username enumeration via response content or timing.
        if not verify_password_or_dummy(
            password, user.hashed_password if user else None
        ):
            raise AppException(401, "اسم المستخدم أو كلمة المرور غير صحيحة.")
        assert user is not None
        if not user.is_active:
            raise AppException(403, "هذا الحساب معطل، يرجى مراجعة مدير النظام.")
        return self._issue_tokens(user)

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """Exchange a valid refresh token for a fresh pair, re-checking the account."""
        payload = decode_token(refresh_token, expected_type="refresh", expected_realm="staff")
        user = await self.session.get(User, int(payload["sub"]))
        if user is None or not user.is_active:
            raise AppException(401, "الحساب غير موجود أو معطل.")
        return self._issue_tokens(user)

    async def create_user(self, data: UserCreate) -> User:
        """Create a user account with a hashed password; usernames are unique."""
        if await self._get_by_username(data.username) is not None:
            raise AppException(409, "اسم المستخدم مستخدم من قبل، يرجى اختيار اسم آخر.")
        user = User(
            username=data.username,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            role=data.role,
            commission_rate=data.commission_rate,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_user(self, user_id: int, data: UserUpdate) -> User:
        """Amend a user: details, role, explicit permissions, or disable them."""
        user = await self.session.get(User, user_id)
        if user is None:
            raise AppException(404, "المستخدم غير موجود.")
        if data.full_name is not None:
            user.full_name = data.full_name
        if data.password is not None:
            user.hashed_password = hash_password(data.password)
        if data.role is not None:
            user.role = data.role
        if data.commission_rate is not None:
            user.commission_rate = data.commission_rate
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.reset_permissions:
            # Back to the role's default permission template.
            user.permissions = None
        elif data.permissions is not None:
            unknown = set(data.permissions) - ALL_PERMISSIONS
            if unknown:
                raise AppException(
                    400, f"صلاحيات غير معروفة: {'، '.join(sorted(unknown))}"
                )
            user.permissions = sorted(set(data.permissions))
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def list_users(self) -> list[User]:
        """All user accounts, in creation order."""
        result = await self.session.execute(select(User).order_by(User.id))
        return list(result.scalars().all())

    async def _references_to(self, user_id: int) -> dict[str, int]:
        """Every row in the system that points at this user, counted per table.

        Discovered from the mapper metadata rather than a hand-written list. Thirty-odd
        tables carry a `created_by`, a `salesman_id` or similar, and a list maintained
        by hand would be one migration behind the day someone adds the thirty-fifth —
        which is precisely the day a delete would either fail on a foreign key or, if
        somebody had "helpfully" added ON DELETE SET NULL, quietly strip a name off
        historical records.
        """
        from app.db.base import Base

        counts: dict[str, int] = {}
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                if not any(
                    fk.column.table.name == "users" and fk.column.name == "id"
                    for fk in column.foreign_keys
                ):
                    continue
                found = await self.session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(column == user_id)
                )
                if found:
                    counts[f"{table.name}.{column.name}"] = found
        return counts

    async def delete_user(self, user_id: int, current_user: User) -> None:
        """Remove an account that was created in error.

        Deliberately narrow. A user who has traded is woven through invoices, journal
        entries and the audit log, and deleting them would either break those
        references or leave records nobody can attribute. Deactivating keeps the
        history readable while closing the door, which is what "removing" an employee
        who has worked here actually means.

        So this is for the duplicate, the typo, the account opened for someone who
        never started — and it says as much when it refuses.
        """
        user = await self.session.get(User, user_id)
        if user is None:
            raise AppException(404, "المستخدم غير موجود.")

        # Deleting the account you are signed in with would revoke your own session
        # mid-request and leave you unable to undo it.
        if user.id == current_user.id:
            raise AppException(400, "لا يمكنك حذف حسابك الذي تعمل به الآن.")

        if user.role == UserRole.ADMIN:
            remaining = await self.session.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == UserRole.ADMIN,
                    User.is_active.is_(True),
                    User.id != user.id,
                )
            )
            # Losing the last administrator locks everyone out of the permission
            # screen permanently, with no way back through the interface.
            if not remaining:
                raise AppException(
                    400, "لا يمكن حذف آخر مدير نظام فعّال في النظام."
                )

        references = await self._references_to(user_id)
        if references:
            total = sum(references.values())
            raise AppException(
                409,
                f"لا يمكن حذف هذا المستخدم لارتباطه بـ {total} سجلاً في النظام "
                "(فواتير أو قيود أو حركات). عطّل الحساب بدلاً من حذفه للحفاظ على "
                "سجلات العمليات.",
            )

        await self.session.delete(user)
        await self.session.commit()
