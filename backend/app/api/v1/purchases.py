"""Purchases endpoints: suppliers, purchase invoices, supplier payments, and statements."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.purchases import (
    PurchaseInvoiceCreate,
    PurchaseInvoiceOut,
    PurchaseReturnCreate,
    PurchaseReturnOut,
    SupplierCreate,
    SupplierOut,
    SupplierPaymentCreate,
    SupplierPaymentOut,
    SupplierStatementOut,
    SupplierUpdate,
)
from app.db.session import get_db
from app.domain.models.user import User
from app.services.purchases.purchase_service import PurchaseService

router = APIRouter(prefix="/purchases", tags=["Purchases"])

# Each operation is gated by a granular permission (roles only supply defaults).
suppliers_view = Depends(require_permissions("suppliers.view"))
suppliers_manage = Depends(require_permissions("suppliers.manage"))
purchases_view = Depends(require_permissions("purchases.view"))


# --- Suppliers ---
@router.post(
    "/suppliers",
    response_model=APIResponse[SupplierOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[suppliers_manage],
)
async def create_supplier(
    body: SupplierCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[SupplierOut]:
    """إضافة مورد جديد (مدير النظام أو المحاسب)."""
    supplier = await PurchaseService(db).create_supplier(body)
    return APIResponse(
        data=SupplierOut.model_validate(supplier), message="تم إضافة المورد بنجاح."
    )


@router.get(
    "/suppliers",
    response_model=APIResponse[list[SupplierOut]],
    dependencies=[suppliers_view],
)
async def list_suppliers(
    search: str | None = Query(default=None, description="بحث باسم المورد"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[SupplierOut]]:
    """عرض قائمة الموردين مع إمكانية البحث."""
    suppliers = await PurchaseService(db).list_suppliers(search)
    return APIResponse(data=[SupplierOut.model_validate(s) for s in suppliers])


@router.patch(
    "/suppliers/{supplier_id}",
    response_model=APIResponse[SupplierOut],
    dependencies=[suppliers_manage],
)
async def update_supplier(
    supplier_id: int, body: SupplierUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[SupplierOut]:
    """تعديل بيانات مورد أو إيقافه."""
    supplier = await PurchaseService(db).update_supplier(supplier_id, body)
    return APIResponse(
        data=SupplierOut.model_validate(supplier),
        message="تم تحديث بيانات المورد بنجاح.",
    )


@router.get(
    "/suppliers/{supplier_id}/statement",
    response_model=APIResponse[SupplierStatementOut],
    dependencies=[suppliers_manage],
)
async def supplier_statement(
    supplier_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[SupplierStatementOut]:
    """كشف حساب المورد: الفواتير، المدفوعات، والرصيد المستحق."""
    statement = await PurchaseService(db).supplier_statement(supplier_id)
    return APIResponse(data=statement)


# --- Purchase invoices ---
@router.post(
    "/invoices",
    response_model=APIResponse[PurchaseInvoiceOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    body: PurchaseInvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("purchases.create")),
) -> APIResponse[PurchaseInvoiceOut]:
    """تثبيت فاتورة شراء وإدخال بضاعتها للمخزون في عملية واحدة غير قابلة للتجزئة."""
    invoice = await PurchaseService(db).create_invoice(body, created_by=current_user.id)
    return APIResponse(
        data=PurchaseInvoiceOut.model_validate(invoice),
        message="تم تثبيت فاتورة الشراء وإدخال البضاعة للمخزون بنجاح.",
    )


@router.get(
    "/invoices",
    response_model=APIResponse[list[PurchaseInvoiceOut]],
    dependencies=[purchases_view],
)
async def list_invoices(
    supplier_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[PurchaseInvoiceOut]]:
    """عرض فواتير الشراء، مع إمكانية التصفية حسب المورد."""
    invoices = await PurchaseService(db).list_invoices(supplier_id)
    return APIResponse(data=[PurchaseInvoiceOut.model_validate(i) for i in invoices])


@router.get(
    "/invoices/{invoice_id}",
    response_model=APIResponse[PurchaseInvoiceOut],
    dependencies=[purchases_view],
)
async def get_invoice(
    invoice_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[PurchaseInvoiceOut]:
    """عرض تفاصيل فاتورة شراء واحدة مع أسطرها."""
    invoice = await PurchaseService(db).get_invoice(invoice_id)
    return APIResponse(data=PurchaseInvoiceOut.model_validate(invoice))


@router.put("/invoices/{invoice_id}", response_model=APIResponse[PurchaseInvoiceOut])
async def update_invoice(
    invoice_id: int,
    body: PurchaseInvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("purchases.edit")),
) -> APIResponse[PurchaseInvoiceOut]:
    """تعديل فاتورة شراء (المدير): يُعاد احتساب المخزون والقيود المحاسبية بالكامل."""
    invoice = await PurchaseService(db).update_invoice(
        invoice_id, body, updated_by=current_user.id
    )
    return APIResponse(
        data=PurchaseInvoiceOut.model_validate(invoice),
        message="تم تعديل فاتورة الشراء وإعادة احتساب المخزون والقيود بنجاح.",
    )


@router.delete("/invoices/{invoice_id}", response_model=APIResponse[None])
async def delete_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("purchases.delete")),
) -> APIResponse[None]:
    """حذف فاتورة شراء نهائياً (المدير): يُعكس أثرها على المخزون وتُحذف قيودها."""
    await PurchaseService(db).delete_invoice(invoice_id)
    return APIResponse(data=None, message="تم حذف فاتورة الشراء وعكس أثرها على المخزون بنجاح.")


# --- Purchase returns ---
@router.post(
    "/returns",
    response_model=APIResponse[PurchaseReturnOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_return(
    body: PurchaseReturnCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("purchases.returns")),
) -> APIResponse[PurchaseReturnOut]:
    """تسجيل مرتجع مشتريات: تعاد البضاعة للمورد دائماً بغض النظر عن السبب."""
    purchase_return = await PurchaseService(db).create_return(
        body, created_by=current_user.id
    )
    return APIResponse(
        data=PurchaseReturnOut.model_validate(purchase_return),
        message="تم تسجيل مرتجع المشتريات بنجاح.",
    )


@router.get(
    "/returns",
    response_model=APIResponse[list[PurchaseReturnOut]],
    dependencies=[purchases_view],
)
async def list_returns(
    invoice_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[PurchaseReturnOut]]:
    """عرض مرتجعات المشتريات، مع إمكانية التصفية حسب الفاتورة."""
    returns = await PurchaseService(db).list_returns(invoice_id)
    return APIResponse(data=[PurchaseReturnOut.model_validate(r) for r in returns])


# --- Supplier payments ---
@router.post(
    "/payments",
    response_model=APIResponse[SupplierPaymentOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    body: SupplierPaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("purchases.payments")),
) -> APIResponse[SupplierPaymentOut]:
    """إنشاء سند صرف لمورد وخصمه من رصيده المستحق."""
    payment = await PurchaseService(db).create_payment(body, created_by=current_user.id)
    return APIResponse(
        data=SupplierPaymentOut.model_validate(payment),
        message="تم تسجيل سند الصرف بنجاح.",
    )
