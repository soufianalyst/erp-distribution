"""Inventory endpoints: warehouses, products, and stock operations (receive/transfer/levels)."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.inventory import (
    MarkdownApplyIn,
    MarkdownApplyOut,
    MarkdownPlanOut,
    MarkdownProposalOut,
    ProductOfferCreate,
    ProductOfferOut,
    BatchOut,
    NearExpiryOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    StockAdjustmentCancel,
    StockAdjustmentCreate,
    StockAdjustmentOut,
    StockLevelOut,
    StockReceiveRequest,
    StocktakeCancelIn,
    StocktakeCountsIn,
    StocktakeCreate,
    StocktakeOut,
    StockTransferRequest,
    TransferLineOut,
    WarehouseCreate,
    WarehouseOut,
    WarehouseUpdate,
)
from app.api.schemas.purchases import ReorderSuggestionOut
from app.db.session import get_db
from app.services.inventory.offer_service import OfferService
from app.domain.models.inventory import StocktakeStatus
from app.domain.models.user import User
from app.services.inventory.product_service import ProductService
from app.services.inventory.markdown_service import MarkdownService
from app.services.inventory.stock_service import StockService
from app.services.inventory.warehouse_service import WarehouseService
from app.services.settings.settings_service import SettingsService

router = APIRouter(prefix="/inventory", tags=["Inventory"])

# Each operation is gated by a granular permission (roles only supply defaults).
warehouses_view = Depends(require_permissions("warehouses.view"))
warehouses_manage = Depends(require_permissions("warehouses.manage"))
products_view = Depends(require_permissions("products.view"))
products_manage = Depends(require_permissions("products.manage"))
stock_view = Depends(require_permissions("stock.view"))
stock_receive = Depends(require_permissions("stock.receive"))
stock_transfer = Depends(require_permissions("stock.transfer"))


# --- Warehouses ---
@router.post(
    "/warehouses",
    response_model=APIResponse[WarehouseOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[warehouses_manage],
)
async def create_warehouse(
    body: WarehouseCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[WarehouseOut]:
    """إنشاء مستودع جديد (مدير النظام فقط)."""
    warehouse = await WarehouseService(db).create_warehouse(body)
    return APIResponse(
        data=WarehouseOut.model_validate(warehouse), message="تم إنشاء المستودع بنجاح."
    )


@router.get(
    "/warehouses",
    response_model=APIResponse[list[WarehouseOut]],
    dependencies=[warehouses_view],
)
async def list_warehouses(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[WarehouseOut]]:
    """عرض قائمة المستودعات."""
    warehouses = await WarehouseService(db).list_warehouses()
    return APIResponse(data=[WarehouseOut.model_validate(w) for w in warehouses])


@router.patch(
    "/warehouses/{warehouse_id}",
    response_model=APIResponse[WarehouseOut],
    dependencies=[warehouses_manage],
)
async def update_warehouse(
    warehouse_id: int, body: WarehouseUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[WarehouseOut]:
    """تعديل بيانات مستودع أو إيقافه (مدير النظام فقط)."""
    warehouse = await WarehouseService(db).update_warehouse(warehouse_id, body)
    return APIResponse(
        data=WarehouseOut.model_validate(warehouse), message="تم تحديث المستودع بنجاح."
    )


# --- Products ---
@router.post(
    "/products",
    response_model=APIResponse[ProductOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[products_manage],
)
async def create_product(
    body: ProductCreate, db: AsyncSession = Depends(get_db)
) -> APIResponse[ProductOut]:
    """إنشاء صنف جديد مع وحدات القياس والأسعار (مدير النظام فقط)."""
    product = await ProductService(db).create_product(body)
    return APIResponse(
        data=ProductOut.model_validate(product), message="تم إنشاء الصنف بنجاح."
    )


@router.get(
    "/products",
    response_model=APIResponse[list[ProductOut]],
    dependencies=[products_view],
)
async def list_products(
    search: str | None = Query(default=None, description="بحث بالاسم أو رمز الصنف أو الباركود"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ProductOut]]:
    """عرض قائمة الأصناف مع إمكانية البحث."""
    products = await ProductService(db).list_products(search)
    return APIResponse(data=[ProductOut.model_validate(p) for p in products])


@router.get(
    "/products/barcode/{barcode}",
    response_model=APIResponse[ProductOut],
    dependencies=[products_view],
)
async def get_product_by_barcode(
    barcode: str, db: AsyncSession = Depends(get_db)
) -> APIResponse[ProductOut]:
    """بحث سريع عن صنف بالباركود (لاستخدام ماسح الباركود)."""
    product = await ProductService(db).get_by_barcode(barcode)
    return APIResponse(data=ProductOut.model_validate(product))


@router.get(
    "/products/{product_id}",
    response_model=APIResponse[ProductOut],
    dependencies=[products_view],
)
async def get_product(
    product_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[ProductOut]:
    """عرض تفاصيل صنف واحد."""
    product = await ProductService(db).get_product(product_id)
    return APIResponse(data=ProductOut.model_validate(product))


@router.patch(
    "/products/{product_id}",
    response_model=APIResponse[ProductOut],
    dependencies=[products_manage],
)
async def update_product(
    product_id: int, body: ProductUpdate, db: AsyncSession = Depends(get_db)
) -> APIResponse[ProductOut]:
    """تعديل بيانات صنف أو أسعاره (مدير النظام فقط)."""
    product = await ProductService(db).update_product(product_id, body)
    return APIResponse(
        data=ProductOut.model_validate(product), message="تم تحديث الصنف بنجاح."
    )


@router.delete(
    "/products/{product_id}",
    response_model=APIResponse[None],
    dependencies=[Depends(require_permissions("products.delete"))],
)
async def delete_product(
    product_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[None]:
    """حذف صنف نهائياً؛ يُرفض إن كانت له أي حركات مخزنية سابقة."""
    await ProductService(db).delete_product(product_id)
    return APIResponse(data=None, message="تم حذف الصنف بنجاح.")


@router.get(
    "/products/{product_id}/batches",
    response_model=APIResponse[list[BatchOut]],
    dependencies=[stock_view],
)
async def list_product_batches(
    product_id: int,
    warehouse_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[BatchOut]]:
    """عرض تشغيلات صنف مرتبة حسب الأقرب انتهاءً (FEFO)."""
    batches = await StockService(db).list_batches(product_id, warehouse_id)
    return APIResponse(data=[BatchOut.model_validate(b) for b in batches])


# --- Stock operations ---
@router.post(
    "/stock/receive",
    response_model=APIResponse[BatchOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[stock_receive],
)
async def receive_stock(
    body: StockReceiveRequest,
    db: AsyncSession = Depends(get_db),
    # Taken from the permission check rather than a second auth dependency: a
    # direct receipt now posts a journal entry, and an entry with no author is a
    # hole in the audit trail.
    current_user: User = Depends(require_permissions("stock.receive")),
) -> APIResponse[BatchOut]:
    """استلام بضاعة في المستودع؛ رقم التشغيلة وتاريخ الانتهاء إلزاميان."""
    batch = await StockService(db).receive_stock(body, current_user.id)
    return APIResponse(
        data=BatchOut.model_validate(batch), message="تم استلام البضاعة بنجاح."
    )


@router.post(
    "/stock/transfer",
    response_model=APIResponse[list[TransferLineOut]],
    dependencies=[stock_transfer],
)
async def transfer_stock(
    body: StockTransferRequest, db: AsyncSession = Depends(get_db)
) -> APIResponse[list[TransferLineOut]]:
    """تحويل بضاعة بين مستودعين مع اختيار التشغيلات الأقرب انتهاءً أولاً (FEFO)."""
    moved = await StockService(db).transfer_stock(body)
    return APIResponse(data=moved, message="تم تحويل البضاعة بين المستودعين بنجاح.")


@router.get(
    "/stock/levels",
    response_model=APIResponse[list[StockLevelOut]],
    dependencies=[stock_view],
)
async def stock_levels(
    product_id: int | None = Query(default=None),
    warehouse_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[StockLevelOut]]:
    """عرض أرصدة المخزون الحالية مجمعة حسب الصنف والمستودع."""
    levels = await StockService(db).stock_levels(product_id, warehouse_id)
    return APIResponse(data=levels)


@router.get(
    "/stock/reorder-suggestions",
    response_model=APIResponse[list[ReorderSuggestionOut]],
    dependencies=[stock_view],
)
async def reorder_suggestions(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ReorderSuggestionOut]]:
    """الأصناف التي نفدت أو وصلت حدها الأدنى — لتسهيل تحضير طلب الشراء."""
    items = await StockService(db).reorder_suggestions()
    return APIResponse(data=items)


@router.get(
    "/stock/near-expiry",
    response_model=APIResponse[list[NearExpiryOut]],
    dependencies=[stock_view],
)
async def near_expiry(
    days: int = Query(default=30, ge=0, le=365, description="عدد الأيام حتى الانتهاء"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[NearExpiryOut]]:
    """تنبيهات البضاعة قريبة الانتهاء أو المنتهية وما زالت في المخزون."""
    items = await StockService(db).near_expiry(days)
    return APIResponse(data=items)


# --- Stock adjustments (write-offs) ---
@router.post(
    "/stock/adjustments",
    response_model=APIResponse[StockAdjustmentOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_adjustment(
    body: StockAdjustmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("stock.adjust")),
) -> APIResponse[StockAdjustmentOut]:
    """تسجيل تعديل/إتلاف مخزون مباشرة من تشغيلة محددة، خارج أي عملية بيع أو مرتجع شراء."""
    adjustment = await StockService(db).create_adjustment(
        body, created_by=current_user.id
    )
    return APIResponse(
        data=StockAdjustmentOut.model_validate(adjustment),
        message="تم تسجيل تعديل المخزون بنجاح.",
    )


@router.get(
    "/stock/adjustments",
    response_model=APIResponse[list[StockAdjustmentOut]],
    dependencies=[stock_view],
)
async def list_adjustments(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[StockAdjustmentOut]]:
    """عرض تعديلات/إتلاف المخزون."""
    adjustments = await StockService(db).list_adjustments()
    return APIResponse(data=[StockAdjustmentOut.model_validate(a) for a in adjustments])


@router.get(
    "/stock/adjustments/{adjustment_id}",
    response_model=APIResponse[StockAdjustmentOut],
    dependencies=[stock_view],
)
async def get_adjustment(
    adjustment_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[StockAdjustmentOut]:
    """عرض تفاصيل سجل تعديل/إتلاف مخزون واحد (للطباعة)."""
    adjustment = await StockService(db).get_adjustment(adjustment_id)
    return APIResponse(data=StockAdjustmentOut.model_validate(adjustment))


@router.post(
    "/stock/adjustments/{adjustment_id}/cancel",
    response_model=APIResponse[StockAdjustmentOut],
)
async def cancel_adjustment(
    adjustment_id: int,
    body: StockAdjustmentCancel,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("stock.adjust_cancel")),
) -> APIResponse[StockAdjustmentOut]:
    """إلغاء تعديل/إتلاف سُجّل بالخطأ؛ تعود الكمية للمخزون ويُعكس القيد المحاسبي."""
    adjustment = await StockService(db).cancel_adjustment(
        adjustment_id, body.cancel_reason, cancelled_by=current_user.id
    )
    return APIResponse(
        data=StockAdjustmentOut.model_validate(adjustment),
        message="تم إلغاء السجل وإرجاع الكمية للمخزون.",
    )


# --- Stocktakes (physical counts) ---
@router.post(
    "/stocktakes",
    response_model=APIResponse[StocktakeOut],
    status_code=status.HTTP_201_CREATED,
)
async def open_stocktake(
    body: StocktakeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("stock.stocktake")),
) -> APIResponse[StocktakeOut]:
    """بدء جرد لمستودع: تُلتقط الكميات المتوقعة لكل تشغيلة كورقة جرد."""
    stocktake = await StockService(db).open_stocktake(body, created_by=current_user.id)
    return APIResponse(
        data=StocktakeOut.model_validate(stocktake),
        message="تم بدء الجرد؛ أدخل الكميات الفعلية ثم ثبّت التسوية.",
    )


@router.get(
    "/stocktakes",
    response_model=APIResponse[list[StocktakeOut]],
    dependencies=[stock_view],
)
async def list_stocktakes(
    warehouse_id: int | None = Query(default=None),
    stocktake_status: StocktakeStatus | None = Query(
        default=None, description="تصفية حسب حالة الجرد"
    ),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[StocktakeOut]]:
    """عرض عمليات الجرد، مع إمكانية التصفية حسب المستودع أو الحالة."""
    stocktakes = await StockService(db).list_stocktakes(warehouse_id, stocktake_status)
    return APIResponse(data=[StocktakeOut.model_validate(s) for s in stocktakes])


@router.get(
    "/stocktakes/{stocktake_id}",
    response_model=APIResponse[StocktakeOut],
    dependencies=[stock_view],
)
async def get_stocktake(
    stocktake_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[StocktakeOut]:
    """عرض ورقة جرد واحدة بكل سطورها وفروقاتها (للإدخال أو الطباعة)."""
    stocktake = await StockService(db).get_stocktake(stocktake_id)
    return APIResponse(data=StocktakeOut.model_validate(stocktake))


@router.put("/stocktakes/{stocktake_id}/counts", response_model=APIResponse[StocktakeOut])
async def save_stocktake_counts(
    stocktake_id: int,
    body: StocktakeCountsIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("stock.stocktake")),
) -> APIResponse[StocktakeOut]:
    """حفظ الكميات الفعلية؛ يمكن الحفظ على دفعات أثناء التنقل بين الرفوف."""
    stocktake = await StockService(db).save_counts(stocktake_id, body)
    return APIResponse(
        data=StocktakeOut.model_validate(stocktake), message="تم حفظ الكميات المُدخلة."
    )


@router.post("/stocktakes/{stocktake_id}/post", response_model=APIResponse[StocktakeOut])
async def post_stocktake(
    stocktake_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("stock.stocktake")),
) -> APIResponse[StocktakeOut]:
    """تثبيت الجرد: تُسوّى فروقات النقص والزيادة على المخزون وتُسجّل قيودها."""
    stocktake = await StockService(db).post_stocktake(
        stocktake_id, posted_by=current_user.id
    )
    return APIResponse(
        data=StocktakeOut.model_validate(stocktake),
        message="تم تثبيت الجرد وتسوية الفروقات على المخزون.",
    )


@router.post(
    "/stocktakes/{stocktake_id}/cancel", response_model=APIResponse[StocktakeOut]
)
async def cancel_stocktake(
    stocktake_id: int,
    body: StocktakeCancelIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("stock.stocktake")),
) -> APIResponse[StocktakeOut]:
    """إلغاء جرد لم يُثبّت؛ لا أثر على المخزون لأن الجرد لا يُحرّك شيئاً قبل التثبيت."""
    stocktake = await StockService(db).cancel_stocktake(stocktake_id, body.cancel_reason)
    return APIResponse(
        data=StocktakeOut.model_validate(stocktake), message="تم إلغاء عملية الجرد."
    )


# --- Temporary markdowns ---
# Separated from products.manage: discounting is a pricing decision, and whoever
# counts the shelf should not be able to mark it down.
@router.get(
    "/offers",
    response_model=APIResponse[list[ProductOfferOut]],
    dependencies=[Depends(require_permissions("products.view"))],
)
async def list_offers(
    include_ended: bool = False, db: AsyncSession = Depends(get_db)
) -> APIResponse[list[ProductOfferOut]]:
    """عروض التخفيض الحالية، مع أثرها على الهامش."""
    return APIResponse(data=await OfferService(db).list_offers(include_ended))


@router.post(
    "/offers",
    response_model=APIResponse[ProductOfferOut],
    status_code=201,
)
async def create_offer(
    body: ProductOfferCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("products.offers")),
) -> APIResponse[ProductOfferOut]:
    """إنشاء عرض تخفيض مؤقت — يظهر للعميل في البوابة ويُطبَّق على الفاتورة."""
    offer = await OfferService(db).create(body, current_user.id)
    return APIResponse(data=offer, message="تم إنشاء العرض.")


@router.post(
    "/offers/{offer_id}/end",
    response_model=APIResponse[ProductOfferOut],
    dependencies=[Depends(require_permissions("products.offers"))],
)
async def end_offer(
    offer_id: int, db: AsyncSession = Depends(get_db)
) -> APIResponse[ProductOfferOut]:
    """إيقاف العرض من الآن — لا يُحذف، حفاظاً على تفسير الفواتير السابقة."""
    return APIResponse(data=await OfferService(db).end(offer_id), message="تم إيقاف العرض.")


# --- Markdown plan ---
@router.get(
    "/markdown-plan",
    response_model=APIResponse[MarkdownPlanOut],
    dependencies=[Depends(require_permissions("products.offers"))],
)
async def markdown_plan(
    horizon_days: int = Query(default=60, ge=7, le=365),
    max_discount: Decimal | None = Query(
        default=None, gt=0, le=90,
        description="سقف الخصم لهذه المرة؛ لا يتجاوز سقف الشركة في الإعدادات",
    ),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[MarkdownPlanOut]:
    """خطة تصريف المخزون المهدد: ما الذي يُخصم، وما الذي يحتاج اتصالاً، وما الذي يُشطب.

    الخصم المقترح يُحسب من سرعة البيع الفعلية والأيام المتبقية، فيتعمّق تلقائياً كلما
    اقترب تاريخ الانتهاء دون الحاجة إلى سلّم ثابت.
    """
    plan = await MarkdownService(db).plan(
        horizon_days=horizon_days,
        max_discount=await _discount_ceiling(db, max_discount),
    )
    return APIResponse(
        data=MarkdownPlanOut(
            horizon_days=plan.horizon_days,
            elasticity=plan.elasticity.value,
            elasticity_source=plan.elasticity.source,
            elasticity_observations=plan.elasticity.observations,
            stock_at_risk=plan.stock_at_risk,
            surplus_value=plan.surplus_value,
            recoverable_value=plan.recoverable_value,
            write_off_value=plan.write_off_value,
            items=[MarkdownProposalOut.model_validate(item) for item in plan.items],
        )
    )


@router.post(
    "/markdown-plan/apply",
    response_model=APIResponse[MarkdownApplyOut],
)
async def apply_markdown_plan(
    body: MarkdownApplyIn,
    horizon_days: int = Query(default=60, ge=7, le=365),
    max_discount: Decimal | None = Query(default=None, gt=0, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permissions("products.offers")),
) -> APIResponse[MarkdownApplyOut]:
    """تحويل المقترحات المختارة إلى عروض فعلية تسري على الفواتير والبوابة.

    تُعاد الخطة حسابها هنا من جديد؛ لا يُوثق بأي رقم قادم من الشاشة، لأن الخصم سعرٌ
    يُحاسَب عليه العميل فعلاً.
    """
    created, skipped, notes = await MarkdownService(db).apply(
        body.batch_ids, current_user.id,
        horizon_days=horizon_days,
        max_discount=await _discount_ceiling(db, max_discount),
    )
    return APIResponse(
        data=MarkdownApplyOut(created=created, skipped=skipped, notes=notes),
        message=(
            (f"تم إنشاء {_offers(created)}." if created else "لم يُنشأ أي عرض.")
            + (f" وتم تخطّي {_offers(skipped)}." if skipped else "")
        ),
    )


async def _discount_ceiling(
    db: AsyncSession, requested: Decimal | None
) -> Decimal:
    """The company's markdown ceiling, or a shallower one the caller asked for.

    The screen may be gentler than policy on a given day and never harsher, so the
    request is clamped rather than trusted. Before this, the deepest discount the
    engine could propose was whatever number arrived in a query string — which is a
    price a customer gets charged, decided by the browser.
    """
    policy = (await SettingsService(db).get_company_settings()) \
        .markdown_max_discount_percent
    return min(requested, policy) if requested is not None else policy


def _offers(count: int) -> str:
    """"عرض واحد"، "عرضان"، "٣ عروض"، "١٢ عرضاً" — Arabic counts a noun by its number.

    Written out rather than interpolated as `f"{n} عرضاً"`, which reads as broken
    Arabic for every count below eleven and is the sort of thing that quietly tells
    a user the software was not built for them.
    """
    if count == 1:
        return "عرض واحد"
    if count == 2:
        # Genitive after the masdar إنشاء/تخطّي, so عرضين rather than عرضان.
        return "عرضين"
    if count <= 10:
        return f"{count} عروض"
    return f"{count} عرضاً"
