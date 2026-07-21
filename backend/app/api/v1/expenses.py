"""Expenses API: CRUD for payable notes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.expenses import ExpenseIn, ExpenseOut
from app.db.session import get_db
from app.domain.models.user import User
from app.services.expenses.expense_service import ExpenseService

router = APIRouter(prefix="/expenses", tags=["Expenses"])

view_perm = Depends(require_permissions("expenses.view"))
create_perm = Depends(require_permissions("expenses.create"))
edit_perm = Depends(require_permissions("expenses.edit"))
delete_perm = Depends(require_permissions("expenses.delete"))


@router.get("/", response_model=APIResponse[list[ExpenseOut]], dependencies=[view_perm])
async def list_expenses(db: AsyncSession = Depends(get_db)):
    """عرض جميع المصاريف."""
    expenses = await ExpenseService(db).list_expenses()
    return APIResponse(data=[ExpenseOut.model_validate(e) for e in expenses])


@router.post("/", response_model=APIResponse[ExpenseOut], dependencies=[create_perm])
async def create_expense(
    body: ExpenseIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("expenses.create")),
):
    """إدخال سند مصروف جديد."""
    expense = await ExpenseService(db).create_expense(
        body.model_dump(), current_user.id
    )
    return APIResponse(
        data=ExpenseOut.model_validate(expense),
        message="تم إنشاء سند المصروف بنجاح.",
    )


@router.get("/{expense_id}", response_model=APIResponse[ExpenseOut], dependencies=[view_perm])
async def get_expense(expense_id: int, db: AsyncSession = Depends(get_db)):
    """عرض تفاصيل سند مصروف."""
    expense = await ExpenseService(db).get_expense(expense_id)
    return APIResponse(data=ExpenseOut.model_validate(expense))


@router.put("/{expense_id}", response_model=APIResponse[ExpenseOut], dependencies=[edit_perm])
async def update_expense(
    expense_id: int,
    body: ExpenseIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("expenses.edit")),
):
    """تعديل سند مصروف (فقط إذا لم يتم تحصيله)."""
    expense = await ExpenseService(db).update_expense(
        expense_id, body.model_dump(), current_user.id
    )
    return APIResponse(
        data=ExpenseOut.model_validate(expense),
        message="تم تعديل سند المصروف بنجاح.",
    )


@router.delete("/{expense_id}", dependencies=[delete_perm])
async def delete_expense(expense_id: int, db: AsyncSession = Depends(get_db)):
    """حذف سند مصروف (فقط إذا لم يتم تحصيله)."""
    await ExpenseService(db).delete_expense(expense_id)
    return APIResponse(message="تم حذف سند المصروف بنجاح.")
