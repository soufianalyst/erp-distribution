"""Tax types CRUD endpoints."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.sales import (
    TaxTypeCreate,
    TaxTypeOut,
    TaxTypeUpdate,
)
from app.core.exceptions import AppException
from app.db.session import get_db
from app.domain.models.accounting import Account, AccountType
from app.domain.models.sales import TaxType

router = APIRouter(prefix="/tax-types", tags=["Tax Types"])

manage_taxes = Depends(require_permissions("accounting.manual_entry"))
view_taxes = Depends(require_permissions("accounting.view"))


@router.get(
    "/",
    response_model=APIResponse[list[TaxTypeOut]],
    dependencies=[view_taxes],
)
async def list_tax_types(
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[TaxTypeOut]]:
    """قائمة جميع أنواع الضريبة المتاحة."""
    stmt = select(TaxType).order_by(TaxType.id)
    if active_only:
        stmt = stmt.where(TaxType.is_active == True)
    result = await db.execute(stmt)
    tax_types = list(result.scalars().all())
    return APIResponse(data=[TaxTypeOut.model_validate(tt) for tt in tax_types])


@router.post(
    "/",
    response_model=APIResponse[TaxTypeOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[manage_taxes],
)
async def create_tax_type(
    body: TaxTypeCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[TaxTypeOut]:
    """إضافة نوع ضريبة جديد."""
    existing = await db.execute(select(TaxType).where(TaxType.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise AppException(409, "يوجد نوع ضريبة بنفس الاسم.")
    # Auto-create the liability account if it doesn't exist.
    acct = await db.execute(
        select(Account).where(Account.code == body.accounting_code)
    )
    if acct.scalar_one_or_none() is None:
        db.add(
            Account(
                code=body.accounting_code,
                name=f"ضريبة ({body.name})",
                type=AccountType.LIABILITY,
            )
        )
        await db.flush()
    tax_type = TaxType(
        name=body.name,
        rate=body.rate,
        is_active=body.is_active,
        accounting_code=body.accounting_code,
    )
    db.add(tax_type)
    await db.commit()
    await db.refresh(tax_type)
    return APIResponse(data=TaxTypeOut.model_validate(tax_type))


@router.get(
    "/{tax_type_id}",
    response_model=APIResponse[TaxTypeOut],
    dependencies=[view_taxes],
)
async def get_tax_type(
    tax_type_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[TaxTypeOut]:
    """عرض تفاصيل نوع ضريبة."""
    tax_type = await db.get(TaxType, tax_type_id)
    if tax_type is None:
        raise AppException(404, "نوع الضريبة غير موجود.")
    return APIResponse(data=TaxTypeOut.model_validate(tax_type))


@router.put(
    "/{tax_type_id}",
    response_model=APIResponse[TaxTypeOut],
    dependencies=[manage_taxes],
)
async def update_tax_type(
    tax_type_id: int,
    body: TaxTypeUpdate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TaxTypeOut]:
    """تعديل نوع ضريبة (Admin only)."""
    tax_type = await db.get(TaxType, tax_type_id)
    if tax_type is None:
        raise AppException(404, "نوع الضريبة غير موجود.")
    update_data = body.model_dump(exclude_unset=True)
    if "name" in update_data:
        existing = await db.execute(
            select(TaxType).where(TaxType.name == update_data["name"], TaxType.id != tax_type_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise AppException(409, "يوجد نوع ضريبة بنفس الاسم.")
    for field, value in update_data.items():
        setattr(tax_type, field, value)
    await db.commit()
    await db.refresh(tax_type)
    return APIResponse(data=TaxTypeOut.model_validate(tax_type))


@router.delete("/{tax_type_id}", response_model=APIResponse, dependencies=[manage_taxes])
async def delete_tax_type(
    tax_type_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse:
    """حذف نوع ضريبة."""
    tax_type = await db.get(TaxType, tax_type_id)
    if tax_type is None:
        raise AppException(404, "نوع الضريبة غير موجود.")
    await db.delete(tax_type)
    await db.commit()
    return APIResponse(message="تم حذف نوع الضريبة بنجاح.")
