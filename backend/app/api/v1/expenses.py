"""Expenses endpoints: configurable categories and payable expense notes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.expenses import (
    ExpenseCategoryCreate,
    ExpenseCategoryOut,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpenseOut,
)
from app.db.session import get_db
from app.domain.models.user import User
from app.services.expenses.expense_service import ExpenseService

router = APIRouter(prefix="/expenses", tags=["Expenses"])

expenses_view = Depends(require_permissions("expenses.view"))
expenses_manage = Depends(require_permissions("expenses.manage"))


@router.get(
    "/categories",
    response_model=APIResponse[list[ExpenseCategoryOut]],
    dependencies=[expenses_view],
)
async def list_categories(
    active_only: bool = False, db: AsyncSession = Depends(get_db)
) -> APIResponse[list[ExpenseCategoryOut]]:
    """عرض تصنيفات المصاريف (مثال: كهرباء، ماء، مصاريف عائلية)."""
    categories = await ExpenseService(db).list_categories(active_only)
    return APIResponse(data=[ExpenseCategoryOut.model_validate(c) for c in categories])


@router.post(
    "/categories",
    response_model=APIResponse[ExpenseCategoryOut],
    status_code=201,
    dependencies=[expenses_manage],
)
async def create_category(
    body: ExpenseCategoryCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[ExpenseCategoryOut]:
    """إضافة تصنيف مصاريف جديد."""
    category = await ExpenseService(db).create_category(body)
    return APIResponse(
        data=ExpenseCategoryOut.model_validate(category),
        message="تم إضافة التصنيف بنجاح.",
    )


@router.patch(
    "/categories/{category_id}",
    response_model=APIResponse[ExpenseCategoryOut],
    dependencies=[expenses_manage],
)
async def update_category(
    category_id: int, body: ExpenseCategoryUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[ExpenseCategoryOut]:
    """تعديل تصنيف مصاريف أو إيقافه."""
    category = await ExpenseService(db).update_category(category_id, body)
    return APIResponse(
        data=ExpenseCategoryOut.model_validate(category),
        message="تم تحديث التصنيف بنجاح.",
    )


@router.get(
    "", response_model=APIResponse[list[ExpenseOut]], dependencies=[expenses_view]
)
async def list_expenses(
    category_id: int | None = None, db: AsyncSession = Depends(get_db)
) -> APIResponse[list[ExpenseOut]]:
    """عرض سجل المصاريف، مع إمكانية التصفية حسب التصنيف."""
    expenses = await ExpenseService(db).list_expenses(category_id)
    return APIResponse(data=[ExpenseOut.model_validate(e) for e in expenses])


@router.post("", response_model=APIResponse[ExpenseOut], status_code=201)
async def create_expense(
    body: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("expenses.manage")),
) -> APIResponse[ExpenseOut]:
    """تسجيل مصروف جديد (نقدي أو بالبطاقة)؛ يبقى بانتظار الصرف من الصندوق."""
    expense = await ExpenseService(db).create_expense(body, current_user)
    return APIResponse(
        data=ExpenseOut.model_validate(expense),
        message="تم تسجيل المصروف بنجاح، بانتظار الصرف من الصندوق.",
    )
