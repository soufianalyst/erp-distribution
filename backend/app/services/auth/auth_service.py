"""Authentication and user management business logic."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import TokenPair, UserCreate, UserOut, UserUpdate
from app.core.exceptions import AppException
from app.core.permissions import ALL_PERMISSIONS
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.domain.models.user import User


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
            access_token=create_access_token(str(user.id), user.role.value),
            refresh_token=create_refresh_token(str(user.id), user.role.value),
            user=UserOut.model_validate(user),
        )

    async def authenticate(self, username: str, password: str) -> TokenPair:
        user = await self._get_by_username(username)
        # Same message for unknown user and wrong password to avoid username enumeration.
        if user is None or not verify_password(password, user.hashed_password):
            raise AppException(401, "اسم المستخدم أو كلمة المرور غير صحيحة.")
        if not user.is_active:
            raise AppException(403, "هذا الحساب معطل، يرجى مراجعة مدير النظام.")
        return self._issue_tokens(user)

    async def refresh_tokens(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, expected_type="refresh")
        user = await self.session.get(User, int(payload["sub"]))
        if user is None or not user.is_active:
            raise AppException(401, "الحساب غير موجود أو معطل.")
        return self._issue_tokens(user)

    async def create_user(self, data: UserCreate) -> User:
        if await self._get_by_username(data.username) is not None:
            raise AppException(409, "اسم المستخدم مستخدم من قبل، يرجى اختيار اسم آخر.")
        user = User(
            username=data.username,
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            role=data.role,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_user(self, user_id: int, data: UserUpdate) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise AppException(404, "المستخدم غير موجود.")
        if data.full_name is not None:
            user.full_name = data.full_name
        if data.password is not None:
            user.hashed_password = hash_password(data.password)
        if data.role is not None:
            user.role = data.role
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
        result = await self.session.execute(select(User).order_by(User.id))
        return list(result.scalars().all())
