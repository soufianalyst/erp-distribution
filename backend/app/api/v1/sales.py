"""Sales endpoints: customers, FEFO invoices, returns, receipts, and statements."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.pagination import Page, PageParams
from app.api.schemas.sales import (
    CollectionActivityIn,
    CollectionActivityOut,
    CollectionsWorklistOut,
    ReturnCancelIn,
    CustomerCreditOut,
    CustomerCreditResolveIn,
    FieldSyncIn,
    FieldSyncOut,
    FieldVanOut,
    RoundPositionOut,
    RoundSettlementOpenIn,
    RoundSettlementOut,
    RoundSettlementSettleIn,
    RoundVanSettleIn,
    CommissionReportOut,
    CustomerCreate,
    CustomerOut,
    CustomerPaymentCreate,
    CustomerPaymentOut,
    CustomerStatementOut,
    CustomerUpdate,
    InvoiceTimelineOut,
    QuotationConvertIn,
    SalesInvoiceCreate,
    SalesInvoiceOut,
    SalesQuotationCreate,
    SalesQuotationOut,
    SalesReturnCreate,
    SalesReturnOut,
)
from app.db.session import get_db
from app.domain.models.sales import CollectionOutcome
from app.services.sales.collections_service import CollectionsService
from app.domain.models.user import User
from app.domain.models.sales import CreditResolution, RoundSettlementStatus
from app.services.sales.field_sync_service import FieldSyncService
from app.services.sales.invoice_timeline_service import InvoiceTimelineService
from app.services.sales.round_settlement_service import RoundSettlementService
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


@router.get("/invoices", response_model=APIResponse[Page[SalesInvoiceOut]])
async def list_invoices(
    customer_id: int | None = Query(default=None),
    page: PageParams = Depends(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sales_view),
) -> APIResponse[Page[SalesInvoiceOut]]:
    """عرض فواتير المبيعات صفحةً صفحة؛ يرى المندوب فواتيره فقط."""
    invoices, total = await SalesService(db).list_invoices(
        current_user, customer_id, page
    )
    return APIResponse(
        data=Page(
            items=[SalesInvoiceOut.model_validate(i) for i in invoices],
            total=total,
            limit=page.limit,
            offset=page.offset,
        )
    )


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


@router.get(
    "/invoices/{invoice_id}/timeline",
    response_model=APIResponse[InvoiceTimelineOut],
)
async def invoice_timeline(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(sales_view),
) -> APIResponse[InvoiceTimelineOut]:
    """تتبّع الفاتورة: أين وصلت من الإصدار حتى التسليم أو الاستلام.

    نفس صلاحيات عرض الفاتورة: المندوب يتتبّع فواتير عملائه فقط.
    """
    service = SalesService(db)
    invoice = await service.get_invoice(invoice_id)
    customer = await service.get_customer(invoice.customer_id)
    service.ensure_customer_access(current_user, customer)
    timeline = await InvoiceTimelineService(db).timeline(invoice)
    return APIResponse(data=InvoiceTimelineOut.model_validate(timeline))


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


# --- Field app (offline salesman round) ---
@router.get("/field/van", response_model=APIResponse[FieldVanOut])
async def get_my_van(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.field_sync")),
) -> APIResponse[FieldVanOut]:
    """المركبة المسندة للمندوب وما تحمله حالياً — يخزّنها التطبيق للعمل دون اتصال."""
    van = await FieldSyncService(db).van_snapshot(current_user)
    return APIResponse(data=van)


@router.post("/field/sync", response_model=APIResponse[FieldSyncOut])
async def sync_field_round(
    body: FieldSyncIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.field_sync")),
) -> APIResponse[FieldSyncOut]:
    """رفع جولة المندوب: العملاء الجدد ثم المبيعات والطلبات.

    آمنة للإعادة: كل عنصر يحمل معرّفاً من التطبيق، فما سبق حفظه يُبلَّغ عنه ولا
    يُكرر. فشل مستند واحد لا يمنع بقية الجولة من الحفظ.
    """
    result = await FieldSyncService(db).sync(body, current_user)
    return APIResponse(
        data=result,
        message=(
            f"تمت مزامنة {result.created_count} عنصراً"
            + (f"، و{result.duplicate_count} مسجّل مسبقاً" if result.duplicate_count else "")
            + (f"، وتعذّر حفظ {result.failed_count}" if result.failed_count else "")
            + "."
        ),
    )


# --- Round settlement (تسوية جولة المندوب) ---
@router.get("/rounds", response_model=APIResponse[list[RoundSettlementOut]])
async def list_rounds(
    warehouse_id: int | None = None,
    salesman_id: int | None = None,
    status: RoundSettlementStatus | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.round_settle")),
) -> APIResponse[list[RoundSettlementOut]]:
    """تسويات جولات المناديب، الأحدث أولاً، مع إمكانية التصفية بالمركبة أو الحالة."""
    rounds = await RoundSettlementService(db).list_settlements(
        warehouse_id=warehouse_id, salesman_id=salesman_id, status=status
    )
    return APIResponse(data=[RoundSettlementOut.model_validate(r) for r in rounds])


@router.get("/rounds/position", response_model=APIResponse[RoundPositionOut])
async def round_position(
    warehouse_id: int,
    round_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.round_settle")),
) -> APIResponse[RoundPositionOut]:
    """موقف الجولة الآن: ما بيع، وما حُصّل، وما بقي — وأسباب تعذّر الإقفال إن وُجدت."""
    position = await RoundSettlementService(db).position(warehouse_id, round_date)
    return APIResponse(data=position)


@router.post("/rounds", response_model=APIResponse[RoundSettlementOut], status_code=201)
async def open_round(
    body: RoundSettlementOpenIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.round_settle")),
) -> APIResponse[RoundSettlementOut]:
    """فتح جولة لمركبة. جولة مفتوحة واحدة لكل مركبة في وقت واحد."""
    settlement = await RoundSettlementService(db).open_round(body, current_user)
    return APIResponse(
        data=RoundSettlementOut.model_validate(settlement),
        message="تم فتح الجولة.",
    )


@router.post("/rounds/{settlement_id}/settle", response_model=APIResponse[RoundSettlementOut])
async def settle_round(
    settlement_id: int,
    body: RoundSettlementSettleIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.round_settle")),
) -> APIResponse[RoundSettlementOut]:
    """إقفال الجولة وتثبيت أرقامها.

    يُرفض الإقفال إن بقي نقد غير محصَّل. وفرق المخزون يمرّ بسبب مكتوب، ويحتاج
    صلاحية إقرار إن تجاوز الحدّ المضبوط في الإعدادات.
    """
    settlement = await RoundSettlementService(db).settle(settlement_id, body, current_user)
    return APIResponse(
        data=RoundSettlementOut.model_validate(settlement),
        message="تمت تسوية الجولة.",
    )


@router.post("/rounds/{settlement_id}/cancel", response_model=APIResponse[RoundSettlementOut])
async def cancel_round(
    settlement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.round_settle")),
) -> APIResponse[RoundSettlementOut]:
    """إلغاء جولة مفتوحة. الجولة المسوّاة سجلّ موقّع ولا تُلغى."""
    settlement = await RoundSettlementService(db).cancel(settlement_id, current_user)
    return APIResponse(
        data=RoundSettlementOut.model_validate(settlement),
        message="تم إلغاء الجولة.",
    )


@router.post("/rounds/settle-van", response_model=APIResponse[RoundSettlementOut])
async def settle_van_round(
    body: RoundVanSettleIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.round_settle")),
) -> APIResponse[RoundSettlementOut]:
    """إقفال يوم المركبة في خطوة واحدة — تُفتح الجولة تلقائياً إن لم تكن مفتوحة.

    نفس بوابات الإقفال تنطبق: النقد غير المحصَّل يمنع، وفرق المخزون يحتاج سبباً
    مكتوباً وإقراراً إن تجاوز الحدّ.
    """
    settlement = await RoundSettlementService(db).settle_van(body, current_user)
    return APIResponse(
        data=RoundSettlementOut.model_validate(settlement),
        message="تمت تسوية الجولة.",
    )


# --- Customer credits (money owed back after a return) ---
@router.get("/credits", response_model=APIResponse[list[CustomerCreditOut]])
async def list_customer_credits(
    pending_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.returns")),
) -> APIResponse[list[CustomerCreditOut]]:
    """المبالغ المستحقّة للعملاء بسبب مرتجعات بعد الدفع، وحالة كل منها."""
    credits = await SalesService(db).list_customer_credits(
        CreditResolution.PENDING if pending_only else None
    )
    return APIResponse(data=[CustomerCreditOut.model_validate(c) for c in credits])


@router.post("/credits/{credit_id}/resolve", response_model=APIResponse[CustomerCreditOut])
async def resolve_customer_credit(
    credit_id: int,
    body: CustomerCreditResolveIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.refund_customer")),
) -> APIResponse[CustomerCreditOut]:
    """تحديد مصير المبلغ: ردّ نقدي من الصندوق، أو رصيد يبقى في حساب العميل.

    الردّ النقدي يُسجّل القرار فقط؛ صرف المبلغ يجري من شاشة الصندوق ليدخل في
    إقفال اليوم مثل أي مبلغ يخرج من الدرج.
    """
    credit = await SalesService(db).resolve_customer_credit(
        credit_id, CreditResolution(body.resolution), current_user, body.notes
    )
    return APIResponse(
        data=CustomerCreditOut.model_validate(credit),
        message=(
            "سيُردّ المبلغ نقداً من الصندوق."
            if body.resolution == "refunded"
            else "بقي المبلغ رصيداً في حساب العميل."
        ),
    )


@router.post("/returns/{return_id}/cancel", response_model=APIResponse[SalesReturnOut])
async def cancel_return(
    return_id: int,
    body: ReturnCancelIn | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.returns_cancel")),
) -> APIResponse[SalesReturnOut]:
    """إلغاء مرتجع سُجّل بالخطأ: تُسحب الكمية من المخزون ويُعكس القيد.

    يُرفض إن كان مبلغ المرتجع قد رُدّ للعميل نقداً، أو إن بِيعت البضاعة بعد إرجاعها.
    السجل يبقى محفوظاً بعلامة «ملغى» لأن الخطأ نفسه جزء من التوثيق.
    """
    sales_return = await SalesService(db).cancel_return(
        return_id, current_user, body.cancel_reason if body else None
    )
    return APIResponse(
        data=SalesReturnOut.model_validate(sales_return),
        message="تم إلغاء المرتجع وعكس أثره.",
    )


# --- Collections ---
collections = Depends(require_permissions("sales.collections"))


@router.get(
    "/collections/worklist",
    response_model=APIResponse[CollectionsWorklistOut],
)
async def collections_worklist(
    min_days: int = Query(default=30, ge=0, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.collections")),
) -> APIResponse[CollectionsWorklistOut]:
    """من يُتصل به اليوم لتحصيل الدين، مرتباً بحسب كلفة التأجيل.

    الترتيب بالمبلغ المتأخر مرجَّحاً بعمره، لا بالمبلغ وحده ولا بالعمر وحده: دينٌ
    كبير متأخر ثلاثة أسابيع مكالمة لا تزال مجدية، وآخر صغير عمره سنة اعترافٌ مؤجَّل.

    المندوب يرى عملاءه فقط؛ من يملك صلاحية «جميع العملاء» يرى الدفتر كاملاً — فوجود
    شخصين يتصلان بشأن دين واحد أسوأ من عدم الاتصال.
    """
    data = await CollectionsService(db).worklist(current_user, min_days=min_days)
    return APIResponse(data=CollectionsWorklistOut.model_validate(data))


@router.post(
    "/customers/{customer_id}/collections",
    response_model=APIResponse[CollectionActivityOut],
    status_code=status.HTTP_201_CREATED,
)
async def log_collection_activity(
    customer_id: int,
    body: CollectionActivityIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("sales.collections")),
) -> APIResponse[CollectionActivityOut]:
    """تسجيل محاولة تحصيل ونتيجتها؛ والوعد بالسداد يحتاج مبلغاً وتاريخاً.

    لا يُخزَّن إن كان الوعد قد أُوفي به: ذلك يُحسب من الدفعات الفعلية، لأن حقلاً
    مخزّناً سيخالف دفتر الحسابات أول مرة يُسدَّد فيها نقداً لمندوب.
    """
    activity = await CollectionsService(db).log(
        customer_id,
        CollectionOutcome(body.outcome),
        current_user,
        promised_amount=body.promised_amount,
        promised_on=body.promised_on,
        note=body.note,
    )
    return APIResponse(
        data=CollectionActivityOut.model_validate(activity),
        message="تم تسجيل المتابعة.",
    )


@router.get(
    "/customers/{customer_id}/collections",
    response_model=APIResponse[list[CollectionActivityOut]],
    dependencies=[collections],
)
async def collection_history(
    customer_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[list[CollectionActivityOut]]:
    """سجل متابعات التحصيل لعميل واحد، الأحدث أولاً."""
    history = await CollectionsService(db).history(customer_id)
    return APIResponse(
        data=[CollectionActivityOut.model_validate(a) for a in history]
    )
