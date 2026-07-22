"""Sales endpoints: customers, FEFO invoices, returns, receipts, and statements."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.sales import (
    CommissionReportOut,
    CustomerCreate,
    CustomerOut,
    CustomerPaymentCreate,
    CustomerPaymentOut,
    CustomerStatementOut,
    CustomerUpdate,
    QuotationConvertIn,
    SalesInvoiceCreate,
    SalesInvoiceOut,
    SalesQuotationCreate,
    SalesQuotationOut,
    SalesReturnCreate,
    SalesReturnOut,
)
from app.db.session import get_db
from app.domain.models.user import User
from app.services.sales.sales_service import SalesService

router = APIRouter(prefix="/sales", tags=["Sales"])

# Each operation is gated by a granular permission (roles only supply defaults).
customers_manage = Depends(require_permissions("customers.manage"))
customers_view = require_permissions("customers.view")
sales_view = require_permissions("sales.view")
sellers = require_permissions("sales.create")
returners = require_permissions("sales.returns")
collectors = require_permissions("sales.payments")
commission_viewers = require_permissions("sales.commission_view")
quoters = require_permissions("sales.quotations")


# --- Customers ---
@router.post(
    "/customers",
    response_model=APIResponse[CustomerOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[customers_manage],
)
async def create_customer(
    body: CustomerCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[CustomerOut]:
    """إضافة عميل جديد مع فئة السعر والحد الائتماني والمندوب المسؤول."""
    customer = await SalesService(db).create_customer(body)
    return APIResponse(
        data=CustomerOut.model_validate(customer), message="تم إضافة العميل بنجاح."
    )


@router.get("/customers", response_model=APIResponse[list[CustomerOut]])
async def list_customers(
    search: str | None = Query(default=None, description="بحث باسم العميل"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(customers_view),
) -> APIResponse[list[CustomerOut]]:
    """عرض العملاء؛ يرى المندوب عملاءه فقط."""
    customers = await SalesService(db).list_customers(current_user, search)
    return APIResponse(data=[CustomerOut.model_validate(c) for c in customers])


@router.patch(
    "/customers/{customer_id}",
    response_model=APIResponse[CustomerOut],
    dependencies=[customers_manage],
)
async def update_customer(
    customer_id: int, body: CustomerUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[CustomerOut]:
    """تعديل بيانات عميل، فئة سعره، حده الائتماني، أو مندوبه."""
    customer = await SalesService(db).update_customer(customer_id, body)
    return APIResponse(
        data=CustomerOut.model_validate(customer),
        message="تم تحديث بيانات العميل بنجاح.",
    )


@router.get(
    "/customers/{customer_id}/statement",
    response_model=APIResponse[CustomerStatementOut],
)
async def customer_statement(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(customers_view),
) -> APIResponse[CustomerStatementOut]:
    """كشف حساب العميل: الفواتير، المرتجعات، المقبوضات، والرصيد."""
    statement = await SalesService(db).customer_statement(customer_id, current_user)
    return APIResponse(data=statement)


# --- Sales invoices ---
@router.post(
    "/invoices",
    response_model=APIResponse[SalesInvoiceOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    body: SalesInvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sellers),
) -> APIResponse[SalesInvoiceOut]:
    """إصدار فاتورة مبيعات: خصم المخزون حسب FEFO والتحقق من الحد الائتماني في عملية واحدة."""
    invoice = await SalesService(db).create_invoice(body, current_user)
    return APIResponse(
        data=SalesInvoiceOut.model_validate(invoice),
        message="تم إصدار وتثبيت الفاتورة بنجاح.",
    )


@router.put("/invoices/{invoice_id}", response_model=APIResponse[SalesInvoiceOut])
async def update_invoice(
    invoice_id: int,
    body: SalesInvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.edit")),
) -> APIResponse[SalesInvoiceOut]:
    """تعديل فاتورة مبيعات (المدير فقط): يعاد المخزون لتشغيلاته ثم تعاد الفوترة والقيود من جديد."""
    invoice = await SalesService(db).update_invoice(invoice_id, body, current_user)
    return APIResponse(
        data=SalesInvoiceOut.model_validate(invoice),
        message="تم تعديل الفاتورة وإعادة احتساب المخزون والقيود بنجاح.",
    )


@router.post(
    "/invoices/{invoice_id}/pickup",
    response_model=APIResponse[SalesInvoiceOut],
    dependencies=[Depends(require_permissions("delivery.manage"))],
)
async def mark_picked_up(
    invoice_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[SalesInvoiceOut]:
    """تسليم بضاعة فاتورة (استلام من المستودع) للعميل عند المحل."""
    invoice = await SalesService(db).mark_picked_up(invoice_id)
    return APIResponse(
        data=SalesInvoiceOut.model_validate(invoice),
        message="تم تسليم البضاعة للعميل بنجاح.",
    )


@router.delete("/invoices/{invoice_id}", response_model=APIResponse[None])
async def delete_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.delete")),
) -> APIResponse[None]:
    """حذف فاتورة مبيعات نهائياً (المدير): يعاد المخزون وتحذف قيودها المحاسبية."""
    await SalesService(db).delete_invoice(invoice_id)
    return APIResponse(data=None, message="تم حذف الفاتورة وإعادة المخزون بنجاح.")


@router.get("/invoices", response_model=APIResponse[list[SalesInvoiceOut]])
async def list_invoices(
    customer_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sales_view),
) -> APIResponse[list[SalesInvoiceOut]]:
    """عرض فواتير المبيعات؛ يرى المندوب فواتيره فقط."""
    invoices = await SalesService(db).list_invoices(current_user, customer_id)
    return APIResponse(data=[SalesInvoiceOut.model_validate(i) for i in invoices])


@router.get("/invoices/{invoice_id}", response_model=APIResponse[SalesInvoiceOut])
async def get_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sales_view),
) -> APIResponse[SalesInvoiceOut]:
    """عرض تفاصيل فاتورة مبيعات مع أسطرها وتشغيلاتها."""
    service = SalesService(db)
    invoice = await service.get_invoice(invoice_id)
    customer = await service.get_customer(invoice.customer_id)
    service.ensure_customer_access(current_user, customer)
    return APIResponse(data=SalesInvoiceOut.model_validate(invoice))


# --- Returns ---
@router.post(
    "/returns",
    response_model=APIResponse[SalesReturnOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_return(
    body: SalesReturnCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(returners),
) -> APIResponse[SalesReturnOut]:
    """تسجيل مرتجع مبيعات مصنف؛ الصالح لإعادة البيع يعود لمخزون تشغيلاته الأصلية."""
    sales_return = await SalesService(db).create_return(body, current_user)
    return APIResponse(
        data=SalesReturnOut.model_validate(sales_return),
        message="تم تسجيل المرتجع بنجاح.",
    )


@router.get("/returns", response_model=APIResponse[list[SalesReturnOut]])
async def list_returns(
    invoice_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sales_view),
) -> APIResponse[list[SalesReturnOut]]:
    """عرض مرتجعات المبيعات."""
    returns = await SalesService(db).list_returns(current_user, invoice_id)
    return APIResponse(data=[SalesReturnOut.model_validate(r) for r in returns])


# --- Quotations ---
@router.post(
    "/quotations",
    response_model=APIResponse[SalesQuotationOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_quotation(
    body: SalesQuotationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(quoters),
) -> APIResponse[SalesQuotationOut]:
    """إنشاء عرض سعر — تسعير فقط، دون خصم مخزون أو أثر محاسبي."""
    quotation = await SalesService(db).create_quotation(body, current_user)
    return APIResponse(
        data=SalesQuotationOut.model_validate(quotation),
        message="تم إنشاء عرض السعر بنجاح.",
    )


@router.get("/quotations", response_model=APIResponse[list[SalesQuotationOut]])
async def list_quotations(
    customer_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sales_view),
) -> APIResponse[list[SalesQuotationOut]]:
    """عرض عروض الأسعار."""
    quotations = await SalesService(db).list_quotations(current_user, customer_id)
    return APIResponse(data=[SalesQuotationOut.model_validate(q) for q in quotations])


@router.get("/quotations/{quotation_id}", response_model=APIResponse[SalesQuotationOut])
async def get_quotation(
    quotation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sales_view),
) -> APIResponse[SalesQuotationOut]:
    """عرض تفاصيل عرض سعر."""
    quotation = await SalesService(db).get_quotation(quotation_id)
    return APIResponse(data=SalesQuotationOut.model_validate(quotation))


@router.post(
    "/quotations/{quotation_id}/convert", response_model=APIResponse[SalesInvoiceOut]
)
async def convert_quotation(
    quotation_id: int,
    body: QuotationConvertIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(quoters),
) -> APIResponse[SalesInvoiceOut]:
    """تحويل عرض سعر مقبول إلى فاتورة مبيعات فعلية، بنفس الأسعار المعروضة."""
    invoice = await SalesService(db).convert_quotation_to_invoice(
        quotation_id, body, current_user
    )
    return APIResponse(
        data=SalesInvoiceOut.model_validate(invoice),
        message="تم تحويل عرض السعر إلى فاتورة بنجاح.",
    )


@router.post(
    "/quotations/{quotation_id}/cancel", response_model=APIResponse[SalesQuotationOut]
)
async def cancel_quotation(
    quotation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(quoters),
) -> APIResponse[SalesQuotationOut]:
    """إلغاء عرض سعر لم يُحوَّل بعد."""
    quotation = await SalesService(db).cancel_quotation(quotation_id, current_user)
    return APIResponse(
        data=SalesQuotationOut.model_validate(quotation),
        message="تم إلغاء عرض السعر.",
    )


# --- Customer payments ---
@router.post(
    "/payments",
    response_model=APIResponse[CustomerPaymentOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_payment(
    body: CustomerPaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(collectors),
) -> APIResponse[CustomerPaymentOut]:
    """إنشاء سند قبض من عميل وخصمه من رصيده المستحق."""
    payment = await SalesService(db).create_payment(body, current_user)
    return APIResponse(
        data=CustomerPaymentOut.model_validate(payment),
        message="تم تسجيل سند القبض بنجاح.",
    )


# --- Salesman commissions ---
@router.get("/reports/commissions", response_model=APIResponse[CommissionReportOut])
async def commission_report(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    salesman_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(commission_viewers),
) -> APIResponse[CommissionReportOut]:
    """تقرير عمولات المناديب: صافي المبيعات (بعد خصم المرتجعات) × نسبة العمولة."""
    report = await SalesService(db).commission_report(date_from, date_to, salesman_id)
    return APIResponse(data=report)
