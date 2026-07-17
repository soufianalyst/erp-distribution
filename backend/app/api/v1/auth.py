"""Authentication endpoints: login, token refresh, current user, and user management."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_permissions
from app.api.schemas.auth import (
    LoginRequest,
    PermissionGroupOut,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.api.schemas.common import APIResponse
from app.db.session import get_db
from app.core.permissions import PERMISSION_GROUPS
from app.domain.models.user import User
from app.services.auth.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=APIResponse[TokenPair])
async def login(
    body: LoginRequest, db: AsyncSession = Depends(get_db)
) -> APIResponse[TokenPair]:
    """تسجيل الدخول باسم المستخدم وكلمة المرور، ويعيد رمز وصول ورمز تحديث."""
    tokens = await AuthService(db).authenticate(body.username, body.password)
    return APIResponse(data=tokens, message="تم تسجيل الدخول بنجاح.")


@router.post("/refresh", response_model=APIResponse[TokenPair])
async def refresh(
    body: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> APIResponse[TokenPair]:
    """تجديد رموز الدخول باستخدام رمز التحديث (Refresh Token)."""
    tokens = await AuthService(db).refresh_tokens(body.refresh_token)
    return APIResponse(data=tokens, message="تم تجديد الجلسة بنجاح.")


@router.get("/me", response_model=APIResponse[UserOut])
async def me(current_user: User = Depends(get_current_user)) -> APIResponse[UserOut]:
    """إرجاع بيانات المستخدم الحالي المسجل دخوله."""
    return APIResponse(data=UserOut.model_validate(current_user))


@router.post(
    "/users",
    response_model=APIResponse[UserOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions("users.manage"))],
)
async def create_user(
    body: UserCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[UserOut]:
    """إنشاء مستخدم جديد وتحديد دوره (مدير النظام فقط)."""
    user = await AuthService(db).create_user(body)
    return APIResponse(
        data=UserOut.model_validate(user), message="تم إنشاء المستخدم بنجاح."
    )


@router.get(
    "/users",
    response_model=APIResponse[list[UserOut]],
    dependencies=[Depends(require_permissions("users.manage"))],
)
async def list_users(db: AsyncSession = Depends(get_db)) -> APIResponse[list[UserOut]]:
    """عرض قائمة مستخدمي النظام (مدير النظام فقط)."""
    users = await AuthService(db).list_users()
    return APIResponse(data=[UserOut.model_validate(u) for u in users])


@router.patch(
    "/users/{user_id}",
    response_model=APIResponse[UserOut],
    dependencies=[Depends(require_permissions("users.manage"))],
)
async def update_user(
    user_id: int, body: UserUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[UserOut]:
    """تعديل بيانات مستخدم أو تعطيل حسابه (مدير النظام فقط)."""
    user = await AuthService(db).update_user(user_id, body)
    return APIResponse(
        data=UserOut.model_validate(user), message="تم تحديث بيانات المستخدم بنجاح."
    )


@router.get(
    "/permissions",
    response_model=APIResponse[list[PermissionGroupOut]],
    dependencies=[Depends(require_permissions("users.manage"))],
)
async def list_permissions() -> APIResponse[list[PermissionGroupOut]]:
    """قائمة الصلاحيات المتاحة في النظام مجمعة حسب الوحدة."""
    return APIResponse(
        data=[PermissionGroupOut.model_validate(g) for g in PERMISSION_GROUPS]
    )
