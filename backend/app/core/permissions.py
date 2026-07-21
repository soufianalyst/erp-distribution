"""Granular permission catalog and per-user resolution.

Roles act as default permission templates; a user with an explicit `permissions`
list overrides their role's defaults entirely. Admins always hold every
permission so the system can never be locked out.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models.user import User

# --- Catalog: (code, Arabic label), grouped for the management UI ---
PERMISSION_GROUPS: list[dict] = [
    {
        "group": "المخزون",
        "permissions": [
            {"code": "products.view", "label": "عرض الأصناف"},
            {"code": "products.manage", "label": "إدارة الأصناف والأسعار"},
            {"code": "products.delete", "label": "حذف الأصناف"},
            {"code": "warehouses.view", "label": "عرض المستودعات"},
            {"code": "warehouses.manage", "label": "إدارة المستودعات"},
            {"code": "stock.view", "label": "عرض الأرصدة وتقارير الصلاحية"},
            {"code": "stock.receive", "label": "استلام بضاعة"},
            {"code": "stock.transfer", "label": "التحويل بين المستودعات"},
            {"code": "stock.adjust", "label": "تعديلات المخزون"},
        ],
    },
    {
        "group": "المبيعات",
        "permissions": [
            {"code": "customers.view", "label": "عرض العملاء"},
            {"code": "customers.manage", "label": "إدارة العملاء والحدود الائتمانية"},
            {"code": "sales.view", "label": "عرض فواتير المبيعات"},
            {"code": "sales.create", "label": "إصدار فواتير مبيعات"},
            {"code": "sales.edit", "label": "تعديل فواتير المبيعات"},
            {"code": "sales.delete", "label": "حذف فواتير المبيعات"},
            {"code": "sales.returns", "label": "تسجيل مرتجعات المبيعات"},
            {"code": "sales.payments", "label": "سندات قبض من العملاء"},
            {"code": "sales.quotations", "label": "عروض الأسعار"},
            {
                "code": "sales.all_customers",
                "label": "الوصول لجميع العملاء (وليس عملاءه فقط)",
            },
            {
                "code": "sales.credit_override",
                "label": "الموافقة على تجاوز الحد الائتماني",
            },
        ],
    },
    {
        "group": "المشتريات",
        "permissions": [
            {"code": "suppliers.view", "label": "عرض الموردين"},
            {"code": "suppliers.manage", "label": "إدارة الموردين وكشوف حساباتهم"},
            {"code": "purchases.view", "label": "عرض فواتير المشتريات"},
            {"code": "purchases.create", "label": "تثبيت فواتير شراء"},
            {"code": "purchases.edit", "label": "تعديل فواتير المشتريات"},
            {"code": "purchases.delete", "label": "حذف فواتير المشتريات"},
            {"code": "purchases.returns", "label": "مرتجعات المشتريات"},
            {"code": "purchases.payments", "label": "سندات صرف للموردين"},
        ],
    },
    {
        "group": "التوزيع والتسليم",
        "permissions": [
            {"code": "delivery.view", "label": "متابعة رحلات التوزيع وقوائم التجهيز"},
            {"code": "delivery.manage", "label": "إدارة الرحلات والتسليم"},
            {
                "code": "delivery.deliver",
                "label": "تسليم الطلبيات وتحديث حالتها أثناء الرحلة",
            },
        ],
    },
    {
        "group": "الحسابات",
        "permissions": [
            {"code": "accounting.view", "label": "عرض القيود وميزان المراجعة"},
            {
                "code": "accounting.manual_entry",
                "label": "تسجيل قيود يدوية وإدارة الحسابات",
            },
        ],
    },
    {
        "group": "التقارير",
        "permissions": [
            {"code": "reports.view", "label": "عرض لوحة التحكم والتقارير التحليلية"},
        ],
    },
    {
        "group": "النظام",
        "permissions": [
            {"code": "users.manage", "label": "إدارة المستخدمين والصلاحيات"},
        ],
    },
    {
        "group": "المصاريف",
        "permissions": [
            {"code": "expenses.view", "label": "عرض المصاريف والمدفوعات"},
            {"code": "expenses.create", "label": "إدخال مصروفات وسندات قبض"},
            {"code": "expenses.edit", "label": "تعديل المصاريف"},
            {"code": "expenses.delete", "label": "حذف المصاريف"},
        ],
    },
    {
        "group": "الصندوق",
        "permissions": [
            {"code": "cashier.view", "label": "عرض الفواتير المعلقة للتحصيل"},
            {"code": "cashier.receive_payment", "label": "تحصيل مدفوعات الفواتير النقدية/البطاقة"},
        ],
    },
]

ALL_PERMISSIONS: frozenset[str] = frozenset(
    item["code"] for group in PERMISSION_GROUPS for item in group["permissions"]
)

# Role templates, applied when a user has no explicit permission list.
ROLE_DEFAULT_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "storekeeper": frozenset(
        {
            "products.view",
            "warehouses.view",
            "stock.view",
            "stock.receive",
            "stock.transfer",
            "stock.adjust",
            "delivery.view",
            "delivery.manage",
            "delivery.deliver",
        }
    ),
    "sales": frozenset(
        {
            "products.view",
            "warehouses.view",
            "stock.view",
            "customers.view",
            "sales.view",
            "sales.create",
            "sales.returns",
            "sales.payments",
            "sales.quotations",
            "delivery.view",
            "reports.view",
        }
    ),
    "driver": frozenset(
        {
            "warehouses.view",
            "delivery.view",
            "delivery.deliver",
        }
    ),
    "accountant": frozenset(
        {
            "products.view",
            "warehouses.view",
            "stock.view",
            "customers.view",
            "customers.manage",
            "sales.view",
            "sales.payments",
            "sales.all_customers",
            "suppliers.view",
            "suppliers.manage",
            "purchases.view",
            "purchases.create",
            "purchases.returns",
            "purchases.payments",
            "expenses.view",
            "expenses.create",
            "expenses.edit",
            "accounting.view",
            "accounting.manual_entry",
            "reports.view",
        }
    ),
    "cashier": frozenset(
        {
            "cashier.view",
            "cashier.receive_payment",
        }
    ),
}


def effective_permissions(user: "User") -> set[str]:
    """Resolve a user's actual permissions: admin = all; explicit list wins; else role defaults."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return set(ALL_PERMISSIONS)
    if user.permissions is not None:
        return set(user.permissions) & ALL_PERMISSIONS
    return set(ROLE_DEFAULT_PERMISSIONS.get(role, frozenset()))


def has_permission(user: "User", permission: str) -> bool:
    return permission in effective_permissions(user)
