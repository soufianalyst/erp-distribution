"""Inventory endpoints: warehouses, products, and stock operations (receive/transfer/levels)."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.inventory import (
    BatchOut,
    NearExpiryOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    StockLevelOut,
    StockReceiveRequest,
    StockTransferRequest,
    TransferLineOut,
    WarehouseCreate,
    WarehouseOut,
    WarehouseUpdate,
)
from app.db.session import get_db
from app.services.inventory.product_service import ProductService
from app.services.inventory.stock_service import StockService
from app.services.inventory.warehouse_service import WarehouseService

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
    search: str | None = Query(default=None, description="بحث بالاسم أو رمز الصنف"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[ProductOut]]:
    """عرض قائمة الأصناف مع إمكانية البحث."""
    products = await ProductService(db).list_products(search)
    return APIResponse(data=[ProductOut.model_validate(p) for p in products])


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
    body: StockReceiveRequest, db: AsyncSession = Depends(get_db)
) -> APIResponse[BatchOut]:
    """استلام بضاعة في المستودع؛ رقم التشغيلة وتاريخ الانتهاء إلزاميان."""
    batch = await StockService(db).receive_stock(body)
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
